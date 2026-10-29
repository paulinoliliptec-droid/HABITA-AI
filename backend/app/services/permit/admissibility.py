"""Which evidence a matter may rely on *now* (Codex HR-003 CX-1, CX-2).

Evidence records are history: they are never deleted, and keep the provenance they had
when collected. Whether a record is *admissible* is decided at use time, against the
current registry. Reconciliation, the drafter's prompt and the verifier all use only
admissible records, so a source retired after retrieval can no longer satisfy a
checklist item or support a VERIFIED outcome; restoring it to ``trusted`` makes its
records admissible again.

Parcel zoning (CX-1): a statement that places the parcel in a land-use class or
category is admissible only when it cites an authoritative planning determination for
this property (a ``resolved`` planning context from a trusted source). General law,
the PDM Regulamento's text, the FAQ or a manual-confirmation context never prove a
parcel's category. Detection is deterministic and deliberately conservative: naming a
category in a sentence about the parcel counts as an assertion.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.schemas.permit import Evidence, PermitMatter

#: Evidence that must come from a trusted registry source.
SOURCED = {"regulatory_source", "planning_context"}


def source_problem(e: Evidence, trusted_sources: set[str]) -> str | None:
    """Why sourced evidence can't be relied on, or None. Legacy (HR-002) records fall back to structured.source_id."""
    source_id = e.provenance.source_id if e.provenance else e.structured.get("source_id")
    if not source_id:
        return "has no source provenance"
    if source_id not in trusted_sources:
        return f"comes from {source_id}, which is not currently a trusted official source for this jurisdiction"
    if e.verification_status == "official_text" and not (e.provenance and e.provenance.snapshot_id and e.provenance.sha256):
        return "is official text without a pinned snapshot"
    return None


def inadmissibility(e: Evidence, matter: PermitMatter, chain: list[str], trusted_sources: set[str]) -> str | None:
    """Why a record can't support this matter now, or None if it can."""
    if e.matter_id != matter.matter_id:
        return "belongs to another matter"
    if e.jurisdiction_id not in chain:
        return f"belongs to {e.jurisdiction_id}, outside this property's jurisdiction"
    if e.source_type in SOURCED and (problem := source_problem(e, trusted_sources)):
        return problem
    if e.source_type == "planning_context" and e.structured.get("property_id") != matter.property_id:
        return "is a planning context for another property"
    return None


@dataclass(frozen=True)
class Excluded:
    evidence_id: str
    reason: str


def partition(
    evidence: list[Evidence], matter: PermitMatter, chain: list[str], trusted_sources: set[str]
) -> tuple[list[Evidence], list[Excluded]]:
    admissible, excluded = [], []
    for e in evidence:
        reason = inadmissibility(e, matter, chain, trusted_sources)
        if reason is None:
            admissible.append(e)
        else:
            excluded.append(Excluded(e.evidence_id, reason))
    return admissible, excluded


# --- evidence capabilities (HR-003 CX-1 / MU-3) ---------------------------------------------
#
# What a record may establish is decided by its *type* (source type, verification status, provenance),
# never by its wording. In particular, anything the user declared has exactly one capability,
# ``user_declaration``: it can be shown back to the user as their own (unverified) statement, and can
# support nothing else, least of all the parcel's planning.

USER_DECLARATION = "user_declaration"
#: Each capability a record can carry, and what it permits.
CAPABILITIES = {
    "parcel_determination": "state this parcel's planning classification (official, resolved, this property)",
    "planning_deferral": "say that the parcel's planning must be confirmed with the authority",
    "official_rule": "support a general planning rule or explanation (official text)",
    "rule_summary": "support a general rule (curated reference)",
    "case_fact": "support a fact of the case resolved by HABITA (location, jurisdiction, authority)",
    USER_DECLARATION: "be shown, verbatim and attributed, as the user's own unverified statement",
}


def is_user_declared(e: Evidence) -> bool:
    return e.source_type == "user_statement" or e.verification_status == "user_declared"


def evidence_capabilities(e: Evidence) -> frozenset[str]:
    if is_user_declared(e):  # whatever else the record claims to be
        return frozenset({USER_DECLARATION})
    if e.source_type == "planning_context" and e.verification_status == "system_record":
        authoritative = (e.provenance is not None and e.provenance.basis == "planning_context"
                         and e.structured.get("authoritative_determination") is True
                         and e.structured.get("status") == "resolved")
        return frozenset({"planning_deferral", "parcel_determination"} if authoritative else {"planning_deferral"})
    if e.source_type == "regulatory_source":
        return frozenset({"official_rule"} if e.verification_status == "official_text" else {"rule_summary"})
    if e.source_type in ("property_record", "jurisdiction_record", "authority_record"):
        return frozenset({"case_fact"})
    return frozenset()


def supports(e: Evidence, capability: str) -> bool:
    return capability in evidence_capabilities(e)


