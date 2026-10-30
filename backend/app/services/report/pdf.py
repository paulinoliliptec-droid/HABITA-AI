"""Render the shared report model as a PDF (HR-006). Presentation only: every word comes from ``PermitReport``, and
the location maps are images fetched for this PDF (``LocationMaps``), embedded with their framing and source."""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.integrations.maps.static_maps import ATTRIBUTION, HEIGHT, WIDTH, LocationMaps
from app.schemas.report import PermitReport, ReportStatus

#: Status → (banner colour, words). The words always carry the status; colour only reinforces it.
STATUS_STYLE: dict[ReportStatus, tuple[colors.Color, str]] = {
    "VERIFIED": (colors.HexColor("#1f6f43"), "VERIFIED"),
    "REJECTED": (colors.HexColor("#9b2c2c"), "REJECTED"),
    "PENDING_CONFIRMATION": (colors.HexColor("#8a5a00"), "PENDING CONFIRMATION"),
}
_INK, _MUTED, _RULE = colors.HexColor("#1d2320"), colors.HexColor("#5b625e"), colors.HexColor("#d9d4c9")
#: The standard PDF fonts cover Latin-1 / WinAnsi; map the few symbols HABITA's texts use outside it.
_SAFE = str.maketrans({"≥": ">=", "≤": "<=", "→": "->", "←": "<-", " ": " ", " ": " "})


def _t(text: str | None) -> str:
    return escape((text or "").translate(_SAFE))


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20,
                                textColor=_INK, alignment=TA_LEFT, spaceAfter=2 * mm),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5,
                             textColor=_INK, spaceBefore=5 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13,
                               textColor=_INK),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=10.5,
                                textColor=_MUTED),
        "brand": ParagraphStyle("brand", parent=base["Title"], fontName="Helvetica-Bold", fontSize=30, leading=34,
                                textColor=_INK, alignment=TA_LEFT, spaceAfter=1 * mm),
        "cover_address": ParagraphStyle("cover_address", parent=base["BodyText"], fontName="Helvetica-Bold",
                                        fontSize=15, leading=19, textColor=_INK, spaceBefore=14 * mm,
                                        spaceAfter=2 * mm),
        "banner": ParagraphStyle("banner", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=11,
                                 leading=14, textColor=colors.white),
    }


