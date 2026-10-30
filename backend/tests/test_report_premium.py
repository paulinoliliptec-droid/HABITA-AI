"""HR-006 v2 premium PDF (HTML in the Clássico and Moderno styles, printed with WeasyPrint): presentation only —
statuses, numbers and relations come from the report model; repeated statements become cross-references that keep
their evidence ids; maps are embedded or explicitly unavailable; no key or token in the output."""

import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader

from app.integrations.maps.static_maps import LocationMaps, MapImage
from app.schemas.report import PermitReport
from app.services.report.premium import (
    STYLES,
    charts,
    display_status,
    graph_model,
    render_html,
    render_premium_pdf,
)

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "report" / "fixtures" / "verified-report.json"


@pytest.fixture(scope="module")
def verified() -> PermitReport:
    return PermitReport.model_validate(json.loads(FIXTURE.read_text()))


def _jpeg(colour) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 40), colour).save(buf, "JPEG")
    return buf.getvalue()


def _maps(street=True) -> LocationMaps:
    images = [MapImage("roadmap", _jpeg((200, 200, 190)), 16), MapImage("hybrid", _jpeg((40, 70, 40)), 16)]
    if street:
        images.append(MapImage("streetview", _jpeg((120, 140, 170)), captured="2024-07", distance_m=6, facing=True))
    return LocationMaps(38.697236, -9.420598, "area_center", 150, tuple(images))


def _text(pdf: bytes) -> str:
    return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages)


@pytest.mark.parametrize("style", STYLES)
def test_each_style_renders_every_section_with_the_reports_status(verified, style):
    pdf = render_premium_pdf(verified, _maps(), style)
    reader = PdfReader(io.BytesIO(pdf))
    text = _text(pdf)
    assert pdf.startswith(b"%PDF") and len(reader.pages) >= 5
    for section in ("Property & Permit Report", "Report at a glance", "Location", "Property and planning context",
                    "Analysis", "Sources and pending items", "No municipal confirmation", "Zoning not verified"):
        assert section.upper() in text.upper(), section
    assert verified.assessment.status == "VERIFIED" and "VERIFIED" in text
    # WeasyPrint shares one resource dictionary across pages, so count distinct images, not per-page references
    assert len({i.name for p in reader.pages for i in p.images}) == 3  # road map, satellite, Street View
    assert all("not legal advice" in p.extract_text() for p in reader.pages[1:])  # footer on every content page


@pytest.mark.parametrize("status", ["PENDING_CONFIRMATION", "REJECTED"])
def test_a_non_verified_report_is_never_presented_as_verified(verified, status):
    a = verified.assessment.model_copy(update={"status": status, "content_verified": False,
                                               "status_reason": "The draft did not pass verification."})
    html = render_html(verified.model_copy(update={"assessment": a}), None, "moderno")
    assert ">VERIFIED<" not in html and "Not verified." in html
    assert {"PENDING_CONFIRMATION": "PENDING CONFIRMATION", "REJECTED": "REJECTED"}[status] in html


def test_charts_print_the_reports_own_counts(verified):
    html = charts(verified)
    assert f">{len(verified.sources)}<" in html
    for status, n in __import__("collections").Counter(e.verification_status for e in verified.assessment.evidence).items():
        assert re.search(rf">{re.escape(status)}</text>.*?>{n}</text>", html)
    assert "No data in this report" not in html


def test_graph_edges_are_only_stored_relations(verified):
    cols, edges = graph_model(verified)
    nodes = {n["id"] for c in cols for n in c}
    a = verified.assessment
    cited = {(f"ev:{i}", f"sec:{s.section}") for s in a.statements for i in s.evidence_ids}
    cited |= {(f"ev:{i}", "conclusion") for i in a.conclusion_evidence_ids}
    structural = {("property", "jurisdiction"), ("jurisdiction", "authority"), ("property", "planning")}
    for src, dst in edges:
        assert src in nodes and dst in nodes
        if src.startswith("ev:"):
            assert (src, dst) in cited  # an evidence edge exists only where the report records the citation
        elif dst.startswith("ev:"):
            ev = next(e for e in a.evidence if f"ev:{e.evidence_id}" == dst)
            assert {"planning": "planning_context", "authority": "authority_record",
                    "jurisdiction": "jurisdiction_record"}[src] == ev.source_type
        else:
            assert (src, dst) in structural


