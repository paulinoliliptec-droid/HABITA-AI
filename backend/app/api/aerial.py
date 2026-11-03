"""Seen from the air: the DGT orthophoto around a property, segmented by Meta SAM 3.1 (owner, 2026-11-01)."""

from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from app.core.errors import NotFoundError
from app.schemas.aerial import AerialReport

router = APIRouter(prefix="/api/property", tags=["aerial"])
PropertyId = Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")]


@router.get("/{property_id}/aerial", response_model=AerialReport)
async def get_aerial(property_id: PropertyId, request: Request) -> AerialReport:
    prop = await request.app.state.property_service.get(property_id)
    report = await request.app.state.aerial.current(prop) if prop is not None else None
    if report is None:
        raise NotFoundError("No aerial analysis has been made for this property yet.")
    return report


@router.post("/{property_id}/aerial", response_model=AerialReport)
async def create_aerial(property_id: PropertyId, request: Request) -> AerialReport:
    """Made once per property; later calls return the same analysis without spending again."""
    prop = await request.app.state.property_service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    return await request.app.state.aerial.create(prop)


@router.get("/{property_id}/aerial/image")
async def aerial_image(property_id: PropertyId, request: Request) -> Response:
    prop = await request.app.state.property_service.get(property_id)
    data = await request.app.state.aerial.current_image(prop) if prop is not None else None
    if data is None:
        raise NotFoundError("No aerial analysis has been made for this property yet.")
    return Response(data, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
