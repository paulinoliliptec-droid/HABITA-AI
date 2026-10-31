"""HR-011 AFFORD: costs, financing and market price, all computed by code (AC11.1–AC11.12)."""

import pytest

from app.schemas.afford import AffordInputs
from app.services.afford import ine, reference
from app.services.afford.compute import (
    DISCLAIMER,
    NO_AREA,
    NO_PLACE,
    NO_RATE,
    NOT_COVERED,
    _payment,
    afford,
)
from app.services.i18n.translator import PINNED
from app.services.report import afford_lines
from tests.permit_fakes import ANSWERS, ScriptedModel, make_client
from tests.test_permit_workflow import answer, create, run

CASCAIS, PARISH = "Cascais", "União das freguesias de Cascais e Estoril"


def test_costs_are_a_range_from_the_table_never_one_price():
    r = afford("interior_works", CASCAIS, PARISH, AffordInputs(area_m2=80))
    (table,) = r.costs
    t = reference.COSTS["interior_works"]
    assert (table.low, table.high, table.likely) == (t.low * 80, t.high * 80, t.likely * 80)
    assert table.low < table.likely < table.high and table.source_kind == "reference_table"
    assert "awaiting" in table.source and table.url and table.as_of == reference.COMPILED_ON and table.author
    assert (table.per_m2_low, table.per_m2_high) == (t.low, t.high)


def test_the_users_quotes_come_first_labelled_as_declared_and_drive_the_scenarios():
    r = afford("interior_works", CASCAIS, None, AffordInputs(area_m2=80, quote_low=30_000, quote_high=20_000))
    quote, table = r.costs
    assert (quote.low, quote.high, quote.source_kind) == (20_000, 30_000, "user_declared")
    assert table.source_kind == "reference_table"  # kept apart, never averaged
    assert [s.cost for s in r.scenarios] == [20_000, 25_000, 30_000]


@pytest.mark.parametrize(("intent", "inputs", "note"), [
    ("general_overview", AffordInputs(area_m2=80), NOT_COVERED),
    ("out_of_scope", AffordInputs(area_m2=80), NOT_COVERED),
    ("interior_works", AffordInputs(), NO_AREA),
])
def test_without_a_basis_no_cost_is_shown(intent, inputs, note):
    r = afford(intent, CASCAIS, None, inputs)
    assert r.costs == [] and r.scenarios == [] and r.costs_note == note


@pytest.mark.parametrize("inputs", [AffordInputs(area_m2=50), AffordInputs(area_m2=50, rate_percent=3, years=20)],
                         ids=["nothing", "no-down-payment"])
def test_no_default_rate_or_down_payment_ever(inputs):
    r = afford("interior_works", CASCAIS, None, inputs)
    assert len(r.scenarios) == 3 and all(s.monthly_payment is None for s in r.scenarios)
    assert r.financing_note == NO_RATE


def test_financing_uses_the_users_terms_and_the_stated_formula():
    r = afford("interior_works", CASCAIS, None,
               AffordInputs(area_m2=50, rate_percent=3.6, years=20, down_payment=10_000, budget=50_000))
    likely = next(s for s in r.scenarios if s.key == "likely")
    assert likely.financed == likely.cost - 10_000
    expected = likely.financed * 0.003 / (1 - 1.003 ** -240)
    assert likely.monthly_payment == round(expected, 2)
    assert [s.within_budget for s in r.scenarios] == [True, True, False]  # 25k, 50k, 75k against 50k
    assert all(s.assumptions and s.moves_it for s in r.scenarios)


def test_a_zero_rate_and_a_down_payment_above_the_cost():
    assert _payment(12_000, 0, 1) == 1000
    r = afford("interior_works", CASCAIS, None, AffordInputs(area_m2=10, rate_percent=3, years=10, down_payment=10**6))
    assert all(s.financed == 0 and s.monthly_payment == 0 for s in r.scenarios)


def test_market_price_from_ine_each_source_apart():
    r = afford("interior_works", CASCAIS, PARISH, AffordInputs(area_m2=100, property_type="house"))
    place = ine.find(CASCAIS, PARISH)
    *sources, spread = r.valuation
    per_m2 = [place.bank_valuation["house"], place.municipal_sale_median, place.parish_sale_median]
    assert [(f.label, f.per_m2_low, f.low) for f in sources] == [
        ("Median bank valuation of houses in the municipality", per_m2[0], per_m2[0] * 100),
        ("Median sale price in the municipality, last 12 months", per_m2[1], per_m2[1] * 100),
        ("Median sale price in the parish, last 12 months", per_m2[2], per_m2[2] * 100),
    ]
    assert all(f.source_kind == "official_statistics" and f.as_of and f.url for f in sources)
    assert spread.source_kind == "computed" and (spread.per_m2_low, spread.per_m2_high) == (min(per_m2), max(per_m2))
    assert (spread.low, spread.high) == (min(per_m2) * 100, max(per_m2) * 100)


def test_an_unknown_or_ambiguous_municipality_shows_no_price(monkeypatch):
    assert afford("interior_works", "Atlantis", None, AffordInputs(area_m2=100)).valuation_note == NO_PLACE
    snap = ine.snapshot()
    twin = {**snap["places"], "9Z99999": {"name": "Cascais", "sale_median": 1}}
    monkeypatch.setattr(ine, "snapshot", lambda: {**snap, "places": twin})
    r = afford("interior_works", CASCAIS, None, AffordInputs(area_m2=100))
    assert r.valuation == [] and r.valuation_note == NO_PLACE


