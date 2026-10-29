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
  consequent.
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
    _DEFERRAL, _UNASSERTED, EXPLANATION, EXPLANATION_FRAME, _sentences, evidence_capabilities, is_official_text,
    is_user_declared,
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
    ("EXC", ("except", "excepto", "exceto", "salvo", "unless", "excluding")),
    ("INCL", ("including", "incluindo", "nomeadamente", "designadamente", "namely")),
    ("COND", ("if", "se", "caso", "where", "when", "quando")),
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
_DEFINITE = {"the", "o", "a", "os", "as", "do", "da", "dos", "das", "no", "na", "nos", "nas", "ao", "pelo", "pela"}


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
            out |= {i - 1, i}
    return out


# --- official passages -------------------------------------------------------------------------------------------

_HEADER = re.compile(r"^.*?\bartigo\s+\d+\.?\s*[oº]?(?!\w).*?(?<!\d)\d+\s*-\s+", re.IGNORECASE)
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
    sequence: tuple[frozenset, ...] = ()  # its concepts in order (see ``_aligned``)


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


def _aligned(concepts: list[tuple[str, set[str]]], sequence: tuple[frozenset, ...]) -> bool:
    """Whether the atom's concepts appear in the passage sentence's order. Each concept is matched to the next unused
    occurrence after the last match; the one occurrence just before it is also allowed, so adjacent pairs may swap,
    as EN and PT order them differently ("construction area" / "área de construção", "single-family houses" /
    "moradias unifamiliares"). A concept placed where the passage doesn't have it breaks the alignment."""
    used: set[int] = set()
    last = -1
    for _, alts in concepts:
        if last - 1 >= 0 and last - 1 not in used and alts & sequence[last - 1]:
            used.add(last - 1)
            continue
        j = next((j for j in range(last + 1, len(sequence)) if j not in used and alts & sequence[j]), None)
        if j is None:
            return False
        used.add(j)
        last = j
    return True


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


def _same_pair(a: frozenset, b: frozenset) -> bool:
    """Two conjunct pairs match when each conjunct shares a concept with one of the other pair's."""
    a, b = list(a), list(b)
    if len(a) != len(b):
        return False
    if len(a) == 1:
        return bool(a[0] & b[0])
    return bool((a[0] & b[0] and a[1] & b[1]) or (a[0] & b[1] and a[1] & b[0]))


def _passage_sentences(e: Evidence) -> list[_Sentence]:
    text = e.excerpt.lower()  # folded by _tokens, which keeps PT "é" apart from "e"
    out = []
    for paragraph in _PARAGRAPH.split(_HEADER.sub("", text, count=1)):
        for sentence in _sentences(re.sub(r"^\s*\d+\s*-\s*", "", paragraph)):
            concepts = _concepts_of(_tokens(sentence))
            core_concepts = _concepts_of(_tokens(_INCLUSION.sub(" ", sentence)))
            allowed = {c for _, alts in concepts for c in alts}
            core = {frozenset(alts) for _, alts in core_concepts}
            required = {next(iter(a)) if len(a) == 1 else min(a) for a in core} - {"INCL"}
            if allowed:
                out.append(_Sentence(e.evidence_id, frozenset(allowed), frozenset(required),
                                     frozenset(_slots(concepts)), frozenset(_slots(core_concepts)),
                                     _limits(concepts), tuple(frozenset(alts) for _, alts in concepts)))
    return out


