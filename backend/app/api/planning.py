"""Planning context and the official sources that apply to a property (HR-003). Public, like the property."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

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
    context = await request.app.state.planning.resolve(prop)
    registry = request.app.state.official_sources
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
