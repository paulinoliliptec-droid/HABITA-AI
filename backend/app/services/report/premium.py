"""Premium PDF (HR-006 v2): the shared report model rendered as HTML in two styles — Clássico and Moderno, after
Dra. Kiesse's export styles — and printed to PDF with WeasyPrint, with embedded open-licence fonts.

Presentation only, like ``pdf.py``: every word, number and relation comes from ``PermitReport`` and the fetched
``LocationMaps``. Charts count report fields; the reasoning graph draws only relations the report stores (jurisdiction
chain, planning status, evidence cited by each statement section and by the conclusion). Statuses are the report's:
nothing here can turn PENDING CONFIRMATION or REJECTED into VERIFIED. A statement repeated word for word in a later
section is shown once, then referenced ("same as K3") with its own evidence ids, so no legal content is lost (TD-044).
"""

import base64
import re
from collections import Counter
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.integrations.maps.static_maps import ATTRIBUTION, LocationMaps
from app.schemas.report import PermitReport

FONTS = Path(__file__).with_name("fonts")
STYLES = ("classico", "moderno")
ACCENT = {"classico": "#8a6d3b", "moderno": "#2c4d82"}  # SVG ignores CSS classes in WeasyPrint: colours are inlined
SECTIONS = (("finding", "Findings"), ("procedure", "Procedure"), ("risk", "Risks"), ("next_action", "Next actions"))
STATUS = {  # status → (label, css class); the words always carry the status, colour only reinforces it
    "VERIFIED": ("VERIFIED", "ok"), "REJECTED": ("REJECTED", "bad"),
    "PENDING_CONFIRMATION": ("PENDING CONFIRMATION", "warn"),
}


DEMO = "DEMONSTRATION DATA — not a real assessment"
SECRET_PARAM = re.compile(r"key|token|secret|signature|sig|password|auth|credential", re.I)


def _e(text) -> str:
    return escape("" if text is None else str(text))


def _url(url: str | None) -> str:
    """A printable URL: user info, the fragment and query parameters that could carry a credential are dropped."""
    if not url:
        return ""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not SECRET_PARAM.search(k)]
    host = parts.hostname or ""
    netloc = host + (f":{parts.port}" if parts.port else "")
    return _e(urlunsplit(parts._replace(netloc=netloc, query=urlencode(query), fragment="")))


def display_status(report: PermitReport) -> tuple[str, str]:
    """The one status every part of the document shows. VERIFIED only when every field agrees — status VERIFIED,
    content verified, and a current verification record whose outcome is VERIFIED; anything else that claims VERIFIED
    is shown as PENDING CONFIRMATION (the builder already guarantees this; the renderer does not rely on it)."""
    a = report.assessment
    if a is None:
        return "PENDING_CONFIRMATION", "No permit assessment is included in this report."
    status = a.status if a.status in STATUS else "PENDING_CONFIRMATION"
    v = a.verification
    if status == "VERIFIED" and not (a.content_verified and v is not None and v.current and v.outcome == "VERIFIED"):
        return "PENDING_CONFIRMATION", "The verification record does not support a verified result."
    return status, a.status_reason


def _font_face(family: str, file: str, weight: int, style: str = "normal") -> str:
    data = base64.b64encode((FONTS / f"{file}.woff2").read_bytes()).decode()
    return (f"@font-face {{ font-family: '{family}'; font-weight: {weight}; font-style: {style}; "
            f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}")


FONT_FACES = {
    "classico": lambda: "\n".join([_font_face("EB Garamond", "eb-garamond-400-normal", 400),
                                   _font_face("EB Garamond", "eb-garamond-400-italic", 400, "italic"),
                                   _font_face("EB Garamond", "eb-garamond-600-normal", 600)]),
    "moderno": lambda: "\n".join([_font_face("Source Serif 4", "source-serif-4-400-normal", 400),
                                  _font_face("Source Serif 4", "source-serif-4-400-italic", 400, "italic"),
                                  _font_face("Source Serif 4", "source-serif-4-600-normal", 600),
                                  _font_face("Source Serif 4", "source-serif-4-700-normal", 700)]),
}