def is_determination(e: Evidence, matter: PermitMatter) -> bool:
    """An authoritative, parcel-specific planning determination (set by HABITA code, never the model)."""
    return (
        supports(e, "parcel_determination")
        and e.source_type == "planning_context"
        and e.structured.get("authoritative_determination") is True
        and e.structured.get("status") == "resolved"
        and e.structured.get("property_id") == matter.property_id
        and bool(e.structured.get("classification"))
    )


# --- planning contract for model statements (CX-1) -------------------------------------------
#
# The model's free text is never what certifies planning content. Every statement declares a
# ``planning_basis`` and the verifier checks it structurally:
#
# - ``general_rule`` / ``authority_confirmation`` / ``parcel_determination``: the statement's text is
#   produced by HABITA (``render_draft``): a verbatim passage of a cited regulatory record, HABITA's own
#   planning condition, or HABITA's rendering of an admissible determination for this property that
#   the current PlanningContextResolver still agrees with. The verifier requires *exact equality* with
#   that HABITA-derived text, so model wording cannot ride along, however it is paraphrased.
# - ``none``: the model's own words, admissible only as non-planning content: it may not cite planning
#   evidence, may not use planning vocabulary, and must be *grounded* in what it cites: every content
#   word must come from its cited records, the case facts (address, jurisdiction, authority) or a
#   small closed list of non-planning connective words, with no unexplained word. A parcel
#   claim assembled from general law, user facts or authority records cannot introduce the planning
#   meaning those records don't contain.
#
# Any mismatch between the declared basis, the cited evidence and the current resolver fails closed.

def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip(" .;:")


RENDERED_STEP = {
    "general_rule": "Applicable rule (quoted)",
    "authority_confirmation": "Confirm the planning position with the authority",
    "parcel_determination": "Official planning classification",
}
MIN_QUOTE = 20
#: Unexplained (ungrounded) words tolerated in a ``none`` statement: none. Every content word must come from the
#: cited records, the case facts or the closed connective list.
UNGROUNDED_ALLOWED = 0

#: PDM-Cascais land classes and categories (from the Regulamento's own vocabulary).
_CATEGORY = re.compile(
    r"\bsolo (?:urbano|rustico|rural)\b"
    r"|\bespacos? (?:centra(?:l|is)|habitaciona(?:l|is)|urbanos? infraestruturados?|urbanos?|"
    r"de atividades economicas|verdes?|natura(?:l|is)|agricolas?|florest(?:al|ais)|de ocupacao turistica|"
    r"de aglomerados rurais|rusticos?|de equipamentos|de infraestruturas|de reestruturacao|de uso especial|"
    r"estrategicos?|de recursos)"
    r"|\baglomerados? rura(?:l|is)\b"
)
#: Word stems that carry planning / land-use meaning; a ``none`` statement may not use them at all
#: (planning content has to come through a structured basis). A tightening, not the mechanism.
_PLANNING_STEMS = (
    "zon", "resid", "habitac", "urban", "rural", "rustic", "regime", "designat", "classif", "categor", "destin",
    "solo", "espac", "territor", "ordenament", "planning", "planta", "plano", "pdm", "master", "agric", "florest",
    "forest", "touris", "turis", "commerc", "industr", "mixed", "densit", "develop", "area", "spatial", "allocat",
    "earmark", "sector", "setor", "district", "perimet", "qualif", "housing", "neighbo", "bairro", "edificab",
    "buildab", "loteament", "parcel", "parcela",
)
_PLANNING_WORDS = {"plan", "plans", "lot", "lots", "lote", "lotes"}
_STOP = set("""
the and for with this that these those its it is are be been being was were has have had not no nor but or if of to in
on at by as an from into under over within per than then so such there here their they them can will do does did any
all each our we you your yours i me my without either neither he she his her him who whom whose which what when where why how also very just
only both either neither via upon about above below between before after while because thus therefore however since
o a os as um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para com sem que se e ou ao aos
este esta estes estas neste nesta nestes nestas isto esse essa isso aquele aquela seu sua seus suas lhe lhes ja nao
mais menos como quando onde qual quais entre sobre ate tambem muito pode podem deve devem ser sao foi estar esta
""".split())
#: Closed list of non-planning connective / assessment words a grounded statement may add. Deliberately excludes
#: permission and applicability words (rules, applicable, allowed, legal, approve …): those must come from evidence.
_META = set("""
condition conditions conditional conditionally confirm confirmed confirmation confirms subject possible possibly
likely may might must should need needs needed required require requires requirement requirements apply applies
applied applying application applications applicant submit submitted submission obtain request requested ask check
consult consulted official officially document documents documentation evidence assessment assess depend depends
dependent determine determined cannot could would further still yet whether case conclusion step steps risk risks
next action actions verify verified unverified answer answers information provided supplied given stated state
states said user listed list following outcome result results first second two three one new current currently
proposed separate separately independent independently own before after until unless proceed process competent
authority authorities responsible decide decision prior control note noted reference source sources cited
condicao condicoes condicional confirmar confirmacao confirmado sujeito sujeita possivel necessario necessaria
requer requisito requisitos pedido pedidos apresentar submeter antes depois apenas cada dois duas novo nova novos
atual proposta proposto verificar consultar oficial documento documentos avaliacao depende decidir decisao
competente autoridade
""".split())
_WORD = re.compile(r"[a-z]+")

