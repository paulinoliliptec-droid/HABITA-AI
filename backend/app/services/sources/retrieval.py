"""Jurisdiction-aware retrieval of official passages.

There is no global index: a search only considers the latest snapshot of *trusted*
sources in the property's jurisdiction chain whose regulatory scope matches the
topics. Passages are ranked deterministically with BM25 over two term sets: the
topics' Portuguese vocabulary and the query's own words (English query words are
mapped through a small glossary, since the official texts are Portuguese). The
query therefore changes the ranking, and the same inputs always give the same
passages.
"""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.schemas.sources import OfficialSource, RegulatoryChunk, SourceSnapshot
from app.services.sources.registry import OfficialSourceRegistry

TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "land_use_planning": ("solo", "urbano", "espacos", "categoria", "qualificacao", "classificacao", "usos",
                          "ordenamento", "edificabilidade", "habitacional", "planta"),
    "change_of_use": ("alteracao", "uso", "usos", "utilizacao", "habitacao", "habitacional"),
    "unit_division": ("fogos", "fogo", "divisao", "fracoes", "habitacao", "unidades", "alojamento"),
    "horizontal_property": ("propriedade", "horizontal", "fracoes", "autonomas"),
    "habitability": ("habitabilidade", "area", "areas", "direito", "ventilacao", "iluminacao"),
    "licensing_procedure": ("licenciamento", "licenca", "comunicacao", "previa", "pedido", "operacoes",
                            "urbanisticas", "controlo", "submissao"),
    "competent_authority": ("camara", "municipal", "competencia", "presidente"),
}

GLOSSARY: dict[str, tuple[str, ...]] = {
    "dwelling": ("habitacao", "fogo"), "dwellings": ("habitacao", "fogos"), "residential": ("habitacional",),
    "unit": ("fogo", "fracao"), "units": ("fogos", "fracoes"), "flat": ("fogo",), "flats": ("fogos",),
    "apartment": ("fogo",), "apartments": ("fogos",), "divide": ("divisao",), "division": ("divisao",),
    "convert": ("alteracao",), "conversion": ("alteracao",), "change": ("alteracao",), "use": ("uso",),
    "licence": ("licenca", "licenciamento"), "license": ("licenca", "licenciamento"), "permit": ("licenca",),
    "zoning": ("ordenamento", "qualificacao"), "land": ("solo",), "parking": ("estacionamento",),
    "height": ("altura", "cercea"), "floor": ("piso",), "floors": ("pisos",), "building": ("edificio", "edificacao"),
    "plan": ("plano",), "urban": ("urbano",), "rural": ("rustico",), "heritage": ("patrimonio",),
    "application": ("pedido",), "prior": ("previa",), "communication": ("comunicacao",),
}

STOPWORDS = {
    "para", "pela", "pelo", "como", "mais", "este", "esta", "isso", "sobre", "entre", "pelos", "pelas", "quando",
    "with", "that", "this", "from", "what", "which", "would", "could", "into", "have", "will", "does", "there",
    "the", "and", "for", "are", "das", "dos", "nos", "nas", "com", "que", "uma", "aos",
}

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [w for w in _WORD.findall(folded) if len(w) >= 3 and w not in STOPWORDS]


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for word in tokens(query):
        terms.extend(GLOSSARY.get(word, (word,)))
    return list(dict.fromkeys(terms))


@dataclass(frozen=True)
class RetrievedPassage:
    source: OfficialSource
    snapshot: SourceSnapshot
    chunk: RegulatoryChunk
    score: float


@dataclass
class _Indexed:
    snapshot: SourceSnapshot
    chunks: list[RegulatoryChunk]
    counts: list[Counter] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)


class RegulatoryRetriever:
    def __init__(self, registry: OfficialSourceRegistry, *, k1: float = 1.2, b: float = 0.75) -> None:
        self._registry = registry
        self._k1, self._b = k1, b
        #: Snapshots are immutable, so their passages are cached per process.
        self._cache: dict[str, _Indexed] = {}

    async def _indexed(self, snapshot_id: str) -> _Indexed | None:
        if snapshot_id not in self._cache:
            repo = self._registry.repository
            snapshot = await repo.get_snapshot(snapshot_id)
            if snapshot is None or not snapshot.text_extracted:
                return None
            chunks = await repo.list_chunks(snapshot_id)
            counts = [Counter(tokens(f"{c.locator.heading or ''} {c.text}")) for c in chunks]
            self._cache[snapshot_id] = _Indexed(snapshot, chunks, counts, [sum(c.values()) for c in counts])
        return self._cache[snapshot_id]

    async def search(
        self, jurisdiction_chain: list[str], topics: list[str], query: str, k: int = 3
    ) -> list[RetrievedPassage]:
        pool: list[tuple[OfficialSource, _Indexed, int]] = []
        for source in await self._registry.trusted(jurisdiction_chain, topics):
            if source.retrieval_method != "http_pdf" or not source.latest_snapshot_id:
                continue
            indexed = await self._indexed(source.latest_snapshot_id)
            if indexed and indexed.snapshot.source_id == source.source_id:
                pool.extend((source, indexed, i) for i in range(len(indexed.chunks)))
        if not pool:
            return []

        topic_terms = list(dict.fromkeys(t for topic in topics for t in TOPIC_TERMS.get(topic, ())))
        own_terms = query_terms(query)
        n = len(pool)
        avg = sum(ix.lengths[i] for _, ix, i in pool) / n or 1.0
        df = Counter(term for _, ix, i in pool for term in set(topic_terms + own_terms) if ix.counts[i][term])

        def bm25(ix: _Indexed, i: int, terms: list[str]) -> float:
            score = 0.0
            for term in terms:
                tf = ix.counts[i][term]
                if tf:
                    idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                    score += idf * tf * (self._k1 + 1) / (tf + self._k1 * (1 - self._b + self._b * ix.lengths[i] / avg))
            return score

        scored = []
        for source, ix, i in pool:
            score = bm25(ix, i, topic_terms) + 2.0 * bm25(ix, i, own_terms)
            if score > 0:
                scored.append((score, source, ix, i))
        scored.sort(key=lambda s: (-s[0], s[2].chunks[s[3]].chunk_id))
        return [RetrievedPassage(source, ix.snapshot, ix.chunks[i], round(score, 4)) for score, source, ix, i in scored[:k]]