CSS_BASE = """
@page { size: A4; margin: 22mm 22mm 24mm 22mm;
  @bottom-left { content: element(disclaimer); width: 150mm; vertical-align: top; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 7.5pt; color: #6b6f76; } }
@page cover { margin: 0; @bottom-left { content: none; } @bottom-right { content: none; } }
html { -weasy-hyphens: auto; }
body { margin: 0; color: #1b1b1b; hyphens: auto; }
.disclaimer-running { position: running(disclaimer); font-size: 6.6pt; line-height: 1.3; color: #6b6f76; text-align: left; }
p, li { text-align: justify; orphans: 3; widows: 3; }
p { margin: 0 0 3mm; }
h2 { break-after: avoid; margin: 7mm 0 3mm; line-height: 1.25; hyphens: manual; }
h3 { break-after: avoid; margin: 5mm 0 2mm; hyphens: manual; }
section { break-before: page; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 8.8pt; }
th, td { padding: 1.6mm 2mm; text-align: left; vertical-align: top; hyphens: manual; }
thead { display: table-header-group; } tr { break-inside: avoid; }
.muted { color: #5f646b; } .small { font-size: 8.4pt; } .mono { font-family: monospace; font-size: 7.6pt; word-break: break-all; }
.pill { display: inline-block; padding: 1.2mm 3mm; border-radius: 1.5mm; font-weight: 700; letter-spacing: .4px; font-size: 9pt; }
.pill.ok { background: #e3f1e8; color: #1f6f43; } .pill.bad { background: #f8e3e3; color: #9b2c2c; } .pill.warn { background: #fbefd9; color: #7a5200; }
.box { border: .7pt solid #8a5a00; background: #fffaf0; padding: 3mm 4mm; margin: 4mm 0; break-inside: avoid; }
.ref { color: #5f646b; font-size: .85em; white-space: nowrap; }
.statement { margin: 0 0 2.6mm; break-inside: avoid; }
.statement .label { font-weight: 600; margin-right: 1.5mm; }
.crossref { color: #5f646b; font-style: italic; }
.notverified { color: #9b2c2c; font-weight: 600; }
.glance { display: flex; gap: 4mm; margin: 2mm 0 5mm; }
.card { flex: 1; border: .5pt solid #cfd3da; border-radius: 2mm; padding: 3mm; break-inside: avoid; }
.card .k { font-size: 7.8pt; text-transform: uppercase; letter-spacing: .6px; color: #5f646b; }
.card .v { font-size: 13pt; font-weight: 700; margin-top: 1mm; }
.charts { display: flex; gap: 6mm; flex-wrap: wrap; }
.chart { width: 78mm; break-inside: avoid; } .chart h3 { margin-top: 2mm; }
figure { margin: 0 0 4mm; break-inside: avoid; } figcaption { font-size: 8pt; color: #5f646b; margin-top: 1mm; }
img.map { display: block; width: 86%; margin: 0 auto; border: .4pt solid #c9ced8; }
.cover { page: cover; height: 297mm; position: relative; padding: 34mm 26mm 0; box-sizing: border-box; }
.cover .brand { letter-spacing: 3px; text-transform: uppercase; font-size: 10pt; }
.cover h1 { margin: 8mm 0 2mm; line-height: 1.15; hyphens: manual; text-align: left; }
.cover .address { font-size: 15pt; margin: 14mm 0 6mm; line-height: 1.3; }
.cover table td { border: 0; border-bottom: .4pt solid #d9d4c9; font-size: 9.5pt; }
.cover .foot { position: absolute; left: 26mm; right: 26mm; bottom: 18mm; font-size: 7.6pt; color: #5f646b; text-align: justify; }
"""

CSS_STYLE = {
    # Clássico: Garamond, centred headings in small capitals, warm rules (after Dra. Kiesse's approved mock-up).
    "classico": """
body { font-family: 'EB Garamond', Georgia, serif; font-size: 11.6pt; line-height: 1.48; }
h2 { font-size: 12.5pt; font-weight: 600; text-align: center; letter-spacing: 1.6px; text-transform: uppercase; }
h3 { font-size: 11.8pt; font-weight: 600; font-style: italic; }
th { border-bottom: .8pt solid #1b1b1b; font-weight: 600; } td { border-bottom: .4pt solid #d9d4c9; }
.cover { background: #fbf8f1; } .cover .brand { color: #6b5a3a; text-align: center; }
.cover h1 { font-size: 26pt; font-weight: 600; text-align: center; letter-spacing: 1px; }
.cover .address { text-align: center; font-style: italic; }
""",
    # Moderno: Source Serif, left-aligned, a very dark blue and fine rules.
    "moderno": """
body { font-family: 'Source Serif 4', Georgia, serif; font-size: 10.6pt; line-height: 1.55; }
h2 { font-size: 13pt; font-weight: 700; color: #13233d; border-bottom: .8pt solid #13233d; padding-bottom: 1.5mm; }
h3 { font-size: 11pt; font-weight: 600; color: #13233d; }
th { background: #13233d; color: #fff; font-weight: 600; } td { border-bottom: .4pt solid #c9ced8; }
.cover { background: #13233d; color: #fff; } .cover .brand { color: #9fb2d1; }
.cover h1 { font-size: 28pt; font-weight: 700; } .cover .address { color: #e8edf5; }
.cover table td { color: #e8edf5; border-bottom-color: #34507d; } .cover .foot { color: #9fb2d1; }
.cover .box { background: #1d3354; border-color: #e0b04f; color: #fff; }
""",
}


