from app.integrations.maps.geocoding import GeocodedLocation
from app.services.jurisdiction.base import (
    Jurisdiction,
    JurisdictionAdapter,
    JurisdictionLevel,
    child_id,
    country_level,
)


class GenericAdapter(JurisdictionAdapter):
    """Fallback for countries without a dedicated adapter.

    Reports the first- and second-order divisions Google returns under neutral
    labels. It never asserts a municipality or a competent authority: which
    body issues permits is not knowable from address components alone.
    """

    key = "generic"
    version = 2

    def resolve(self, location: GeocodedLocation) -> Jurisdiction:
        country = country_level(location)
        levels: list[JurisdictionLevel] = [country] if country else []
        parent_id = country.id if country else "unknown"

        for component_type, level_type, label in (
            ("administrative_area_level_1", "region", "Region"),
            ("administrative_area_level_2", "subregion", "Subregion"),
        ):
            name = location.long_name(component_type)
            if name:
                level = JurisdictionLevel(type=level_type, id=child_id(parent_id, name), name=name, label=label)
                levels.append(level)
                parent_id = level.id

        return Jurisdiction(
            id=levels[-1].id if levels else "unknown",
            country_code=country.id.upper() if country else "",
            levels=tuple(levels),
            locality=location.long_name("locality") or location.long_name("postal_town"),
            local_authority=None,
            coverage="unmodelled",
        )
