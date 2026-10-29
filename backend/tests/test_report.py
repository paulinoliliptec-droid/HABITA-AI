"""HR-006 Premium PDF Report and the shared report model (also feeds the HR-004 map post-its).

AC6.1–AC6.6: the report only presents stored results; VERIFIED appears only under the status rule; zoning only when a
verified layer resolved it; the PDF carries the same status, evidence ids and provenance as the JSON."""

import io
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader

from app.schemas.permit import MatterState, VerificationReport
from app.schemas.sources import PlanningContext, ZoningClassification
from app.services.report.builder import assessment_status, build_report
from app.services.report.pdf import render_pdf
from tests.permit_fakes import ScriptedModel, make_client
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter


def pdf_text(content: bytes) -> str:
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(content)).pages)


@pytest.fixture(scope="module")
def verified_matter():
    """A real end-to-end Cascais run with the scripted model: NEEDS_INPUT → VERIFIED conditional."""
    model = ScriptedModel()
    with make_client(model) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        calls = len(model.calls)
        report = client.get(f"/api/permit/matters/{mid}/report", headers=auth(token))
        pdf = client.get(f"/api/permit/matters/{mid}/report.pdf", headers=auth(token))
        unauthorised = (client.get(f"/api/permit/matters/{mid}/report").status_code,
                        client.get(f"/api/permit/matters/{mid}/report.pdf").status_code)
        matter = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        property_pdf = client.get(f"/api/property/{matter['property_id']}/report.pdf")
        property_json = client.get(f"/api/property/{matter['property_id']}/report").json()
        yield {"report": report, "pdf": pdf, "unauthorised": unauthorised, "calls_before": calls,
               "calls_after": len(model.calls), "property_pdf": property_pdf, "property_json": property_json}


def test_ac6_1_a_verified_assessment_report_with_every_section(verified_matter):
    r = verified_matter["report"].json()
    a = r["assessment"]
    assert verified_matter["report"].status_code == 200 and a["status"] == "VERIFIED" and a["content_verified"]
    assert a["verification"]["outcome"] == "VERIFIED" and a["verification"]["trust_pin"]
    assert r["property"]["authority"] == "Câmara Municipal de Cascais" and r["property"]["jurisdiction"]
    assert a["statements"] and a["evidence"] and r["sources"] and r["disclaimer"]


def test_ac6_2_6_the_pdf_carries_the_jsons_status_ids_and_provenance(verified_matter):
    r, pdf = verified_matter["report"].json(), verified_matter["pdf"]
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    text = pdf_text(pdf.content)
    assert "VERIFIED" in text and "PENDING CONFIRMATION" not in text.split("Pending confirmation")[0][:400]
    for e in r["assessment"]["evidence"]:
        assert e["evidence_id"] in text
        if e["sha256"]:
            assert e["sha256"][:16] in text.replace(" ", "").replace("\n", "")
    assert "not legal advice" in text and "No verified zoning layer" in text


def test_ac6_4_generating_a_report_calls_no_model(verified_matter):
    assert verified_matter["calls_after"] == verified_matter["calls_before"]


def test_ac6_5_an_assessment_report_needs_the_capability_token(verified_matter):
    assert verified_matter["unauthorised"] == (401, 401)


def test_ac6_5_a_property_report_is_public_and_has_no_assessment(verified_matter):
    assert verified_matter["property_pdf"].status_code == 200
    assert verified_matter["property_json"]["assessment"] is None
    assert "No permit assessment is included" in pdf_text(verified_matter["property_pdf"].content)


# --- the status rule (AC6.2, adversarial) ----------------------------------------------------------------------------

def _matter(state, revision=0, latest="pv_1"):
    from tests.test_permit_admissibility import draft
    from tests.test_permit_verifier import matter
    m = matter().model_copy(update={"state": state, "revision": revision, "latest_verification_id": latest})
    return m.model_copy(update={"draft": draft().model_copy(update={"revision": revision})})


def _report(outcome="VERIFIED", revision=0, vid="pv_1"):
    return VerificationReport(verification_id=vid, matter_id="pm_1", draft_revision=revision, outcome=outcome,
                              issues=[], checks={}, created_at=datetime(2026, 10, 29, tzinfo=UTC))


@pytest.mark.parametrize("matter_state, report, expected", [
    (MatterState.VERIFIED, _report(), "VERIFIED"),
    (MatterState.VERIFIED, _report(revision=1), "PENDING_CONFIRMATION"),  # report of another draft revision
    (MatterState.VERIFIED, _report(vid="pv_other"), "PENDING_CONFIRMATION"),  # not the matter's latest report
    (MatterState.VERIFIED, None, "PENDING_CONFIRMATION"),  # no report at all
    (MatterState.VERIFIED, _report(outcome="REJECTED"), "REJECTED"),
    (MatterState.DRAFT_READY, None, "PENDING_CONFIRMATION"),  # an unverified draft
    (MatterState.VERIFYING, _report(), "PENDING_CONFIRMATION"),
    (MatterState.NEEDS_INPUT, None, "PENDING_CONFIRMATION"),
    (MatterState.REJECTED, _report(outcome="REJECTED"), "REJECTED"),
    (MatterState.ESCALATE, None, "PENDING_CONFIRMATION"),
    (MatterState.FAILED, None, "PENDING_CONFIRMATION"),
])
def test_ac6_2_verified_appears_only_under_the_status_rule(matter_state, report, expected):
    assert assessment_status(_matter(matter_state), report)[0] == expected