#: A general planning explanation (how planning works, what must be checked) is the model's own wording. It needs an
#: admissible regulatory source and HABITA frames it as general. It may mention the property as context, but must
#: never attribute planning content to it: what makes a statement parcel-specific is that attribution, not its words.
EXPLANATION = "general_planning_explanation"
EXPLANATION_FRAME = "General planning explanation, not a determination for this property: "
EXPLANATION_STEP = "General planning context"
#: Singular specific reference to a property or place (the subject of a parcel determination). English and
#: Portuguese determiners are paired only with nouns of their own language (and gender), so "a local authority" or
#: "a house" (indefinite, generic) don't count. A definite article counts only with nouns that, in a permit matter,
#: always mean the subject property; demonstratives and possessives count with every place noun.
_EN_SPECIFIC = {"this", "that", "its", "my", "your", "our", "their", "his", "her"}
_EN_DEFINITE = {"the"}
_EN_PLACES = {"property", "parcel", "plot", "site", "lot", "building", "house", "home", "flat", "apartment", "premises",
              "address", "location", "street", "area", "zone", "district", "neighbourhood", "neighborhood", "land",
              "part", "place", "spot", "sector", "block"}
_EN_SUBJECTS = {"property", "parcel", "plot", "site", "premises", "house"}
_PT_SPECIFIC = {
    "m": {"este", "esse", "aquele", "deste", "desse", "daquele", "neste", "nesse", "naquele", "seu", "vosso", "meu"},
    "f": {"esta", "essa", "aquela", "desta", "dessa", "daquela", "nesta", "nessa", "naquela", "sua", "vossa", "minha"},
}
_PT_DEFINITE = {"m": {"o", "do", "no", "ao", "pelo"}, "f": {"a", "da", "na", "pela"}}
_PT_PLACES = {"m": {"imovel", "predio", "lote", "terreno", "edificio", "local", "sitio", "bairro", "quarteirao"},
              "f": {"casa", "parcela", "moradia", "fracao", "morada", "rua", "zona", "area", "freguesia", "localizacao"}}
_PT_SUBJECTS = {"m": {"imovel", "predio", "lote", "terreno"}, "f": {"casa", "parcela", "moradia"}}
_DEICTIC = {"here", "locally", "aqui", "ali", "onsite"}
_DEICTIC_PAIRS = {("on", "site"), ("in", "situ"), ("in", "loco"), ("no", "local")}


def has_planning_content(text: str) -> bool:
    return any(_planning_word(w) for w in _tokens(text)) or bool(_CATEGORY.search(fold(text)))


def _place_names(case_facts: list[Evidence]) -> set[str]:
    """The property's own address words (minus the names of its jurisdictions, which are general context):
    a general explanation that names the property's street or neighbourhood is about that place."""
    jurisdictions = {w for e in case_facts if e.source_type == "jurisdiction_record"
                     for lvl in e.structured.get("levels") or [] for w in _WORD.findall(fold(str(lvl.get("name", ""))))}
    return {w for e in case_facts if e.source_type == "property_record"
            for w in _tokens(str(e.structured.get("formatted_address") or ""))
            if len(w) >= 4 and w not in jurisdictions}


#: Predication that ties a property or place to something: being, lying, belonging, being classified / shown /
#: covered / admitted … (EN + PT). Only counted near a reference to the property (within ``_REACH`` words).
_ATTRIBUTION = set("""
is are was were be been being lies lie lying sits sit falls fall belongs belong stands located situated classified
zoned designated qualified included inserted integrated shown shows show marked mapped placed covered covers cover
governed has have having apply applies admitted admits allowed allows permitted permits appears coloured colored
assigned earmarked allocated reserved intended destined
e sao ser sera esta estao estar estara fica ficam situa situam situado situada localiza localizado localizada insere
inserem inserido inserida integra integrado integrada pertence pertencem enquadra enquadrado enquadrada classificado
classificada qualificado qualificada abrangido abrangida abrange incluido incluida inclui encontra encontram assinala
assinalado assinalada mostra tem possui aplica aplicam admite admitem admitido admitida permite permitem destinado
destinada afeto afeta
""".split())
_REACH = 6
#: What only the authority can settle, said as such: "must be confirmed", "deve ser verificada", "está por
#: confirmar", "has not yet been determined", "ainda não foi determinada", "is still unknown", "requires
#: confirmation". A copula inside it attributes nothing; what is left of the sentence is still checked.
_DEFERRAL = re.compile(
    r"\b(?:must|should|shall|will|needs? to|has to|have to|(?:is|are) to|deve(?:m|ra|rao)?|tem de|teem de|tera de|"
    r"precisa(?:m)? de|carece(?:m)? de|ha que|(?:esta|estao|fica|ficam) (?:por|a))\s+(?:(?:be|ser|still|ainda|first|"
    r"primeiro)\s+)*(?:confirm|check|verif|determin|assess|establish|clarif|apur|avali)\w*"
    r"|\b(?:is|are|has|have|was|were)\s+(?:not|never)\s+(?:yet\s+)?(?:been\s+)?"
    r"(?:confirm|determin|verif|establish|known|settled|resolved)\w*"
    r"|\b(?:remains?|is still|are still|is|are)\s+(?:to be\s+)?(?:unknown|unconfirmed|undetermined|pending)\b"
    r"|\bremains? to be\s+(?:confirm|determin|verif|establish)\w*"
    r"|\b(?:ainda\s+)?nao\s+(?:foi|foram|esta|estao|se encontra)\s+(?:ainda\s+)?"
    r"(?:determinad|confirmad|verificad|apurad|definid)\w*"
    r"|\b(?:e|esta|sao|estao)\s+(?:ainda\s+)?desconhecid\w*"
    r"|\bpor\s+(?:confirmar|determinar|verificar|apurar)\b"
    r"|\b(?:requires?|needs?|awaits?|requer|exige|carece de|aguarda)\s+(?:\w+\s+){0,2}?"
    r"(?:confirmation|verification|determination|confirmacao|verificacao|determinacao)\b"
    # An instruction to check, at the start of a sentence or clause ("Confirm … with the Câmara", "Verifique …").
    r"|(?:^|(?<=[,;:]))\s*(?:please\s+)?(?:confirm|check|verify|consult|request|ask|obtain|seek|clarify|confirme|"
    r"verifique|consulte|solicite|peca|obtenha|confirmar|verificar|consultar|solicitar|pedir|obter|esclarecer)\b")
