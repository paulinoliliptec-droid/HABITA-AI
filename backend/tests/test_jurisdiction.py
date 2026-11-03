import pytest

from app.integrations.maps.geocoding import _parse_result
from app.services.jurisdiction import JurisdictionResolver
from app.services.jurisdiction.adapters.cities import FranceAdapter, SingaporeAdapter, UnitedStatesAdapter
from app.services.jurisdiction.adapters.generic import GenericAdapter
from app.services.jurisdiction.adapters.portugal import PortugalAdapter, camara_municipal
from app.services.jurisdiction.base import slug
from tests import fixtures


def location(payload: dict, language: str = "pt"):
    return _parse_result(payload["results"][0], language)


def levels(j):
    return [(lvl.type, lvl.id, lvl.name, lvl.label) for lvl in j.levels]


def test_portugal_mainland_hierarchy_ids_and_authority():
    j = PortugalAdapter().resolve(location(fixtures.cascais()))

    assert levels(j) == [
        ("country", "pt", "Portugal", "Country"),
        ("region", "pt/lisboa", "Lisboa", "District"),
        ("municipality", "pt/lisboa/cascais", "Cascais", "Municipality"),
        ("subdivision", "pt/lisboa/cascais/cascais-e-estoril", "Cascais e Estoril", "Parish"),
    ]
    assert j.id == "pt/lisboa/cascais"
    assert j.country_code == "PT"
    assert j.coverage == "modelled"
    assert j.locality == "Cascais"

    authority = j.local_authority
    assert authority.id == "pt/lisboa/cascais:camara-municipal"
    assert authority.name == "Câmara Municipal de Cascais"
    assert authority.kind == "municipal_executive"
    assert authority.jurisdiction_id == "pt/lisboa/cascais"
    assert authority.sources[0].reference == "art. 5.º"


def test_portugal_contracted_preposition_in_display_name_only():
    j = PortugalAdapter().resolve(location(fixtures.porto()))
    assert j.local_authority.name == "Câmara Municipal do Porto"
    assert j.local_authority.id == "pt/porto/porto:camara-municipal"


def test_portugal_autonomous_region_has_canonical_id():
    j = PortugalAdapter().resolve(location(fixtures.funchal()))
    region = j.level("region")
    assert (region.id, region.label) == ("pt/madeira", "Autonomous region")
    assert j.id == "pt/madeira/funchal"


def test_portugal_ids_are_independent_of_accents_and_case():
    assert slug("Região Autónoma dos Açores") == "regiao-autonoma-dos-acores"
    assert slug("  São João da Madeira ") == "sao-joao-da-madeira"


def test_portugal_without_municipality_does_not_guess_authority():
    payload = fixtures.cascais()
    payload["results"][0]["address_components"] = [
        c for c in payload["results"][0]["address_components"] if "administrative_area_level_2" not in c["types"]
    ]
    j = PortugalAdapter().resolve(location(payload))
    assert j.level("municipality") is None
    assert j.local_authority is None
    assert j.coverage == "modelled"  # the country is modelled; this address just lacks the evidence
    assert j.id == "pt/lisboa"


@pytest.mark.parametrize(
    ("municipality", "expected"),
    [
        ("Lisboa", "Câmara Municipal de Lisboa"),
        ("Amadora", "Câmara Municipal da Amadora"),
        ("Caldas da Rainha", "Câmara Municipal das Caldas da Rainha"),
        ("Arcos de Valdevez", "Câmara Municipal dos Arcos de Valdevez"),
    ],
)
def test_camara_municipal_naming(municipality, expected):
    assert camara_municipal(municipality) == expected


def test_generic_adapter_reports_neutral_levels_and_no_municipality():
    j = GenericAdapter().resolve(location(fixtures.mountain_view(), "en"))
    assert levels(j) == [
        ("country", "us", "United States", "Country"),
        ("region", "us/california", "California", "Region"),
        ("subregion", "us/california/santa-clara-county", "Santa Clara County", "Subregion"),
    ]
    # A postal place is never promoted to the permit-competent municipality.
    assert j.level("municipality") is None
    assert j.locality == "Mountain View"
    assert j.local_authority is None
    assert j.coverage == "unmodelled"


