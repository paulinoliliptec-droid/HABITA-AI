"""HR-011 in words: the same rows for the PDFs and the same sentences for the voice, so all three say one thing."""

import re

from app.schemas.afford import AffordReport, Figure
from app.services.i18n.translator import msg, translator_for

TITLE = msg("Costs, financing and price")
_SCENARIO = {"lower": msg("Lower scenario"), "likely": msg("Likely scenario"), "higher": msg("Higher scenario")}


def euros(value: float) -> str:
    return f"{round(value):,}".replace(",", " ") + " €"


def _amount(f: Figure, t) -> str:
    total = (t("about {value}", value=euros(f.low)) if f.low == f.high
             else t("from {low} to {high}", low=euros(f.low), high=euros(f.high)))
    if f.per_m2_low is None:
        return total
    per = (euros(f.per_m2_low) if f.per_m2_low == f.per_m2_high
           else t("{low} to {high}", low=euros(f.per_m2_low), high=euros(f.per_m2_high)))
    return t("{per} per m², {total} in total", per=per, total=total)


_MONTHS = {"janeiro": "January", "fevereiro": "February", "março": "March", "marco": "March", "abril": "April",
           "maio": "May", "junho": "June", "julho": "July", "agosto": "August", "setembro": "September",
           "outubro": "October", "novembro": "November", "dezembro": "December"}


def period(text: str | None, lang: str) -> str:
    """An INE period in the reader's language ("Setembro de 2026" -> "September 2026", "2.º Trimestre de 2026" ->
    "Q2 2026"); unknown shapes stay as INE wrote them (afinamentos HR-011)."""
    if not text or lang != "en":
        return text or ""
    m = re.fullmatch(r"\s*(\d)\.?\s*[ºo]\s*trimestre\s+de\s+(\d{4})\s*", text, re.I)
    if m:
        return f"Q{m.group(1)} {m.group(2)}"
    m = re.fullmatch(r"\s*([A-Za-zçÇ]+)\s+de\s+(\d{4})\s*", text)
    if m and m.group(1).lower() in _MONTHS:
        return f"{_MONTHS[m.group(1).lower()]} {m.group(2)}"
    return text


def rows(a: AffordReport, lang: str) -> list[tuple[str, str]]:
    """(label, text) rows, in the report's language; every text but the amounts is pinned."""
    t = translator_for(lang)
    out: list[tuple[str, str]] = []
    for f in [*a.costs, *a.valuation]:
        out.append((f.label, f"{_amount(f, t)} · {f.source}" + (f" · {f.author}" if f.author else "")
                    + (f" · {period(f.as_of, lang)}" if f.as_of else "")))
    for s in a.scenarios:
        text = euros(s.cost)
        if s.monthly_payment is not None:
            text += " · " + t("about {payment} a month", payment=euros(s.monthly_payment))
        if s.within_budget is not None:
            text += " · " + (t("within your budget") if s.within_budget else t("above your budget"))
        out.append((t(_SCENARIO[s.key]), text + " · " + " ".join(s.assumptions)))
    if a.scenarios:
        out.append((t("What would change it:"), " ".join(a.scenarios[0].moves_it)))
    if a.valuation and a.inputs.area_m2 is not None:
        out.append(("", t("Totals use the area you declared: {area} m². They are market estimates, not a valuation of "
                          "this property.", area=f"{a.inputs.area_m2:g}")))
    for note in (a.costs_note, a.financing_note, a.valuation_note, a.fees_note):
        if note:
            out.append(("", note))
    if a.scenarios and a.scenarios[0].monthly_payment is not None:
        out.append(("", a.formula))
    out.append(("", a.disclaimer))
    return out


def sentences(a: AffordReport, lang: str) -> list[str]:
    t = translator_for(lang)
    return [t(TITLE), *[f"{label}: {text}." if label else text for label, text in rows(a, lang)]]
