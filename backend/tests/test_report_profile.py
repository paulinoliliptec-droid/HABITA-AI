"""HR-008 property profile: three kinds that never mix, origin on every item, unknowns stated, disagreements shown, and no
effect on any status (AC8.1–AC8.8)."""

import io
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace as NS

import pytest
from pypdf import PdfReader

from app.schemas.permit import Evidence
from app.schemas.report import PermitReport
from app.services.i18n.translator import translator_for
from app.services.report.pdf import render_pdf
from app.services.report.premium import render_html
from app.services.report.profile import build_profile
from app.services.report.voice import build_voice_script
from tests.test_report import verified_matter  # noqa: F401
from tests.test_report_premium import FIXTURE

PROPERTY = NS(
    formatted_address="Praça 5 de Outubro, Cascais", precision="area_center", resolved_at=datetime(2026, 10, 30, tzinfo=UTC),
    coordinates=NS(lat=38.697236, lng=-9.420598),
    jurisdiction=NS(levels=[NS(type="country", name="Portugal"), NS(type="municipality", name="Cascais")],
                    local_authority=NS(name="Câmara Municipal de Cascais",
                                       sources=[NS(title="RJUE", url="https://example.pt/rjue")])),
)


def source(status="trusted"):
    return NS(source_id="pdm", status=status, publisher="Câmara", verified_on=date(2026, 10, 1), title="PDM",
              official_url="https://example.pt/pdm", version="2015")


def context(status="manual", classification=None, instrument=True):
    return NS(status=status, classification=NS(label="Espaço Central") if classification else None,
              instrument=NS(source_id="pdm") if instrument else None)


def declared(key="current_licensed_use", answer="Habitação"):
    return Evidence(evidence_id="E1", matter_id="m", source_type="user_statement", source_title="User",
                    source_reference="Answer to: What is the licensed use?", jurisdiction_id="pt",
                    retrieved_at=datetime(2026, 10, 30, tzinfo=UTC), claim_supported=key, excerpt=answer,
                    structured={"input_key": key, "answer": answer}, confidence="medium",
                    verification_status="user_declared", dedupe_key=f"{key}:{answer}")


def by_key(items, key):
    return [i for i in items if i.key == key]


def test_every_item_has_one_kind_and_an_origin():
    items = build_profile(PROPERTY, context(), [source()], [declared()])
    assert {i.kind for i in items} == {"official", "observation", "declaration"}
    assert all(i.origin for i in items)


def test_a_geocoder_or_reference_is_never_official():
    items = build_profile(PROPERTY, context(), [source()])
    for key in ("address", "location", "jurisdiction", "competent_authority"):
        assert by_key(items, key)[0].kind == "observation"


@pytest.mark.parametrize("status", ["candidate", "retired"])
def test_only_a_registered_source_makes_an_official_fact(status):
    items = build_profile(PROPERTY, context("resolved", True), [source(status)])
    assert by_key(items, "planning_instrument")[0].value is None
    assert by_key(items, "zoning")[0].value is None


def test_a_missing_source_or_instrument_gives_no_fact():
    assert by_key(build_profile(PROPERTY, context(instrument=False), [source()]), "planning_instrument")[0].value is None
    assert by_key(build_profile(PROPERTY, context("resolved", True), []), "zoning")[0].value is None


def test_zoning_only_from_a_resolved_layer_of_a_registered_source():
    item = by_key(build_profile(PROPERTY, context("resolved", True), [source()]), "zoning")[0]
    assert (item.value, item.kind, item.origin, item.as_of) == ("Espaço Central", "official", "Câmara", date(2026, 10, 1))


def test_what_is_unknown_is_not_confirmed_and_says_where_to_confirm():
    items = build_profile(PROPERTY, context(), [source()])
    for key in ("zoning", "parcel_boundary"):
        assert by_key(items, key)[0].value is None and "competent authority" in by_key(items, key)[0].origin


def test_a_declaration_stays_a_declaration_and_in_the_users_words():
    item = by_key(build_profile(PROPERTY, context(), [source()], [declared()]), "current_licensed_use")[0]
    assert (item.kind, item.value, item.label) == ("declaration", "Habitação", "What is the licensed use?")


