"""The bilingual system (PT/EN): translation for reading, after verification, never instead of it.

HABITA verifies its answers in English against Portuguese official sources (MU-9), so what was verified stays the
stored English text; nothing here writes to a matter, a draft or a verification. A translation is a labelled view of
it. Each text goes through ``fidelity_problems``: a translation that changes a number, an evidence id, a quotation, a
negation or an obligation, or that adds approval vocabulary, is dropped and that text stays in English. Machine
translation cannot prove it kept the meaning, so these checks only catch what they can see, and the English text
prevails (the label says so). Statuses, warnings and the disclaimer never reach the machine: they are pinned in
``pinned.json``, reviewed by hand.
"""

import html
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.integrations.translate.client import GoogleTranslateClient, TranslationUnavailable

HERE = Path(__file__).parent
TARGET = {"pt": "pt-PT"}
CACHE_SIZE = 5000

#: Portuguese institutions and instruments, as they are named officially: a machine turned "the Câmara's index" into
#: the House of Representatives' and dropped "Regulamento" altogether.
_OFFICIAL = re.compile(r"Câmara Municipal(?: de [A-ZÀ-Ý]\w+)?|Câmara\b|Regulamento\b|Plano Diretor Municipal(?: de [A-ZÀ-Ý]\w+)?|"
                       r"Reserva Ecológica Nacional|Reserva Agrícola Nacional|Parque Natural(?: de [A-ZÀ-Ý][\w-]+)?")
#: Portuguese legal terms of art that the machine renders as something else ("prior control" as prior authorisation).
_GLOSSARY = {"municipal prior control": "controlo prévio municipal", "prior control": "controlo prévio"}
_glossary = re.compile("|".join(sorted(_GLOSSARY, key=len, reverse=True)), re.I)
_protected = re.compile(rf'"[^"\n]{{3,}}"|“[^”\n]{{3,}}”|«[^»\n]{{3,}}»|\b[EK]\d+\b|\{{[a-z_]+\}}|{_OFFICIAL.pattern}')
_span = re.compile(r'<span translate="no">\s*(.*?)\s*</span>', re.S)
_number = re.compile(r"\d+(?:[.,\s]\d+)*")
_ident = re.compile(r"\b[EK]\d+\b")
_acronym = re.compile(r"\b[A-Z][A-Z-]{2,}\b")
_quoted = re.compile(r'"([^"\n]{3,})"|“([^”\n]{3,})”|«([^»\n]{3,})»')
_placeholder = re.compile(r"\{[a-z_]+\}")
#: English number words, by value, with their Portuguese forms.
_NUMBER_WORDS = {"one": r"um|uma", "two": r"dois|duas", "three": r"tr[eê]s", "four": "quatro", "five": "cinco",
                 "six": "seis", "seven": "sete", "eight": "oito", "nine": "nove", "ten": "dez"}
_CHECKS = (  # (what, in the English source, must have one of these in the Portuguese)
    ("negation", re.compile(r"\b(?:not|no|never|cannot|none|without|neither|nor|unless)\b|n't\b", re.I),
     re.compile(r"\b(?:não|nunca|nem|sem|nenhum\w*|nada|a menos|salvo|exceto|ausência|falta\w*|impossível)\b", re.I)),
    ("obligation", re.compile(r"\b(?:must|shall|required|mandatory|need to|needs to)\b"),
     re.compile(r"\b(?:dev\w+|tem de|têm de|terá de|terão de|tem que|têm que|necess\w+|obrigat\w+|requer\w*|requisit\w*|"
                r"exig\w+|é preciso|precis\w+)\b", re.I)),
    ("possibility", re.compile(r"\b(?:may|might|could|possibly|likely|probably)\b"),
     re.compile(r"\b(?:pod\w+|poss[ií]\w+|prov[aá]v\w+|talvez|parece\w*|eventual\w*)\b", re.I)),
)
#: A machine must not introduce a legal outcome the source does not state.
_OUTCOME_PT = re.compile(r"\b(?:aprovad|licenciad|deferid|autorizad|legalizad|garantid)\w*", re.I)
_OUTCOME_EN = re.compile(r"approv|licen[cs]|grant|authori[sz]|permit|legal|guarant", re.I)
_ARTICLE = {"A": "O", "a": "o", "da": "do", "pela": "pelo", "à": "ao"}
_STATUS_WORDS = {"VERIFIED", "REJECTED", "PENDING", "CONFIRMATION", "HABITA"}


def fidelity_problems(source: str, target: str) -> list[str]:
    """What a translation visibly fails to preserve; empty when none of the checks objects."""
    problems = []
    # 1.5 and 1,5 are the same number: only the digits are compared, in any order (word order changes).
    digits = lambda text: sorted(re.sub(r"\D", "", n) for n in _number.findall(_ident.sub(" ", text)))  # noqa: E731
    if digits(source) != digits(target):
        problems.append("number")
    if sorted(_ident.findall(source)) != sorted(_ident.findall(target)):
        problems.append("reference")
    if sorted(_placeholder.findall(source)) != sorted(_placeholder.findall(target)):
        problems.append("placeholder")
    for match in _quoted.finditer(source):
        if next(g for g in match.groups() if g) not in target:
            problems.append("quotation")
    if any(a not in _STATUS_WORDS and a not in target for a in _acronym.findall(source)):
        problems.append("acronym")
    if any(name not in target for name in _OFFICIAL.findall(source)):
        problems.append("official name")
    if re.search(r"Representantes|Deputados|Comuns", target) and not re.search(r"Representatives|Deputies|Commons", source):
        problems.append("official name")  # "Câmara" is never a parliament here
    if target.count("(") > source.count("("):  # an invented expansion: "REN" became "REN (Região de Referência de Energia)"
        problems.append("added explanation")
    if any(symbol in target and symbol not in source for symbol in "™®©"):
        problems.append("stray symbol")
    for word, pattern in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", source, re.I) and not re.search(rf"\b(?:{pattern})\b", target, re.I):
            problems.append("number word")
    problems += [name for name, en, pt in _CHECKS if en.search(source) and not pt.search(target)]
    if _OUTCOME_PT.search(target) and not _OUTCOME_EN.search(source):
        problems.append("legal outcome")
    return problems