#: Conditional / interrogative clauses ("if this parcel is …", "check whether …", "concluir se …") assert nothing.
#: PT "se" counts only at a clause start or after a verb of checking (it is also the reflexive in "situa-se").
_UNASSERTED = re.compile(
    r"\b(?:if|whether|unless)\b[^,;:.!?]*"
    r"|(?:^|(?<=[,;:.!?]))\s*(?:se|caso)\b[^,;:.!?]*"
    r"|\b(?:confirmar|verificar|apurar|saber|avaliar|confirme|verifique|concluir|decidir|determinar)\s+se\b[^,;:.!?]*")
_ABBREVIATIONS = {"art", "arts", "n", "no", "al", "cf", "eg", "ie", "etc", "p", "pp", "dr", "sr", "min", "max"}


def _sentences(text: str) -> list[str]:
    """Split on . ! ? ; — but not after an abbreviation or a number ("Art. 67.º")."""
    out, start = [], 0
    for m in re.finditer(r"[.!?;]+(?=\s|$)", text):
        before = _WORD.findall(text[start:m.start()])
        if m.group().startswith(".") and before and (before[-1] in _ABBREVIATIONS or text[m.start() - 1].isdigit()):
            continue
        out.append(text[start:m.end()])
        start = m.end()
    out.append(text[start:])
    return [x for x in out if x.strip()]


def _noun_at(nxt: list[str], nouns: set[str]) -> int:
    """Offset of the place noun among the (up to two) words after a determiner."""
    return next(k for k, w in enumerate(nxt) if w in nouns)


def _references(words: list[str], names: set[str], pronoun: bool) -> list[tuple[int, str]]:
    """(position, expression) for each reference to a particular property or place in ``words``."""
    refs = []
    for i, w in enumerate(words):
        nxt = words[i + 1:i + 3]  # the noun, possibly after one modifier ("this residential area")
        if w in _DEICTIC or tuple(words[i:i + 2]) in _DEICTIC_PAIRS:
            refs.append((i, w if w in _DEICTIC else " ".join(words[i:i + 2])))
        elif (w in _EN_SPECIFIC and _EN_PLACES & set(nxt)) or (w in _EN_DEFINITE and nxt[:1] and nxt[0] in _EN_SUBJECTS):
            refs.append((i, " ".join(words[i:i + 2 + _noun_at(nxt, _EN_PLACES)])))
        elif any((w in _PT_SPECIFIC[g] and _PT_PLACES[g] & set(nxt))
                 or (w in _PT_DEFINITE[g] and nxt[:1] and nxt[0] in _PT_SUBJECTS[g]) for g in ("m", "f")):
            refs.append((i, " ".join(words[i:i + 2 + _noun_at(nxt, _PT_PLACES["m"] | _PT_PLACES["f"])])))
        # Five-letter stems: cognates and translations of the property's place names count too (Centro → centre).
        elif len(w) >= 4 and any(w[:5] == n[:5] for n in names):
            refs.append((i, w))
        elif pronoun and w == "it":  # "it", once the statement has named the property
            refs.append((i, w))
    return refs


@dataclass(frozen=True)
class PlanningReading:
    """How a model-worded statement's sentences relate to planning (see ``read_planning``)."""
    problem: str | None
    general: bool = False  # it has a general planning sentence (not about the property)
    deferral: bool = False  # it has a sentence leaving the planning position to be confirmed
    about_property: bool = False  # it refers to the property or its place


