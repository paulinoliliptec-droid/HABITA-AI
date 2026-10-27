"""Geocoding API payloads shaped like real Google responses."""


def _component(long_name: str, short_name: str, *types: str) -> dict:
    return {"long_name": long_name, "short_name": short_name, "types": list(types)}


def geocode_payload(
    *,
    place_id: str,
    formatted_address: str,
    lat: float,
    lng: float,
    components: list[dict],
    location_type: str = "ROOFTOP",
    partial_match: bool = False,
) -> dict:
    result = {
        "place_id": place_id,
        "formatted_address": formatted_address,
        "geometry": {"location": {"lat": lat, "lng": lng}, "location_type": location_type},
        "address_components": components,
        "types": ["street_address"],
    }
    if partial_match:
        result["partial_match"] = True
    return {"status": "OK", "results": [result]}


CASCAIS_PLACE_ID = "ChIJcascais-praca-5-outubro"


def cascais(language: str = "pt") -> dict:
    district = "Lisboa" if language == "pt" else "Lisbon"
    return geocode_payload(
        place_id=CASCAIS_PLACE_ID,
        formatted_address="Praça 5 de Outubro, 2750-642 Cascais, Portugal",
        lat=38.6969,
        lng=-9.4215,
        components=[
            _component("Praça 5 de Outubro", "Praça 5 de Outubro", "route"),
            _component("Cascais", "Cascais", "locality", "political"),
            _component("Cascais e Estoril", "Cascais e Estoril", "administrative_area_level_3", "political"),
            _component("Cascais", "Cascais", "administrative_area_level_2", "political"),
            _component(district, district, "administrative_area_level_1", "political"),
            _component("Portugal", "PT", "country", "political"),
            _component("2750-642", "2750-642", "postal_code"),
        ],
    )


def porto() -> dict:
    return geocode_payload(
        place_id="ChIJporto-aliados",
        formatted_address="Av. dos Aliados, 4000-064 Porto, Portugal",
        lat=41.1486,
        lng=-8.6110,
        components=[
            _component("Avenida dos Aliados", "Av. dos Aliados", "route"),
            _component("Porto", "Porto", "locality", "political"),
            _component(
                "Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e Vitória",
                "Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e Vitória",
                "administrative_area_level_3",
                "political",
            ),
            _component("Porto", "Porto", "administrative_area_level_2", "political"),
            _component("Porto", "Porto", "administrative_area_level_1", "political"),
            _component("Portugal", "PT", "country", "political"),
        ],
    )


def funchal() -> dict:
    return geocode_payload(
        place_id="ChIJfunchal-se",
        formatted_address="Largo da Sé, 9000-050 Funchal, Portugal",
        lat=32.6489,
        lng=-16.9084,
        components=[
            _component("Funchal", "Funchal", "locality", "political"),
            _component("Sé", "Sé", "administrative_area_level_3", "political"),
            _component("Funchal", "Funchal", "administrative_area_level_2", "political"),
            _component("Madeira", "Madeira", "administrative_area_level_1", "political"),
            _component("Portugal", "PT", "country", "political"),
        ],
    )


def mountain_view() -> dict:
    return geocode_payload(
        place_id="ChIJmountain-view",
        formatted_address="1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
        lat=37.4220,
        lng=-122.0841,
        components=[
            _component("1600", "1600", "street_number"),
            _component("Amphitheatre Parkway", "Amphitheatre Pkwy", "route"),
            _component("Mountain View", "Mountain View", "locality", "political"),
            _component("Santa Clara County", "Santa Clara County", "administrative_area_level_2", "political"),
            _component("California", "CA", "administrative_area_level_1", "political"),
            _component("United States", "US", "country", "political"),
        ],
    )


def cascais_premise(
    *,
    place_id: str,
    postal_code: str = "2750-512",
    lat: float = 38.69712,
    lng: float = -9.42932,
    street_number: str = "1011",
    location_type: str = "ROOFTOP",
    subpremise: str | None = None,
) -> dict:
    """A numbered Cascais address. Google can return different place IDs and postcodes
    for the same premise depending on the entry path (observed live for this address)."""
    components = [
        _component(street_number, street_number, "street_number"),
        _component("Avenida 25 de Abril", "Av. 25 de Abril", "route"),
        _component("Cascais", "Cascais", "locality", "political"),
        _component("União das freguesias de Cascais e Estoril", "Cascais e Estoril", "administrative_area_level_3", "political"),
        _component("Cascais", "Cascais", "administrative_area_level_2", "political"),
        _component("Lisboa", "Lisboa", "administrative_area_level_1", "political"),
        _component("Portugal", "PT", "country", "political"),
        _component(postal_code, postal_code, "postal_code"),
    ]
    if subpremise:
        components.insert(0, _component(subpremise, subpremise, "subpremise"))
    return geocode_payload(
        place_id=place_id,
        formatted_address=f"Av. 25 de Abril {street_number}, {postal_code} Cascais, Portugal",
        lat=lat,
        lng=lng,
        components=components,
        location_type=location_type,
    )