def _encode(text: str) -> str:
    """HTML for the service, with what must not change wrapped so it is not translated."""
    text = _glossary.sub(lambda m: f"«{_GLOSSARY[m.group().lower()]}»", text)
    out, at = [], 0
    for m in _protected.finditer(text):
        out += [html.escape(text[at:m.start()], quote=False),
                f'<span translate="no">{html.escape(m.group(), quote=False)}</span>']
        at = m.end()
    return "".join(out) + html.escape(text[at:], quote=False)


def _decode(text: str) -> str:
    text = html.unescape(_span.sub(lambda m: m[1].strip("«»") if m[1].strip("«»") in _GLOSSARY.values() else m[1], text))
    text = re.sub(r"\s+([.,;:!?)\]])", r"\1", re.sub(r"[ \t]{2,}", " ", text))
    text = re.sub(r"([(\[])\s+", r"\1", re.sub(r"<b>\s+", "<b>", re.sub(r"\s+</b>", "</b>", text)))
    # HABITA is a system, not a company: "o HABITA" throughout.
    return re.sub(r"\b([Aa]|da|pela|à)( HABITA\b)", lambda m: _ARTICLE[m[1]] + m[2], text).strip()


def _load(name: str) -> dict[str, str]:
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


PINNED = _load("pinned.json")
CATALOG = _load("pt.json")


def fixed(text: str, lang: str) -> str | None:
    """A reviewed or generated Portuguese text; None when there is none."""
    return (PINNED.get(text) or CATALOG.get(text)) if lang == "pt" else None


def translator_for(lang: str) -> Callable[..., str]:
    """``t("English {x}", x=…)`` for fixed texts; a text without an entry stays English."""

    def t(text: str, **values) -> str:
        out = fixed(text, lang) or text
        for k, v in values.items():
            out = out.replace(f"{{{k}}}", str(v))
        return out

    return t


def msg(text: str) -> str:
    """Marks a fixed text for the catalog where it is defined; ``t`` translates it where it is shown."""
    return text


@dataclass(frozen=True)
class Translations:
    lang: str
    texts: dict[str, str] = field(default_factory=dict)  # English → shown text (English again when kept)
    kept_original: int = 0  # texts left in English because their translation could not be confirmed
    available: bool = True

    def __call__(self, text: str | None) -> str | None:
        return self.texts.get(text, text) if text else text


class Translator:
    def __init__(self, client: GoogleTranslateClient) -> None:
        self._client = client
        self._cache: dict[tuple[str, str], str] = {}  # only texts that passed; no text is stored outside the process

    async def translate(self, texts: Iterable[str], lang: str) -> Translations:
        wanted = list(dict.fromkeys(t for t in texts if t and t.strip()))
        if lang not in TARGET:
            return Translations(lang, {t: t for t in wanted})
        out: dict[str, str] = {}
        missing: list[str] = []
        for text in wanted:
            known = fixed(text, lang) or self._cache.get((lang, text))
            if known:
                out[text] = known
            else:
                missing.append(text)
        kept, available = 0, True
        if missing:
            try:
                translated = await self._client.translate([_encode(t) for t in missing], TARGET[lang])
            except TranslationUnavailable:
                translated, available = [], False
                out |= {t: t for t in missing}
                kept = len(missing)
            for source, raw in zip(missing, translated, strict=False):
                text = _decode(raw)
                if fidelity_problems(source, text):
                    out[source], kept = source, kept + 1
                    continue
                out[source] = text
                if len(self._cache) >= CACHE_SIZE:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[(lang, source)] = text
        return Translations(lang, out, kept, available)

    async def detect(self, text: str) -> str | None:
        """"pt" or "en" for the user's own words; None when unsure, so the language shown stays as it is."""
        try:
            code = await self._client.detect(text)
        except TranslationUnavailable:
            return None
        return code.split("-")[0] if code and code.split("-")[0] in ("pt", "en") else None


def translation_note(result: Translations, *, verified: bool, has_answer: bool = True) -> str | None:
    """The label every translated text carries. Never calls an unverified draft a verified answer."""
    if result.lang == "en":
        return None
    t = translator_for(result.lang)
    if not result.available:
        return t("Translation is unavailable right now: the original English text is shown.")
    note = t("Automatic translation of the verified answer. The English text is the one HABITA verified and it prevails."
             if verified else "Automatic translation of a draft that has not been verified."
             if has_answer else "Automatic translation.")
    if result.kept_original:
        note += " " + t("{n} passage(s) stay in English because their translation could not be confirmed as faithful.",
                        n=result.kept_original)
    return note
