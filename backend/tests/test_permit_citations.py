"""Claim-to-evidence reconciliation (HR-003 CX-1, evidence-first): a general planning explanation the model left
without its official passage gets one linked by HABITA, from this matter's admissible official text only, when the
match is strong and unambiguous. It never resolves the parcel's planning."""

import pytest

from app.services.permit.admissibility import EXPLANATION_FRAME, render_draft, render_user_declaration
from app.services.permit.citations import reconcile_citations
from app.services.permit.verifier import Verifier, model_statements
from tests.permit_fakes import ScriptedModel, default_draft, make_client
from tests.test_permit_admissibility import (
    ADDRESS, CASE_RECORDS, JURISDICTION, LABELS, PDM_TEXT, SECTIONS, TRUSTED, MutableTrust, authority, in_section,
    planning, record, rjue, user,
)
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, codes, matter

# The model forgot the citation (or cited a curated summary / no evidence); E3 is the PDM's own passage (Art. 61.º).
GENERAL = [
    "Urban land is intended mainly for building and housing, commerce and services.",
    "Em solo urbano, os espaços destinam-se sobretudo à edificação e à habitação, comércio e serviços.",
]
UNRELATED = [
    "Heritage protection rules limit façade alterations.",
    "As regras de proteção do património limitam alterações de fachada.",
]
PARCEL = [
    "This parcel is intended for building and housing under the PDM.",
    "Este imóvel está em solo urbano destinado à edificação e habitação.",
]


def porto_official(eid="E21"):
    return record(eid, "regulatory_source", PDM_TEXT, source="porto-pdm", basis="official_text",
                  authority_class="municipal_instrument", jurisdiction="pt/porto/porto", title="PDM-Porto — Regulamento",
                  status="official_text")


async def reconcile_and_verify(d, records=CASE_RECORDS, trust=TRUSTED):
    d = render_draft(d, records, matter())
    d = reconcile_citations(d, records, matter(), CHAIN, await trust.trusted_ids(CHAIN))
    report = await Verifier(Reviewer(VERIFIED), trust, None).verify(matter(), checklist(), d, records, CHAIN)
    return d, report


def statement(d, section):
    return next(s for s in model_statements(d) if s.label == LABELS[section])


@pytest.mark.parametrize("cites", [[], ["E1"], ["E1", "E6"], ["E8"]], ids=str)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", GENERAL)
async def test_forgotten_official_citation_is_reconciled_and_can_verify(text, section, cites):
    """In every section (incl. procedure, risk, next action): HABITA links E3 and records it as a system action."""
    d, report = await reconcile_and_verify(in_section(section, text, cites, basis="general_planning_explanation"))
    st = statement(d, section)
    assert "E3" in st.evidence_ids and st.text == EXPLANATION_FRAME + text
    [link] = d.citation_reconciliation
    assert (link.statement, link.outcome, link.evidence_id, link.added_by) == (LABELS[section], "linked", "E3", "system")
    assert link.score >= 2 and link.coverage >= 0.6 and link.matched
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", UNRELATED)
async def test_without_a_relevant_official_passage_nothing_is_linked_and_it_stays_rejected(text, section):
    d, report = await reconcile_and_verify(in_section(section, text, ["E1"], basis="general_planning_explanation"))
    assert statement(d, section).evidence_ids == ["E1"]
    assert [link.outcome for link in d.citation_reconciliation] == ["no_match"]
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("text", GENERAL)
async def test_official_text_from_another_jurisdiction_is_never_linked(text):
    records = [rjue("E1"), porto_official(), planning("E2"), user("E8"), authority("E9"), ADDRESS, JURISDICTION]
    trust = MutableTrust(*TRUSTED.ids, "porto-pdm")
    d, report = await reconcile_and_verify(in_section("claim", text, ["E1"]), records, trust)
    assert "E21" not in statement(d, "claim").evidence_ids
    assert [link.outcome for link in d.citation_reconciliation] == ["no_match"]
    assert report.outcome == "REJECTED"


