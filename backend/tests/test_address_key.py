from app.integrations.maps.geocoding import _parse_result
from app.services.jurisdiction.adapters.portugal import PortugalAdapter
from app.services.property_location import address_key
from tests import fixtures


def key_for(payload: dict) -> str | None:
    location = _parse_result(payload["results"][0], "pt")
    return address_key(location, PortugalAdapter().resolve(location))


def test_premise_key_ignores_postcode_and_place_id():
    a = key_for(fixtures.cascais_premise(place_id="A", postal_code="2750-515"))
    b = key_for(fixtures.cascais_premise(place_id="B", postal_code="2750-512"))
    assert a == b == "pt/lisboa/cascais|avenida-25-de-abril|1011|"


def test_units_and_numbers_stay_distinct():
    base = key_for(fixtures.cascais_premise(place_id="A"))
    assert key_for(fixtures.cascais_premise(place_id="A", subpremise="2º Esq")) != base
    assert key_for(fixtures.cascais_premise(place_id="A", street_number="1013")) != base


def test_no_key_without_a_street_number_or_premise_precision():
    assert key_for(fixtures.cascais()) is None  # a square, no street number
    assert key_for(fixtures.cascais_premise(place_id="A", location_type="GEOMETRIC_CENTER")) is None
    assert key_for(fixtures.cascais_premise(place_id="A", location_type="APPROXIMATE")) is None
