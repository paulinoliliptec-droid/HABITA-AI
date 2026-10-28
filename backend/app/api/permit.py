"""Permit Intelligence API.

A matter is private to whoever created it. Creating one returns a capability
token once; every matter operation requires it as ``Authorization: Bearer <token>``.
There is deliberately no lookup of matters by property ID: the property is
public, its permit matters are not.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request

from app.core.errors import NotFoundError
from app.schemas.permit import (
    Checklist,
    CreateMatterRequest,
    CreateMatterResponse,
    Evidence,
    PermitMatter,
    SupplyInputsRequest,
    VerificationReport,
)
from app.services.permit.workflow import PermitWorkflow

router = APIRouter(prefix="/api/permit", tags=["permit"])


def get_workflow(request: Request) -> PermitWorkflow:
    return request.app.state.permit_workflow


Workflow = Annotated[PermitWorkflow, Depends(get_workflow)]


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


async def authorized_matter_id(
    workflow: Workflow,
    matter_id: Annotated[str, Path(pattern=r"^pm_[0-9a-f]{16}$")],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    await workflow.authorize(matter_id, _bearer(authorization))
    return matter_id


MatterId = Annotated[str, Depends(authorized_matter_id)]


@router.get("/status")
async def permit_status(request: Request) -> dict[str, object]:
    """Whether the reasoning model is configured, so the UI can explain instead of failing."""
    settings = request.app.state.settings
    return {"available": settings.meta_api_key is not None, "model": settings.meta_text_model}


@router.post("/matters", response_model=CreateMatterResponse, status_code=201)
async def create_matter(body: CreateMatterRequest, workflow: Workflow) -> CreateMatterResponse:
    """Create a private matter. The access token is returned here, once; keep it to resume."""
    matter, token = await workflow.create(body.property_id, body.question)
    return CreateMatterResponse(matter=matter, access_token=token)


@router.get("/matters/{matter_id}", response_model=PermitMatter)
async def get_matter(matter_id: MatterId, workflow: Workflow) -> PermitMatter:
    return await workflow.get(matter_id)


@router.post("/matters/{matter_id}/continue", response_model=PermitMatter)
async def continue_matter(matter_id: MatterId, workflow: Workflow) -> PermitMatter:
    """Advance the matter until it needs input, is verified, escalates, is rejected or fails."""
    return await workflow.run(matter_id)


@router.post("/matters/{matter_id}/inputs", response_model=PermitMatter)
async def supply_inputs(matter_id: MatterId, body: SupplyInputsRequest, workflow: Workflow) -> PermitMatter:
    return await workflow.supply_inputs(matter_id, body.inputs)


@router.get("/matters/{matter_id}/checklist", response_model=Checklist)
async def get_checklist(matter_id: MatterId, workflow: Workflow) -> Checklist:
    checklist = await workflow.checklist(matter_id)
    if checklist is None:
        raise NotFoundError("The checklist hasn't been created yet.")
    return checklist


@router.get("/matters/{matter_id}/evidence", response_model=list[Evidence])
async def get_evidence(matter_id: MatterId, workflow: Workflow) -> list[Evidence]:
    return await workflow.evidence(matter_id)


@router.get("/matters/{matter_id}/verification", response_model=VerificationReport)
async def get_verification(matter_id: MatterId, workflow: Workflow) -> VerificationReport:
    report = await workflow.verification(matter_id)
    if report is None:
        raise NotFoundError("This matter hasn't been verified yet.")
    return report
