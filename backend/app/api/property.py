from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.core.errors import NotFoundError
from app.schemas.property import ResolvedProperty, ResolveLocationRequest, ResolveLocationResponse
from app.services.property_location import PropertyLocationService

router = APIRouter(prefix="/api/property", tags=["property"])


def get_property_service(request: Request) -> PropertyLocationService:
    return request.app.state.property_service


Service = Annotated[PropertyLocationService, Depends(get_property_service)]


@router.post("/resolve-location", response_model=ResolveLocationResponse)
async def resolve_location(body: ResolveLocationRequest, service: Service) -> ResolveLocationResponse:
    return await service.resolve(address=body.address, place_id=body.place_id)


@router.get("/{property_id}", response_model=ResolvedProperty)
async def get_property(
    property_id: Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")],
    service: Service,
) -> ResolvedProperty:
    prop = await service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    return prop
