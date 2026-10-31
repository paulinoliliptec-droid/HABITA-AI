"""Permit Intelligence API.

A matter is private to whoever created it. Creating one returns a capability
token once; every matter operation requires it as ``Authorization: Bearer <token>``.
There is deliberately no lookup of matters by property ID: the property is
public, its permit matters are not.
"""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import Response

from app.core.errors import NotFoundError
from app.schemas.afford import AffordInputs, AffordReport
from app.schemas.files import FileKind, MatterFile
from app.services.afford.compute import afford
from app.services.files.inspect import MAX_BYTES
from app.services.files.service import InvalidFileError, MatterFiles
from app.schemas.permit import (
    Checklist,
    CreateMatterRequest,
    CreateMatterResponse,
    Evidence,
    MatterTranslation,
    PermitMatter,
    SupplyInputsRequest,
    VerificationReport,
)
from app.services.i18n.translator import translation_note
from app.services.permit.workflow import PermitWorkflow
from app.services.report.builder import assessment_status
from app.services.report.localize import matter_texts

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
async def create_matter(body: CreateMatterRequest, request: Request, workflow: Workflow) -> CreateMatterResponse:
    """Create a private matter. The access token is returned here, once; keep it to resume."""
    matter, token = await workflow.create(body.property_id, body.question, body.intent)
    return CreateMatterResponse(matter=matter, access_token=token,
                                detected_language=await request.app.state.translator.detect(body.question))


@router.get("/matters/{matter_id}", response_model=PermitMatter)
async def get_matter(matter_id: MatterId, workflow: Workflow) -> PermitMatter:
    return await workflow.get(matter_id)


@router.get("/matters/{matter_id}/translation", response_model=MatterTranslation)
async def get_translation(matter_id: MatterId, workflow: Workflow, request: Request,
                          lang: Annotated[Literal["en", "pt"], Query()] = "en") -> MatterTranslation:
    """The matter's texts for reading in ``lang``, after verification; it changes nothing in the matter."""
    matter = await workflow.get(matter_id)
    verified = assessment_status(matter, await workflow.verification(matter_id))[0] == "VERIFIED"
    result = await request.app.state.translator.translate(matter_texts(matter), lang)
    return MatterTranslation(lang=lang, available=result.available, verified=verified,
                             kept_original=result.kept_original, texts=result.texts,
                             note=translation_note(result, verified=verified, has_answer=matter.draft is not None))


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


# --- HR-010: the user's photos, plans and documents ------------------------------------------------------------


def get_files(request: Request) -> MatterFiles:
    return request.app.state.matter_files


Files = Annotated[MatterFiles, Depends(get_files)]
FileId = Annotated[str, Path(pattern=r"^fl_[0-9a-f]{16}$")]


#: A slow upload can't hold a concurrency slot longer than this.
BODY_SECONDS = 30


async def _body(request: Request) -> bytes:
    """The upload, refused as soon as it passes the size limit or the time limit, so a large or trickling body is never
    held for long."""
    data = bytearray()
    try:
        async with asyncio.timeout(BODY_SECONDS):
            async for chunk in request.stream():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise InvalidFileError("Files can have at most 10 MB.")
    except TimeoutError:
        raise InvalidFileError("The upload took too long. Please try again.") from None
    return bytes(data)


@router.get("/matters/{matter_id}/files", response_model=list[MatterFile])
async def list_files(matter_id: MatterId, files: Files) -> list[MatterFile]:
    return await files.list(matter_id)


@router.post("/matters/{matter_id}/files", response_model=MatterFile, status_code=201)
async def add_file(matter_id: MatterId, request: Request, workflow: Workflow, files: Files,
                   kind: Annotated[FileKind, Query()], consent: Annotated[str, Query(max_length=8)]) -> MatterFile:
    """The file is the raw request body. It is checked, cleaned, kept privately and read; the matter is not changed."""
    matter = await workflow.get(matter_id)
    prop = await request.app.state.property_service.get(matter.property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    # Admission comes before the body is read, so refused uploads are never buffered or decoded.
    async with await files.admit(matter_id, consent):
        return await files.add_admitted(matter_id, (prop.coordinates.lat, prop.coordinates.lng), kind, consent,
                                        await _body(request))


@router.get("/matters/{matter_id}/files/{file_id}/content")
async def file_content(matter_id: MatterId, file_id: FileId, files: Files) -> Response:
    record, data = await files.content(matter_id, file_id)
    return Response(data, media_type=record.content_type,
                    headers={"Cache-Control": "no-store", "Content-Disposition": "attachment",
                             "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.delete("/matters/{matter_id}/files/{file_id}", status_code=204)
async def delete_file(matter_id: MatterId, file_id: FileId, files: Files) -> Response:
    await files.delete(matter_id, file_id)
    return Response(status_code=204)


# --- HR-011: costs, financing and market price ------------------------------------------------------------------


async def afford_report(request: Request, workflow: PermitWorkflow, matter_id: str,
                        inputs: AffordInputs | None = None) -> AffordReport:
    """Computed from the matter's type, its property's place and the user's figures; nothing in the matter changes."""
    matter = await workflow.get(matter_id)
    prop = await request.app.state.property_service.get(matter.property_id)
    levels = {lvl.type: lvl.name for lvl in prop.jurisdiction.levels} if prop is not None else {}
    stored = inputs or await request.app.state.afford_repo.get(matter_id) or AffordInputs()
    return afford(matter.intent, levels.get("municipality"), levels.get("subdivision"), stored, levels.get("region"))


@router.get("/matters/{matter_id}/afford", response_model=AffordReport)
async def get_afford(matter_id: MatterId, request: Request, workflow: Workflow) -> AffordReport:
    return await afford_report(request, workflow, matter_id)


@router.put("/matters/{matter_id}/afford", response_model=AffordReport)
async def put_afford(matter_id: MatterId, body: AffordInputs, request: Request, workflow: Workflow) -> AffordReport:
    await request.app.state.afford_repo.save(matter_id, body)
    return await afford_report(request, workflow, matter_id, body)