def test_ac6_2_a_protocol_superseded_assessment_is_never_verified():
    """Codex R1 P1: after raise-protocol-floor the stored values stay VERIFIED but the matter needs re-verification."""
    superseded_matter = _matter(MatterState.VERIFIED).model_copy(update={"superseded_protocol": "statement-v1"})
    assert assessment_status(superseded_matter, _report())[0] == "PENDING_CONFIRMATION"
    superseded_report = _report().model_copy(update={"superseded_protocol": "statement-v1"})
    assert assessment_status(_matter(MatterState.VERIFIED), superseded_report)[0] == "PENDING_CONFIRMATION"


def test_ac6_2_an_older_verified_record_is_shown_as_history_not_as_the_status():
    """Codex R1 P1: re-verifying a new draft while the previous report said VERIFIED."""
    report = build_report(_property(), _context("requires_manual_confirmation"), [],
                          _matter(MatterState.VERIFYING, revision=1), [], _report(revision=0))
    assert report.assessment.status == "PENDING_CONFIRMATION" and not report.assessment.verification.current
    text = pdf_text(render_pdf(report))
    assert "Earlier verification (not current)" in text and "history only" in text and "Verification record" not in text


def test_a_rejected_report_of_an_older_draft_does_not_reject_the_current_one():
    assert assessment_status(_matter(MatterState.DRAFT_READY, revision=1), _report("REJECTED", revision=0))[0] \
        == "PENDING_CONFIRMATION"


def test_evidence_ids_outside_the_e_n_form_do_not_break_the_report():
    from tests.test_permit_verifier import ev
    items = [ev(i) for i in ("E10", "legacy-1", "E2")]
    m = _matter(MatterState.DRAFT_READY).model_copy(update={"draft": None})
    ids = [e.evidence_id for e in build_report(_property(), _context("requires_manual_confirmation"), [], m,
                                               items).assessment.evidence]
    assert ids == ["E2", "E10", "legacy-1"]


def _context(status, classification=None):
    from app.schemas.property import Coordinates
    return PlanningContext(property_id="prp_0000000000000000", jurisdiction_id="pt/lisboa/cascais", status=status,
                           classification=classification, coordinates=Coordinates(lat=38.7, lng=-9.42),
                           precision="rooftop", guidance="Confirm on the official maps.", resolver="test",
                           resolver_version=1, resolved_at=datetime(2026, 10, 29, tzinfo=UTC))


def _property():
    from tests.test_property_repository import snapshot
    from app.schemas.property import ResolvedProperty
    return ResolvedProperty(**snapshot().model_dump(), property_id="prp_0000000000000000")


def test_an_unverified_draft_is_shown_as_not_verified_in_the_pdf():
    report = build_report(_property(), _context("requires_manual_confirmation"), [], _matter(MatterState.DRAFT_READY))
    assert report.assessment.status == "PENDING_CONFIRMATION" and not report.assessment.content_verified
    text = pdf_text(render_pdf(report))
    assert "PENDING CONFIRMATION" in text and "Not verified." in text and "VERIFIED —" not in text


def test_a_rejected_assessment_shows_why():
    m = _matter(MatterState.REJECTED)
    from app.schemas.permit import VerificationIssue
    rejected = _report(outcome="REJECTED").model_copy(update={"issues": [VerificationIssue(
        code="unsupported_legal_claim", message="The draft's K1 is not supported.", origin="rule")]})
    report = build_report(_property(), _context("requires_manual_confirmation"), [], m, [], rejected)
    text = pdf_text(render_pdf(report))
    assert report.assessment.status == "REJECTED" and "REJECTED" in text and "K1 is not supported" in text


# --- zoning only when verified (shared with HR-004, AC4.3) -----------------------------------------------------------

def test_a_classification_appears_only_when_resolved_by_a_verified_layer():
    cls = ZoningClassification(label="Espaços centrais")
    resolved = build_report(_property(), _context("resolved", cls), [])
    assert resolved.planning.verified_zoning and resolved.planning.classification == "Espaços centrais"
    manual = build_report(_property(), _context("requires_manual_confirmation", cls), [])
    assert not manual.planning.verified_zoning and manual.planning.classification is None
    assert "Espaços centrais" not in pdf_text(render_pdf(manual))


def test_demo_data_is_labelled():
    report = build_report(_property(), _context("requires_manual_confirmation"), [], demo=True)
    assert "DEMONSTRATION DATA" in pdf_text(render_pdf(report))


def test_the_frontends_report_fixture_still_matches_the_schema():
    """frontend/src/features/report/fixtures/verified-report.json is this backend's report; the map post-it tests
    (AC4.5) rely on it, so a schema change must regenerate it."""
    import json
    from pathlib import Path
    from app.schemas.report import PermitReport
    path = Path(__file__).parents[2] / "frontend/src/features/report/fixtures/verified-report.json"
    data = json.loads(path.read_text())
    assert PermitReport.model_validate(data).model_dump(mode="json").keys() == data.keys()
    assert data["assessment"]["status"] == "VERIFIED" and data["planning"]["verified_zoning"] is False