@pytest.mark.parametrize("answer", ["I don't know", "Não sei", "não sei "])
def test_an_unknown_answer_is_not_a_value(answer):
    item = by_key(build_profile(PROPERTY, context(), [source()], [declared(answer=answer)]), "current_licensed_use")[0]
    assert item.value is None and item.kind == "declaration" and "competent authority" in item.origin


def test_a_known_answer_says_how_far_it_goes():
    item = by_key(build_profile(PROPERTY, context(), [source()], [declared()]), "current_licensed_use")[0]
    assert item.precision == "As stated by you, not verified" and item.as_of == date(2026, 10, 30)


def test_other_evidence_is_not_a_declaration():
    other = declared().model_copy(update={"source_type": "regulatory_source", "verification_status": "official_text"})
    assert not [i for i in build_profile(PROPERTY, context(), [source()], [other]) if i.kind == "declaration"]


def test_a_disagreement_shows_both_sides_and_chooses_nothing():
    items = by_key(build_profile(PROPERTY, context(), [source()], [declared(), declared(answer="Comércio")]),
                   "current_licensed_use")
    assert [i.value for i in items] == ["Habitação", "Comércio"] and all(i.conflict for i in items)


def test_a_repeated_answer_is_one_item_and_no_conflict():
    items = by_key(build_profile(PROPERTY, context(), [source()], [declared(), declared(answer="habitação ")]),
                   "current_licensed_use")
    assert len(items) == 1 and not items[0].conflict


def test_declarations_reach_only_the_matter_report(verified_matter):
    assert any(i["kind"] == "declaration" for i in verified_matter["report"].json()["profile"])
    assert not any(i["kind"] == "declaration" for i in verified_matter["property_json"]["profile"])


def test_the_profile_changes_no_status(verified_matter):
    a = verified_matter["report"].json()["assessment"]
    assert a["status"] == "VERIFIED" and a["content_verified"] is True


REPORT = PermitReport.model_validate(json.loads(FIXTURE.read_text()))


def with_profile(language="en"):
    return REPORT.model_copy(update={"language": language, "profile": build_profile(PROPERTY, context(), [source()], [declared()])})


def test_voice_keeps_the_kinds_apart_and_says_the_unknown():
    text = " ".join(build_voice_script(with_profile()))
    assert "Official facts" in text and "Observations" in text and "Your declarations, not verified" in text
    assert "Not confirmed" in text and "Parcel boundary: confirm with" in text


def test_pdf_shows_the_profile_with_its_kinds():
    html = render_html(with_profile())
    assert "Property profile" in html and "Declaration" in html and "Not confirmed" in html and "Habitação" in html


def test_both_pdfs_carry_the_profile():
    report = with_profile()
    assert "As stated by you" in render_html(report)
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(render_pdf(report))).pages)
    assert "Property profile" in text and "Declaration" in text and "Not confirmed" in text


def test_every_known_item_has_a_precision():
    items = build_profile(PROPERTY, context(), [source()], [declared()])
    assert all(i.precision for i in items if i.value)


def test_a_source_without_a_version_still_states_its_precision():
    versionless = NS(**{**vars(source()), "version": None})
    item = by_key(build_profile(PROPERTY, context(), [versionless]), "planning_instrument")[0]
    assert item.precision == "Registered source, no version recorded"


def test_voice_says_an_unknown_answer_was_the_users():
    profile = build_profile(PROPERTY, context(), [source()], [declared(answer="Não sei")])
    text = " ".join(build_voice_script(REPORT.model_copy(update={"profile": profile})))
    assert "you declared that you do not know" in text


def test_the_portuguese_legacy_pdf_labels_the_profile_in_portuguese():
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(render_pdf(with_profile("pt")))).pages)
    assert "Ficha do imóvel" in text and "Declaração" in text and "Não confirmado" in text


def test_portuguese_labels_exist():
    t = translator_for("pt")
    assert t("Property profile") == "Ficha do imóvel" and t("Parcel boundary") == "Limites do lote"