# ── Charts (inline SVG, data from the report only) ──────────────────────────────────────────────────────────────
def bar_chart(title: str, items: list[tuple[str, int]], note: str = "", color: str = "#2c4d82") -> str:
    """Horizontal bars with the exact counts printed; empty data says so instead of drawing anything."""
    if not items or not any(v for _, v in items):
        return f'<div class="chart"><h3>{_e(title)}</h3><p class="muted small">No data in this report.</p></div>'
    top, width, bar_h, gap, label_w = max(v for _, v in items), 300, 14, 7, 120
    rows = []
    for i, (label, value) in enumerate(items):
        y = i * (bar_h + gap)
        w = 0 if top == 0 else round((width - label_w - 40) * value / top)
        rows.append(f'<text x="0" y="{y + 11}" font-size="9">{_e(label)}</text>'
                    f'<rect fill="{color}" x="{label_w}" y="{y}" width="{max(w, 1)}" height="{bar_h}" rx="2"/>'
                    f'<text x="{label_w + w + 4}" y="{y + 11}" font-size="9" font-weight="600">{value}</text>')
    height = len(items) * (bar_h + gap)
    # Fixed physical size (75 mm wide): every chart has the same scale whatever its number of rows.
    return (f'<div class="chart"><h3>{_e(title)}</h3><svg xmlns="http://www.w3.org/2000/svg" '
            f'style="width:75mm;height:{75 * height / width:.1f}mm" viewBox="0 0 {width} {height}" '
            f'font-family="sans-serif">{"".join(rows)}</svg>'
            + (f'<p class="muted small">{_e(note)}</p>' if note else "") + "</div>")


def charts(report: PermitReport, color: str = "#2c4d82") -> str:
    by_status = Counter(s.status for s in report.sources)
    out = [bar_chart("Official sources by trust status", sorted(by_status.items(), key=lambda kv: -kv[1]),
                     f"{len(report.sources)} official sources registered for this jurisdiction.", color)]
    a = report.assessment
    if a is not None:
        out.append(bar_chart("Evidence cited, by verification status",
                             sorted(Counter(e.verification_status for e in a.evidence).items(), key=lambda kv: -kv[1]),
                             color=color))
        seen: set[str] = set()
        rows = []
        for key, name in SECTIONS:
            texts = [s.text.strip() for s in a.statements if s.section == key]
            unique = [t for t in texts if t not in seen]
            seen.update(texts)
            rows.append((f"{name} ({len(unique)} new)", len(texts)))
        out.append(bar_chart("Statements per section", rows,
                             "Count of statements; 'new' excludes text already stated in an earlier section.", color))
    return f'<div class="charts">{"".join(out)}</div>'


# ── Reasoning graph (inline SVG; nodes and edges only from stored relations) ────────────────────────────────────
def _wrap(text: str, width: int, lines: int = 3) -> list[str]:
    words, out, cur = (text or "").split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
        else:
            cur = f"{cur} {w}".strip()
    if cur and len(out) < lines:
        out.append(cur)
    if len(out) == lines and len(" ".join(words)) > sum(len(x) + 1 for x in out):
        out[-1] = out[-1][: width - 1] + "…"
    return out


