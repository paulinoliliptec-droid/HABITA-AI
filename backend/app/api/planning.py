"""Planning context and the official sources that apply to a property (HR-003). Public, like the property."""

from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel

from app.core.errors import NotFoundError
from app.schemas.sources import OfficialSourceOut, PlanningContextResponse

router = APIRouter(prefix="/api/property", tags=["planning"])


@router.get("/{property_id}/planning-context", response_model=PlanningContextResponse)
async def planning_context(
    property_id: Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")],
    request: Request,
) -> PlanningContextResponse:
    prop = await request.app.state.property_service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    return await planning_response(request.app.state, prop)


async def planning_response(state, prop) -> PlanningContextResponse:
    """The property's planning context and the trusted official sources of its jurisdiction chain (also used by the
    report, HR-004/HR-006, so both show exactly the same)."""
    context = await state.planning.resolve(prop)
    registry = state.official_sources
    chain = [level.id for level in prop.jurisdiction.levels]
    sources = []
    for s in await registry.trusted(chain):
        snapshot = await registry.repository.get_snapshot(s.latest_snapshot_id) if s.latest_snapshot_id else None
        sources.append(OfficialSourceOut(
            source_id=s.source_id, jurisdiction_id=s.jurisdiction_id, title=s.title, source_type=s.source_type, publisher=s.publisher,
            official_url=s.official_url, version=s.version, designation=s.designation,
            retrieval_method=s.retrieval_method, machine_readable=s.machine_readable, status=s.status,
            verified_on=s.provenance.verified_on, snapshot_retrieved_at=snapshot.retrieved_at if snapshot else None,
        ))
    # Most specific jurisdiction first (municipal before national); the instrument before its maps.
    sources.sort(key=lambda o: (-o.jurisdiction_id.count("/"), o.designation or "", o.source_id))
    return PlanningContextResponse(planning_context=context, sources=sources)


class MarketFigure(BaseModel):
    """One official market statistic for the property's area (afinamentos 2026-11-03: Paris, New York City, Singapore);
    computed by HABITA from an open official dataset of real sales, dated, with its source."""

    label: str
    value: int
    unit: str
    area: str
    period: str
    count: int
    source: str
    url: str
    note: str


class MarketResponse(BaseModel):
    retrieved_on: str | None
    figures: list[MarketFigure]


@router.get("/{property_id}/market", response_model=MarketResponse)
async def market(
    property_id: Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")],
    request: Request,
) -> MarketResponse:
    """Official market prices for partial-coverage cities. Portugal's (INE) stay in a matter's costs (HR-011)."""
    from app.services.afford import international

    prop = await request.app.state.property_service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    j = prop.jurisdiction
    subdivision = next((lvl.name for lvl in j.levels if lvl.type == "subdivision"), None)
    figures = international.figures_for(j.id, prop.formatted_address, subdivision) if j.coverage == "partial" else []
    return MarketResponse(retrieved_on=international.snapshot().get("retrieved_on") if figures else None,
                          figures=[MarketFigure(**f) for f in figures])