def test_every_text_is_pinned_and_numbers_live_in_fields():
    r = afford("unit_conversion", CASCAIS, PARISH,
               AffordInputs(area_m2=123, rate_percent=4, years=30, quote_low=12345, budget=54321))
    texts = [r.disclaimer, r.fees_note, r.formula, *(f.label for f in r.costs + r.valuation),
             *(f.source for f in r.costs + r.valuation),
             *(x for s in r.scenarios for x in (*s.assumptions, *s.moves_it))]
    assert all(t in PINNED for t in texts), [t for t in texts if t not in PINNED]
    joined = " ".join(texts)
    assert not any(str(round(v)) in joined for f in r.costs + r.valuation for v in (f.low, f.high))  # amounts stay out


def test_the_report_pdf_and_voice_carry_it_with_the_disclaimer():
    with make_client(ScriptedModel()) as client:
        matter_id = create(client)["matter_id"]
        assert client.get(f"/api/permit/matters/{matter_id}/report").json()["afford"] is None  # nothing entered
        res = client.put(f"/api/permit/matters/{matter_id}/afford",
                         json={"area_m2": 90, "property_type": "apartment", "rate_percent": 3.5, "years": 25})
        assert res.status_code == 200, res.text
        report = client.get(f"/api/permit/matters/{matter_id}/report").json()
        pt = client.get(f"/api/permit/matters/{matter_id}/report", params={"lang": "pt"}).json()
        lines = client.get(f"/api/permit/matters/{matter_id}/report/voice").json()["lines"]
        pdf = client.get(f"/api/permit/matters/{matter_id}/report.pdf")
    assert report["afford"]["inputs"]["area_m2"] == 90 and report["afford"]["valuation"]
    assert pt["afford"]["disclaimer"] == PINNED[DISCLAIMER]
    assert any("Costs, financing and price" in line for line in lines)
    assert any(DISCLAIMER.split(".")[0] in line for line in lines)
    assert pdf.status_code == 200


def test_costs_need_the_matter_capability_and_never_touch_the_assessment():
    with make_client(ScriptedModel()) as client:
        matter_id = create(client)["matter_id"]
        run(client, matter_id)
        token = client.headers.pop("Authorization")
        assert client.put(f"/api/permit/matters/{matter_id}/afford", json={"area_m2": 50}).status_code in (401, 403)
        client.headers["Authorization"] = token
        client.put(f"/api/permit/matters/{matter_id}/afford", json={"area_m2": 50, "budget": 1})
        answer(client, matter_id, ANSWERS)
        done = run(client, matter_id)
        evidence = client.get(f"/api/permit/matters/{matter_id}/evidence").json()
    assert done["state"] == "VERIFIED"
    assert not any("afford" in str(e) or "budget" in str(e) for e in evidence)


@pytest.mark.parametrize("bad", [{"area_m2": -1}, {"rate_percent": 99}, {"years": 0}, {"budget": -5}])
def test_impossible_figures_are_refused(bad):
    with make_client(ScriptedModel()) as client:
        matter_id = create(client)["matter_id"]
        assert client.put(f"/api/permit/matters/{matter_id}/afford", json=bad).status_code == 422


def test_euro_amounts_are_formatted_without_decimals():
    assert afford_lines.euros(1234567.4) == "1 234 567 €"



def test_a_single_quote_is_shown_but_never_becomes_the_range():
    alone = afford("general_overview", CASCAIS, None, AffordInputs(quote_low=20_000))
    assert [f.source_kind for f in alone.costs] == ["user_declared"] and alone.scenarios == []
    with_table = afford("interior_works", CASCAIS, None, AffordInputs(area_m2=40, quote_high=20_000))
    assert [s.cost for s in with_table.scenarios] == [500 * 40, 1000 * 40, 1500 * 40]  # the table's range, not the quote


@pytest.mark.parametrize(("name", "region", "found"), [
    ("Lagoa", None, None), ("Lagoa", "Região Autónoma dos Açores", "Lagoa (R.A.A.)"), ("Lagoa", "Faro", "Lagoa"),
    ("Calheta", None, None), ("Calheta", "Região Autónoma da Madeira", "Calheta (R.A.M.)"),
])
def test_homonym_municipalities_need_their_region(name, region, found):
    place = ine.find(name, None, region)
    assert (place.municipality if place else None) == found


def test_a_parish_is_only_found_inside_its_municipality():
    assert ine.find("Sintra", PARISH).parish is None


# --- Codex HR-011 round 2 regressions ------------------------------------------------------------------------------

from app.services.afford.compute import ONE_FIGURE  # noqa: E402


def test_one_official_figure_is_said_to_be_no_range():
    snap = ine.snapshot()["places"]
    code, place = next((c, p) for c, p in snap.items()
                       if len(c) == 7 and "sale_median" in p and not p.get("bank_valuation") and "(" not in p["name"])
    r = afford("interior_works", place["name"], None, AffordInputs(area_m2=100))
    assert len(r.valuation) == 1 and r.valuation_note == ONE_FIGURE


def test_pdf_and_voice_rows_carry_assumptions_and_the_declared_area():
    r = afford("interior_works", CASCAIS, PARISH, AffordInputs(area_m2=87))
    text = " ".join(b for _, b in afford_lines.rows(r, "en"))
    assert "Usual finishes." in text and "The area actually renovated." in text
    assert "Totals use the area you declared: 87 m²" in text
    pt = " ".join(b for _, b in afford_lines.rows(r, "pt"))
    assert "Os totais usam a área que indicou: 87 m²" in pt
