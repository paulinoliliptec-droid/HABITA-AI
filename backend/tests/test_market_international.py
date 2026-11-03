"""Official market prices for the partial-coverage cities (afinamentos 2026-11-03): medians computed by HABITA from open
official datasets, looked up offline from a dated snapshot."""

import json

from app.services.afford import international as intl


def test_the_paris_arrondissement_comes_from_the_postcode():
    assert intl.paris_arrondissement("10 Rue de Rivoli, 75004 Paris, France") == "75104"
    assert intl.paris_arrondissement("1 Av. Foch, 75116 Paris, France") == "75116"
    assert intl.paris_arrondissement("Lyon 69002") is None and intl.paris_arrondissement("75021 Paris") is None


def test_nyc_boroughs_are_named_as_google_gives_them():
    assert intl.nyc_borough("Manhattan") == "Manhattan" and intl.nyc_borough("The Bronx") == "Bronx"
    assert intl.nyc_borough("Jersey City") is None and intl.nyc_borough(None) is None


def test_figures_come_from_the_snapshot_for_covered_cities_only():
    paris = intl.figures_for("fr/ile-de-france/paris/paris", "10 Rue de Rivoli, 75004 Paris, France", None)
    nyc = intl.figures_for("us/new-york/new-york-city", "350 5th Ave, New York, NY 10118, USA", "Manhattan")
    sg = intl.figures_for("sg/singapore", "1 Raffles Pl, Singapore 048616", None)
    assert [f["unit"] for f in paris + nyc + sg] == ["€/m²", "US$", "S$/m²"]
    assert paris[0]["area"] == "Paris 4e arrondissement" and paris[0]["count"] > 100
    assert all(f["url"].startswith("https://") and f["source"] and f["period"] for f in paris + nyc + sg)
    assert intl.figures_for("pt/lisboa/cascais", "Cascais", None) == []  # Portugal keeps INE, in a matter's costs
    assert intl.figures_for("us/new-york/new-york-city", "x", "Hoboken") == []


def test_paris_counts_single_apartment_sales_and_drops_mixed_or_absurd_ones():
    header = "id_mutation,nature_mutation,valeur_fonciere,type_local,surface_reelle_bati"
    rows = [
        "m1,Vente,500000,Appartement,50",       # 10 000 €/m²
        "m1,Vente,500000,Dépendance,",          # a cellar with it: still one apartment
        "m2,Vente,900000,Appartement,60",       # 15 000 €/m²
        "m3,Vente,800000,Appartement,40",       # two apartments in one sale: not a unit price
        "m3,Vente,800000,Appartement,45",
        "m4,Vente,300000,Local industriel. commercial ou assimilé,30",
        "m5,Vente,1,Appartement,40",            # a symbolic price
        "m6,Echange,400000,Appartement,40",     # not a sale
        "m7,Vente,2000000,Appartement,50",      # an apartment with a plot of land: not a unit price (Codex market r1)
        "m7,Vente,2000000,,",
    ]
    csv_text = "\n".join([header, *rows])
    out = intl.build_paris(lambda url: csv_text if url.endswith("75101.csv") else header, 2025)
    assert out["areas"] == {"75101": {"area": "Paris 1er arrondissement", "value": 12500, "count": 2}}


def test_nyc_keeps_homes_above_nominal_prices():
    rows = [{"sale_price": "1000000", "building_class_category": "13 CONDOS - ELEVATOR APARTMENTS"},
            {"sale_price": "2000000", "building_class_category": "01 ONE FAMILY DWELLINGS"},
            {"sale_price": "0", "building_class_category": "10 COOPS - ELEVATOR APARTMENTS"},
            {"sale_price": "9000000", "building_class_category": "21 OFFICE BUILDINGS"}]
    out = intl.build_nyc(lambda url, params: rows if "borough='1'" in params["$where"] else [], 2025)
    assert out["areas"] == {"Manhattan": {"area": "Manhattan", "value": 1500000, "count": 2}}


def test_singapore_is_per_square_metre_over_the_months_asked():
    def get_json(url, params):
        month = json.loads(params["filters"])["month"]
        return {"result": {"records": [{"resale_price": "500000", "floor_area_sqm": "100"}] if month == "2026-10" else []}}

    out = intl.build_singapore(get_json, ["2026-09", "2026-10"])
    assert out["areas"]["Singapore"]["value"] == 5000 and out["meta"]["period"] == "2026-09 to 2026-10"
    assert intl._last_complete_months(__import__("datetime").date(2026, 1, 15), 2) == ["2025-11", "2025-12"]


def test_the_market_endpoint_serves_partial_coverage_only():
    from types import SimpleNamespace

    import httpx
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from tests.permit_fakes import google_handler

    def prop(jid, coverage, address, levels=()):
        return SimpleNamespace(formatted_address=address,
                               jurisdiction=SimpleNamespace(id=jid, coverage=coverage, levels=list(levels)))

    props = {
        "prp_00000000000000a1": prop("fr/ile-de-france/paris/paris", "partial", "10 Rue de Rivoli, 75004 Paris, France"),
        "prp_00000000000000a2": prop("pt/lisboa/cascais", "modelled", "Praça 5 de Outubro, Cascais"),
    }

    class Properties:
        async def get(self, pid):
            return props.get(pid)

    settings = Settings(_env_file=None, google_maps_api_key="k", mongodb_uri=None, app_env="test",
                        allow_ephemeral_storage=True)
    with TestClient(create_app(settings, http_transport=httpx.MockTransport(google_handler))) as c:
        c.app.state.property_service = Properties()
        paris = c.get("/api/property/prp_00000000000000a1/market").json()
        cascais = c.get("/api/property/prp_00000000000000a2/market").json()
        missing = c.get("/api/property/prp_00000000000000ff/market")
    assert paris["figures"][0]["area"] == "Paris 4e arrondissement" and paris["retrieved_on"]
    assert cascais == {"retrieved_on": None, "figures": []} and missing.status_code == 404