def graph_model(report: PermitReport) -> tuple[list[list[dict]], list[tuple[str, str]]]:
    """Columns of nodes and the edges between them, each edge backed by a report field."""
    p, pl, a = report.property, report.planning, report.assessment
    municipality = next((j.split(": ", 1)[1] for j in p.jurisdiction if j.startswith("Municipality:")), p.jurisdiction_id)
    cols: list[list[dict]] = [
        [{"id": "property", "title": "Property", "text": p.address}],
        [{"id": "jurisdiction", "title": "Jurisdiction", "text": municipality},
         *([{"id": "authority", "title": "Competent authority", "text": p.authority}] if p.authority else []),
         {"id": "planning", "title": "Zoning", "text": pl.classification if pl.verified_zoning else "not verified",
          "cls": "ok" if pl.verified_zoning else "warn"}],
    ]
    edges = [("property", "jurisdiction"), ("property", "planning")]
    if p.authority:  # the authority relation exists only when the report names one
        edges.insert(1, ("jurisdiction", "authority"))
    if a is None:
        # The pending items belong to the report as a whole: linked to the property, never to a specific node.
        cols.append([{"id": "pending", "title": "Pending", "text": f"{len(report.pending)} item(s) to confirm"}])
        edges.append(("property", "pending"))
        return cols, edges
    evidence = [{"id": f"ev:{e.evidence_id}", "title": e.evidence_id, "text": e.title} for e in a.evidence]
    cols.append(evidence or [{"id": "ev:none", "title": "Evidence", "text": "none cited"}])
    section_nodes, cited = [], {}
    for key, name in SECTIONS:
        ids = {i for s in a.statements if s.section == key for i in s.evidence_ids}
        count = sum(1 for s in a.statements if s.section == key)
        if count:
            section_nodes.append({"id": f"sec:{key}", "title": name, "text": f"{count} statement(s)"})
            cited[f"sec:{key}"] = ids
    status_label, status_cls = STATUS[display_status(report)[0]]
    section_nodes.append({"id": "conclusion", "title": "Conclusion", "text": status_label, "cls": status_cls})
    cited["conclusion"] = set(a.conclusion_evidence_ids)
    cols.append(section_nodes)
    for node, ids in cited.items():
        edges += [(f"ev:{i}", node) for i in sorted(ids) if any(e["id"] == f"ev:{i}" for e in evidence)]
    edges += [("planning", f"ev:{e.evidence_id}") for e in a.evidence if e.source_type == "planning_context"]
    if p.authority:
        edges += [("authority", f"ev:{e.evidence_id}") for e in a.evidence if e.source_type == "authority_record"]
    edges += [("jurisdiction", f"ev:{e.evidence_id}") for e in a.evidence if e.source_type == "jurisdiction_record"]
    return cols, edges


def reasoning_graph(report: PermitReport, color: str = "#2c4d82") -> str:
    cols, edges = graph_model(report)
    col_w, node_w, node_h, vgap, x0 = 128, 104, 46, 10, 4
    height = max(len(c) for c in cols) * (node_h + vgap) + 10
    pos, nodes_svg = {}, []
    for ci, col in enumerate(cols):
        top = (height - len(col) * (node_h + vgap)) / 2
        for ni, n in enumerate(col):
            x, y = x0 + ci * col_w, top + ni * (node_h + vgap)
            pos[n["id"]] = (x, y)
            fill = {"ok": "#e3f1e8", "bad": "#f8e3e3", "warn": "#fbefd9"}.get(n.get("cls"), "#f4f5f7")
            lines = "".join(f'<tspan x="{x + 6}" dy="{10 if i else 0}">{_e(t)}</tspan>'
                            for i, t in enumerate(_wrap(n["text"], 22)))
            nodes_svg.append(f'<rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="4" fill="{fill}" '
                             f'stroke="#9aa3b2" stroke-width=".6"/><text x="{x + 6}" y="{y + 12}" font-size="8" '
                             f'font-weight="700">{_e(n["title"])}</text><text x="{x + 6}" y="{y + 24}" '
                             f'font-size="7.4">{lines}</text>')
    edges_svg = []
    for a, b in edges:
        if a in pos and b in pos:
            (ax, ay), (bx, by) = pos[a], pos[b]
            sx, sy, ex, ey = ax + node_w, ay + node_h / 2, bx, by + node_h / 2
            if bx <= ax:  # same column: route around the right side
                sx, ex = ax + node_w, bx + node_w
            mid = (sx + ex) / 2 if bx > ax else sx + 14
            edges_svg.append(f'<path d="M{sx},{sy} C{mid},{sy} {mid},{ey} {ex},{ey}" fill="none" stroke="{color}" '
                             f'stroke-width="1" stroke-opacity=".8"/>')
    width = x0 + len(cols) * col_w
    return (f'<figure><svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" '
            f'font-family="sans-serif">{"".join(edges_svg)}{"".join(nodes_svg)}</svg><figcaption>Reasoning graph: '
            "each line is a relation stored in this report (jurisdiction chain, planning status, the evidence each "
            "statement section and the conclusion cite). It shows how the result was reached; it is not a legal "
            "determination.</figcaption></figure>")


