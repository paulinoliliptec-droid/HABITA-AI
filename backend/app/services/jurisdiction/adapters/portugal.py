"""Portugal: distrito / região autónoma → município → freguesia.

Google's Portuguese address components map as follows:

    administrative_area_level_1  distrito, or região autónoma (Açores, Madeira)
    administrative_area_level_2  município (concelho)
    administrative_area_level_3  freguesia (parish, often a union of parishes)

The competent local authority for building permits is the município's Câmara
Municipal (RJUE, Decreto-Lei n.º 555/99, art. 5.º).
"""

from app.integrations.maps.geocoding import GeocodedLocation
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

# Google returns several spellings for the autonomous regions; their IDs are fixed.
_AUTONOMOUS_REGION_IDS = {
    "acores": "acores",
    "azores": "acores",
    "regiao-autonoma-dos-acores": "acores",
    "madeira": "madeira",
    "regiao-autonoma-da-madeira": "madeira",
}

# Most municipalities take "de" ("Câmara Municipal de Cascais"). These take a
# contracted article in their official name.
_PREPOSITIONS = {
    "do": {
        "Alandroal", "Barreiro", "Bombarral", "Cadaval", "Cartaxo", "Corvo", "Crato",
        "Entroncamento", "Funchal", "Fundão", "Marco de Canaveses", "Montijo",
        "Nordeste", "Peso da Régua", "Porto", "Porto Santo", "Redondo", "Sabugal",
        "Sardoal", "Seixal",
    },
    "da": {
        "Amadora", "Batalha", "Calheta", "Chamusca", "Covilhã", "Figueira da Foz",
        "Golegã", "Guarda", "Horta", "Lourinhã", "Lousã", "Madalena", "Maia",
        "Marinha Grande", "Mealhada", "Mêda", "Moita", "Murtosa", "Nazaré",
        "Ponta do Sol", "Póvoa de Lanhoso", "Póvoa de Varzim", "Praia da Vitória",
        "Ribeira Brava", "Ribeira Grande", "Sertã", "Trofa", "Vidigueira",
    },
    "dos": {"Arcos de Valdevez"},
    "das": {"Caldas da Rainha", "Lajes das Flores", "Lajes do Pico", "Velas"},
}
_PREPOSITION_BY_MUNICIPALITY = {name: prep for prep, names in _PREPOSITIONS.items() for name in names}

RJUE_COMPETENCE = SourceRef(
    title="Regime Jurídico da Urbanização e da Edificação (RJUE), Decreto-Lei n.º 555/99",
    reference="art. 5.º",
)


def camara_municipal(municipality: str) -> str:
    """Display name of a município's Câmara Municipal."""
    preposition = _PREPOSITION_BY_MUNICIPALITY.get(municipality, "de")
    return f"Câmara Municipal {preposition} {municipality}"


class PortugalAdapter(JurisdictionAdapter):
    key = "PT"
    version = 2
    official_language = "pt"

    def resolve(self, location: GeocodedLocation) -> Jurisdiction:
        country = country_level(location)
        levels: list[JurisdictionLevel] = [country] if country else []
        parent_id = country.id if country else "pt"

        region_name = location.long_name("administrative_area_level_1")
        if region_name:
            autonomous_id = _AUTONOMOUS_REGION_IDS.get(slug(region_name))
            region = JurisdictionLevel(
                type="region",
                id=f"{parent_id}/{autonomous_id}" if autonomous_id else child_id(parent_id, region_name),
                name=region_name,
                label="Autonomous region" if autonomous_id else "District",
            )
            levels.append(region)
            parent_id = region.id

        authority = None
        municipality_name = location.long_name("administrative_area_level_2")
        if municipality_name:
            municipality = JurisdictionLevel(
                type="municipality", id=child_id(parent_id, municipality_name), name=municipality_name, label="Municipality"
            )
            levels.append(municipality)
            authority = Authority(
                id=f"{municipality.id}:camara-municipal",
                name=camara_municipal(municipality_name),
                kind="municipal_executive",
                jurisdiction_id=municipality.id,
                competence="Licensing of urban operations, including building permits (licenciamento urbanístico).",
                sources=(RJUE_COMPETENCE,),
            )
            parish_name = location.long_name("administrative_area_level_3")
            if parish_name:
                levels.append(
                    JurisdictionLevel(
                        type="subdivision", id=child_id(municipality.id, parish_name), name=parish_name, label="Parish"
                    )
                )

        governing = next((lvl for lvl in levels if lvl.type == "municipality"), levels[-1] if levels else None)
        return Jurisdiction(
            id=governing.id if governing else "pt",
            country_code=country.id.upper() if country else "PT",
            levels=tuple(levels),
            locality=location.long_name("locality"),
            local_authority=authority,
            coverage="modelled",
        )
