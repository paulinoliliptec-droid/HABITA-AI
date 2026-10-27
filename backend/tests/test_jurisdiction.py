import pytest

from app.integrations.maps.geocoding import _parse_result
from app.services.jurisdiction import JurisdictionResolver
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
    [("PT", PortugalAdapter), ("pt", PortugalAdapter), ("US", GenericAdapter), (None, GenericAdapter)],
)
def test_resolver_selects_adapter(code, adapter_type):
    assert isinstance(JurisdictionResolver().adapter_for(code), adapter_type)
