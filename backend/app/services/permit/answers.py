"""TD-061: typed, contextual validation of the user's answers to structural questions.

A user's answer is stored as a *user declaration* (never an official fact, MU-9). Before this check any text satisfied
the checklist item: "yes" to "how would the two units be arranged (floors, areas, entrances)?" closed the question
and the missing facts were never asked again. Now each USER key declares what an answer must contain; an answer
that lacks it is refused with a fixed clarifying message (409 ``input_incomplete``) and the question stays open.

The checks only decide whether the answer *has the shape* of an answer (a number with a unit, a floor count, an
access, a use). They never decide that the answer is true, and never turn it into an official fact.
Messages are fixed English texts (translated by the frontend catalog); they never echo the user's text.
"""

import re
import unicodedata

from app.services.i18n.translator import msg


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


_WORD = re.compile(r"[a-z]+")
#: Answers that answer nothing, whatever the question (EN + PT).
_NON_ANSWERS = {
    "yes", "no", "ok", "okay", "sure", "y", "n", "yep", "nope", "maybe", "none", "na", "n a", "idk", "dunno",
    "i don t know", "don t know", "not sure", "unknown", "areas", "area", "floors", "floor", "entrance", "entrances",
    "access", "same", "as above", "see above", "sim", "nao", "talvez", "nada", "nenhum", "nenhuma", "nao sei",
    "sei la", "desconheco", "desconhecido", "areas", "pisos", "piso", "andares", "entrada", "entradas", "acesso",
    "igual", "o mesmo", "a mesma", "idem", "tbd", "test", "teste", "x", "xx", "xxx", "asdf", "etc",
}
_AREA = re.compile(r"\d+(?:[.,]\d+)?\s*(?:m2|m²|m\^2|sqm|sq\s?m|square\s+met(?:er|re)s?|metros?\s+quadrados?|"
                   r"sq\s?ft|square\s+feet)\b")
_NUMBER_WORDS = ("one|two|three|four|five|six|a single|single|um|uma|dois|duas|tres|quatro|cinco|seis|"
                 "unico|unica|ground|first|second|third|top|res do chao|r c|primeiro|segundo|terceiro|cave|sotao")
_FLOORS = re.compile(rf"(?:\b\d+\b|\b(?:{_NUMBER_WORDS})\b)[\w\s-]{{0,25}}\b(?:floors?|storeys?|stories|levels?|"
                     rf"pisos?|andar(?:es)?|niveis|nivel)\b|\b(?:floors?|storeys?|pisos?|andar(?:es)?)\s+\d+\b|"
                     rf"\b(?:per|each|por|cada)\s+(?:floor|storey|piso|andar)\b|\bground\s+floor\b|\bres do chao\b")
_ACCESS = re.compile(r"\b(?:entrances?|doors?|exits?|access(?:es)?|hall(?:way)?|stair(?:case|s)?|"
                     r"entradas?|portas?|saidas?|acessos?|escadas?|patio|corredor|hall)\b")
_USE = re.compile(r"\b(?:hous\w*|dwelling\w*|residen\w*|home|flats?|apartments?|habita\w*|moradi\w*|vivend\w*|"
                  r"apartament\w*|fogos?|office\w*|escritori\w*|commerc\w*|comerci\w*|shops?|retail|lojas?|"
                  r"servic\w*|services?|restaurant\w*|cafe|bar|industr\w*|warehouse|armaz\w*|storage|garage\w*|"
                  r"garag\w*|tourism|turis\w*|alojamento|hotel\w*|hostel|clinic\w*|clinica|studio|estudio|atelier|"
                  r"workshop|oficina|school|escola|gym|ginasio|mixed|misto|vacant|devoluto|ruin\w*)\b")
_OWNERSHIP = re.compile(r"\b(?:single|sole|one|only|unico|unica|so|um|uma|several|two|three|co\s?own\w*|"
                        r"compropriedade|coproprietar\w*|herdeiros|heirs|fractions?|fraccoes|fracoes|fracao|"
                        r"horizontal|condominium|condominio|owners?|ownership|propriet\w*|dono\w*|donos|"
                        r"divided|dividid\w*|undivided|indivis\w*)\b")