# ── Document ────────────────────────────────────────────────────────────────────────────────────────────────────
def _refs(ids) -> str:
    return f' <span class="ref">[{_e(", ".join(ids))}]</span>' if ids else ""


def _status(report: PermitReport) -> tuple[str, str, str]:
    status, reason = display_status(report)
    label, cls = STATUS[status]
    return label, cls, reason


def _cover(report: PermitReport) -> str:
    p, pl = report.property, report.planning
    label, cls, reason = _status(report)
    municipality = next((j.split(": ", 1)[1] for j in p.jurisdiction if j.startswith("Municipality:")), "—")
    rows = [("Property", p.property_id), ("Municipality", municipality),
            ("Competent authority", p.authority or "Not modelled for this jurisdiction"),
            ("Zoning", f"{pl.classification} (verified official layer)" if pl.verified_zoning else
             "Zoning not verified: no classification or boundary is stated"),
            ("Generated", f"{report.generated_at:%Y-%m-%d %H:%M} UTC")]
    demo = f'<p><span class="pill warn">{DEMO}</span></p>' if report.demo else ""
    return (f'<div class="cover"><div class="brand">HABITA AI · Property Intelligence</div>'
            f'<h1>Property &amp; Permit Report</h1><div class="address">{_e(p.address)}</div>{demo}'
            f'<p><span class="pill {cls}">{label}</span> <span class="small">{_e(reason)}</span></p>'
            f'<table>{"".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in rows)}</table>'
            '<div class="box"><b>No municipal confirmation.</b> This report has not been confirmed by the Câmara '
            "Municipal or any other authority; HABITA's statuses, VERIFIED included, are its own checks. Items marked "
            "pending must be confirmed with the competent authority before any decision.</div>"
            f'<div class="foot">{_e(report.disclaimer)}</div></div>')


def _glance(report: PermitReport, style: str) -> str:
    label, cls, _ = _status(report)
    a = report.assessment
    cards = [("Assessment", f'<span class="pill {cls}">{label}</span>'),
             ("Zoning", "Verified" if report.planning.verified_zoning else "Not verified"),
             ("Official sources", str(len(report.sources))),
             ("Evidence cited", str(len(a.evidence)) if a else "—")]
    demo = f'<p><span class="pill warn">{DEMO}</span></p>' if report.demo else ""
    return (f'<section><h2>Report at a glance</h2>{demo}<div class="glance">'
            + "".join(f'<div class="card"><div class="k">{_e(k)}</div><div class="v">{v}</div></div>' for k, v in cards)
            + f"</div>{charts(report, ACCENT[style])}<h3>How the result was reached</h3>"
            f"{reasoning_graph(report, ACCENT[style])}</section>")


def _location(maps: LocationMaps | None) -> str:
    if maps is None or not maps.images:
        why = maps.unavailable if maps is not None else "Maps were not requested for this report."
        return (f'<section><h2>Location</h2><div class="box"><b>Location maps unavailable.</b> {_e(why)} No image has '
                "been substituted; use the coordinates in the property identification.</div></section>")
    caps = {"roadmap": "A. Road map", "hybrid": "B. Satellite image (with labels)"}
    figs = [f'<figure><img class="map" src="data:image/jpeg;base64,{base64.b64encode(i.jpeg).decode()}"/><figcaption>'
            f'<b>{caps[i.kind]}</b> — centre {maps.lat:.6f}, {maps.lng:.6f}; zoom {i.zoom}; same centre, zoom, size and '
            "marker in both maps.</figcaption></figure>" for i in maps.images if i.kind in caps]
    street = next((i for i in maps.images if i.kind == "streetview"), None)
    if street is not None:
        figs.append(f'<figure><img class="map" style="width:72%" src="data:image/jpeg;base64,'
                    f'{base64.b64encode(street.jpeg).decode()}"/><figcaption><b>C. Street-level view</b> — Google Street '
                    f"View panorama about {street.distance_m} m from the geocoded point"
                    f"{', facing it' if street.facing else ''}; captured {_e(street.captured) or 'on an unknown date'}. "
                    "It shows the surroundings at that date, not the property's current state.</figcaption></figure>")
    elif maps.street_view_note:
        figs.append(f'<p class="small"><b>Street-level view:</b> {_e(maps.street_view_note)}</p>')
    legend = (f'<p class="small"><b>Legend.</b> Red marker: the geocoded point. Shaded circle (radius about '
              f"{maps.radius_m} m): <b>approximate location</b>, sized from the geocoding precision "
              f"({_e(maps.precision)}). It is <b>not a cadastral or parcel boundary</b>: HABITA holds no verified "
              "parcel geometry for this property. Google imagery does not prove ownership, parcel limits, zoning or "
              f"the existence of a municipal licence. Source: {_e(ATTRIBUTION)}.</p>")
    return f'<section><h2>Location</h2>{"".join(figs[:2])}{legend}{"".join(figs[2:])}</section>'


