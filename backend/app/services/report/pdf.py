"""Render the shared report model as a PDF (HR-006). Presentation only: every word comes from ``PermitReport``."""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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


def _refs(ids: list[str]) -> str:
    return f" <font color='#5b625e'>[{', '.join(_t(i) for i in ids)}]</font>" if ids else ""


def render_pdf(report: PermitReport) -> bytes:
    s = _styles()
    flow = []
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
    flow.append(Paragraph("Planning context", s["h2"]))
    zoning = (f"<b>{_t(pl.classification)}</b> (verified official layer)" if pl.verified_zoning else
              "<b>No verified zoning layer.</b> HABITA does not determine the classification; it must be confirmed "
              "on the official maps or with the competent authority.")
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
            flow.append(Paragraph("Verification record", s["h2"]))
            flow.append(_table([
                ("Outcome", _t(v.outcome)), ("Report", _t(v.verification_id)),
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
        canvas.drawString(18 * mm, 10 * mm, report.disclaimer[:150])
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=18 * mm, title="HABITA AI report", author="HABITA AI").build(
        flow + [Spacer(1, 4 * mm), Paragraph(_t(report.disclaimer), s["small"])],
        onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
