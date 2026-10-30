"""Reports (HR-004 map post-its, HR-006 PDF): one shared model, as JSON or PDF.

The property report is public, like the property; an assessment report needs the matter's capability token, like the
matter. Both only present stored results: no model, retriever or verifier runs here. The PDF also embeds two location
maps fetched for it (road map and satellite, same framing), or says why they are missing."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.permit import MatterId, Workflow
from app.api.planning import planning_response
from app.core.errors import NotFoundError
from app.schemas.report import PermitReport
from app.services.report.builder import build_report
from app.services.report.localize import localize_report
from app.services.report.pdf import render_pdf
from app.services.report.premium import render_premium_pdf

log = logging.getLogger(__name__)
router = APIRouter(tags=["report"])
PropertyId = Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")]
Lang = Annotated[Literal["en", "pt"], Query()]


async def _property_report(request: Request, property_id: str, lang: str, matter=None, evidence=(), verification=None):
    prop = await request.app.state.property_service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    planning = await planning_response(request.app.state, prop)
    report = build_report(prop, planning.planning_context, planning.sources, matter, evidence, verification)
    return await localize_report(report, lang, request.app.state.translator)


async def _matter_report(request: Request, matter_id: str, workflow, lang: str) -> PermitReport:
    matter = await workflow.get(matter_id)
    return await _property_report(request, matter.property_id, lang, matter, await workflow.evidence(matter_id),
                                  await workflow.verification(matter_id))


async def _pdf(request: Request, report: PermitReport, name: str) -> Response:
    p = report.property
    maps = await request.app.state.static_maps.location_maps(p.lat, p.lng, p.precision, place=p.property_id)
    style = request.app.state.settings.report_pdf_style
    content = None
    if style != "legacy":
        try:  # both renderers are CPU-bound: they run off the event loop
            content = await run_in_threadpool(render_premium_pdf, report, maps, style)
        except (ImportError, OSError):  # WeasyPrint or pango missing in this image: the legacy PDF is still correct
            log.exception("premium PDF unavailable; serving the legacy PDF")
    if content is None:
        content = await run_in_threadpool(render_pdf, report, maps)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"', "Cache-Control": "no-store"})


@router.get("/api/property/{property_id}/report", response_model=PermitReport)
async def property_report(property_id: PropertyId, request: Request, lang: Lang = "en") -> PermitReport:
    return await _property_report(request, property_id, lang)


@router.get("/api/property/{property_id}/report.pdf")
async def property_report_pdf(property_id: PropertyId, request: Request, lang: Lang = "en") -> Response:
    return await _pdf(request, await _property_report(request, property_id, lang), f"habita-{property_id}")


@router.get("/api/permit/matters/{matter_id}/report", response_model=PermitReport)
async def matter_report(matter_id: MatterId, request: Request, workflow: Workflow, lang: Lang = "en") -> PermitReport:
    return await _matter_report(request, matter_id, workflow, lang)


@router.get("/api/permit/matters/{matter_id}/report.pdf")
async def matter_report_pdf(matter_id: MatterId, request: Request, workflow: Workflow, lang: Lang = "en") -> Response:
    return await _pdf(request, await _matter_report(request, matter_id, workflow, lang), f"habita-{matter_id}")