@pytest.mark.parametrize(
    ("code", "adapter_type"),
    [("PT", PortugalAdapter), ("pt", PortugalAdapter), ("US", UnitedStatesAdapter), ("FR", FranceAdapter),
     ("SG", SingaporeAdapter), ("DE", GenericAdapter), (None, GenericAdapter)],
)
def test_resolver_selects_adapter(code, adapter_type):
    assert isinstance(JurisdictionResolver().adapter_for(code), adapter_type)


def test_new_york_city_is_partial_with_the_department_of_buildings():
    j = UnitedStatesAdapter().resolve(location(fixtures.new_york(), "en"))
    assert levels(j) == [
        ("country", "us", "United States", "Country"),
        ("region", "us/new-york", "New York", "State"),
        ("municipality", "us/new-york/new-york-city", "New York City", "City"),
        ("subdivision", "us/new-york/new-york-city/manhattan", "Manhattan", "Borough"),
    ]
    assert j.id == "us/new-york/new-york-city" and j.coverage == "partial"
    assert j.local_authority.name == "NYC Department of Buildings"
    assert j.local_authority.jurisdiction_id == j.id
    # Every source either has an official https URL or is a reference without one; nothing is inferred.
    assert all(s.url is None or s.url.startswith("https://") for s in j.local_authority.sources)


def test_elsewhere_in_the_us_stays_generic():
    j = UnitedStatesAdapter().resolve(location(fixtures.mountain_view(), "en"))
    assert j == GenericAdapter().resolve(location(fixtures.mountain_view(), "en"))
    assert j.coverage == "unmodelled" and j.local_authority is None


def test_paris_is_partial_with_the_mayor_and_the_plu():
    j = FranceAdapter().resolve(location(fixtures.paris(), "fr"))
    assert levels(j) == [
        ("country", "fr", "France", "Country"),
        ("region", "fr/ile-de-france", "Île-de-France", "Region"),
        ("subregion", "fr/ile-de-france/paris", "Paris", "Department"),
        ("municipality", "fr/ile-de-france/paris/paris", "Paris", "Commune"),
    ]
    assert j.coverage == "partial" and j.local_authority.name == "Maire de Paris"
    assert any(s.reference == "art. L422-1" for s in j.local_authority.sources)


def test_elsewhere_in_france_stays_generic():
    j = FranceAdapter().resolve(location(fixtures.lyon(), "fr"))
    assert j.coverage == "unmodelled" and j.local_authority is None and j.level("municipality") is None


def test_singapore_is_partial_with_the_ura():
    j = SingaporeAdapter().resolve(location(fixtures.singapore(), "en"))
    assert levels(j) == [
        ("country", "sg", "Singapore", "Country"),
        ("municipality", "sg/singapore", "Singapore", "City-state"),
    ]
    assert j.coverage == "partial" and j.local_authority.name == "Urban Redevelopment Authority (URA)"


def test_a_brooklyn_address_without_a_locality_is_still_new_york_city():
    """Codex landing r2: Google may return a borough only as a sublocality; the county decides."""
    j = UnitedStatesAdapter().resolve(location(fixtures.brooklyn(), "en"))
    assert j.coverage == "partial" and j.id == "us/new-york/new-york-city"
    assert j.level("subdivision").name == "Brooklyn"
    assert j.local_authority.name == "NYC Department of Buildings"


def test_the_borough_comes_from_the_county_when_google_gives_no_sublocality():
    """Codex market r1: a Brooklyn address with Kings County but no sublocality still gets its borough."""
    payload = fixtures.brooklyn()
    payload["results"][0]["address_components"] = [
        c for c in payload["results"][0]["address_components"] if "sublocality" not in c["types"]]
    j = UnitedStatesAdapter().resolve(location(payload, "en"))
    assert j.level("subdivision").name == "Brooklyn" and j.coverage == "partial"


def test_a_neighbourhood_sublocality_never_replaces_the_borough():
    """Codex market r2: "Williamsburg" as a sublocality of a Kings County address: the borough stays Brooklyn."""
    payload = fixtures.brooklyn()
    for c in payload["results"][0]["address_components"]:
        if "sublocality" in c["types"]:
            c["long_name"] = c["short_name"] = "Williamsburg"
    j = UnitedStatesAdapter().resolve(location(payload, "en"))
    assert j.level("subdivision").name == "Brooklyn"
