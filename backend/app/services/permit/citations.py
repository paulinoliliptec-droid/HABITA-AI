"""Claim-to-evidence reconciliation (HR-003 CX-1, evidence-first).

The drafter sometimes words a general planning explanation correctly but cites the curated summary or the
planning context instead of the official passage it rests on. Between the draft and the verifier, HABITA looks for
that passage itself — only among this matter's evidence, only in admissible ``official_text`` records — and links it
when the match is strong and unambiguous. Every decision is recorded on the draft as a system action.

What this can't do, by construction:
- add anything but an existing ``official_text`` regulatory record (never a planning context, so never a parcel
  determination; never a URL or a model-supplied ID);
- change a statement's text or basis (parcel-specific wording is still rejected by ``read_planning``);
- run on statements the reading already rejects, or on anything but general planning explanations.
The verifier re-checks every citation's admissibility (trust, retirement, jurisdiction) at verification and at the
final gate, exactly as for model citations.
"""

from __future__ import annotations

from app.schemas.permit import CitationLink, Draft, Evidence, PermitMatter
from app.services.permit.admissibility import (
    _META,
    _STOP,
    _WORD,
    EXPLANATION,
    EXPLANATION_FRAME,
    fold,
    inadmissibility,
    is_official_text,
    read_planning,
)

#: Planning concepts, EN + PT, as (concept, folded word prefixes). Cross-language matching for the official
#: Portuguese passages and the drafter's English; anything else falls back to five-letter cognate stems.
_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land", ("land", "solo", "terreno", "terrain")),
    ("urban", ("urban",)),
    ("rustic", ("rustic", "rural")),
    ("housing", ("housing", "dwelling", "residen", "habitac", "fogo", "moradia", "home")),
    ("building", ("building", "construct", "construc", "constru", "edific", "obra")),
    ("use", ("use", "uses", "uso", "usos", "utiliza")),
    ("classification", ("classif",)),
    ("qualification", ("qualif",)),
    ("category", ("categor",)),
    ("space", ("space", "espac")),
    ("parameter", ("parameter", "parametr", "index", "indice", "density", "densidad", "height", "altura", "cercea")),
    ("parking", ("parking", "estaciona")),
    ("licensing", ("licen", "comunicac", "prior")),
    ("commerce", ("commerc", "comerc")),
    ("services", ("servic",)),
    ("tourism", ("touris", "turis")),
    ("occupation", ("occup", "ocupa")),
    ("zone", ("zone", "zona", "zoning", "zonament")),
)
#: Too generic to show that a passage states the rule (document names, places, framing words).
_GENERIC = {"munic", "camar", "casca", "portu", "artig", "regul", "decre", "gener", "accor", "segun", "under", "plano",
            "plans", "princ", "geral", "gerai", "relat", "estab", "speci", "parte", "parts", "first", "secon"}
#: Concepts present in almost any urban-planning passage (licensing of urban operations, building, works, projects):
#: they can't by themselves show that a passage states the statement's rule (a licensing statement must not be
#: linked to the parking article because both mention urban operations).
_DOMAIN_GENERIC = {"urban", "building", "licensing", "opera", "inclu", "permi", "proje", "regim"}
_MIN_SHARED = 2  # distinctive (non-generic) concepts shared with the passage
_MIN_COVERAGE = 0.6


def concepts(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall(fold(text)):
        if w in _STOP or w in _META or len(w) < 3:
            continue
        concept = next((c for c, prefixes in _CONCEPTS if w.startswith(prefixes)), None)
        if concept:
            out.add(concept)
        elif len(w) >= 5 and w[:5] not in _GENERIC:
            out.add(w[:5])
    return out


def _link(label: str, text: str, cited: list[Evidence], candidates: list[Evidence]) -> tuple[CitationLink, str | None]:
    wanted = concepts(text)
    scored = []
    for e in candidates:
        shared = wanted & concepts(e.excerpt)
        coverage = len(shared) / len(wanted) if wanted else 0.0
        if len(shared - _DOMAIN_GENERIC) >= _MIN_SHARED and coverage >= _MIN_COVERAGE:
            scored.append((len(shared), coverage, e.evidence_id, sorted(shared)))
    if not scored:
        return CitationLink(statement=label, outcome="no_match"), None
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    best = scored[0]
    tied = [s[2] for s in scored if s[:2] == best[:2]]
    if len(tied) > 1:  # two passages fit equally well: HABITA doesn't pick one arbitrarily
        return CitationLink(statement=label, outcome="ambiguous", score=best[0], coverage=round(best[1], 2),
                            matched=best[3], candidates=tied), None
    return CitationLink(statement=label, outcome="linked", evidence_id=best[2], score=best[0],
                        coverage=round(best[1], 2), matched=best[3], candidates=[best[2]]), best[2]


def reconcile_citations(draft: Draft, evidence: list[Evidence], matter: PermitMatter, chain: list[str],
                        trusted_sources: set[str]) -> Draft:
    """Link admissible official text to general planning explanations that cite none (see module docstring)."""
    admissible = [e for e in evidence if inadmissibility(e, matter, chain, trusted_sources) is None]
    passages = [e for e in admissible if is_official_text(e) and e.jurisdiction_id in chain]
    by_id = {e.evidence_id: e for e in admissible}
    case_facts = [e for e in admissible if e.source_type in ("property_record", "jurisdiction_record", "authority_record")]
    links: list[CitationLink] = []

    def reconcile(label: str, entry, text: str):
        if entry.planning_basis != EXPLANATION:
            return entry
        cited = [by_id[i] for i in entry.evidence_ids if i in by_id]
        if any(is_official_text(e) for e in cited):
            return entry
        body = text[len(EXPLANATION_FRAME):] if text.startswith(EXPLANATION_FRAME) else text
        if read_planning(body, cited, case_facts).problem is not None:
            return entry  # parcel-specific or unsupported fact: no citation can make it admissible
        link, eid = _link(label, body, cited, passages)
        links.append(link)
        return entry if eid is None else entry.model_copy(update={"evidence_ids": [*entry.evidence_ids, eid]})

    updates = {"conclusion": reconcile("conclusion", draft.conclusion, draft.conclusion.summary),
               "claims": [reconcile(k.claim_id, k, k.text) for k in draft.claims],
               "procedure": [reconcile(f"procedure {n}", p, p.description) for n, p in enumerate(draft.procedure, 1)],
               "risks": [reconcile(f"risk {n}", r, r.text) for n, r in enumerate(draft.risks, 1)],
               "next_actions": [reconcile(f"next action {n}", a, a.text) for n, a in enumerate(draft.next_actions, 1)],
               "citation_reconciliation": [*draft.citation_reconciliation, *links]}
    return draft.model_copy(update=updates)


__all__ = ["reconcile_citations", "concepts"]