def read_planning(text: str, cited: list[Evidence], case_facts: list[Evidence], ground: bool = True) -> PlanningReading:
    """Read ``text`` sentence by sentence. A sentence that refers to the property (or its place) and carries planning
    content states or implies the parcel's planning: never admissible in model wording ("the land-use category of
    the parcel conditions the admissible uses" included), unless it only defers it ("… must be confirmed", "… has not
    yet been determined") with nothing attributed in the rest of the sentence. A fact about the property must come
    from the records the statement cites (so "this property is in the blue band" can't be slipped in as a fact and
    paired with a general rule). A planning sentence that refers to no property is a general explanation."""
    names = _place_names(case_facts)
    sentences = _sentences(fold(text))
    named = any(_references(_WORD.findall(x), names, False) for x in sentences)
    corpus = {_stem(w) for e in [*cited, *case_facts] if not is_user_declared(e)
              for w in _tokens(" ".join((e.excerpt, e.source_title, e.source_reference)))}
    corpus |= {_stem(w) for w in (*_META, *_ATTRIBUTION)}
    places = _EN_PLACES | _PT_PLACES["m"] | _PT_PLACES["f"]
    general = deferral = False
    for sentence in sentences:
        deferred = bool(_DEFERRAL.search(sentence))
        rest = _WORD.findall(_UNASSERTED.sub(" ", _DEFERRAL.sub(" ", sentence)))
        refs = _references(rest, names, named)
        planning = has_planning_content(" ".join(rest))
        # The reference's own words don't count (folded PT "esta" is both "this" and "is").
        own = {i + k for i, ref in refs for k in range(len(ref.split()))}
        attributed = any(w in _ATTRIBUTION and j not in own and abs(j - i) <= _REACH
                         for i, _ in refs for j, w in enumerate(rest))
        shown = " ".join(_WORD.findall(sentence))
        if refs and planning and (attributed or not deferred):
            return PlanningReading(
                f"states or implies planning content for this property (\"{shown}\") without an authoritative parcel "
                "determination; while the planning position is unconfirmed, only its confirmation may be stated")
        if refs and attributed and ground:
            ungrounded = sorted({w for w in _tokens(" ".join(rest)) if w not in places and _stem(w) not in corpus})
            if ungrounded:
                return PlanningReading(f"states a fact about the property that its cited records don't support "
                                       f"(unsupported words: {', '.join(ungrounded)})")
        if deferred and has_planning_content(sentence):
            deferral = True
        elif planning:
            general = True
    return PlanningReading(None, general, deferral, named)


#: Records of this case that HABITA resolved itself (property, jurisdiction, authority). User answers are not
#: among them: they are only ever shown as the user's own declaration (see ``render_user_declaration``).
CASE_TYPES = {"property_record", "jurisdiction_record", "authority_record"}
#: Words that name a planning classification. A case record (least of all a user's answer) can't establish one.
_CLASSIFICATION_STEMS = ("zon", "classif", "categor", "qualif", "pdm", "ordenament", "planta")


def case_restatement(text: str, cited: list[Evidence]) -> bool:
    """Whether ``text`` only restates the case records it cites ("District: Lisboa", "licensed as one single-family
    dwelling (habitação)"): every content word comes from those records. Such a statement is a fact of the case,
    not a planning explanation, whatever words the record happens to use."""
    if not cited or any(not supports(e, "case_fact") for e in cited):
        return False
    corpus = {_stem(w) for e in cited for w in _tokens(" ".join((e.excerpt, e.source_title, e.source_reference)))}
    corpus |= {_stem(w) for w in _META}
    words = _tokens(text)
    return bool(words) and all(_stem(w) in corpus for w in words)


def case_fact_problem(text: str, cited: list[Evidence], case_facts: list[Evidence]) -> str | None:
    named = sorted({w for w in _tokens(text) if w.startswith(_CLASSIFICATION_STEMS)})
    if named or _CATEGORY.search(fold(text)):
        return (f"restates a case record but names a planning classification ({', '.join(named) or 'a PDM category'}); "
                "property, jurisdiction, authority and user records can't establish one")
    return read_planning(text, cited, case_facts).problem


def is_official_text(e: Evidence) -> bool:
    return e.source_type == "regulatory_source" and e.verification_status == "official_text"


def explanation_problem(text: str, cited: list[Evidence], case_facts: list[Evidence]) -> str | None:
    """A general planning explanation needs admissible official text (a trusted official passage) for its normative
    part. Property records, user facts and authority records may accompany it as context, never as support;
    curated summaries don't support a planning rule; the planning context can't be cited (the parcel's planning goes
    through authority_confirmation / parcel_determination)."""
    if not any(is_official_text(e) for e in cited):
        return ("is a general planning explanation but cites no admissible official text (a trusted official "
                "passage) for its normative part; property, user, authority, planning-context and curated records "
                "can't support a planning rule")
    if any(e.source_type == "planning_context" for e in cited):
        return ("is a general planning explanation but cites this property's planning context; the parcel's planning "
                "position is stated only through authority_confirmation or parcel_determination")
    return read_planning(text, cited, case_facts).problem


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(fold(text)) if len(w) >= 3 and w not in _STOP]


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("s"):  # units → unit, dwellings → dwelling
        word = word[:-1]
    return word[:7]