@pytest.mark.parametrize("text", GENERAL)
async def test_a_retired_or_untrusted_official_source_is_never_linked(text):
    trust = MutableTrust(*(TRUSTED.ids - {"cascais-pdm"}))
    d, report = await reconcile_and_verify(in_section("claim", text, ["E1"]), trust=trust)
    assert "E3" not in statement(d, "claim").evidence_ids
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", PARCEL)
async def test_a_parcel_statement_is_not_reconciled_and_the_general_pdm_never_supports_it(text, section):
    """Only the general PDM passage exists: no link is attempted, and the statement is rejected."""
    d, report = await reconcile_and_verify(in_section(section, text, ["E1"]))
    assert d.citation_reconciliation == [] and "E3" not in statement(d, section).evidence_ids
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)
    assert not any(s.planning_basis == "parcel_determination" for s in model_statements(d))
    # Even citing the PDM passage itself doesn't help.
    _, report = await reconcile_and_verify(in_section(section, text, ["E3"]))
    assert report.outcome == "REJECTED"


@pytest.mark.parametrize("text", GENERAL)
async def test_an_ambiguous_match_between_sources_is_not_resolved_arbitrarily(text):
    twin = record("E22", "regulatory_source", PDM_TEXT, source="cascais-pdm", basis="official_text",
                  authority_class="municipal_instrument", title="PDM-Cascais — Regulamento (Art. 61.º-A)",
                  status="official_text")
    records = [*CASE_RECORDS, twin]
    d, report = await reconcile_and_verify(in_section("claim", text, ["E1"]), records)
    [link] = d.citation_reconciliation
    assert link.outcome == "ambiguous" and set(link.candidates) == {"E3", "E22"} and link.evidence_id is None
    assert statement(d, "claim").evidence_ids == ["E1"]
    assert report.outcome == "REJECTED"


async def test_already_cited_official_text_is_left_alone():
    d, report = await reconcile_and_verify(in_section("claim", GENERAL[0], ["E3"]))
    assert d.citation_reconciliation == [] and statement(d, "claim").evidence_ids == ["E3"]
    assert report.outcome == "VERIFIED"


async def test_only_official_regulatory_records_are_ever_linked():
    """Reconciliation never adds a planning context, property, user, authority or curated record."""
    records = [rjue("E1"), planning("E2"), user("E8"), authority("E9"), ADDRESS, JURISDICTION]
    for text in GENERAL:
        d, _ = await reconcile_and_verify(in_section("claim", text, ["E1"]), records)
        assert statement(d, "claim").evidence_ids == ["E1"]
        assert [link.outcome for link in d.citation_reconciliation] == ["no_match"]


def test_cascais_workflow_reconciles_the_forgotten_citation_without_resolving_zoning():
    """End to end: the model cites only the curated PDM summary for a general explanation and words the parcel's
    category as a deferral → HABITA links the PDM passage, renders the condition, VERIFIED conditional, manual."""
    general = "Urban land is intended mainly for urbanisation and building, including housing, commerce and services."

    def drafting(parcel_risk):
        def draft_(payload):
            d = default_draft(payload)
            curated = [e["id"] for e in payload["evidence"] if e["basis"] == "curated_reference" and "PDM" in e["source"]]
            planning_ids = [e["id"] for e in payload["evidence"] if e["type"] == "planning_context"]
            d["claims"].append({"text": general, "evidence_ids": curated, "planning_basis": "general_planning_explanation",
                                "quote": None})
            d["next_actions"].append({"text": general, "evidence_ids": [], "planning_basis": "none", "quote": None})
            d["risks"].append({"text": parcel_risk, "evidence_ids": planning_ids, "planning_basis": "none", "quote": None})
            return d
        return draft_

    with make_client(ScriptedModel(draft=drafting("The parcel's land-use category must be confirmed with the Câmara."))) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        persisted = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        evidence = {e["evidence_id"]: e for e in client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()}
    draft = persisted["draft"]
    assert persisted["state"] == "VERIFIED" and draft["conclusion"]["answer"] == "conditional"
    links = [link for link in draft["citation_reconciliation"] if link["outcome"] == "linked"]
    assert {link["statement"] for link in links} >= {f"K{len(draft['claims'])}"} and len(links) == 2
    for link in links:
        linked = evidence[link["evidence_id"]]
        assert linked["verification_status"] == "official_text" and linked["source_type"] == "regulatory_source"
        assert link["added_by"] == "system"
    assert any(r["text"].startswith("The land-use category applicable to this parcel has not yet been determined")
               and r["planning_basis"] == "authority_confirmation" for r in draft["risks"])
    assert [e["structured"]["status"] for e in evidence.values() if e["source_type"] == "planning_context"] == \
        ["requires_manual_confirmation"]

    # The parcel-specific version still ends REJECTED: reconciliation doesn't touch it.
    with make_client(ScriptedModel(draft=drafting("The parcel's land-use category admits housing, so two dwellings fit."))) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        assert client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"] == "REJECTED"