def test_repeated_statements_become_cross_references_that_keep_their_evidence(verified):
    a = verified.assessment
    first = a.statements[0]
    dup = first.model_copy(update={"section": "risk", "label": "risk 9", "evidence_ids": ["E99"]})
    html = render_html(verified.model_copy(update={"assessment": a.model_copy(update={"statements": [*a.statements, dup]})}))
    assert f"Same as {first.label} above." in html and "[E99]" in html
    assert html.count(first.text.strip()) >= 1


def test_without_maps_the_pdf_says_so_and_embeds_no_image(verified):
    pdf = render_premium_pdf(verified, LocationMaps(38.7, -9.42, "area_center", 150,
                                                    unavailable="The map service did not return an image."), "classico")
    assert not {i.name for p in PdfReader(io.BytesIO(pdf)).pages for i in p.images}
    assert "Location maps unavailable" in _text(pdf)


def test_no_key_or_token_in_the_output(verified):
    pdf = render_premium_pdf(verified, _maps(), "moderno")
    for needle in (b"key=", b"AIza", b"Bearer"):
        assert needle not in pdf


def test_unknown_style_is_refused(verified):
    with pytest.raises(ValueError):
        render_html(verified, None, "baroque")


@pytest.mark.parametrize("change", [{"content_verified": False}, {"verification": None}, "not-current", "outcome"])
def test_a_verified_status_without_a_supporting_record_is_shown_as_pending(verified, change):
    a = verified.assessment
    if change == "not-current":
        change = {"verification": a.verification.model_copy(update={"current": False})}
    elif change == "outcome":
        change = {"verification": a.verification.model_copy(update={"outcome": "REJECTED"})}
    report = verified.model_copy(update={"assessment": a.model_copy(update=change)})
    assert display_status(report)[0] == "PENDING_CONFIRMATION"
    html = render_html(report)
    assert 'class="pill ok"' not in html and "Not verified." in html
    cols, _ = graph_model(report)
    assert next(n for c in cols for n in c if n["id"] == "conclusion")["text"] == "PENDING CONFIRMATION"


def test_without_an_assessment_pending_items_hang_from_the_property_only(verified):
    _, edges = graph_model(verified.model_copy(update={"assessment": None}))
    assert ("property", "pending") in edges and not any(dst == "pending" and src != "property" for src, dst in edges)


def test_demonstration_data_is_labelled_on_every_page(verified):
    pdf = render_premium_pdf(verified.model_copy(update={"demo": True}), None, "classico")
    pages = [" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages]
    assert all("DEMONSTRATION DATA" in t for t in pages)


def test_credential_parameters_are_stripped_from_printed_urls(verified):
    url = "https://user:SECRET0@example.pt/doc.pdf?page=2&key=SECRET1&access_token=SECRET2#token=SECRET3"
    src = verified.sources[0].model_copy(update={"url": url})
    html = render_html(verified.model_copy(update={"sources": [src, *verified.sources[1:]]}))
    assert not any(f"SECRET{i}" in html for i in range(4)) and "https://example.pt/doc.pdf?page=2" in html


def test_a_cross_reference_names_what_was_displayed(verified):
    a = verified.assessment
    first = a.statements[0].model_copy(update={"step": "Check the PDM"})
    dup = first.model_copy(update={"section": "risk", "label": "risk 9", "step": None})
    html = render_html(verified.model_copy(update={"assessment": a.model_copy(update={"statements": [first, dup]})}))
    assert "Same as Check the PDM above." in html


def test_no_authority_node_or_edge_when_the_report_names_none(verified):
    report = verified.model_copy(update={"property": verified.property.model_copy(update={"authority": None})})
    cols, edges = graph_model(report)
    assert "authority" not in {n["id"] for c in cols for n in c}
    assert not any("authority" in (src, dst) for src, dst in edges)