def _planning_word(word: str) -> bool:
    return word in _PLANNING_WORDS or word.startswith(_PLANNING_STEMS)


def is_planning_evidence(e: Evidence) -> bool:
    return e.source_type == "planning_context" or (
        e.provenance is not None and e.provenance.authority_class == "municipal_instrument")


def render_determination(e: Evidence) -> str:
    c = e.structured.get("classification") or {}
    instrument = (e.structured.get("instrument") or {}).get("title") or e.source_title
    return f"Official planning classification for this property: {c.get('label')} ({instrument})."


def planning_condition(conditions) -> str | None:
    return next((c.text for c in conditions if c.item_key == "planning_constraints"), None)


def _quoted_record(quote: str | None, cited: list[Evidence]) -> Evidence | None:
    q = _norm(quote or "")
    if len(q) < MIN_QUOTE:
        return None
    return next((e for e in cited if e.source_type == "regulatory_source" and q in _norm(e.excerpt)), None)


def rendered_text(basis: str, quote: str | None, cited: list[Evidence], matter: PermitMatter, conditions) -> str | None:
    """The HABITA-derived text a structured statement must consist of, or None if it can't be derived."""
    if basis == "general_rule":
        if not quote or (record := _quoted_record(quote, cited)) is None:
            return None
        from app.services.permit.claims import bound_quote  # claims builds on this module
        return bound_quote(record, quote)
    if basis == "authority_confirmation":
        return planning_condition(conditions)
    if basis == "parcel_determination":
        determination = next((e for e in cited if is_determination(e, matter)), None)
        return render_determination(determination) if determination else None
    return None


#: Neutral location predicates (EN + PT), a narrow subset of ``_ATTRIBUTION``. Usable in a free-text statement only
#: when it cites HABITA's own location evidence (jurisdiction or property record), and they ground nothing else.
_LOCATION_PREDICATES = ("located", "situated", "localizado", "localizada", "situado", "situada")
_LOCATION_RECORDS = ("jurisdiction_record", "property_record")


def grounding_problem(text: str, cited: list[Evidence], case_facts: list[Evidence]) -> str | None:
    words = _tokens(text)
    planning = sorted({w for w in words if _planning_word(w)})
    if planning or _CATEGORY.search(fold(text)):
        return f"uses planning vocabulary ({', '.join(planning) or 'a PDM category'}) without a structured planning basis"
    corpus = {_stem(w) for e in [*cited, *case_facts] if not is_user_declared(e)
              for w in _tokens(" ".join((e.excerpt, e.source_title, e.source_reference)))}
    corpus |= {_stem(w) for w in _META}
    if any(e.source_type in _LOCATION_RECORDS and not is_user_declared(e) for e in cited):
        # "The property is located in Cascais …" restating HABITA's own location record: the neutral location verb
        # is grounded by that record; every other word (the place itself) still has to be.
        corpus |= {_stem(w) for w in _LOCATION_PREDICATES}
    ungrounded = sorted({w for w in words if _stem(w) not in corpus})
    if len(ungrounded) > UNGROUNDED_ALLOWED:
        return f"is not grounded in its cited evidence (unsupported words: {', '.join(ungrounded)})"
    return None


USER_FRAME = "You stated (declared by you, not verified by HABITA): "
USER_STEP = "Your declaration"


def _restates(text: str, records: list[Evidence]) -> bool:
    """Every content word of ``text`` comes from ``records`` (or the closed connective list)."""
    corpus = {_stem(w) for e in records for w in _tokens(e.excerpt)} | {_stem(w) for w in _META}
    words = _tokens(text)
    return bool(words) and all(_stem(w) in corpus for w in words)


def render_user_declaration(users: list[Evidence]) -> str:
    """The only way a user's answer appears in a draft: verbatim, attributed, marked unverified."""
    return " ".join(f"{USER_FRAME}\u201c{e.excerpt.strip()}\u201d" for e in users)


#: What a user may declare about the property: the private facts HABITA asks them about (current and intended use,
#: layout, floors, areas, access, ownership). Word stems, EN + PT. When a user's answer attributes something to the
#: property, it must be one of these: anything else ("belongs to the blue band", "is in zone X", "the Câmara
#: confirmed …") is outside what a user can establish, so it fails closed whatever its wording.
_PRIVATE_FACT_STEMS = (
    "licen", "use", "used", "using", "dwell", "home", "house", "flat", "apart", "unit", "floor", "storey", "stor",
    "level", "room", "bedro", "kitch", "bath", "door", "entra", "acces", "exit", "stair", "own", "single", "coown",
    "fract", "divid", "horiz", "area", "sqm", "squar", "metr", "meter", "year", "old", "renov", "famil", "occup",
    "rent", "vacan", "empty", "inhab", "habit", "fogo", "moradi", "casa", "aparta", "fraca", "fracc", "piso", "andar",
    "divis", "quart", "cozin", "porta", "entrad", "acess", "saida", "escad", "propri", "dono", "unico", "unica", "ano",
    "anos", "famil", "arrend", "devolut", "ocupa", "about", "approx", "cerca", "each", "cada", "both", "ambos",
    "separate", "separa", "independ", "street", "rua", "public", "publica", "way", "via", "currently", "atualmente",
    "today", "hoje", "first", "ground", "rés", "res", "chao", "cave", "basement", "garage", "garag", "garden", "jardim",
)


