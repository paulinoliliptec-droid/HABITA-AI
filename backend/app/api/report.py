"""Reports (HR-004 map post-its, HR-006 PDF): one shared model, as JSON or PDF.

The property report is public, like the property; an assessment report needs the matter's capability token, like the
matter. Both only present stored results: no model, retriever or verifier runs here."""

from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from app.api.permit import MatterId, Workflow
from app.api.planning import planning_response
from app.core.errors import NotFoundError
from app.schemas.report import PermitReport
from app.services.report.builder import build_report
from app.services.report.pdf import render_pdf

router = APIRouter(tags=["report"])
PropertyId = Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")]


async def _property_report(request: Request, property_id: str, matter=None, evidence=(), verification=None):
    prop = await request.app.state.property_service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    planning = await planning_response(request.app.state, prop)
    return build_report(prop, planning.planning_context, planning.sources, matter, evidence, verification)


async def _matter_report(request: Request, matter_id: str, workflow) -> PermitReport:
    matter = await workflow.get(matter_id)
    return await _property_report(request, matter.property_id, matter, await workflow.evidence(matter_id),
                                  await workflow.verification(matter_id))


def _pdf(report: PermitReport, name: str) -> Response:
    return Response(render_pdf(report), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"', "Cache-Control": "no-store"})


@router.get("/api/property/{property_id}/report", response_model=PermitReport)
async def property_report(property_id: PropertyId, request: Request) -> PermitReport:
    return await _property_report(request, property_id)


@router.get("/api/property/{property_id}/report.pdf")
async def property_report_pdf(property_id: PropertyId, request: Request) -> Response:
    return _pdf(await _property_report(request, property_id), f"habita-{property_id}")


@router.get("/api/permit/matters/{matter_id}/report", response_model=PermitReport)
async def matter_report(matter_id: MatterId, request: Request, workflow: Workflow) -> PermitReport:
    return await _matter_report(request, matter_id, workflow)


@router.get("/api/permit/matters/{matter_id}/report.pdf")
async def matter_report_pdf(matter_id: MatterId, request: Request, workflow: Workflow) -> Response:
    return _pdf(await _matter_report(request, matter_id, workflow), f"habita-{matter_id}")