def _table(rows, widths, s):
    t = Table([[Paragraph(_t(a), s["small"]), Paragraph(b, s["body"])] for a, b in rows], colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _banner(status: ReportStatus, reason: str, s):
    colour, words = STATUS_STYLE[status]
    t = Table([[Paragraph(f"{words} — {_t(reason)}", s["banner"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colour), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _boxed(paragraph, colour=_RULE):
    t = Table([[paragraph]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colour), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _status(report: PermitReport) -> tuple[ReportStatus, str]:
    a = report.assessment
    return (a.status, a.status_reason) if a is not None else (
        "PENDING_CONFIRMATION", "No permit assessment is included in this report.")


def _cover(report: PermitReport, s) -> list:
    p, (status, reason) = report.property, _status(report)
    municipality = next((x for x in p.jurisdiction if x.startswith("Municipality:")), None)
    flow = [Spacer(1, 30 * mm), Paragraph("HABITA AI", s["brand"]),
            Paragraph("Property &amp; Permit Report", s["h2"]),
            Paragraph(_t(p.address), s["cover_address"])]
    if report.demo:
        flow += [_banner("PENDING_CONFIRMATION", "DEMONSTRATION DATA — not a real assessment", s), Spacer(1, 2 * mm)]
    flow += [_banner(status, reason, s), Spacer(1, 6 * mm), _table([
        ("Property", _t(p.property_id)),
        ("Municipality", _t(municipality.split(": ", 1)[1]) if municipality else "—"),
        ("Competent authority", _t(p.authority) or "Not modelled for this jurisdiction"),
        ("Zoning", _t(report.planning.classification) + " (verified official layer)" if report.planning.verified_zoning
         else "<b>Zoning not verified</b>: no classification or boundary is stated."),
        ("Generated", f"{report.generated_at:%Y-%m-%d %H:%M} UTC"),
    ], [42 * mm, 132 * mm], s), Spacer(1, 10 * mm)]
    # Always: no HABITA status, VERIFIED included, records a confirmation by the municipality.
    flow.append(_boxed(Paragraph(
        "<b>No municipal confirmation.</b> This report has not been confirmed by the Câmara Municipal or any other "
        "authority; HABITA's statuses, VERIFIED included, are its own checks. Items marked pending must be confirmed "
        "with the competent authority before any decision.", s["body"]), colors.HexColor("#8a5a00")))
    flow.append(Spacer(1, 4 * mm))
    flow += [Paragraph(_t(report.disclaimer), s["small"]), PageBreak()]
    return flow


def _location(maps: LocationMaps | None, s) -> list:
    flow = [PageBreak(), Paragraph("Location", s["h2"])]
    if maps is None or not maps.images:
        why = maps.unavailable if maps is not None else "Maps were not requested for this report."
        return flow + [_boxed(Paragraph(f"<b>Location maps unavailable.</b> {_t(why)} No image has been substituted; "
                                        "use the coordinates in the property identification.", s["body"]))]
    width = 140 * mm  # both maps and the legend on one page
    captions = {"roadmap": "A. Road map", "hybrid": "B. Satellite image (with labels)"}
    for image in (i for i in maps.images if i.kind in captions):
        flow.append(KeepTogether([
            Image(io.BytesIO(image.jpeg), width=width, height=width * HEIGHT / WIDTH),
            Paragraph(f"<b>{captions[image.kind]}</b> — centre {maps.lat:.6f}, {maps.lng:.6f}; zoom {image.zoom}; "
                      "same centre, zoom, size and marker in both maps.", s["small"]),
            Spacer(1, 3 * mm),
        ]))
    flow.append(Paragraph(
        f"<b>Legend.</b> Red marker: the geocoded point. Shaded circle (radius about {maps.radius_m} m): "
        f"<b>approximate location</b>, sized from the geocoding precision ({_t(maps.precision)}). It is "
        "<b>not a cadastral or parcel boundary</b>: HABITA holds no verified parcel geometry for this property. "
        "Google imagery does not prove ownership, parcel limits, zoning or the existence of a municipal licence. "
        f"Source: {_t(ATTRIBUTION)}.", s["small"]))
    street = next((i for i in maps.images if i.kind == "streetview"), None)
    if street is not None:
        flow.append(KeepTogether([
            Spacer(1, 4 * mm),
            Image(io.BytesIO(street.jpeg), width=110 * mm, height=110 * mm * HEIGHT / WIDTH),
            Paragraph(f"<b>C. Street-level view</b> — Google Street View panorama about {street.distance_m} m from "
                      f"the geocoded point{', facing it' if street.facing else ''}; captured "
                      f"{_t(street.captured) or 'on an unknown date'}. It shows the surroundings at that date, not the "
                      "property's current state.", s["small"]),
        ]))
    elif maps.street_view_note:
        flow.append(Paragraph(f"<b>Street-level view:</b> {_t(maps.street_view_note)}", s["small"]))
    return flow


def _refs(ids: list[str]) -> str:
    return f" <font color='#5b625e'>[{', '.join(_t(i) for i in ids)}]</font>" if ids else ""


def render_pdf(report: PermitReport, maps: LocationMaps | None = None) -> bytes:
    s = _styles()
    flow = _cover(report, s)
    p = report.property
    flow.append(Paragraph("HABITA AI — Property &amp; Permit Report", s["title"]))
    flow.append(Paragraph(_t(p.address), s["body"]))
    flow.append(Paragraph(f"Generated {report.generated_at:%Y-%m-%d %H:%M} UTC · Property {_t(p.property_id)}",
                          s["small"]))
    if report.demo:
        flow.append(Spacer(1, 2 * mm))
        flow.append(_banner("PENDING_CONFIRMATION", "DEMONSTRATION DATA — not a real assessment", s))
    flow.append(Spacer(1, 4 * mm))

    a = report.assessment
    if a is not None:
        flow.append(_banner(a.status, a.status_reason, s))
    else:
        flow.append(_banner("PENDING_CONFIRMATION", "No permit assessment is included in this report.", s))

    flow.append(Paragraph("Property identification", s["h2"]))
    flow.append(_table([
        ("Address", _t(p.address)),
        ("Coordinates", f"{p.lat:.6f}, {p.lng:.6f} (precision: {_t(p.precision)})"),
        ("Jurisdiction", "<br/>".join(_t(x) for x in p.jurisdiction) or "—"),
        ("Competent authority", _t(p.authority) or "Not modelled for this jurisdiction"),
    ], [42 * mm, 132 * mm], s))

    pl = report.planning
    flow += _location(maps, s)
    flow.append(Paragraph("Planning context", s["h2"]))
    zoning = (f"<b>{_t(pl.classification)}</b> (verified official layer)" if pl.verified_zoning else
              "<b>Zoning not verified.</b> No verified zoning layer. HABITA does not determine the classification; it "
              "must be confirmed on the official maps or with the competent authority.")
    rows = [("Zoning", zoning)]
    if pl.instrument:
        rows.append(("Instrument", _t(pl.instrument) + (f" — {_t(pl.instrument_version)}" if pl.instrument_version
                                                        else "")))
    if pl.reasons:
        rows.append(("Why pending", "<br/>".join(_t(r) for r in pl.reasons)))
    if pl.documents_to_consult:
        rows.append(("Official maps to consult", "<br/>".join(
            f"{_t(d.designation or d.title)}: {_t(d.reason)}" + (f"<br/><font size=7>{_t(d.url)}</font>"
                                                                    if d.url else "")
            for d in pl.documents_to_consult)))
    flow.append(_table(rows, [42 * mm, 132 * mm], s))

    if a is not None:
        flow.append(Paragraph("Analysis", s["h2"]))
        if not a.content_verified:
            flow.append(Paragraph("<b>Not verified.</b> The statements below have not passed HABITA's verification "
                                  "and must not be relied on.", s["body"]))
        flow.append(Paragraph(f"<b>Question:</b> {_t(a.question)}", s["body"]))
        if a.conclusion_summary:
            flow.append(Paragraph(f"<b>Conclusion ({_t(a.conclusion_answer)}):</b> {_t(a.conclusion_summary)}"
                                  + _refs(a.conclusion_evidence_ids), s["body"]))
        for section, heading in (("finding", "Findings"), ("procedure", "Procedure"), ("risk", "Risks"),
                                 ("next_action", "Next actions")):
            items = [x for x in a.statements if x.section == section]
            if items:
                flow.append(Paragraph(heading, s["h2"]))
                for x in items:
                    lead = f"<b>{_t(x.step)}.</b> " if x.step else ""
                    flow.append(Paragraph(f"• {lead}{_t(x.text)}{_refs(x.evidence_ids)}", s["body"]))
        if a.conditions:
            flow.append(Paragraph("Conditions", s["h2"]))
            flow += [Paragraph(f"• {_t(c)}", s["body"]) for c in a.conditions]
        if a.issues:
            flow.append(Paragraph("Why it was rejected", s["h2"]))
            flow += [Paragraph(f"• {_t(i)}", s["body"]) for i in a.issues]
        if a.verification:
            v = a.verification
            flow.append(Paragraph("Verification record" if v.current else "Earlier verification (not current)",
                                  s["h2"]))
            flow.append(_table([
                ("Outcome", _t(v.outcome) if v.current else
                 f"{_t(v.outcome)} for draft revision {v.draft_revision}: history only, not the current status"), ("Report", _t(v.verification_id)),
                ("Draft revision", str(v.draft_revision)), ("Verified at", f"{v.created_at:%Y-%m-%d %H:%M} UTC"),
                ("Protocol", _t(v.protocol)),
                ("Trust pin", "<br/>".join(f"{_t(k)}: {_t(val)}" for k, val in sorted(v.trust_pin.items())) or "—"),
            ], [42 * mm, 132 * mm], s))

    if report.pending:
        flow.append(Paragraph("Pending confirmation", s["h2"]))
        flow += [Paragraph(f"• {_t(x)}", s["body"]) for x in report.pending]

    if a is not None and a.evidence:
        flow.append(Paragraph("Evidence and provenance", s["h2"]))
        for e in a.evidence:
            prov = " · ".join(f"{k} {_t(v)}" for k, v in (
                ("source", e.source_id), ("trust", e.trust_status), ("version", e.version),
                ("snapshot", e.snapshot_id), ("sha256", e.sha256), ("locator", e.locator)) if v)
            block = [Paragraph(f"<b>{_t(e.evidence_id)}</b> {_t(e.title)} — {_t(e.reference)}", s["body"]),
                     Paragraph(f"{_t(e.verification_status)} · retrieved {e.retrieved_at:%Y-%m-%d}"
                               + (f" · {prov}" if prov else ""), s["small"])]
            if e.url:
                block.append(Paragraph(_t(e.url), s["small"]))
            block.append(Paragraph(f"“{_t(e.excerpt[:600])}{'…' if len(e.excerpt) > 600 else ''}”", s["small"]))
            block.append(Spacer(1, 2 * mm))
            flow.append(KeepTogether(block))

    if report.sources:
        flow.append(Paragraph("Official sources for this jurisdiction", s["h2"]))
        flow += [Paragraph(f"• <b>{_t(x.title)}</b> ({_t(x.publisher)}; {_t(x.status)}"
                           + (f"; version {_t(x.version)}" if x.version else "")
                           + (f"; verified {x.verified_on}" if x.verified_on else "") + ")"
                           + (f"<br/><font size=7>{_t(x.url)}</font>" if x.url else ""), s["body"])
                 for x in report.sources]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_MUTED)
        # The whole disclaimer, wrapped to the footer's width (no truncation).
        lines = simpleSplit(report.disclaimer.translate(_SAFE), "Helvetica", 7, 150 * mm)
        for n, line in enumerate(lines[:3]):
            canvas.drawString(18 * mm, (11 - 3 * n) * mm, line)
        canvas.drawRightString(192 * mm, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=22 * mm, title="HABITA AI report", author="HABITA AI").build(
        flow + [Spacer(1, 4 * mm), Paragraph(_t(report.disclaimer), s["small"])],
        onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