# --- Regression: the real Muse Spark run of 2026-10-28 (pm_6eec5e833d751d8d) ----------------------------------
# K1-K3 were case facts copied verbatim from the records they cite; the words "District", "urbanístico" and
# "habitação" made HABITA treat them as planning explanations needing PDM text (REJECTED), and reconciliation then
# linked K2 to the parking article (Art. 120.º) on generic concepts. Exact texts and record wordings from that run.

LIVE_JURISDICTION = record("E2", "jurisdiction_record",
                           "Country: Portugal → District: Lisboa → Municipality: Cascais → Parish: União das freguesias "
                           "de Cascais e Estoril", status="system_record", title="HABITA jurisdiction resolution",
                           structured={"levels": [{"name": "Portugal"}, {"name": "Lisboa"}, {"name": "Cascais"},
                                                  {"name": "União das freguesias de Cascais e Estoril"}]})
LIVE_AUTHORITY = record("E3", "authority_record", "Câmara Municipal de Cascais: Licensing of urban operations, including "
                        "building permits (licenciamento urbanístico).", status="system_record",
                        title="Câmara Municipal de Cascais")
LIVE_USER = record("E18", "user_statement", "TEST DATA: licensed as one single-family dwelling (habitação).",
                   status="user_declared", title="Answer to: What is the property's currently licensed use?")
LIVE_PARKING = record("E13", "regulatory_source",
                      "Artigo 120.º Dotação de estacionamento 1 - Nas operações urbanísticas de edificação, incluindo "
                      "obras de ampliação e alteração de uso, sujeitas a licenciamento ou comunicação prévia, deve ser "
                      "assegurada a dotação de estacionamento.", source="cascais-pdm", basis="official_text",
                      authority_class="municipal_instrument", title="PDM-Cascais — Regulamento", status="official_text")
LIVE_RECORDS = [LIVE_JURISDICTION, LIVE_AUTHORITY, LIVE_USER, LIVE_PARKING, ADDRESS, planning("E4"), rjue("E1")]
LIVE_K = [
    ("K1", "Country: Portugal → District: Lisboa → Municipality: Cascais → Parish: União das freguesias de Cascais e "
           "Estoril", ["E2"]),
    ("K2", "Câmara Municipal de Cascais: Licensing of urban operations, including building permits (licenciamento "
           "urbanístico).", ["E3"]),
    ("K3", "licensed as one single-family dwelling (habitação).", ["E18"]),
]


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("label, text, cites", LIVE_K, ids=[k[0] for k in LIVE_K])
async def test_live_k1_k3_restated_case_facts_are_facts_not_planning_explanations(label, text, cites, section):
    """K1/K2 stay `none` facts of HABITA's own records; K3 (the user's answer) is shown verbatim as the user's
    declaration (HR-003 MU-3). No frame, no PDM citation, nothing reconciled; all verify."""
    d, report = await reconcile_and_verify(in_section(section, text, cites), LIVE_RECORDS)
    st = statement(d, section)
    assert st.evidence_ids == cites
    if label == "K3" and section != "claim":  # a user's answer stands only as a finding
        assert report.outcome == "REJECTED"
        assert all(link.outcome != "linked" for link in d.citation_reconciliation)
        return
    assert d.citation_reconciliation == []
    if label == "K3":
        assert st.planning_basis == "user_declaration" and st.text == render_user_declaration([LIVE_USER])
    else:
        assert st.planning_basis == "none" and st.text == text
    assert report.outcome == "VERIFIED", report.issues


async def test_live_k2_is_never_linked_to_the_parking_article():
    """Even read as a planning explanation, a licensing statement shares only generic concepts with Art. 120.º."""
    d, report = await reconcile_and_verify(
        in_section("claim", LIVE_K[1][1], ["E3"], basis="general_planning_explanation"), LIVE_RECORDS)
    assert "E13" not in statement(d, "claim").evidence_ids
    assert [link.outcome for link in d.citation_reconciliation] == ["no_match"]
    assert report.outcome == "REJECTED"


