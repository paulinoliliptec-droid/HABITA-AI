"""HR-011: every number, computed by code from named sources and the user's own figures (AC11.7).

Texts here carry no numbers, so their Portuguese is pinned; amounts travel in numeric fields and are formatted where
they are shown."""

from app.schemas.afford import AffordInputs, AffordReport, Figure, Scenario
from app.services.afford import ine, reference
from app.services.i18n.translator import msg

DISCLAIMER = msg("This is an estimate with no financial guarantee. It is not a quote, a valuation or financial advice, "
                 "and it does not change the assessment.")
FEES = msg("Municipal fees are not included: confirm them with the Câmara Municipal.")
FORMULA = msg("Monthly payment = amount financed × r ÷ (1 − (1 + r) ^ −n), with r the annual rate ÷ 12 and n the "
              "number of months.")
NO_AREA = msg("Enter the area to see a cost range.")
NOT_COVERED = msg("HABITA has no cost reference for this type of request.")
NO_RATE = msg("Enter a rate, a term and a down payment (0 if none) to see financing scenarios. HABITA uses no default "
              "rate.")
ONE_QUOTE = msg("Enter a second quote, or the area, to see a cost range.")
NO_PLACE = msg("HABITA has no official price statistics for this municipality, so it shows no price.")
NO_VALUATION_AREA = msg("Enter the area to see a price range for the property.")
_TABLE = {
    "interior_works": msg("HABITA reference table: interior works"),
    "change_of_use": msg("HABITA reference table: change of use"),
    "unit_conversion": msg("HABITA reference table: dividing into units"),
}
_AWAITING = msg("Public price guides compiled by HABITA; awaiting the owner's approval")
_APPROVED = msg("Public price guides compiled by HABITA; approved by the owner")
_QUOTE = msg("Your quotes")
_ONE_QUOTE = msg("Your quote")
_RANGE = msg("Range across the official figures above")
_COMPUTED = msg("Computed by HABITA from the figures above, not averaged")
_AUTHOR = msg("Compiled by Claude Code for HABITA")
ONE_FIGURE = msg("Only one official figure exists for this place, so no range is shown: a single median is not a range.")
_DECLARED = msg("Declared by you")
_BANK = {"total": msg("Median bank valuation in the municipality"),
         "apartment": msg("Median bank valuation of apartments in the municipality"),
         "house": msg("Median bank valuation of houses in the municipality")}
_SALE_MUNICIPALITY = msg("Median sale price in the municipality, last 12 months")
_SALE_PARISH = msg("Median sale price in the parish, last 12 months")
_INE = msg("INE, official statistics")
_ASSUME = {
    "lower": [msg("The low end of the cost range."), msg("Simple finishes and no surprises in the existing building.")],
    "likely": [msg("The middle of the cost range."), msg("Usual finishes.")],
    "higher": [msg("The high end of the cost range."),
               msg("Higher-end finishes, or repairs found once the works start.")],
}
_MOVES = [msg("Quotes from contractors for this property."), msg("The area actually renovated."),
          msg("The state of the building and its installations.")]


def _payment(principal: float, rate_percent: float, years: int) -> float:
    n, r = years * 12, rate_percent / 100 / 12
    return principal / n if r == 0 else principal * r / (1 - (1 + r) ** -n)


def _costs(intent: str | None, inputs: AffordInputs) -> tuple[list[Figure], str | None]:
    figures: list[Figure] = []
    quotes = [q for q in (inputs.quote_low, inputs.quote_high) if q is not None]
    if len(quotes) == 2:  # a range of the user's own: it drives the scenarios
        low, high = min(quotes), max(quotes)
        figures.append(Figure(label=_QUOTE, low=low, high=high, likely=(low + high) / 2, source=_DECLARED,
                              source_kind="user_declared"))
    elif quotes:  # one quote is shown as theirs, but is no range, so it never drives the scenarios
        figures.append(Figure(label=_ONE_QUOTE, low=quotes[0], high=quotes[0], source=_DECLARED,
                              source_kind="user_declared"))
    single = len(quotes) == 1
    table = reference.COSTS.get(intent or "")
    if table is None:
        return figures, ONE_QUOTE if single else None if figures else NOT_COVERED
    if inputs.area_m2 is None:
        return figures, ONE_QUOTE if single else None if figures else NO_AREA
    a = inputs.area_m2
    figures.append(Figure(
        label=_TABLE[intent], low=table.low * a, high=table.high * a, likely=table.likely * a,
        per_m2_low=table.low, per_m2_high=table.high, author=_AUTHOR,
        source=_APPROVED if reference.APPROVED_ON else _AWAITING, source_kind="reference_table",
        as_of=reference.APPROVED_ON or reference.COMPILED_ON, url=table.sources[0][1]))
    return figures, None