def _user_attribution_problem(text: str, case_facts: list[Evidence]) -> str | None:
    names = _place_names(case_facts)
    sentences = _sentences(fold(text))
    named = any(_references(_WORD.findall(x), names, False) for x in sentences)
    for sentence in sentences:
        rest = _WORD.findall(_UNASSERTED.sub(" ", _DEFERRAL.sub(" ", sentence)))
        refs = _references(rest, names, named)
        own = {i + k for i, ref in refs for k in range(len(ref.split()))}
        verbs = {j for j, w in enumerate(rest) if w in _ATTRIBUTION and j not in own
                 and any(abs(j - i) <= _REACH for i, _ in refs)}
        if not verbs:
            continue
        # The predicate: from the reference on when the verb follows it ("the property has …"), or the words leading
        # up to a verb that comes first ("in the blue band lies my property"); not a label before the subject.
        first_ref, first_verb = min(i for i, _ in refs), min(verbs)
        start = first_ref if first_verb > first_ref else max(0, first_verb - _REACH)
        beyond = sorted({w for j, w in enumerate(rest) if j >= start and j not in own | verbs and len(w) >= 3
                         and w not in _STOP and w not in _META and not w.isdigit()
                         and not w.startswith(_PRIVATE_FACT_STEMS)})
        if beyond:
            return f"\"{' '.join(_WORD.findall(sentence))}\" (beyond private facts: {', '.join(beyond)})"
    return None


def user_claim_problem(users: list[Evidence], case_facts: list[Evidence]) -> str | None:
    """A user's answer can be shown only as their own private facts. One that states the parcel's planning, or
    attributes to the property anything beyond those facts, can never stand in a verified assessment: it is the
    user's claim, and planning needs an official determination (HR-003 CX-1 / MU-3)."""
    for e in users:
        named = sorted({w for w in _tokens(e.excerpt) if w.startswith(_CLASSIFICATION_STEMS)})
        reading = read_planning(e.excerpt, [], case_facts, ground=False)
        if named or _CATEGORY.search(fold(e.excerpt)) or reading.problem:
            return ("repeats the user's own claim about the parcel's planning; a user declaration can never establish, "
                    "confirm or support zoning, land-use category or planning classification")
        if beyond := _user_attribution_problem(e.excerpt, case_facts):
            return (f"repeats a user's claim about the property that goes beyond the private facts a user can declare "
                    f"({beyond}); a user declaration can never establish the parcel's planning or status")
    return None


def statement_problem(
    text: str, basis: str, quote: str | None, step: str | None, cited: list[Evidence], matter: PermitMatter,
    conditions, case_facts: list[Evidence], current_planning=None, section: str = "claim",
) -> str | None:
    """Why a model statement can't be certified, or None. ``cited`` = its admissible citations; ``step`` is the
    procedure step name (procedure only); ``current_planning`` = the resolver's PlanningContext now, if known."""
    users = [e for e in cited if is_user_declared(e)]
    if basis == USER_DECLARATION:
        if section != "claim":
            return ("is a user declaration outside the findings; the conclusion, procedure, risks and next actions are "
                    "HABITA's assessment and can't rest on the user's answers")
        if not users or len(users) != len(cited):
            return "is a user declaration but cites something other than the user's own answers"
        if text != render_user_declaration(users) or (step is not None and step != USER_STEP):
            return "is not HABITA's verbatim, attributed rendering of the user's answer"
        return user_claim_problem(users, case_facts)
    if users and basis == "parcel_determination":
        return "declares a parcel planning determination but cites user declarations, which can never support one"
    # User answers support nothing else: they are dropped from the statement's support (shown only as declarations).
    cited = [e for e in cited if not is_user_declared(e)]
    if users and not cited:
        return "rests only on the user's answers; those are shown only as the user's own (unverified) declaration"
    if basis in RENDERED_STEP:
        expected = rendered_text(basis, quote, cited, matter, conditions)
        if expected is None:
            return {
                "general_rule": f"is declared a general rule but its quote is not a verbatim passage (≥ {MIN_QUOTE} "
                                "characters) of a cited regulatory record",
                "authority_confirmation": "defers to the authority but there is no HABITA planning condition",
                "parcel_determination": "declares a parcel planning determination but cites none that is "
                                        "authoritative and admissible for this property",
            }[basis]
        if _norm(text) != _norm(expected) or (step is not None and step != RENDERED_STEP[basis]):
            return "has a structured planning basis but its text is not the HABITA-rendered content for that basis"
        if basis == "parcel_determination":
            determination = next(e for e in cited if is_determination(e, matter))
            label = (determination.structured.get("classification") or {}).get("label")
            now = current_planning
            if now is None or now.status != "resolved" or now.classification is None or now.classification.label != label:
                return "relies on a parcel determination that the current planning resolver does not confirm"
        return None
    if basis == EXPLANATION:
        # Only HABITA-framed explanations can be certified; the model's wording follows the frame.
        if not text.startswith(EXPLANATION_FRAME) or (step is not None and step != EXPLANATION_STEP):
            return "is a general planning explanation that HABITA has not framed as general"
        return explanation_problem(text[len(EXPLANATION_FRAME):], cited, case_facts)
    if any(is_planning_evidence(e) for e in cited):
        return "cites planning evidence without a structured planning basis"
    full = " ".join(filter(None, (step, text)))
    if has_planning_content(full) and case_restatement(full, cited):
        return case_fact_problem(full, cited, case_facts)
    return grounding_problem(full, cited, case_facts)


