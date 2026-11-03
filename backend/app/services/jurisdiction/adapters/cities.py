"""Partial coverage outside Portugal (afinamentos 2026-11-02, owner: New York, Paris, Singapore).

For one city per country, HABITA names the government that decides on building permits and the official sources to
consult, each with its legal basis. Nothing more: no rule of these places is in HABITA's verified registry, so an
answer for them is never VERIFIED (the permit catalogue covers Portugal only). Anywhere else in these countries the
generic adapter's behaviour applies: the hierarchy Google returns, no authority.

Every URL below answered from its official host on 2026-11-02 with the expected page title; a reference whose official
site refuses automated checks (Légifrance, Singapore Statutes Online, the NYC Charter's publisher) has no URL.
"""

from app.integrations.maps.geocoding import GeocodedLocation
from app.services.jurisdiction.adapters.generic import GenericAdapter
from app.services.jurisdiction.base import (
    Authority,
    Jurisdiction,
    JurisdictionAdapter,
    JurisdictionLevel,
    SourceRef,
    child_id,
    country_level,
    slug,
)

NYC_ZONING = SourceRef(title="NYC Zoning Resolution (Department of City Planning)", url="https://zr.planning.nyc.gov/")
NYC_DOB = SourceRef(title="NYC Department of Buildings", url="https://www.nyc.gov/site/buildings/index.page")
NYC_CHARTER = SourceRef(title="New York City Charter", reference="Chapter 26, Department of Buildings")
PARIS_PLU = SourceRef(title="Plan Local d'Urbanisme de Paris (Ville de Paris)",
                      url="https://www.paris.fr/pages/le-plan-local-d-urbanisme-plu-2329")
PARIS_PSMV = SourceRef(title="Plans de Sauvegarde et de Mise en Valeur (Marais, part of the 7th arrondissement)",
                       url="https://www.paris.fr/pages/secteurs-sauvegardes-psmv-2351/")
CODE_URBANISME = SourceRef(title="Code de l'urbanisme", reference="art. L422-1")
URA_MASTER_PLAN = SourceRef(title="URA Master Plan", url="https://www.ura.gov.sg/land-planning/master-plan/")
URA_DC = SourceRef(title="URA Development Control Guidelines", url="https://www.ura.gov.sg/guidelines/development-control/")
BCA = SourceRef(title="Building and Construction Authority (building plans)", url="https://www1.bca.gov.sg/")
PLANNING_ACT_SG = SourceRef(title="Planning Act 1998 (Singapore)")


def _hierarchy(location: GeocodedLocation, labels: tuple[tuple[str, str, str], ...]) -> tuple[list[JurisdictionLevel], str]:
    country = country_level(location)
    levels: list[JurisdictionLevel] = [country] if country else []
    parent_id = country.id if country else "unknown"
    for component_type, level_type, label in labels:
        name = location.long_name(component_type)
        if name:
            level = JurisdictionLevel(type=level_type, id=child_id(parent_id, name), name=name, label=label)  # type: ignore[arg-type]
            levels.append(level)
            parent_id = level.id
    return levels, parent_id


def _partial(location: GeocodedLocation, levels: list[JurisdictionLevel], municipality: JurisdictionLevel,
             authority: Authority) -> Jurisdiction:
    country = levels[0] if levels else None
    return Jurisdiction(
        id=municipality.id,
        country_code=country.id.upper() if country else "",
        levels=tuple([*levels, municipality]),
        locality=location.long_name("locality"),
        local_authority=authority,
        coverage="partial",
    )


#: New York City is exactly these five counties (one per borough); Google may give a borough's address no locality
#: ("Brooklyn" as a sublocality only), so the county decides, not the locality.
NYC_COUNTIES = {"New York County": "Manhattan", "Kings County": "Brooklyn", "Queens County": "Queens",
                "Bronx County": "Bronx", "Richmond County": "Staten Island"}


class UnitedStatesAdapter(JurisdictionAdapter):
    """New York City only: the city, not its counties, issues building permits (Department of Buildings)."""

    key = "US"
    version = 1
    official_language = "en"

    def resolve(self, location: GeocodedLocation) -> Jurisdiction:
        state = location.component("administrative_area_level_1")
        if not (state and state.short_name == "NY" and location.long_name("administrative_area_level_2") in NYC_COUNTIES):
            return GenericAdapter().resolve(location)
        levels, _ = _hierarchy(location, (("administrative_area_level_1", "region", "State"),))
        city = JurisdictionLevel(type="municipality", id=child_id(levels[-1].id, "New York City"),
                                 name="New York City", label="City")
        # Each county is exactly one borough: the county decides, never a sublocality, which may be a neighbourhood such
        # as "Williamsburg" (Codex market r1-r2).
        borough = NYC_COUNTIES[location.long_name("administrative_area_level_2")]
        authority = Authority(
            id=f"{city.id}:department-of-buildings",
            name="NYC Department of Buildings",
            kind="municipal_agency",
            jurisdiction_id=city.id,
            competence="Construction and alteration permits under the NYC Building Code and the Zoning Resolution.",
            sources=(NYC_CHARTER, NYC_DOB, NYC_ZONING),
        )
        result = _partial(location, levels, city, authority)
        if borough:
            sub = JurisdictionLevel(type="subdivision", id=child_id(city.id, borough), name=borough, label="Borough")
            result = Jurisdiction(id=result.id, country_code=result.country_code, levels=(*result.levels, sub),
                                  locality=result.locality, local_authority=authority, coverage="partial")
        return result


class FranceAdapter(JurisdictionAdapter):
    """Paris only: with a local plan, the mayor decides on building permits in the commune's name (PLU, or a PSMV in the
    safeguarded sectors)."""

    key = "FR"
    version = 1
    official_language = "fr"

    def resolve(self, location: GeocodedLocation) -> Jurisdiction:
        if location.long_name("locality") != "Paris" or slug(location.long_name("administrative_area_level_2") or "") != "paris":
            return GenericAdapter().resolve(location)
        levels, parent = _hierarchy(location, (
            ("administrative_area_level_1", "region", "Region"),
            ("administrative_area_level_2", "subregion", "Department"),
        ))
        commune = JurisdictionLevel(type="municipality", id=child_id(parent, "Paris"), name="Paris", label="Commune")
        authority = Authority(
            id=f"{commune.id}:maire",
            name="Maire de Paris",
            kind="mayor",
            jurisdiction_id=commune.id,
            competence="Building permits and prior declarations (permis de construire, déclaration préalable) in the commune, under the local plan (PLU) or, in the Marais and part of the 7th arrondissement, a safeguarding plan (PSMV).",
            sources=(CODE_URBANISME, PARIS_PLU, PARIS_PSMV),
        )
        return _partial(location, levels, commune, authority)


class SingaporeAdapter(JurisdictionAdapter):
    """Singapore, a city-state: planning permission from the URA; building plans approved by the BCA."""

    key = "SG"
    version = 1
    official_language = "en"

    def resolve(self, location: GeocodedLocation) -> Jurisdiction:
        country = country_level(location)
        if country is None or country.id != "sg":
            return GenericAdapter().resolve(location)
        city = JurisdictionLevel(type="municipality", id="sg/singapore", name="Singapore", label="City-state")
        authority = Authority(
            id=f"{city.id}:ura",
            name="Urban Redevelopment Authority (URA)",
            kind="national_planning_authority",
            jurisdiction_id=city.id,
            competence="Planning permission for development under the Master Plan; building plans are approved separately by the BCA.",
            sources=(PLANNING_ACT_SG, URA_MASTER_PLAN, URA_DC, BCA),
        )
        return _partial(location, [country], city, authority)