def _scenarios(costs: list[Figure], inputs: AffordInputs) -> tuple[list[Scenario], str | None]:
    ranges = [f for f in costs if f.low != f.high]
    if not ranges:
        return [], None
    base = ranges[0]  # the user's own range when they gave one, else the reference table
    # All three terms are the user's; a blank down payment is not taken as zero.
    financing = inputs.rate_percent is not None and inputs.years is not None and inputs.down_payment is not None
    out = []
    for key, cost in (("lower", base.low), ("likely", base.likely if base.likely is not None else base.low),
                      ("higher", base.high)):
        financed = max(cost - inputs.down_payment, 0) if financing else None
        out.append(Scenario(
            key=key, cost=round(cost, 2), financed=round(financed, 2) if financed is not None else None,
            monthly_payment=round(_payment(financed, inputs.rate_percent, inputs.years), 2) if financing else None,
            within_budget=cost <= inputs.budget if inputs.budget is not None else None,
            assumptions=list(_ASSUME[key]), moves_it=list(_MOVES)))
    return out, None if financing else NO_RATE


def _valuation(municipality: str | None, parish: str | None, region: str | None,
               inputs: AffordInputs) -> tuple[list[Figure], str | None]:
    place = ine.find(municipality, parish, region)
    if place is None:
        return [], NO_PLACE
    if inputs.area_m2 is None:
        return [], NO_VALUATION_AREA
    src = ine.snapshot()["source"]
    a, figures = inputs.area_m2, []
    kind = inputs.property_type or "total"
    per_m2 = place.bank_valuation.get(kind) or place.bank_valuation.get("total")
    if per_m2:
        b = src["bank_valuation"]
        figures.append(Figure(label=_BANK[kind if place.bank_valuation.get(kind) else "total"], low=per_m2 * a,
                              high=per_m2 * a, per_m2_low=per_m2, per_m2_high=per_m2, source=_INE, source_kind="official_statistics", as_of=b["period"],
                              url=b["url"]))
    s = src["sale_median"]
    for label, value in ((_SALE_MUNICIPALITY, place.municipal_sale_median), (_SALE_PARISH, place.parish_sale_median)):
        if value:
            figures.append(Figure(label=label, low=value * a, high=value * a, per_m2_low=value, per_m2_high=value,
                                  source=_INE,
                                  source_kind="official_statistics", as_of=s["period"], url=s["url"]))
    if len(figures) > 1:  # the spread of the official figures, each still shown on its own above
        lo, hi = min(f.per_m2_low for f in figures), max(f.per_m2_high for f in figures)
        figures.append(Figure(label=_RANGE, low=lo * a, high=hi * a, per_m2_low=lo, per_m2_high=hi,
                              source=_COMPUTED, source_kind="computed"))
    if len(figures) == 1:
        return figures, ONE_FIGURE
    return figures, None if figures else NO_PLACE


def afford(intent: str | None, municipality: str | None, parish: str | None, inputs: AffordInputs,
           region: str | None = None) -> AffordReport:
    costs, costs_note = _costs(intent, inputs)
    scenarios, financing_note = _scenarios(costs, inputs)
    valuation, valuation_note = _valuation(municipality, parish, region, inputs)
    return AffordReport(inputs=inputs, costs=costs, costs_note=costs_note, fees_note=FEES, scenarios=scenarios,
                        financing_note=financing_note, formula=FORMULA, valuation=valuation,
                        valuation_note=valuation_note, disclaimer=DISCLAIMER)
