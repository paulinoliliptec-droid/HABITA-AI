"""Atomic legal claims (HR-003 MU-9, Phase 1): what each sentence asserts, about whom, and whether the cited evidence
is capable of proving it, in the direction it is stated.

The planning contract (``admissibility.statement_problem``) decides how a statement may be *phrased*. This module
decides what it *claims*. It only ever adds rejections, and it decides by allowlist, never by spotting bad words:

- Every model-written statement is split into atoms (sentences and ``;`` clauses). Each atom gets a bearer (the
  matter — this property, site, project or works, also implicit or pronominal — the authority, or a general scope)
  and a kind from a closed set (``KINDS``).
- A **general explanation** atom is admissible only when one sentence of a cited official passage supports it in
  both directions: every concept in the atom is in that sentence (nothing added: no new object, status, tense,
  modality, number, exception or reference to the matter), and every restrictive concept of the sentence is in
  the atom (nothing dropped: no antecedent, alternative, limit or exception). Concepts are compared through a
  closed bilingual table (``_CONCEPTS``); a word outside it must appear literally. An unknown word therefore
  fails closed. The matter may appear only inside an ``if`` antecedent ("If the works are …, …"), never in the
  consequent. A **normative** atom (``_normative``: a legal instrument, requirement, duty, asserted permission,
  prohibition, number, limit or exception) must also be the sentence's own wording (``_literal``): concept sets keep
  the words but not their roles (object vs scope, ACC-QO-09 / ACC-ROLE-01), so a paraphrase is never supported.
- A **free-text** atom (basis ``none``) that touches a legal instrument or outcome (licence, permit, prior
  communication, approval, validity, exemption …) is admissible only as the authority's competence in its own
  record's words, or as a deferral / recommendation that asserts nothing about the matter.
- Deferrals and recommendations ("must be confirmed with the Câmara", "Confirm with the Câmara whether …") are
  admissible in both bases when what is left after the deferral and its embedded question asserts nothing.
- A legal-status atom about the matter needs the ``property_legal_status`` capability. No evidence provides it, so
  it is never supported: a PDM, a general rule, the RJUE or an authority's competence record can't prove that this
  property holds a licence, an approval or a valid prior communication.

Statements whose text HABITA renders (quoted rules, deferral conditions, determinations, user declarations) are
not re-read here: their content is already HABITA's own.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.schemas.permit import Evidence
from app.services.permit.admissibility import (
    _DEFERRAL, _UNASSERTED, _UNASSERTED_BOUNDED, EXPLANATION, EXPLANATION_FRAME, _norm, _sentences,
    evidence_capabilities, is_official_text, is_user_declared,
)

#: Bases whose text HABITA renders itself.
RENDERED = {"general_rule", "authority_confirmation", "parcel_determination", "user_declaration"}

KINDS = ("deferral", "general_rule", "conditional_rule", "authority_competence", "case_fact", "legal_status",
         "unsupported", "other")
#: What each record capability can prove. ``property_legal_status`` has no provider: no record type carries it.
CAN_PROVE = {
    "official_rule": frozenset({"general_rule", "conditional_rule"}),
    "case_fact": frozenset({"authority_competence", "case_fact"}),
    "rule_summary": frozenset(),  # a curated summary is context only (C1)
    "planning_deferral": frozenset(),
    "parcel_determination": frozenset(),
    "user_declaration": frozenset(),
    "property_legal_status": frozenset({"legal_status"}),
}
#: Kinds that assert nothing and so need no proving capability.
NEEDS_NO_SUPPORT = frozenset({"deferral", "other"})


@dataclass(frozen=True)
class Atom:
    text: str
    kind: str
    bearer: str  # "matter" | "authority" | "general"
    supported_by: tuple[str, ...]
    problem: str | None
    #: False: a shadow verdict (recorded on the report, not yet enforced; Phase 4 measures it).
    enforced: bool = True


# --- tokens and concepts -----------------------------------------------------------------------------------------

def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|%|[^\W\d_]+\d*", re.UNICODE)


def _tokens(text: str) -> list[str]:
    """Lower-case, accent-folded tokens. The PT copulas "é" and "está" keep their accent: folded they would read as
    "e" (and) and "esta" (this)."""
    out = []
    text = re.sub(r"-(?:se|lhe|lhes)\b", " ", text.lower())  # PT clitics ("destinam-se") are not conditions
    for t in _TOKEN.findall(text):
        out.append(t if t in _KEEP_ACCENT else _fold(t))
    return out


_KEEP_ACCENT = {"é", "está", "estás"}


#: Function words: no legal content of their own (articles, prepositions, copulas in the present, "and"-less glue).
#: Anything that changes meaning (negation, modality, tense, quantifiers, "or", conditions) is a concept instead.
_FUNCTION = set("""
the a an of in on at to for from into as is are be being that which who whom whose with by there
o a os as um uma uns umas de do da dos das em no na nos nas ao aos por pelo pela pelos pelas com que é sao ser estar
está estao se para
""".split())
#: Concept table: (concept, phrases). A phrase of one word matches by prefix of the folded token; a phrase of several
#: words matches that exact token sequence. The first match wins, so specific entries come first.
_CONCEPT_TABLE: list[tuple[str, tuple[str, ...]]] = [
    ("PRIOR_COMM", ("comunicacao previa", "comunicacoes previas", "prior communication", "prior communications",
                    "prior notification")),
    ("PRIOR_CONTROL", ("controlo previo", "prior control")),
    ("SINGLE_FAMILY", ("single family", "unifamiliar", "unifamiliares")),
    ("UPTO", ("up to", "at most", "no maximo", "ate", "maximum", "maximo")),
    ("ATLEAST", ("at least", "pelo menos", "minimum", "minimo")),
    ("M2", ("m2", "square metres", "square meters", "metros quadrados")),
    ("PCT", ("%", "percent", "por cento")),
    ("CHANGE_USE", ("change of use", "changes of use", "alteracao de uso", "alteracoes de uso")),
    ("GREEN_LIGHT", ("green light", "luz verde")),
    ("LEGAL_CONDITIONS", ("condicoes legais", "legal conditions")),
    ("LICENSED_STATE", ("licensed", "licenciad")),
    ("LICENSING", ("licenc", "licens")),
    ("NEG", ("not", "no", "never", "without", "nao", "sem", "nunca", "nenhum", "nenhuma", "none")),
    ("OBLIG", ("must", "shall", "should", "deve", "devem", "devera", "deverao", "has to", "have to", "tem de",
               "teem de", "required", "requires", "require", "requer", "exige", "obrigatori", "necessar", "needs",
               "need")),
    ("PERM", ("may", "can", "pode", "podem", "admitid", "admitted", "admissib", "admiss", "allowed", "permitted",
              "permitid", "permissib")),
    ("TENSE", ("was", "were", "been", "had", "will", "would", "foi", "foram", "era", "eram", "sera", "serao",
               "seria", "vai", "vao", "ia")),
    ("HAVE", ("has", "have", "holds", "hold", "tem", "teem", "possui", "dispoe", "deten", "detem", "owns")),
    ("ALL", ("all", "every", "each", "any", "todos", "todas", "cada", "qualquer")),
    ("SOME", ("some", "algum", "alguns", "alguma", "algumas")),
    ("ONLY", ("only", "apenas", "somente", "so")),
    ("DISJ", ("or", "ou")),
    ("CONJ", ("and", "e")),
    ("EXC", ("com excecao de", "com excecao do", "com excecao da", "com excecao dos", "com excecao das",
             "with the exception of", "except for", "except", "excepto", "exceto", "salvo", "unless", "excluding")),
    ("INCL", ("including", "incluindo", "nomeadamente", "designadamente", "namely")),
    ("COND", ("if", "se", "caso", "where", "when", "quando", "desde que", "contanto que", "provided that",
              "providing that", "as long as", "on condition that", "sempre que")),
    ("OPERATION", ("operac", "operat")),
    ("URBAN", ("urban",)),
    ("BUILD", ("edificac", "edificar", "build")),
    ("BUILDING", ("edifici", "build")),
    ("SUBJECT", ("sujeit", "subject")),
    ("PARKING", ("estacionament", "parking")),
    ("PROVISION", ("dotac", "provision", "provid")),
    ("ENSURE", ("assegur", "garant", "ensur", "guarante", "provid")),
    ("ENLARGE", ("ampliac", "ampliar", "enlarg", "extension", "extend")),
    ("HOUSE", ("moradia", "house")),
    ("AREA", ("area",)),
    ("CONSTRUCTION", ("construc",)),
    ("EXISTING", ("existent", "existing")),
    ("CLASSIFIED", ("classificad", "classified")),
    ("WORKS", ("obra", "works")),
    ("USE", ("uso", "use")),
    ("CHANGE", ("alterac", "alter", "change")),
    ("LAND", ("solo", "land")),
    ("INTENDED", ("destin", "intend")),
    ("MAINLY", ("sobretudo", "mainly", "principalmente", "predominant")),
    ("HOUSING", ("habitac", "housing")),
    ("COMMERCE", ("comerci", "commerc")),
    ("SERVICES", ("servic",)),
    ("SPACES", ("espac", "space")),
    ("AUTHORITY", ("camara", "council", "municipality", "municipio")),
]
# "building" names both the activity (edificação) and the object (edifício): it may stand for either.
_ALTERNATIVES = {"BUILD": {"BUILD", "BUILDING"}, "BUILDING": {"BUILD", "BUILDING"},
                 "PROVISION": {"PROVISION", "ENSURE"}, "ENSURE": {"PROVISION", "ENSURE"}}
_PHRASES = sorted(((c, tuple(p.split())) for c, ps in _CONCEPT_TABLE for p in ps if " " in p),
                  key=lambda x: -len(x[1]))
_PREFIXES = [(c, p) for c, ps in _CONCEPT_TABLE for p in ps if " " not in p]
_EXACT = {"no", "so", "e", "se", "ou", "or", "can", "may", "use", "uso", "has", "had", "was", "ia", "vai", "era",
          "tem", "all", "any", "each", "ate", "caso", "when", "where", "if", "and", "not", "must", "need", "needs"}

#: Words that make the matter the bearer: deixis, possessives and pronouns, and the definite article before a
#: place, project or works noun ("the property", "o imóvel", "the works", "a obra").
_MATTER_WORDS = {"this", "these", "its", "it", "they", "their", "here", "aqui", "este", "esta", "estes", "estas",
                 "neste", "nesta", "deste", "desta", "ele", "ela", "eles", "elas", "dele", "dela", "seu", "sua"}
_PRONOUNS = {"it", "its", "they", "their", "ele", "ela", "eles", "elas", "dele", "dela", "seu", "sua"}
_MATTER_NOUNS = ("propert", "parcel", "plot", "site", "premise", "house", "home", "building", "flat", "apartment",
                 "dwelling", "works", "project", "imovel", "predio", "lote", "terreno", "casa", "moradia", "parcela",
                 "edificio", "obra", "projeto", "projecto", "fraccao", "fracao", "applicant", "requerente", "owner",
                 "proprietari")
_PT_DEFINITE_PLURAL = {"os", "as", "dos", "das", "nos", "nas", "aos", "pelos", "pelas"}
#: Nouns that refer to this matter even in the plural ("as obras", "os projetos" of this application).
_MATTER_ALWAYS = ("obra", "works", "project", "projeto", "projecto", "applicant", "requerente", "owner", "proprietari")
_DEFINITE = {"the", "o", "a", "os", "as", "do", "da", "dos", "das", "no", "na", "nos", "nas", "ao", "pelo", "pela"}


_TARGET_WORDS = {"to", "para"}
_ARTICLES = {"a", "an", "the", "o", "um", "uma", "os", "as"}


def _limit_follows(tokens: list[str], i: int) -> bool:
    """Whether a numeric limit starts at ``tokens[i]`` (articles skipped): a number or a comparator phrase."""
    while i < len(tokens) and tokens[i] in _ARTICLES:
        i += 1
    if i >= len(tokens):
        return False
    if tokens[i].isdigit():
        return True
    return any(tuple(tokens[i:i + len(p)]) == p for c, p in _PHRASES if c in _COMPARATORS) or any(
        tokens[i] == p for c, ps in _CONCEPT_TABLE if c in _COMPARATORS for p in ps if " " not in p)


def _concepts_of(tokens: list[str]) -> list[tuple[str, set[str]]]:
    """[(surface, alternatives)] — function words dropped; unknown words stand for themselves (``w:<stem>``)."""
    out, i = [], 0
    while i < len(tokens):
        for concept, phrase in _PHRASES:
            if tuple(tokens[i:i + len(phrase)]) == phrase:
                out.append((" ".join(phrase), _ALTERNATIVES.get(concept, {concept})))
                i += len(phrase)
                break
        else:
            t = tokens[i]
            i += 1
            if t in _TARGET_WORDS and _limit_follows(tokens, i):
                # "enlarged *to* a maximum of 20 %" sets the resulting value; "by up to 20 %" / "até 20 %" limit the
                # amount. The role is part of what the limit means, so it is a concept, not a function word.
                out.append((t, {"TARGET"}))
                continue
            if t.isdigit() or re.fullmatch(r"\d+[.,]\d+", t):
                out.append((t, {"NUM:" + t.replace(",", ".")}))
                continue
            match = next((c for c, p in _PREFIXES if (t == p if p in _EXACT else t.startswith(p))), None)
            if match is not None:
                out.append((t, _ALTERNATIVES.get(match, {match})))
            elif t not in _FUNCTION:
                out.append((t, {"w:" + (t[:-1] if len(t) > 4 and t.endswith("s") else t)[:7]}))
    return out


def _matter_spans(tokens: list[str]) -> set[int]:
    """Token positions that refer to the matter (the reference word and its determiner)."""
    out = set()
    for i, t in enumerate(tokens):
        if t in _PRONOUNS and any(w not in _FUNCTION and w not in _MATTER_WORDS for w in tokens[:i]):
            continue  # "classifies land … and qualifies it": the pronoun takes up a noun of the same atom
        if t in _MATTER_WORDS:
            out.add(i)
        elif t.startswith(_MATTER_NOUNS) and i and tokens[i - 1] in _DEFINITE | _MATTER_WORDS:
            if tokens[i - 1] in _PT_DEFINITE_PLURAL and t.endswith("s") and not t.startswith(_MATTER_ALWAYS):
                continue  # PT generic plural: "nas moradias", "os imóveis" name a class, not this property
            out |= {i - 1, i}
    return out


# --- official passages -------------------------------------------------------------------------------------------

_PARAGRAPH = re.compile(r"\s(?=\d+\s*-\s)")
_INCLUSION = re.compile(r"\b(?:incluindo|including|nomeadamente|designadamente|namely)\b[^,;:]*", re.IGNORECASE)


@dataclass(frozen=True)
class _Sentence:
    evidence_id: str
    allowed: frozenset[str]   # every concept of the sentence
    required: frozenset[str]  # its restrictive concepts (all but inclusion lists)
    slots: frozenset[tuple]   # every bound slot of the sentence (see ``_slots``)
    required_slots: frozenset[tuple]  # its bound slots outside inclusion lists
    limits: tuple[tuple, ...] = ()  # its numeric limits in order (see ``_limits``)
    exceptions: frozenset = frozenset()  # what each exception covers (see ``_exceptions``)
    main: frozenset = frozenset()  # the concepts outside the exceptions (see ``_main_concepts``)
    main_required: frozenset = frozenset()  # the restrictive ones among them (all but inclusion lists)
    #: The sentence's own wording, normalised (``_norm``), for ``_literal``.
    wordings: tuple[str, ...] = ()


_UNITS = {"M2", "PCT"}
_COMPARATORS = {"UPTO", "ATLEAST"}
_OPERATORS = {"DISJ", "CONJ"}


def _slots(concepts: list[tuple[str, set[str]]]) -> set[tuple]:
    """Concepts bound to each other, so that a set comparison can't swap them: each number with the comparator
    before it and the unit after it ("up to 200 m2", "até 20 %"), and each "or" / "and" with the concepts it joins
    ("licensing or prior communication"; the order of the two conjuncts doesn't matter)."""
    seq = [frozenset(alts) for _, alts in concepts]
    out = set()
    for i, alts in enumerate(seq):
        number = next((c for c in alts if c.startswith("NUM:")), None)
        if number:
            before = next((next(iter(seq[j])) for j in range(max(0, i - 2), i) if seq[j] & _COMPARATORS), None)
            after = next((next(iter(seq[j] & _UNITS)) for j in range(i + 1, min(len(seq), i + 2)) if seq[j] & _UNITS),
                         None)
            # What the number limits: the content concepts just before it and its comparator ("construction area
            # up to 200 m2", "enlarged by up to 20 %"); EN and PT order them differently, so a window, not one word.
            start = i - (1 if before else 0)
            head = frozenset(c for j in range(max(0, start - 2), start) for c in seq[j]
                             if c not in _COMPARATORS | _OPERATORS | _UNITS and not c.startswith("NUM:"))
            out.add(("NUM", before, number, after, head))
        elif alts & _OPERATORS and 0 < i < len(seq) - 1:
            op = next(iter(alts & _OPERATORS))
            out.add(("OP", op, frozenset({seq[i - 1], seq[i + 1]})))
    return out


#: An exception and what it covers, up to the next clause boundary: "salvo em edifícios classificados", "except
#: classified buildings". Read from the text, because the concept list keeps no punctuation.
_EXCEPTION = re.compile(r"\b(?:salvo|exceto|excepto|except|unless|excluding|com exce[cç][aã]o d\w+)\b([^,;:.()]*)")


def _representatives(concepts: list[tuple[str, set[str]]]) -> frozenset[str]:
    """One concept per position, the smallest of its alternatives, as ``required`` uses them."""
    return frozenset(next(iter(a)) if len(a) == 1 else min(a) for _, a in concepts) - {"INCL"}


def _main_concepts(text: str, tokens: list[str] | None = None) -> list[tuple[str, set[str]]]:
    """The concepts outside the exception spans (the rule's own scope, subject and consequence). ``tokens``: the
    atom's tokens, possibly filtered (the matter inside an "if" antecedent); the exception spans' tokens are removed
    from them one for one."""
    lower = text.lower()
    folded = _fold(lower)
    if tokens is None:
        # Cut the spans out of the original text (folding keeps offsets for precomposed accents), so PT "é" stays a
        # copula for _tokens instead of turning into "e" (and).
        source = lower if len(lower) == len(folded) else folded
        kept, last = [], 0
        for m in _EXCEPTION.finditer(folded):
            kept.append(source[last:m.start()])
            last = m.end()
        kept.append(source[last:])
        return _concepts_of(_tokens(" ".join(kept)))
    remaining = list(tokens)
    for m in _EXCEPTION.finditer(folded):
        for t in _tokens(m.group(0)):  # the marker and what it covers
            if t in remaining:
                remaining.remove(t)
    return _concepts_of(remaining)


def _exceptions(text: str) -> frozenset[frozenset]:
    """Each exception's span as the set of its concepts, so an exception can't swap with the rule's scope."""
    return frozenset(frozenset(frozenset(alts) for _, alts in _concepts_of(_tokens(m.group(1))))
                     for m in _EXCEPTION.finditer(_fold(text.lower())))


def _limits(concepts: list[tuple[str, set[str]]]) -> tuple[tuple, ...]:
    """The numeric limits in the order they appear: (comparator, number, unit)."""
    return tuple(slot[1:4] for _, slot in _numbered_slots(concepts))


def _numbered_slots(concepts: list[tuple[str, set[str]]]) -> list[tuple[int, tuple]]:
    seq = [frozenset(alts) for _, alts in concepts]
    out = []
    for i, alts in enumerate(seq):
        number = next((c for c in alts if c.startswith("NUM:")), None)
        if number:
            before = next((next(iter(seq[j])) for j in range(max(0, i - 2), i) if seq[j] & _COMPARATORS), None)
            after = next((next(iter(seq[j] & _UNITS)) for j in range(i + 1, min(len(seq), i + 2)) if seq[j] & _UNITS),
                         None)
            out.append((i, ("NUM", before, number, after)))
    return out


def _slot_matches(slot: tuple, others: set[tuple]) -> bool:
    if slot[0] == "OP":
        return any(o[0] == "OP" and o[1] == slot[1] and _same_pair(slot[2], o[2]) for o in others)
    # Same comparator, number and unit, limiting the same thing: what the atom says the limit applies to (the two
    # concepts just before its comparator) is all among what the passage's limit applies to, so a limit can't be
    # moved onto another quantity ("construction area is enlarged up to 200 m2" vs "construction area up to 200 m2").
    return any(o[0] == "NUM" and o[1:4] == slot[1:4] and slot[4] <= _expand(o[4]) and (slot[4] or not o[4])
               for o in others)


def _expand(concepts: frozenset) -> set:
    return {a for c in concepts for a in _ALTERNATIVES.get(c, {c})}


def _same_span(a: frozenset, b: frozenset) -> bool:
    """Two spans match when every concept of each shares an alternative with one of the other's."""
    return all(any(x & y for y in b) for x in a) and all(any(x & y for x in a) for y in b)


def _same_pair(a: frozenset, b: frozenset) -> bool:
    """Two conjunct pairs match when each conjunct shares a concept with one of the other pair's."""
    a, b = list(a), list(b)
    if len(a) != len(b):
        return False
    if len(a) == 1:
        return bool(a[0] & b[0])
    return bool((a[0] & b[0] and a[1] & b[1]) or (a[0] & b[1] and a[1] & b[0]))


def _title_only(header: str, body: str) -> bool:
    """Whether the text of an "Artigo N.º … 1 - " header (or before "1 - ") is a label that adds nothing to the
    excerpt: no sentence or bracketed aside, and its words are a phrase of the body ("Dotação de estacionamento").
    Anything else ("Obras necessitam de vistoria municipal", "Princípios gerais …") stays bound to the quote: what a
    header adds is decided by content, not by which words it uses (owner principle, ACC-NRM-44)."""
    # Only the article's own number goes ("Artigo 997.º"); any other number or ordinal ("2.º acesso") or any text
    # before it ("A permissão depende de … Artigo 997.º") is content.
    title = re.sub(r"\bartigo\s+\d+(?:\.\s*[oº])?\s*", "", header, count=1, flags=re.IGNORECASE)
    if re.search(r"[.!?;()\[\]]", title):
        return False
    # The title must be a literal phrase of the body ("Dotação de estacionamento" in "… a dotação de estacionamento"):
    # any approximation (scattered words, shared roots) can relate the words differently ("Obras permitidas com
    # vistoria" vs "As obras permitem vistoria"), so none is used.
    # Literal means accents kept ("pode" is not "pôde"): only case and spacing are normalised.
    phrase, text = (re.sub(r"\s+", " ", t.lower()).strip(" .;:") for t in (title, body))
    return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _excerpt_parts(text: str) -> tuple[str | None, list[str]]:
    """(the header text that stays bound to the rule, the numbered paragraphs without their numbers). The text before
    "1 - " ("Artigo 120.º Dotação de estacionamento", "Princípios gerais do solo urbano", "Artigo 997.º Obras
    necessitam de vistoria municipal") is dropped only when it adds nothing to the body (``_title_only``); otherwise it
    is part of paragraph 1, so a quote or transcription carries it (owner principle, ACC-NRM-44)."""
    raw = _PARAGRAPH.split(text)
    # Containment (ACC-NRM-51, open): "N - " is read as paragraph numbering only when the markers run 1, 2, 3 … in
    # order; otherwise ("de 2 - 3 metros") the structure isn't trusted and the excerpt is one unit, quoted whole.
    numbers = [int(m.group(1)) for p in raw if (m := re.match(r"\s*(\d+)\s*-", p))]
    lead = 0 if re.match(r"\s*\d+\s*-", raw[0]) else 1  # an unnumbered header before "1 - "
    if numbers != list(range(1, len(numbers) + 1)) or len(numbers) != len(raw) - lead:
        return None, [text]
    if len(raw) > 1 and not re.match(r"\s*\d+\s*-", raw[0]):
        header, raw = raw[0].strip(), raw[1:]
    else:
        header = None
    paragraphs = [re.sub(r"^\s*\d+\s*-\s*", "", p) for p in raw]
    if header and _title_only(header, " ".join(paragraphs)):
        header = None
    return header, paragraphs


def bound_quote(e: Evidence, quote: str) -> str:
    """A quote as HABITA shows it: with the header its record keeps bound to the rule (``_excerpt_parts``)."""
    header, _ = _excerpt_parts(e.excerpt)
    quote = re.sub(r"\s+", " ", quote).strip()
    if header and not _norm(quote).startswith(_norm(header)):
        return f"{header} {quote}"
    return quote


def _passage_sentences(e: Evidence) -> list[_Sentence]:
    text = e.excerpt.lower()  # folded by _tokens, which keeps PT "é" apart from "e"
    out = []
    header, paragraphs = _excerpt_parts(text)
    units = [s for p in paragraphs for s in _full_sentences(p)]
    if header and units:
        units[0] = f"{header} {units[0].lstrip()}"  # bound to paragraph 1 (see ``_excerpt_parts``)
    # Owner rule (after ACC-NRM-36): an excerpt with more than one unit is quoted whole. Which other unit conditions,
    # excepts or merely describes can't be read reliably from its words, so none is left out.
    body = " ".join(u.strip() for u in units)
    units_whole = [(body if len(units) > 1 else u, u) for u in units]
    for whole, sentence in ((w, c) for w, u in units_whole for c in _sentences(u)):
        concepts = _concepts_of(_tokens(sentence))
        core_concepts = _concepts_of(_tokens(_without_inclusions(sentence, _INCLUSION)))
        allowed = {c for _, alts in concepts for c in alts}
        core = {frozenset(alts) for _, alts in core_concepts}
        required = {next(iter(a)) if len(a) == 1 else min(a) for a in core} - {"INCL"}
        if allowed:
            out.append(_Sentence(e.evidence_id, frozenset(allowed), frozenset(required),
                                 frozenset(_slots(concepts)), frozenset(_slots(core_concepts)),
                                 _limits(concepts), _exceptions(sentence),
                                 frozenset(c for _, alts in _main_concepts(sentence) for c in alts),
                                 _representatives(_main_concepts(_without_inclusions(sentence, _INCLUSION))),
                                 (_norm(whole),)))
    return out


def _full_sentences(text: str) -> list[str]:
    """Sentences up to . ! ? (``_sentences`` also stops at ";", which ends a clause, not a sentence)."""
    out, current = [], ""
    for piece in _sentences(text):
        current += piece
        if not piece.rstrip().endswith(";"):
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return [s for s in out if s.strip()]


def _clauses(text: str) -> list[tuple[str, str]]:
    """(the whole sentence, one of its clauses), clause by clause."""
    return [(whole, clause) for whole in _full_sentences(text) for clause in _sentences(whole)]


def _statement_clauses(text: str) -> list[tuple[tuple[str, ...], str]]:
    """(the runs of consecutive sentences that contain it, one clause), clause by clause: a quote of several sentences
    is literal when one of those runs is a whole official excerpt."""
    sentences = [w.strip() for w in _full_sentences(text)]
    out = []
    for k, whole in enumerate(sentences):
        runs = tuple(" ".join(sentences[a:b]) for a in range(k + 1) for b in range(k + 1, len(sentences) + 1))
        # A paragraph number opening a sentence ("2 - Essa …") is a reference, not a number of the rule.
        out += [(runs, c) for clause in _sentences(whole)
                if _tokens(c := re.sub(r"^\s*\d+\s*-\s+", "", clause.strip()))]
    return out


#: What makes a span restrictive: a condition, exclusivity, negation, modality, exception, limit, tense or quantifier.
_RESTRICTIVE = {"COND", "ONLY", "NEG", "OBLIG", "PERM", "EXC", "UPTO", "ATLEAST", "M2", "PCT", "TARGET", "TENSE", "ALL",
                "SOME"}


def _without_inclusions(sentence: str, pattern: re.Pattern) -> str:
    """The sentence without its inclusion lists. A span that restricts anything ("incluindo … apenas se tiverem
    parecer favorável", "including works of up to 50 m2") is not a mere list of covered cases: it stays."""
    def drop(m: re.Match) -> str:
        span = m.group(0)
        folded = _fold(span.lower())
        restrictive = any(c in _RESTRICTIVE or c.startswith("NUM:")
                          for _, alts in _concepts_of(_tokens(span)) for c in alts)
        return m.group(0) if restrictive or _legal(folded) or _DEONTIC_WORDS.search(folded) else " "
    return pattern.sub(drop, sentence)


#: A paragraph number at the start of the quote or of one of its sentences ("… é permitida. 2 - Essa …").
_NUMBERING = re.compile(r"(?:^|(?<=[.!?;])|(?<=\w))\s*(?<![\d.])\d+\s*-\s+")


def _literal(atom: str | tuple[str, ...], s: _Sentence) -> bool:
    """Whether the atom is the whole sentence in its own wording (accents, case, spacing, a paragraph number and the
    final stop aside). Never a part of it: what a part leaves out can be a condition in any wording ("desde que …"),
    so a partial quote is not decided by reading what it drops."""
    candidates = (atom,) if isinstance(atom, str) else atom
    # As written, or without paragraph markers ("… permitida. 2 - Essa …"): the excerpt's own wording has lost its
    # markers only where its numbering was trusted (``_excerpt_parts``), so "de 2 - 3 metros" can't become "de 3".
    return any(a and a in s.wordings for c in candidates for a in {_norm(c), _norm(_NUMBERING.sub(" ", c))})


def _supports(atom_concepts: list[tuple[str, set[str]]], s: _Sentence, verbatim: bool = False,
              exceptions: frozenset = frozenset(), main: list | None = None) -> bool:
    """Whether one passage sentence supports the atom in the direction stated. ``verbatim``: the atom is a literal
    quote rendered by HABITA (``general_rule``). ``exceptions``: the atom's own (``_exceptions``)."""
    if len(s.limits) >= 2 and not verbatim:
        # A rule with several numeric limits (MU-9 V2, owner decision 2026-10-29): which limit binds which quantity,
        # and in which role, can't be read back reliably from a paraphrase, so only a literal quote is admitted.
        return False
    # An added "if" only narrows a rule's scope; every other concept must be in the sentence.
    if not all(alts & s.allowed or alts == {"COND"} for _, alts in atom_concepts):
        return False
    present = {c for _, alts in atom_concepts for c in alts}
    if not all(r in present or (_ALTERNATIVES.get(r, set()) & present) for r in s.required):
        return False  # also a partial quote that drops a limit, a condition or an exception
    # The rule's own part is supported by the passage's own part: a concept of an exception can't move into the scope
    # ("Em solo urbano classificado … salvo em edifícios classificados").
    if main is not None:
        if not all(alts & s.main or alts == {"COND"} for _, alts in main):
            return False
        # …and everything the passage's own part requires is in the atom's own part: the limit's object can't be
        # dropped and "found" in an exception ("a altura [das edificações] … salvo em edifícios classificados").
        main_present = {c for _, alts in main for c in alts}
        if not all(r in main_present or (_ALTERNATIVES.get(r, set()) & main_present) for r in s.main_required):
            return False
    # Each exception covers the same thing, both ways (none moved onto the scope, none invented or dropped).
    if not (all(any(_same_span(x, y) for y in s.exceptions) for x in exceptions)
            and all(any(_same_span(y, x) for x in exceptions) for y in s.exceptions)):
        return False
    # Bound slots, both ways: no number, limit, unit or alternative moved to another place or changed, none dropped.
    concepts = [(t, alts) for t, alts in atom_concepts if alts != {"COND"}]
    slots = _slots(concepts)
    return (all(_slot_matches(x, set(s.slots)) for x in slots)
            and all(_slot_matches(r, slots) for r in s.required_slots))


# --- classification ----------------------------------------------------------------------------------------------

#: Legal instruments and outcomes (licence, permit, prior communication, approval, validity, exemption …). An atom
#: that names one is always held to the allowlist below.
_LEGAL = re.compile(
    r"\b(?:licen[cs]\w*|permits?\b|alvar\w*|prior (?:communication|control|notification)\w*|"
    r"comunica\w* previ\w*|controlo previo|authori[sz]\w*|autoriz\w*|approv\w*|aprov\w*|confirm\w*|grant\w*|"
    r"conced\w*|concess\w*|issu\w*|emit\w*|emiss\w*|receiv\w*|receb\w*|obtain\w*|obtid\w*|valid\w*|vigor\w*|"
    r"in force|deferid\w*|deferiment\w*|legal\w*|ilegal\w*|regulariz\w*|conform\w*|complian\w*|compliant|"
    r"complet\w*|conclu\w*|done|finish\w*|luz verde|green light|exempt\w*|isent\w*|isenc\w*|dispens\w*|"
    r"accept\w*|aceit\w*|communicat\w*|comunicad\w*|submit\w*|submet\w*|apresentad\w*|entitle\w*|direito|"
    r"covered|abrangid\w*|parecer\w*)")
#: Permission words. A permission with no explicit general scope ("Two dwellings are permitted", "São permitidos
#: dois fogos") is about the matter (MU-9 M1); with one ("in urban land", "each category", "depending on …") it is a
#: general statement.
#: Prohibitions, acts that remove or override a duty, and the deontic qualifiers that turn one into a faculty, whatever
#: their grammar ("é proibida", "interdita", "o PDM revoga …", "is waived", "deixa de ser exigida", "… facultativa").
_DEONTIC_WORDS = re.compile(
    r"\b(?:proib\w*|prohibit\w*|interdit\w*|forbid\w*|forbidden|vedad\w*|impedid\w*|revog\w*|revok\w*|"
    r"revoca\w*|repeal\w*|derrog\w*|suspend\w*|suspens\w*|anul\w*|annul\w*|isen[tc]\w*|exempt\w*|dispens\w*|"
    r"waiv\w*|prevalec\w*|prevail\w*|overrid\w*|substitu\w*|replac\w*|cessa\w*|deixa\w* de|no longer|carec\w*|"
    r"necessit\w*|sujeit\w*|facultativ\w*|opciona\w*|optional\w*|voluntari\w*|voluntary|discricion\w*|"
    r"discretion\w*)\b")
_PERMISSION = re.compile(r"\b(?:permitted|permissible|permitid\w*|permite\w*|allow\w*|admit\w*|admiss\w*)\b")
_GENERIC_SCOPE = re.compile(
    r"\b(?:each|every|any|cada|qualquer|tod[oa]s?|depending|depend\w*|consoante|conforme|according)\b"
    r"|\b(?:in|em|no|na|nos|nas|within|under|for)\s+(?:\w+\s+){0,3}?(?:land|solo|zones?|zonas?|areas?|categor\w*|"
    r"espac\w*|operations?|operac\w*|districts?|distritos?|plans?|planos?|spaces?)\b"
    # A scope phrase over a class: "in / em" + an unqualified plural ("Em habitações coletivas", "In single-family
    # houses"). Still enforced as a norm: it needs an official sentence that supports it.
    r"|(?:^|[,;:]\s*)(?:in|em|nas|nos)\s+(?:[\w-]+\s+){0,2}?[\w-]{3,}s\b")


#: "not (yet) confirmed / verified / determined" says that something is unknown, not that a legal act happened.
_UNKNOWN = re.compile(r"\b(?:not|nao)\s+(?:yet\s+|ainda\s+)?(?:confirm|verif|determin)\w*")


def _legal(folded: str) -> bool:
    return bool(_LEGAL.search(_UNKNOWN.sub(" ", folded)))


def _bare_permission(folded: str) -> bool:
    return bool(_PERMISSION.search(folded)) and not _GENERIC_SCOPE.search(folded)


#: Verbs that make the rest of a sentence an assertion (finite or auxiliary forms), after the deferral is removed.
_FINITE = set("""
is are was were has have had does did will would shall can could may might must am é sao esta estao foi foram era
eram sera serao seria tem teem tinha tinham ha houve possui possuem dispoe dispoem detem vai vao deve devem pode podem
precisa precisam requer requerem exige exigem carece carecem received obtained granted issued approved confirmed
""".split())
_COMPETENCE = set("""
competent competence responsible handles handle handled deals deal decides decide decided processes process
assesses assess trata tratam compete competente competentes responsavel responsaveis decide decidem aprecia
""".split())


#: Recommendations to act through the authority, at the start of the atom, beyond ``_DEFERRAL``'s checking verbs.
_IMPERATIVE = re.compile(r"^\s*(?:please\s+)?(?:contact|contacte|contactar|apply|submit|requerer|submeta|submeter|"
                         r"consult|ask|request|pergunte|solicite)\b")


def _deferral_rest(atom: str) -> str | None:
    """The part of a deferral/recommendation atom that is still asserted, or None if the atom is not one."""
    folded = _fold(atom.lower())
    m = _DEFERRAL.search(folded) or _IMPERATIVE.search(folded)
    if m is None or "pending" in m.group():  # "the licence is pending" says an application exists
        return None
    # A question before the deferral is deferred whole; after it, it ends at a coordinator, so a clause coordinated
    # after the deferral stays asserted (FP-4 review: "… must be confirmed … and the property is approved").
    return f"{_UNASSERTED.sub(' ', folded[:m.start()])} {_UNASSERTED_BOUNDED.sub(' ', folded[m.end():])}"


#: A clause boundary: a comma, colon or bracket, a coordinator or a relative pronoun.
_BOUNDARY = re.compile(r"[,;:(]|\b(?:and|e|but|mas|yet|porem|contudo|which|that|who|whose|que|o qual|a qual|"
                       r"os quais|as quais|cujo|cuja)\b")


def _coordinated_clause(atom: str) -> str | None:
    """The clause before a deferral when a clause boundary separates them; it is an assertion of its own: "The
    property remains licensed *and* must be confirmed", "The property holds a licence*, which* must be confirmed"
    assert "The property remains licensed" / "holds a licence" (MU-9 P1: no assertion is dropped because it shares
    a sentence with a deferral). Only a noun phrase directly followed by the deferral ("The property's licensed use
    must be confirmed") is the deferral's own object."""
    folded = _fold(atom.lower())
    m = _DEFERRAL.search(folded) or _IMPERATIVE.search(folded)
    if m is None:
        return None
    # Folding keeps offsets when accented letters are precomposed (the usual case); otherwise use the folded text.
    prefix = atom[:m.start()] if len(atom) == len(folded) else folded[:m.start()]
    # The last clause boundary before the deferral, anywhere ("… a licence and it must be confirmed"), ignoring the
    # boundaries inside the question being deferred ("Whether X and Y must be confirmed").
    masked = _UNASSERTED.sub(lambda q: " " * len(q.group()), _fold(prefix.lower()))
    cuts = [b for b in _BOUNDARY.finditer(masked)]
    if not cuts:
        return None
    clause = prefix[:cuts[-1].start()].strip(" ,;:(")
    return clause if _tokens(clause) else None


def _asserts(rest: str) -> bool:
    tokens = _tokens(rest)
    return any(t in _FINITE for t in tokens) or bool(re.search(r"\b\w+(?:ed|ad[oa]s?|id[oa]s?)\s+(?:by|pel[oa]s?)\b",
                                                               rest))


def _bearer(tokens: list[str], text: str) -> str:
    if _matter_spans(tokens):
        return "matter"
    first = tokens[0] if tokens else ""
    # A fragment with no subject ("Approved by the Câmara.", "Licenciamento confirmado …") is about the matter.
    if re.match(r"^\s*\w{3,}(?:ed|ad[oa]s?|id[oa]s?)\b", _fold(text.lower())) or first in _FINITE:
        return "matter"
    if re.match(r"^\s*\w+\s+\w{3,}(?:ed|ad[oa]s?|id[oa]s?)\b", _fold(text.lower())) and _legal(_fold(text.lower())):
        return "matter"
    return "general"


#: Concepts that give their bearer a legal position: permission, obligation, negation, tense, possession.
_MODAL = {"PERM", "OBLIG", "NEG", "TENSE", "HAVE", "LICENSED_STATE", "GREEN_LIGHT", "LEGAL_CONDITIONS"}
#: Concepts that make a general statement a norm that must be proven: a duty, numbers, limits, units, exceptions,
#: exclusivity. (A hedged possibility — "may depend on the plan" — stays a shadow verdict in Phase 1.)
_PRECISE = {"OBLIG", "UPTO", "ATLEAST", "M2", "PCT", "EXC", "ONLY"}
#: Words a restatement of the case records may add: location verbs and prepositions.
_LOCATION_WORDS = {"located", "situated", "lies", "sits", "localizado", "localizada", "situado", "situada", "fica",
                   "situa", "encontra", "parish", "freguesia", "municipality", "concelho", "district", "distrito"}


_MODAL_AUX = {"may", "can", "might", "could", "pode", "podem", "podera", "poderao", "poderia", "poderiam"}
_COPULA = {"is", "are", "be", "é", "está", "sao", "estao", "fica", "ficam", "remains", "remain"}
_SKIP = {"be", "ser", "also", "still", "tambem", "ainda", "then", "entao", "now", "agora"}
_PERMITTING = re.compile(r"^(?:permitted|permissible|allowed|admissib\w*|admissiv\w*|admitid\w*|permitid\w*)$")
#: Verbs of dependency or uncertainty after a modal: "may depend on the plan" permits nothing.
_DEPENDENCY_VERB = re.compile(r"^(?:depend|vary|vari|differ|change|mudar)\w*$")
#: An explicit dependency clause keeps a permission hedged: "may be admissible, depending on the land category".
_DEPENDENCY_CLAUSE = re.compile(r"\b(?:depending on|dependendo d\w*|consoante|conforme|according to|subject to the "
                                r"(?:plan|category|rules))\b")


def _deontic_permission(tokens: list[str], folded: str) -> bool:
    """Whether the atom asserts a permission as its predicate: a modal followed by a main verb ("building operations
    may proceed", "pode avançar"), or a copula followed by a permission word ("two dwellings are permitted"). A
    permission named attributively ("the admissible uses", "os usos admitidos") or hedged by an explicit dependency
    clause asserts nothing here (Phase 1 records it in shadow)."""
    if _DEPENDENCY_CLAUSE.search(folded):
        return False
    for i, t in enumerate(tokens):
        nxt = [w for w in tokens[i + 1:i + 4] if w not in _SKIP]
        if not nxt:
            continue
        if t in _MODAL_AUX and not _DEPENDENCY_VERB.match(nxt[0]):
            return True
        if t in _COPULA and _PERMITTING.match(nxt[0]):
            return True
    return False


def _precise(concepts: list[tuple[str, set[str]]], tokens: list[str] = (), folded: str = "") -> bool:
    """A norm that must be proven: a duty, a number, limit, unit, exception or exclusivity, or a permission asserted
    as the predicate (``_deontic_permission``)."""
    if any(c in _PRECISE or c.startswith("NUM:") for _, alts in concepts for c in alts):
        return True
    return _deontic_permission(list(tokens), folded)




def _normative(concepts: list[tuple[str, set[str]]], tokens: list[str], folded: str, legal: bool) -> bool:
    """A normative statement (owner decision, ACC-QO-09 / ACC-ROLE-01): a legal instrument, or a requirement, duty,
    permission asserted as the predicate, prohibition, number, limit, unit, exception or exclusivity. Its words can be
    checked against the passage, but not their grammatical roles (which noun is the object, which the scope), so it
    is supported only as the passage's own wording. A permission named as an object ("defines the admissible uses")
    or hedged by a dependency ("may depend on the plan") grants nothing and stays descriptive. A prohibition, or an
    act that removes or overrides a duty (revokes, repeals, suspends, waives, exempts), is normative too, and so is a
    use designation ("os espaços destinam-se a …", "intended for …"): it says which uses the land admits."""
    return (legal or _precise(concepts, tokens, folded) or bool(_DEONTIC_WORDS.search(folded))
            or any("INTENDED" in alts for _, alts in concepts) or _stative(tokens, folded))


#: A participle or a "-vel" / "-ble" adjective: the form of a legal state ("consentida", "autorizadas", "allowed",
#: "admissível", "permissible"), whatever the verb.
_STATE_FORM = re.compile(r"^\w{3,}(?:ad[oa]s?|id[oa]s?|ed|vel|veis|ble)$")


def _stative(tokens: list[str], folded: str) -> bool:
    """Whether a copula gives its subject a state ("a edificação é consentida", "works are allowed", "o uso é
    admissível"). Decided by the form of the predicate, not by a list of permission words. A possibility under an
    explicit dependency ("may be admissible, depending on the land category") asserts no state."""
    if _DEPENDENCY_CLAUSE.search(folded) and _MODAL_AUX & set(tokens):
        return False
    for i, t in enumerate(tokens):
        if t in _COPULA | {"ficam", "estao", "sejam", "seja", "esteja", "estejam", "being", "been"}:
            nxt = [w for w in tokens[i + 1:i + 4] if w not in _SKIP and w not in {"not", "nao", "never", "nunca"}]
            if nxt and _STATE_FORM.match(nxt[0]):
                return True
    return False


def _restates_case_records(tokens: list[str], cited: list[Evidence]) -> tuple[str, ...]:
    """The case records (property, jurisdiction, authority) a matter atom only restates, or () if it says more."""
    records = [e for e in cited if e.source_type in ("property_record", "jurisdiction_record", "authority_record")]
    corpus = {t for e in records for t in _tokens(" ".join((e.excerpt, e.source_title, e.source_reference)))}
    content = [t for i, t in enumerate(tokens) if i not in _matter_spans(tokens) and t not in _FUNCTION
               and not t.isdigit()]
    if records and all(t in corpus or t in _LOCATION_WORDS for t in content):
        return tuple(e.evidence_id for e in records)
    return ()


_ATTRIBUTION = "segundo under according acordo termos per pdm plano plan regulamento regulation municipal director"


def _restates(concepts: list[tuple[str, set[str]]], cited: list[Evidence]) -> bool:
    """Whether the atom restates one sentence of a cited official passage: every concept it uses is that sentence's
    (a role swap keeps them all: "Nas operações de estacionamento, a edificação carece de …"). Its content is then
    the sentence's, whatever its vocabulary, so it is held to the sentence's own wording like a normative statement.
    Decided by the passage, not by spotting deontic words."""
    for e in cited:
        if is_official_text(e):
            # Attribution to the cited source ("Segundo o PDM, …", "Under the PDM-Cascais regulation, …") frames the
            # restatement; it doesn't make it say something else.
            framing = {c for _, alts in _concepts_of(_tokens(f"{e.source_title} {_ATTRIBUTION}")) for c in alts}
            # A deontic word is never mere framing (a title "Usos Admissíveis" doesn't make "usos permitidos" the
            # source's own wording; ACC-NRM-45): admissível, permitido, obrigatório … are not interchangeable.
            content = [alts for _, alts in concepts
                       if alts != {"COND"} and (not alts <= framing or alts & _DEONTIC_CONCEPTS)]
            if len(content) < 2:
                continue
            for s in _passage_sentences(e):
                if all(alts & s.allowed for alts in content):
                    return True
    return False


def _directional(tokens: list[str], cited: list[Evidence], verbatim: bool = False,
                 text: str = "", literal: bool = False,
                 whole: str | tuple[str, ...] | None = None) -> tuple[tuple[str, ...], bool]:
    """(supporting evidence ids, quote_required): the ids are empty when nothing supports the atom;
    ``quote_required`` says a cited sentence would support it as a literal quote. ``literal``: only the sentence's
    own wording supports it (a normative statement, see ``_normative``)."""
    concepts = _concepts_of(tokens)
    exceptions = _exceptions(text)
    main = _main_concepts(text, tokens)
    quote_required = False
    for e in cited:
        if is_official_text(e):
            for s in _passage_sentences(e):
                if (not literal or _literal(whole or text, s)) and _supports(concepts, s, verbatim, exceptions, main):
                    return (e.evidence_id,), False
                quote_required = quote_required or ((literal or len(s.limits) >= 2)
                                                    and _supports(concepts, s, True, exceptions, main))
    return (), quote_required


_UNSUPPORTED = ("is not supported, in the direction stated, by any one sentence of the official text it cites (it "
                "adds or drops a condition, alternative, limit, exception, status, tense or object)")
_QUOTE_REQUIRED = ("restates a normative rule (a requirement, duty, permission, prohibition, number, limit or "
                   "exception) in its own words; such a rule can only be stated as a literal quote of the official "
                   "passage (planning_basis general_rule)")


def _explanation_atom(atom: str, cited: list[Evidence], verbatim: bool = False,
                      whole: str | tuple[str, ...] | None = None) -> Atom:
    """A general explanation atom. Enforced when it touches a legal instrument or outcome, or gives the matter a legal
    position; otherwise the planning contract decides and the directional verdict is recorded in shadow.

    ``verbatim``: a literal quote that HABITA rendered from a cited record (``general_rule``). Its bearer is the
    source itself, so it is not read for references to the matter; it must be one whole official sentence, still
    supported by it (a partial quote can't drop a limit, condition or exception)."""
    tokens = _tokens(atom)
    folded = _fold(atom.lower())
    legal = _legal(folded)
    if verbatim:
        # A quote is held to the whole sentence: a part can leave out a condition in any wording.
        supported, _ = _directional(tokens, cited, verbatim=True, text=atom, literal=True, whole=whole)
        # Every quote is enforced: a quote that is not one whole, supporting official sentence is never certified,
        # whatever it says (ACC-NRM-11).
        enforced = True
        return Atom(atom, "general_rule" if supported else "unsupported", "source", supported,
                    None if supported else _UNSUPPORTED, enforced=enforced)
    bearer = "matter" if _bare_permission(folded) else _bearer(tokens, atom)
    legal = legal or bearer == "matter" and bool(_PERMISSION.search(folded))
    if (clause := _coordinated_clause(atom)) is not None:
        inner = _explanation_atom(clause, cited)
        if inner.problem and inner.enforced:
            return Atom(atom, inner.kind, inner.bearer, (), inner.problem)
    if (rest := _deferral_rest(atom)) is not None:
        if _asserts(rest) and (legal or _matter_spans(_tokens(rest))):
            return Atom(atom, "legal_status" if legal else "unsupported", bearer, (),
                        "defers to the authority but still asserts something about the matter")
        return Atom(atom, "deferral", bearer, (), None)
    conditional = bool(tokens) and tokens[0] in {"if", "se", "caso", "where", "when", "quando"}
    matter = _matter_spans(tokens)
    if conditional:
        # The matter may be named only inside the antecedent (up to the first comma), never in the consequence.
        antecedent = len(_tokens(atom.split(",", 1)[0])) if "," in atom else 0
        if any(i >= antecedent for i in matter):
            return Atom(atom, "legal_status" if legal else "unsupported", "matter", (),
                        "attributes the rule's consequence to this matter outside an 'if' condition")
        tokens = [t for i, t in enumerate(tokens) if i not in matter]
    elif matter or bearer == "matter":
        positioned = {c for _, alts in _concepts_of(tokens) for c in alts} & _MODAL
        if legal or positioned:
            kind = "legal_status" if legal else "unsupported"
            return Atom(atom, kind, "matter", (), _no_provider(kind) or
                        "gives this matter a legal position (permission, obligation, exemption, possession or a past "
                        "or future outcome) that a general rule can't establish")
        # Context about the matter: only what its own case records say (where it is, who decides).
        if records := _restates_case_records(tokens, cited):
            return Atom(atom, "case_fact", "matter", records, None)
        return Atom(atom, "unsupported", "matter", (),
                    "says something about this matter that its cited case records don't state; a general rule can't "
                    "establish it")
    normative = _normative(_concepts_of(tokens), tokens, folded, legal) or _restates(_concepts_of(tokens), cited)
    supported, quote_required = _directional(tokens, cited, verbatim, text=atom, literal=normative, whole=whole)
    kind = ("conditional_rule" if conditional else "general_rule") if supported else "unsupported"
    # An unsupported statement stays a shadow verdict only when it is about the plan's structure (allowlist below);
    # anything else it asserts is held to its cited text, whatever its words.
    enforced = normative or not (supported or _meta_descriptive(tokens, folded, cited))
    problem = None if supported else _QUOTE_REQUIRED if quote_required else _UNSUPPORTED
    return Atom(atom, kind, "general", supported, problem, enforced=enforced)


#: Predicates that describe what an instrument does or how rules relate, without stating a rule's content: "the PDM
#: classifies and qualifies land", "each zone has specific rules", "housing use may depend on the plan".
_META = re.compile(
    r"\b(?:classif\w*|qualif\w*|defin\w*|establish\w*|estabelec\w*|sets?|regul\w*|determin\w*|condicion\w*|"
    r"condition\w*|depend\w*|vari\w*|differ\w*|consta\w*|contain\w*|cont[eé]m|identif\w*|delimit\w*|organi[sz]\w*|"
    r"divid\w*|specific|especific\w*|check\w*|verific\w*|segue|seguem|follows?|apply|applies|aplica|aplicam|"
    r"governs?|governed)\b")
#: Words after which "as" is the PT feminine plural article, not the EN predicative "as".
_PT_BEFORE_ARTICLE = {"e", "ou", "de", "todas", "com", "para", "sobre", "entre", "por", "segundo", "sob", "que", "nem",
                      "ambas", "segue", "seguem", "define", "definem", "regula", "regulam", "estabelece", "estabelecem"}
_NEGATION = {"not", "nao", "never", "nunca", "nenhum", "nenhuma", "none", "nem", "nor", "sem", "without", "doesn",
             "don", "isn", "aren"}
_APPLICABILITY = re.compile(r"\b(?:segue|seguem|follows?|apply|applies|applied|aplica|aplicam|aplicar|aplicado|"
                            r"aplicada|governs?|governed|rege|regem|regido|regida|subordin\w*)\b")
#: What a structural statement may say applies: the plan's own rules, not a regime of its choosing.
_GENERIC_RULES = {"regras", "regra", "rules", "rule", "plano", "plan", "planos", "plans", "municipal", "aplicavel",
                  "aplicaveis", "applicable", "respetivo", "respetiva", "respective", "pdm", "regulamento", "regulation",
                  "urbanisticas", "urbanistica", "urbanisticos", "own", "proprio", "propria", "proprias", "its"}
#: …unless it introduces content of its own: "o PDM define que …", "the plan establishes that …".
_CONTENT_CLAUSE = re.compile(r"\b(?:que|that)\b")


#: Planning topics a structural description may name ("each zone or district", "the land-use category", "urban
#: parameters"). Closed: any other word is a claim of the statement's own.
_TOPIC_STEMS = ("zon", "distrit", "district", "categor", "parametr", "parameter", "municip", "plan", "dwelling", "fogo",
                "habitacion", "residenc", "residential", "which", "segund", "second", "qual", "classif", "rustic",
                "rural", "espac", "space", "solo", "land", "uso", "use", "rule", "regra", "regime", "lote", "parcel",
                "terren", "imovel", "propert", "local", "area", "map", "plant", "ordenament", "territor",
                # dependency and reference words: "consoante a zona", "qualifies it", "as respetivas regras"
                "consoant", "conform", "depending", "according", "acordo", "it", "its", "they", "their", "respetiv",
                "respectiv", "cada", "each", "own", "proprio", "propria")


_DEONTIC_CONCEPTS = (_RESTRICTIVE - {"ALL", "SOME", "COND"}) | {"LICENSED_STATE", "LICENSING", "GREEN_LIGHT",
                                                                 "LEGAL_CONDITIONS"}


def _adds_nothing(tokens: list[str], cited: list[Evidence]) -> bool:
    """Whether every content word of a structural description is a structural or generic word, the attribution to a
    cited source, or a concept of a cited official sentence: it describes the cited text and adds no claim of its own
    ("… ao critério do promotor", "… as an option" add one, whatever their wording)."""
    official = [e for e in cited if is_official_text(e)]
    allowed = {c for e in official for s in _passage_sentences(e) for c in s.allowed}
    framing = {c for e in official for _, alts in _concepts_of(_tokens(f"{e.source_title} {_ATTRIBUTION}")) for c in alts}
    words = list(tokens)
    hedged = bool(_DEPENDENCY_CLAUSE.search(" ".join(words)))
    for t, alts in _concepts_of(tokens):
        # Structure, generic rules, attribution (never for a deontic word: a title "Usos Admissíveis" frames nothing),
        # PT "no" ("in the"), planning topics, connectives.
        attribution = alts <= framing and not alts & _DEONTIC_CONCEPTS
        if _META.fullmatch(t) or t in _GENERIC_RULES or attribution or t == "no" or t.startswith(_TOPIC_STEMS) \
                or alts & {"CONJ", "DISJ", "ALL", "INCL"}:
            continue
        # "may depend on …", "pode ser admissível consoante …": a hedged possibility, not a permission.
        if alts == {"PERM"} and t in _MODAL_AUX and (hedged or (
                (i := words.index(t)) + 1 < len(words) and _DEPENDENCY_VERB.match(words[i + 1]))):
            continue
        # "os usos admissíveis", "which uses each zone admits": admissibility names a category of uses; qualifying
        # anything else ("a dotação … admissível") is a claim.
        deontic = bool(alts & _DEONTIC_CONCEPTS)
        if alts & allowed:
            if deontic:
                return False  # a duty, permission or limit taken from the cited text is its content, not structure
            continue
        # The closed concept table names what a structure is about, not a claim; a deontic or restrictive concept
        # ("allowed", "only", "never") is a claim unless the cited text has it. Admissibility has no exception, not even
        # "os usos admissíveis" (owner rule after ACC-NRM-37).
        if not any(c.startswith("w:") for c in alts) and not deontic:
            continue
        return False
    return True


def _meta_descriptive(tokens: list[str], folded: str, cited: list[Evidence] = ()) -> bool:
    """A predicate about the plan's structure that states no rule content ("the PDM classifies and qualifies land").
    A predicative complement ("classifies X as Y", "define X como Y") attributes content, whatever Y is."""
    if not _META.search(folded) or _CONTENT_CLAUSE.search(folded):
        return False
    # Which regime applies to what ("segue o regime …", "does not apply to …") is rule content, not structure.
    if _NEGATION & set(tokens):  # PT "no" is "in the", not a negation
        return False
    if not _adds_nothing(tokens, cited):
        return False
    if m := _APPLICABILITY.search(folded):
        if not all(t in _FUNCTION or t in _GENERIC_RULES for t in _tokens(folded[m.end():])):
            return False
    return not _predicative(tokens)


def _predicative(tokens: list[str]) -> bool:
    """A predicative complement after a structural verb ("classifies X as Y", "define X como Y"), anywhere after the
    verb however long the object (ACC-NRM-10). EN "as" needs an object between ("classifies land as"); after "e",
    "de", "todas" … it is the PT article ("define a dotação e as regras"), whatever the language of the rest."""
    return any((t == "como" and any(_META.match(w) for w in tokens[:i]))
               or (t == "as" and tokens[i - 1] not in _PT_BEFORE_ARTICLE
                   and any(_META.match(w) for w in tokens[:i - 1]))
               for i, t in enumerate(tokens))


def _no_provider(kind: str) -> str | None:
    if kind != "legal_status":
        return None
    return ("states the legal status of this matter (licence, permit, prior communication, approval, validity or "
            "exemption); that needs property-specific legal-status evidence, and no such source is available")


def _free_text_atom(atom: str, cited: list[Evidence]) -> Atom:
    folded = _fold(atom.lower())
    tokens = _tokens(atom)
    bearer = "matter" if _bare_permission(folded) else _bearer(tokens, atom)
    if not (_legal(folded) or bearer == "matter" and _PERMISSION.search(folded)):
        return Atom(atom, "other", bearer, (), None)  # the ordinary grounding rule decides
    if (clause := _coordinated_clause(atom)) is not None:
        inner = _free_text_atom(clause, cited)
        if inner.problem:
            return Atom(atom, inner.kind, inner.bearer, (), inner.problem)
    if (rest := _deferral_rest(atom)) is not None:
        if _asserts(rest):
            return Atom(atom, "legal_status", bearer, (), "defers to the authority but still asserts a legal status")
        return Atom(atom, "deferral", bearer, (), None)
    authorities = [e for e in cited if e.source_type == "authority_record" and not is_user_declared(e)]
    for e in authorities:
        record = set(_tokens(" ".join((e.excerpt, e.source_title))))
        names = set(_tokens(e.source_title))
        words = [t for t in tokens if t not in _FUNCTION]
        if (bearer != "matter" and names & set(tokens) and (_COMPETENCE & set(tokens) or ":" in atom)
                and all(t in record or t in _COMPETENCE for t in words)):
            return Atom(atom, "authority_competence", "authority", (e.evidence_id,), None)
    if bearer == "matter":
        return Atom(atom, "legal_status", bearer, (), _no_provider("legal_status"))
    return Atom(atom, "legal_status", bearer, (),
                "makes a legal claim (licence, permit, prior communication, approval, validity or exemption) that "
                "its cited records can't prove: only an authority's own competence wording or a deferral is "
                "admissible here")


def atoms(text: str) -> list[str]:
    return [a.strip() for a in _sentences(text) if _tokens(a)]


def assess(text: str, basis: str, step: str | None, cited: list[Evidence]) -> list[Atom]:
    """The atoms of one model statement, each with its verdict. Rendered statements are HABITA's own text."""
    cited = [e for e in cited if not is_user_declared(e)]
    if basis == "general_rule":
        # A verbatim quote is the source's own words, but a partial one can drop the rule's scope, alternatives or
        # exceptions ("deve ser assegurada a dotação de estacionamento"): it is held to the same support check.
        # The literal test reads the whole sentence each clause belongs to: a clause ending in ";" is not a sentence.
        return [_explanation_atom(a, cited, verbatim=True, whole=w) for w, a in _statement_clauses(text)]
    if basis in RENDERED:
        return []
    if basis == EXPLANATION:
        body = text[len(EXPLANATION_FRAME):] if text.startswith(EXPLANATION_FRAME) else text
        return [_explanation_atom(a, cited, whole=w) for w, a in _statement_clauses(body)]
    full = ". ".join(filter(None, (step, text)))
    return [_free_text_atom(a, cited) for a in atoms(full)]


def capability_problem(atom: Atom, cited: list[Evidence]) -> str | None:
    """Whether some cited record has a capability that can prove the atom's kind."""
    if atom.kind in NEEDS_NO_SUPPORT:
        return None
    capabilities = {c for e in cited for c in evidence_capabilities(e)}
    if not any(atom.kind in CAN_PROVE.get(c, frozenset()) for c in capabilities):
        return _no_provider(atom.kind) or f"is a {atom.kind.replace('_', ' ')} that none of its cited records can prove"
    return None


def verdict(atom: Atom, cited: list[Evidence]) -> tuple[str, str | None]:
    """("supported" | "no_support_needed" | "rejected", reason)."""
    if problem := atom.problem or capability_problem(atom, cited):
        return "rejected", problem
    return ("no_support_needed" if atom.kind in NEEDS_NO_SUPPORT or atom.kind == "deferral" else "supported"), None


def legal_claim_problem(text: str, basis: str, step: str | None, cited: list[Evidence]) -> str | None:
    for atom in assess(text, basis, step, cited):
        if not atom.enforced:
            continue
        if problem := atom.problem or capability_problem(atom, cited):
            return f"(\"{atom.text}\") {problem}"
    return None