@pytest.mark.parametrize("answer, claim", [
    ("TEST DATA: the property is zoned residential (espaço habitacional).", "zoned residential (espaço habitacional)."),
    ("TEST DATA: the property is in a residential zone.", "the property is in a residential zone."),
    ("TEST DATA: o imóvel está em solo urbano, categoria habitacional.", "o imóvel está em solo urbano, categoria habitacional."),
    ("TEST DATA: the PDM classifies it as central space.", "the PDM classifies it as central space."),
], ids=["zoned-en", "zone-en", "solo-urbano-pt", "pdm-classifies"])
async def test_a_restated_user_answer_never_establishes_a_planning_classification(answer, claim):
    """A user's (or any case record's) zoning claim, repeated verbatim, is still not a parcel determination."""
    stated = record("E18", "user_statement", answer, status="user_declared", title="Answer")
    records = [*LIVE_RECORDS[:2], stated, LIVE_PARKING, ADDRESS, planning("E4"), rjue("E1")]
    for section in SECTIONS:
        _, report = await reconcile_and_verify(in_section(section, claim, ["E18"]), records)
        assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues), (section, claim)


async def test_a_restatement_must_be_verbatim_to_count_as_a_fact():
    """Adding planning wording of the model's own to a case record makes it a planning explanation again."""
    text = "licensed as one single-family dwelling (habitação) in an urban residential area."
    d, report = await reconcile_and_verify(in_section("claim", text, ["E18"]), LIVE_RECORDS)
    assert statement(d, "claim").planning_basis == "general_planning_explanation"
    assert report.outcome == "REJECTED"


# --- K1 false REJECTED (real run, round 6): a neutral location verb restating HABITA's location record --------------
# "The property is located in Cascais …" citing the jurisdiction record was rejected because "located" isn't in the
# record. The neutral location predicate is grounded by HABITA's own location evidence — and by nothing else.

LIVE_K1_LOCATED = ("The property is located in Cascais, Lisboa, Portugal, in the parish of Uniao das freguesias de "
                   "Cascais e Estoril.")  # exact text of the real run


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text, cites", [
    (LIVE_K1_LOCATED, ["E2"]),
    ("The property is situated in Cascais, Lisboa, Portugal.", ["E2"]),
    ("Localizado em Cascais, Lisboa, Portugal.", ["E2"]),
    ("The property is located at Praça 5 de Outubro, Cascais.", ["E6"]),
], ids=["live-k1", "situated", "pt-localizado", "property-record"])
async def test_a_neutral_location_restating_habitas_location_record_verifies(text, cites, section):
    d, report = await reconcile_and_verify(in_section(section, text, cites), LIVE_RECORDS)
    st = statement(d, section)
    assert st.planning_basis == "none" and st.text == text
    assert report.outcome == "VERIFIED", (section, report.issues)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text, cites", [
    ("The property is located in the blue band.", ["E2"]),
    ("The property is located in an urban residential zone.", ["E2"]),
    ("The property is located in espaço central.", ["E2"]),
    ("The property is located in Cascais, in the zone where housing is admitted.", ["E2"]),
    ("O imóvel está localizado na faixa azul.", ["E2"]),
    ("O imóvel está situado em solo urbano habitacional.", ["E2"]),
    # Without HABITA's location evidence the verb grounds nothing.
    ("The property is located in Cascais.", ["E1"]),
    ("The property is located in Cascais.", ["E3"]),
    ("The property is located in Cascais.", ["E18"]),
], ids=["blue-band", "urban-zone", "pdm-category", "zone-clause", "pt-faixa-azul", "pt-solo-urbano",
        "law-only", "authority-only", "user-only"])
async def test_location_wording_never_carries_zoning_or_stands_without_location_evidence(text, cites, section):
    _, report = await reconcile_and_verify(in_section(section, text, cites), LIVE_RECORDS)
    assert report.outcome == "REJECTED", (section, text, cites)
    assert "unverified_zoning" in codes(report.issues) and not report.checks["zoning_supported"]


@pytest.mark.parametrize("answer", ["TEST DATA: the property is located in the blue band.",
                                    "TEST DATA: o imóvel está localizado em espaço habitacional."])
async def test_a_user_answer_with_a_location_verb_still_cannot_state_planning(answer):
    stated = record("E18", "user_statement", answer, status="user_declared", title="Answer")
    records = [*LIVE_RECORDS[:2], stated, LIVE_PARKING, ADDRESS, planning("E4"), rjue("E1")]
    for section in SECTIONS:
        _, report = await reconcile_and_verify(in_section(section, answer.removeprefix("TEST DATA: "), ["E18"]), records)
        assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues), section
