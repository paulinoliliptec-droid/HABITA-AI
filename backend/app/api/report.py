"""Reports (HR-004 map post-its, HR-006 PDF): one shared model, as JSON or PDF.

The property report is public, like the property; an assessment report needs the matter's capability token, like the
matter. Both only present stored results: no model, retriever or verifier runs here. The PDF also embeds two location
maps fetched for it (road map and satellite, same framing), or says why they are missing. The voice explanation is
spoken from that same report, one stored sentence at a time."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.permit import MatterId, Workflow, afford_report
from app.api.planning import planning_response
from app.core.errors import ConflictError, NotFoundError, ServiceNotConfiguredError
from app.integrations.speech.client import SpeechUnavailable
from app.schemas.report import PermitReport, VoiceScript
from app.services.report.builder import build_report
from app.services.report.localize import localize_report
from app.services.report.pdf import render_pdf
from app.services.report.premium import AerialFigure, ConceptFigure, render_premium_pdf
from app.services.report.voice import build_voice_script, script_version

log = logging.getLogger(__name__)
router = APIRouter(tags=["report"])
PropertyId = Annotated[str, Path(pattern=r"^prp_[0-9a-f]{16}$")]
Lang = Annotated[Literal["en", "pt"], Query()]
Line = Annotated[int, Path(ge=0)]
Version = Annotated[str, Query(pattern=r"^[0-9a-f]{16}$")]


async def _property_report(request: Request, property_id: str, lang: str, matter=None, evidence=(), verification=None,
                           files=(), afford=None, concepts=()):
    prop = await request.app.state.property_service.get(property_id)
    if prop is None:
        raise NotFoundError("This property hasn't been resolved yet.")
    planning = await planning_response(request.app.state, prop)
    report = build_report(prop, planning.planning_context, planning.sources, matter, evidence, verification,
                          files=list(files), afford=afford, concepts=list(concepts),
                          aerial=await request.app.state.aerial.get(property_id))
    return await localize_report(report, lang, request.app.state.translator)


async def _matter_report(request: Request, matter_id: str, workflow, lang: str) -> PermitReport:
    matter = await workflow.get(matter_id)
    stored = await request.app.state.afford_repo.get(matter_id)
    return await _property_report(request, matter.property_id, lang, matter, await workflow.evidence(matter_id),
                                  await workflow.verification(matter_id),
                                  await request.app.state.matter_files.list(matter_id),
                                  await afford_report(request, workflow, matter_id) if stored else None,
                                  await request.app.state.concepts.list(matter_id))


async def _aerial_figure(request: Request, property_id: str) -> AerialFigure | None:
    """HR-006 polish 2: the property's aerial view, if one was made; never a reason for the PDF to fail."""
    try:
        aerial = await request.app.state.aerial.get(property_id)
        jpeg = await request.app.state.aerial.image(property_id) if aerial is not None else None
    except Exception:  # noqa: BLE001 - storage or service trouble only drops the figure
        log.exception("aerial view unavailable for the PDF")
        return None
    # The PDF's aerial figure and its notice are written for the DGT orthophoto; other sources (IGN, NYS, 2026-11-03)
    # are shown on screen and on the map only.
    if aerial is None or not jpeg or aerial.source.provider != "DGT" or aerial.source.year is None:
        return None
    return AerialFigure(jpeg=jpeg, year=aerial.source.year)


#: At most this many concept images in a PDF, each reduced to this width (the PDF stays light).
PDF_CONCEPTS, PDF_CONCEPT_WIDTH = 4, 1000


def _shrink(jpeg: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image
    image = Image.open(BytesIO(jpeg)).convert("RGB")
    image.thumbnail((PDF_CONCEPT_WIDTH, PDF_CONCEPT_WIDTH * 2))
    out = BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue()


async def _concept_figures(request: Request, report: PermitReport) -> list[ConceptFigure]:
    """HR-006 polish 3: the matter's own concept images (only a matter report lists concepts, behind its capability);
    any trouble only drops the images, never the PDF."""
    if not report.concepts or report.assessment is None:
        return []
    matter_id = report.assessment.matter_id
    try:
        concepts = (await request.app.state.concepts.list(matter_id))[:PDF_CONCEPTS]
        figures = []
        for c in concepts:
            data = await request.app.state.concepts.content(matter_id, c.concept_id)
            if data:
                figures.append(ConceptFigure(jpeg=await run_in_threadpool(_shrink, data), label=c.change_label))
        return figures
    except Exception:  # noqa: BLE001
        log.exception("concept images unavailable for the PDF")
        return []


async def _pdf(request: Request, report: PermitReport, name: str) -> Response:
    p = report.property
    maps = await request.app.state.static_maps.location_maps(p.lat, p.lng, p.precision, place=p.property_id)
    style = request.app.state.settings.report_pdf_style
    content = None
    if style != "legacy":
        aerial = await _aerial_figure(request, p.property_id)
        concepts = await _concept_figures(request, report)
        try:  # both renderers are CPU-bound: they run off the event loop
            # The public site, for the property link of the integrity seal (never a matter's capability).
            site = next((o for o in request.app.state.settings.cors_origins if o.startswith("https://")), None)
            content = await run_in_threadpool(render_premium_pdf, report, maps, style, aerial, concepts, site)
        except (ImportError, OSError):  # WeasyPrint or pango missing in this image: the legacy PDF is still correct
            log.exception("premium PDF unavailable; serving the legacy PDF")
    if content is None:
        content = await run_in_threadpool(render_pdf, report, maps)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"', "Cache-Control": "no-store"})


def _voice_script(request: Request, report: PermitReport, lang: str) -> VoiceScript:
    lines = build_voice_script(report)
    return VoiceScript(version=script_version(lines), lines=lines, audio=request.app.state.speech.configured(lang))


async def _voice_line(request: Request, report: PermitReport, lang: str, line: int, version: str) -> Response:
    """One sentence of the report's script, by position: the text is never the caller's, so no one can spend on theirs."""
    script = build_voice_script(report)
    if script_version(script) != version:
        raise ConflictError("This report has changed. Please listen again.")
    if line >= len(script):
        raise NotFoundError("This report has no such sentence.")
    try:
        audio = await request.app.state.speech.speak(script[line], lang)
    except SpeechUnavailable:
        raise ServiceNotConfiguredError("Spoken audio is not available right now.") from None
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


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


@router.get("/api/property/{property_id}/report/voice", response_model=VoiceScript)
async def property_voice(property_id: PropertyId, request: Request, lang: Lang = "en") -> VoiceScript:
    return _voice_script(request, await _property_report(request, property_id, lang), lang)


@router.get("/api/property/{property_id}/report/voice/{line}")
async def property_voice_line(property_id: PropertyId, line: Line, request: Request, version: Version,
                              lang: Lang = "en") -> Response:
    return await _voice_line(request, await _property_report(request, property_id, lang), lang, line, version)


@router.get("/api/permit/matters/{matter_id}/report/voice", response_model=VoiceScript)
async def matter_voice(matter_id: MatterId, request: Request, workflow: Workflow, lang: Lang = "en") -> VoiceScript:
    return _voice_script(request, await _matter_report(request, matter_id, workflow, lang), lang)


@router.get("/api/permit/matters/{matter_id}/report/voice/{line}")
async def matter_voice_line(matter_id: MatterId, line: Line, request: Request, workflow: Workflow, version: Version,
                            lang: Lang = "en") -> Response:
    return await _voice_line(request, await _matter_report(request, matter_id, workflow, lang), lang, line, version)
