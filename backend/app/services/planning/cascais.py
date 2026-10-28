"""Cascais planning context: the PDM-Cascais, with a controlled manual-confirmation fallback.

HABITA has not yet verified an official machine-readable service that can reliably
classify an arbitrary Cascais coordinate against the PDM's zoning layers (the official
maps are published as PDF). Until one is validated and trusted in the registry, this
resolver has no layer connector and returns ``requires_manual_confirmation`` with the
exact official maps to check. Adding a connector later changes no contract.
"""

from app.services.planning.resolver import LayerConnector, ManualDocument, OfficialPlanningResolver
from app.services.sources.catalog import CASCAIS
from app.services.sources.registry import OfficialSourceRegistry

DOCUMENTS = (
    ManualDocument("cascais-pdm-planta-01-02", "Land-use category (qualificação do solo) of the parcel."),
    ManualDocument("cascais-pdm-planta-01-01", "Urban or rustic land classification (classificação do solo)."),
    ManualDocument("cascais-pdm-planta-01-06", "Heritage protections shown on the planning map."),
    ManualDocument("cascais-pdm-planta-02-04", "Heritage constraints (servidões e restrições)."),
    ManualDocument("cascais-pdm-planta-02-01-03a", "Reserva Ecológica Nacional constraints (map A)."),
    ManualDocument("cascais-pdm-planta-02-01-03b", "Reserva Ecológica Nacional constraints (map B)."),
    ManualDocument("cascais-pdm-planta-01-10a", "Coastal protection regime (POC-ACE), map A."),
    ManualDocument("cascais-pdm-planta-01-10b", "Coastal protection regime (POC-ACE), map B."),
    ManualDocument("cascais-pdm-planta-02-01-01", "Protected areas (e.g. Parque Natural de Sintra-Cascais)."),
    ManualDocument("cascais-pdm", "The Regulamento's rules for the category found on the maps."),
    ManualDocument("cascais-pdm-elementos", "The Câmara's index of the PDM documents in force."),
)


def cascais_resolver(registry: OfficialSourceRegistry, connector: LayerConnector | None = None) -> OfficialPlanningResolver:
    return OfficialPlanningResolver(
        jurisdiction_id=CASCAIS,
        name="cascais-pdm",
        instrument_source_id="cascais-pdm",
        registry=registry,
        documents=DOCUMENTS,
        connector=connector,
    )