_WORKS = re.compile(r"\b(?:kitchen|bath\w*|floor\w*|tiles?|paint\w*|walls?|windows?|doors?|roof|facade|"
                    r"plumb\w*|electric\w*|ceiling|stairs?|partition\w*|cozinha|banho|wc|pavimento|chao|azulej\w*|"
                    r"pintur\w*|pint\w*|parede\w*|janela\w*|porta\w*|cobertura|telhado|fachada|canaliza\w*|"
                    r"eletric\w*|electric\w*|tecto|teto|escada\w*|divisoria\w*|remodel\w*|renov\w*|demol\w*|"
                    r"build\w*|obra\w*|works?|replace\w*|substitu\w*|install\w*|instal\w*|load\s?bearing|"
                    r"mestra\w*|estrutur\w*|structur\w*)\b")

NOT_AN_ANSWER = msg("This doesn't answer the question. Please describe it in a few words.")
TOO_SHORT = msg("Please answer with a few words, so HABITA records what you declare.")
NEED_USE = msg("Please name the use, for example housing (one dwelling), office, shop or services. If you don't know "
               "the licensed use, it is on the licence of use (licença de utilização) or the caderneta predial.")
NEED_LAYOUT = msg("To assess a division HABITA needs the layout: how many floors or units, the approximate area of "
                  "each in m2, and each unit's entrance (from the street or a shared hall).")
NEED_LAYOUT_AREA = msg("Please add the approximate area of each unit in m2 (for example, about 60 m2 each).")
NEED_LAYOUT_FLOORS = msg("Please say how the units are arranged by floor (for example, one per floor, on two floors).")
NEED_LAYOUT_ACCESS = msg("Please say how each unit would be entered: its own street door or a shared hall or "
                         "staircase.")
NEED_OWNERSHIP = msg("Please say whether the property has a single owner, several co-owners, or is already divided "
                     "into fractions (propriedade horizontal).")
NEED_WORKS = msg("Please list the works (for example kitchen, bathroom, floors, walls, windows) and say whether they "
                 "touch load-bearing walls, the facades, the roof or the height.")

#: Every fixed message, for the translation catalogs.
MESSAGES = (NOT_AN_ANSWER, TOO_SHORT, NEED_USE, NEED_LAYOUT, NEED_LAYOUT_AREA, NEED_LAYOUT_FLOORS,
            NEED_LAYOUT_ACCESS, NEED_OWNERSHIP, NEED_WORKS)


def _non_answer(folded: str) -> bool:
    words = " ".join(_WORD.findall(folded))
    return not words or words in _NON_ANSWERS or all(w in _NON_ANSWERS for w in words.split())


def answer_problem(intent: str | None, key: str, answer: str) -> str | None:
    """The fixed clarifying message if ``answer`` can't stand as the user's answer to ``key``; else None."""
    folded = _fold(answer).strip()
    if _non_answer(folded):  # "yes", "ok", "areas", "não sei": the key's own clarifying question
        return {"current_licensed_use": NEED_USE, "ownership_status": NEED_OWNERSHIP, "works_description": NEED_WORKS,
                "intended_use": NEED_LAYOUT if intent == "unit_conversion" else NEED_USE}.get(key, NOT_AN_ANSWER)
    words = _WORD.findall(folded)
    if key == "current_licensed_use":
        return None if _USE.search(folded) else NEED_USE
    if key == "intended_use":
        if intent == "unit_conversion":
            missing = [m for m, ok in ((NEED_LAYOUT_FLOORS, _FLOORS.search(folded)),
                                       (NEED_LAYOUT_AREA, _AREA.search(folded)),
                                       (NEED_LAYOUT_ACCESS, _ACCESS.search(folded))) if not ok]
            if len(missing) > 1:
                return NEED_LAYOUT
            return missing[0] if missing else None
        return None if _USE.search(folded) else NEED_USE
    if key == "ownership_status":
        return None if _OWNERSHIP.search(folded) else NEED_OWNERSHIP
    if key == "works_description":
        return None if _WORKS.search(folded) and len(words) >= 3 else NEED_WORKS
    return TOO_SHORT if len(words) < 2 else None