def _supports(atom_concepts: list[tuple[str, set[str]]], s: _Sentence) -> bool:
    # An added "if" only narrows a rule's scope; every other concept must be in the sentence.
    if not all(alts & s.allowed or alts == {"COND"} for _, alts in atom_concepts):
        return False
    present = {c for _, alts in atom_concepts for c in alts}
    if not all(r in present or (_ALTERNATIVES.get(r, set()) & present) for r in s.required):
        return False
    # Bound slots, both ways: no number, limit, unit or alternative moved to another place or changed, none dropped.
    concepts = [(t, alts) for t, alts in atom_concepts if alts != {"COND"}]
    if len(s.limits) >= 2:
        # A rule with several numeric limits (MU-9 V2): which limit binds which quantity can't be read from a window
        # around each number, so the whole atom must follow the passage sentence in order (``_aligned``): each limit
        # keeps its comparator, unit and the quantity before it, and nothing is attached to it that the passage
        # doesn't have there. Any other paraphrase has to be quoted (general_rule).
        return _limits(concepts) == s.limits and _aligned(concepts, s.sequence)
    # Bound slots, both ways: no number, limit, unit or alternative moved to another place or changed, none dropped.
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
    r"covered|abrangid\w*)")
#: Permission words. A permission with no explicit general scope ("Two dwellings are permitted", "São permitidos
#: dois fogos") is about the matter (MU-9 M1); with one ("in urban land", "each category", "depending on …") it is a
#: general statement.
_PERMISSION = re.compile(r"\b(?:permitted|permissible|permitid\w*|permite\w*|allow\w*|admit\w*|admiss\w*)\b")
_GENERIC_SCOPE = re.compile(
    r"\b(?:each|every|any|cada|qualquer|tod[oa]s?|depending|depend\w*|consoante|conforme|according)\b"
    r"|\b(?:in|em|no|na|nos|nas|within|under|for)\s+(?:\w+\s+){0,3}?(?:land|solo|zones?|zonas?|areas?|categor\w*|"
    r"espac\w*|operations?|operac\w*|districts?|distritos?|plans?|planos?|spaces?)\b")


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
    return _UNASSERTED.sub(" ", folded[:m.start()] + " " + folded[m.end():])


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


def _restates_case_records(tokens: list[str], cited: list[Evidence]) -> tuple[str, ...]:
    """The case records (property, jurisdiction, authority) a matter atom only restates, or () if it says more."""
    records = [e for e in cited if e.source_type in ("property_record", "jurisdiction_record", "authority_record")]
    corpus = {t for e in records for t in _tokens(" ".join((e.excerpt, e.source_title, e.source_reference)))}
    content = [t for i, t in enumerate(tokens) if i not in _matter_spans(tokens) and t not in _FUNCTION
               and not t.isdigit()]
    if records and all(t in corpus or t in _LOCATION_WORDS for t in content):
        return tuple(e.evidence_id for e in records)
    return ()


def _directional(atom: str, tokens: list[str], cited: list[Evidence], conditional: bool) -> tuple[str, ...] | None:
    concepts = _concepts_of(tokens)
    for e in cited:
        if is_official_text(e):
            if any(_supports(concepts, s) for s in _passage_sentences(e)):
                return (e.evidence_id,)
    return None


_UNSUPPORTED = ("is not supported, in the direction stated, by any one sentence of the official text it cites (it "
                "adds or drops a condition, alternative, limit, exception, status, tense or object)")


def _explanation_atom(atom: str, cited: list[Evidence]) -> Atom:
    """A general explanation atom. Enforced when it touches a legal instrument or outcome, or gives the matter a legal
    position; otherwise the planning contract decides and the directional verdict is recorded in shadow."""
    tokens = _tokens(atom)
    folded = _fold(atom.lower())
    legal = _legal(folded)
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
    supported = _directional(atom, tokens, cited, conditional)
    kind = ("conditional_rule" if conditional else "general_rule") if supported else "unsupported"
    enforced = legal or _precise(_concepts_of(tokens), tokens, folded)
    return Atom(atom, kind, "general", supported or (), None if supported else _UNSUPPORTED, enforced=enforced)


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
        return [_explanation_atom(a, cited) for a in atoms(text)]
    if basis in RENDERED:
        return []
    if basis == EXPLANATION:
        body = text[len(EXPLANATION_FRAME):] if text.startswith(EXPLANATION_FRAME) else text
        return [_explanation_atom(a, cited) for a in atoms(body)]
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