def render_draft(draft, evidence: list[Evidence], matter: PermitMatter):
    """Replace the text of structured-basis statements with HABITA-derived content (model wording kept as
    ``model_text``). Statements whose content can't be derived are left as written and fail verification.

    General planning explanations keep the model's wording behind HABITA's "not a determination" frame. Free text
    (``none``) that turns out to use planning vocabulary is treated as an explanation, so it is held to those rules
    (no reference to the property, regulatory citations only) instead of being rejected for its words alone."""
    by_id = {e.evidence_id: e for e in evidence}
    case_facts = [e for e in evidence if e.source_type in ("property_record", "jurisdiction_record", "authority_record")]

    def rendered(entry, text: str, step: str | None = None, finding: bool = False):
        """(basis, step, text) as HABITA will show it, or None to leave the statement as written."""
        basis = entry.planning_basis
        cited_all = [by_id[i] for i in entry.evidence_ids if i in by_id]
        if (finding and basis in ("none", EXPLANATION, USER_DECLARATION) and cited_all
                and all(is_user_declared(e) for e in cited_all)):
            # A statement resting only on the user's answers shows those answers, verbatim and attributed: when the
            # model declares it so, or when its wording only restates them. Anything else it says (planning prose, a
            # claim the user didn't make) is left as written and fails: user answers support nothing else. A planning
            # claim inside the answer itself is rejected by ``user_claim_problem``.
            if basis == USER_DECLARATION or _restates(" ".join(filter(None, (step, text))), cited_all):
                return USER_DECLARATION, USER_STEP, render_user_declaration(cited_all)
        full = " ".join(filter(None, (step, text)))
        if basis == "none" and has_planning_content(full) and not case_restatement(
                full, [by_id[i] for i in entry.evidence_ids if i in by_id]):
            basis = EXPLANATION  # planning prose of the model's own (a restated case record stays a fact)
        if basis == EXPLANATION:
            # Model wording that only leaves the parcel's planning to be confirmed is shown as HABITA's own
            # condition (never as model prose); anything it attributes keeps it as written, and it fails.
            cited = [by_id[i] for i in entry.evidence_ids if i in by_id]
            reading = read_planning(text, cited, case_facts)
            condition = planning_condition(draft.conditions)
            # A deferral without official support can't stand as an explanation, so it is the condition too.
            if (reading.problem is None and reading.deferral and not reading.general and condition is not None
                    and (reading.about_property or not any(is_official_text(e) for e in cited))):
                return "authority_confirmation", RENDERED_STEP["authority_confirmation"], condition
            # Shown: HABITA's step name + frame + the description; the model's own step name stays in model_text.
            return basis, EXPLANATION_STEP, text if text.startswith(EXPLANATION_FRAME) else EXPLANATION_FRAME + text
        cited = [by_id[i] for i in entry.evidence_ids if i in by_id]
        t = rendered_text(basis, entry.quote, cited, matter, draft.conditions)
        return None if t is None else (basis, RENDERED_STEP.get(basis), t)

    updates = {}
    if (r := rendered(draft.conclusion, draft.conclusion.summary)) is not None:
        updates["conclusion"] = draft.conclusion.model_copy(update={
            "planning_basis": r[0], "summary": r[2], "model_text": draft.conclusion.summary})
    for field in ("claims", "risks", "next_actions"):
        items = []
        for entry in getattr(draft, field):
            r = rendered(entry, entry.text, finding=field == "claims")
            items.append(entry if r is None else entry.model_copy(update={
                "planning_basis": r[0], "text": r[2], "model_text": entry.text}))
        updates[field] = items
    steps = []
    for entry in draft.procedure:
        r = rendered(entry, entry.description, entry.step)
        steps.append(entry if r is None else entry.model_copy(update={
            "planning_basis": r[0], "step": r[1], "description": r[2],
            "model_text": f"{entry.step}: {entry.description}"}))
    updates["procedure"] = steps
    return draft.model_copy(update=updates)