def _planning(report: PermitReport) -> str:
    p, pl = report.property, report.planning
    rows = [("Address", _e(p.address)), ("Coordinates", f"{p.lat:.6f}, {p.lng:.6f} (precision: {_e(p.precision)})"),
            ("Jurisdiction", "<br/>".join(_e(j) for j in p.jurisdiction) or "—"),
            ("Competent authority", _e(p.authority) or "Not modelled for this jurisdiction"),
            ("Zoning", f"<b>{_e(pl.classification)}</b> (verified official layer)" if pl.verified_zoning else
             "<b>Zoning not verified.</b> No verified zoning layer; HABITA does not determine the classification. It "
             "must be confirmed on the official maps or with the competent authority.")]
    if pl.instrument:
        rows.append(("Instrument", _e(pl.instrument) + (f" — {_e(pl.instrument_version)}" if pl.instrument_version else "")))
    if pl.reasons:
        rows.append(("Why pending", "<br/>".join(_e(r) for r in pl.reasons)))
    docs = "".join(f"<tr><td>{_e(d.designation or d.title)}</td><td>{_e(d.reason)}"
                   + (f'<br/><span class="mono">{_url(d.url)}</span>' if d.url else "") + "</td></tr>"
                   for d in pl.documents_to_consult)
    return ('<section><h2>Property and planning context</h2><table>'
            + "".join(f"<tr><td style='width:34mm'>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>"
            + (f"<h3>Official maps to consult</h3><table><thead><tr><th>Document</th><th>What it shows</th></tr></thead>"
               f"<tbody>{docs}</tbody></table>" if docs else "") + "</section>")


def _analysis(report: PermitReport) -> str:
    a = report.assessment
    if a is None:
        return ""
    out = ["<section><h2>Analysis</h2>"]
    if not a.content_verified or display_status(report)[0] != "VERIFIED":
        out.append('<p class="notverified">Not verified. The statements below have not passed HABITA\'s verification '
                   "and must not be relied on.</p>")
    out.append(f"<p><b>Question:</b> {_e(a.question)}</p>")
    if a.conclusion_summary:
        out.append(f"<p><b>Conclusion ({_e(a.conclusion_answer)}):</b> {_e(a.conclusion_summary)}"
                   f"{_refs(a.conclusion_evidence_ids)}</p>")
    first: dict[str, str] = {}
    for key, heading in SECTIONS:
        items = [s for s in a.statements if s.section == key]
        if not items:
            continue
        out.append(f"<h3>{heading}</h3>")
        for s in items:
            text = s.text.strip()
            shown_as = s.step or s.label
            lead = f'<span class="label">{_e(shown_as)}</span>'
            if text in first:  # repeated word for word: referenced, with its own evidence ids (TD-044)
                out.append(f'<p class="statement">{lead}<span class="crossref">Same as {_e(first[text])} above.'
                           f"</span>{_refs(s.evidence_ids)}</p>")
            else:
                first[text] = shown_as
                out.append(f'<p class="statement">{lead}{_e(text)}{_refs(s.evidence_ids)}</p>')
    if a.conditions:
        out.append("<h3>Conditions</h3><ul>" + "".join(f"<li>{_e(c)}</li>" for c in a.conditions) + "</ul>")
    if a.issues:
        out.append("<h3>Why it was rejected</h3><ul>" + "".join(f"<li>{_e(i)}</li>" for i in a.issues) + "</ul>")
    if a.verification:
        v = a.verification
        # The record's outcome is shown bare only when it is the assessment's own status; any other record (earlier,
        # superseded or disagreeing) is labelled as history so it can never read as the current result.
        shown = display_status(report)[0]
        current = v.current and v.outcome == shown
        outcome = _e(v.outcome) if current else (f"{_e(v.outcome)} — recorded for draft revision {v.draft_revision}; "
                                                 f"history only, not the current status ({STATUS[shown][0]})")
        out.append(f"<h3>{'Verification record' if current else 'Earlier verification (not current)'}</h3><table>"
                   f"<tr><td>Outcome</td><td>{outcome}</td></tr>"
                   f"<tr><td>Report</td><td>{_e(v.verification_id)}</td></tr>"
                   f"<tr><td>Verified at</td><td>{v.created_at:%Y-%m-%d %H:%M} UTC</td></tr>"
                   f"<tr><td>Protocol</td><td>{_e(v.protocol)}</td></tr>"
                   f"<tr><td>Trust pin</td><td class='small'>{'<br/>'.join(f'{_e(k)}: {_e(val)}' for k, val in sorted(v.trust_pin.items())) or '—'}</td></tr></table>")
    if a.evidence:
        out.append("<h3>Evidence and provenance</h3><table><thead><tr><th>Id</th><th>Source</th><th>Status</th>"
                   "<th>Provenance</th></tr></thead><tbody>")
        for e in a.evidence:
            prov = " · ".join(f"{k} {_e(v)}" for k, v in (("source", e.source_id), ("trust", e.trust_status),
                                                         ("version", e.version), ("snapshot", e.snapshot_id),
                                                         ("sha256", e.sha256), ("locator", e.locator)) if v)
            out.append(f"<tr><td><b>{_e(e.evidence_id)}</b></td><td>{_e(e.title)}<br/><span class='small muted'>"
                       f"{_e(e.reference)}</span>" + (f"<br/><span class='mono'>{_url(e.url)}</span>" if e.url else "")
                       + f"</td><td class='small'>{_e(e.verification_status)}<br/>retrieved {e.retrieved_at:%Y-%m-%d}"
                       f"</td><td class='mono'>{prov or '—'}</td></tr>")
        out.append("</tbody></table>")
    return "".join(out) + "</section>"


def _sources(report: PermitReport) -> str:
    out = []
    if report.pending:
        out.append("<h3>Pending confirmation</h3><ul>" + "".join(f"<li>{_e(x)}</li>" for x in report.pending) + "</ul>")
    if report.sources:
        out.append("<h3>Official sources for this jurisdiction</h3><table><thead><tr><th>Source</th><th>Publisher</th>"
                   "<th>Status</th></tr></thead><tbody>" + "".join(
                       f"<tr><td>{_e(s.title)}" + (f"<br/><span class='mono'>{_url(s.url)}</span>" if s.url else "")
                       + f"</td><td class='small'>{_e(s.publisher)}</td><td class='small'>{_e(s.status)}"
                       + (f"<br/>verified {s.verified_on}" if s.verified_on else "") + "</td></tr>"
                       for s in report.sources) + "</tbody></table>")
    return (f'<section><h2>Sources and pending items</h2>{"".join(out)}<p class="small muted">{_e(report.disclaimer)}'
            "</p></section>")


def render_html(report: PermitReport, maps: LocationMaps | None = None, style: str = "moderno") -> str:
    if style not in STYLES:
        raise ValueError(f"Unknown style {style!r}; expected one of {', '.join(STYLES)}.")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>HABITA AI report</title><meta name="author" content="HABITA AI">'
            f"<style>{FONT_FACES[style]()}\n{CSS_BASE}\n{CSS_STYLE[style]}</style></head><body class='{style}'>"
            f'<div class="disclaimer-running">{"<b>" + DEMO + ".</b> " if report.demo else ""}{_e(report.disclaimer)}</div>'
            f"{_cover(report)}{_glance(report, style)}{_location(maps)}{_planning(report)}{_analysis(report)}"
            f"{_sources(report)}</body></html>")


def render_premium_pdf(report: PermitReport, maps: LocationMaps | None = None, style: str = "moderno") -> bytes:
    from weasyprint import HTML  # imported lazily: heavy, and only this renderer needs it

    return HTML(string=render_html(report, maps, style)).write_pdf()
