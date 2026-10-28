"""HR-003 CX-1 (Codex, final) / MU-3 (Muse): user-declared parcel planning can never become a planning fact or a
parcel determination. User answers carry one capability, ``user_declaration``: they are shown back verbatim and
attributed, as findings only, and only for private facts; they support nothing else. Every case below runs with a
reviewer that approves everything and flags nothing."""

import pytest

from app.schemas.permit import Evidence
from app.services.permit.admissibility import (
    USER_FRAME, evidence_capabilities, is_determination, render_draft, render_user_declaration,
)
from app.services.permit.verifier import Verifier, model_statements
from tests.permit_fakes import CONVERSION_QUESTION, ScriptedModel, default_draft, make_client, resolve_cascais
from tests.test_permit_admissibility import (
    CASE_RECORDS, CENTRAL, LABELS, SECTIONS, TRUSTED, in_section, planning, record, resolved_state,
)
from tests.test_permit_official_sources import auth, ingest_regulamento
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, codes, matter

USER_PLANNING_CLAIMS = [
    # The reviewers' cases (Muse MU-3, Codex CX-1).
    "TEST DATA: the property belongs to the blue band.",
    "TEST DATA: The parcel is classified as Espaço Central.",
    # Direct user statements, EN + PT.
    "TEST DATA: my property is in the blue band.",
    "TEST DATA: this parcel is urban residential.",
    "TEST DATA: the PDM says my lot is category X.",
    "TEST DATA: a minha casa está em solo urbano.",
    "TEST DATA: o meu lote pertence à faixa azul.",
    # Citing an official URL; claiming the Câmara confirmed it.
    "TEST DATA: my lot is category X, see https://www.cascais.pt/pdm/planta-01-02.",
    "TEST DATA: segundo https://www.cascais.pt/pdm, o meu prédio pertence à faixa azul.",
    "TEST DATA: the Câmara confirmed my property is in the blue band.",
    "TEST DATA: a Câmara confirmou que o imóvel está em espaço habitacional.",
]
PRIVATE_FACTS = [
    "TEST DATA: licensed as one single-family dwelling (habitação).",
    "TEST DATA: two flats, one per floor, about 90 m2 each; each floor has its own street door.",
    "TEST DATA: single owner; not divided into fractions.",
    "TEST DATA: the property has two floors and a garden; each flat has its own entrance.",
    "TEST DATA: o imóvel tem dois pisos, cada um com entrada própria; proprietário único.",
]


def answer(text: str, eid: str = "E30", **kw) -> Evidence:
    return record(eid, "user_statement", text, status="user_declared", title="Answer to: What is the intended use?",
                  **kw)


def restated(text: str) -> str:
    return text.removeprefix("TEST DATA: ")


async def run(d, records, reviewer=None, planning_state=None):
    """HABITA's path: render, verify (approving reviewer), and the final gate on whatever the verifier returned."""
    async def state(_matter):
        return planning_state
    verifier = Verifier(reviewer or Reviewer(VERIFIED), TRUSTED, state)
    d = render_draft(d, records, matter())
    report = await verifier.verify(matter(), checklist(), d, records, CHAIN)
    gated = await verifier.final_gate(report.model_copy(update={"outcome": "VERIFIED"}), matter(), checklist(), d,
                                      records, CHAIN)
    return d, report, gated


def assert_never_verified(report, gated, why):
    assert report.outcome != "VERIFIED", why
    assert not report.checks["zoning_supported"] and "unverified_zoning" in codes(report.issues), why
    # The final gate, run independently on a report forced to VERIFIED, refuses it too.
    assert gated.outcome != "VERIFIED" and gated.checks["final_gate_passed"] is False, why


# --- capability: what a user record can be ------------------------------------------------------------------------

@pytest.mark.parametrize("claim", USER_PLANNING_CLAIMS[:4])
def test_a_user_record_has_only_the_user_declaration_capability_whatever_it_claims(claim):
    forged = [
        answer(claim),
        # A user record dressed up as a resolved, authoritative determination for this property.
        answer(claim, structured={"status": "resolved", "authoritative_determination": True,
                                  "property_id": matter().property_id, "classification": CENTRAL}),
        # A planning-context record whose content the user supplied.
        record("E30", "planning_context", claim, source="cascais-pdm", basis="planning_context",
               authority_class="municipal_instrument", status="user_declared",
               structured={"status": "resolved", "authoritative_determination": True,
                           "property_id": matter().property_id, "classification": CENTRAL}),
    ]
    for e in forged:
        assert evidence_capabilities(e) == {"user_declaration"}
        assert not is_determination(e, matter())


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("claim", USER_PLANNING_CLAIMS[:4])
async def test_a_parcel_determination_resting_on_a_user_record_is_rejected(claim, section):
    forged = answer(claim, structured={"status": "resolved", "authoritative_determination": True,
                                       "property_id": matter().property_id, "classification": CENTRAL})
    records = [*CASE_RECORDS, forged]
    _, report, gated = await run(in_section(section, "x", ["E30"], basis="parcel_determination"), records,
                                 planning_state=resolved_state())
    assert_never_verified(report, gated, (section, claim))
    # Even alongside a genuine determination, citing the user's answer for it is refused.
    genuine = planning("E4", status="resolved", classification=CENTRAL)
    _, report, gated = await run(in_section(section, "x", ["E4", "E30"], basis="parcel_determination"),
                                 [*records, genuine], planning_state=resolved_state())
    assert_never_verified(report, gated, (section, claim))
    assert report.checks["determinations_authoritative"] is False


# --- the user's planning claim, in every section, every way -----------------------------------------------------

@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("claim", USER_PLANNING_CLAIMS)
async def test_verbatim_repetition_never_verifies(claim, section):
    records = [*CASE_RECORDS, answer(claim)]
    d, report, gated = await run(in_section(section, restated(claim), ["E30"]), records)
    assert_never_verified(report, gated, (section, claim))
    if section == "claim":  # shown, if at all, only as the user's own words — never in HABITA's voice
        st = next(s for s in model_statements(d) if s.label == LABELS[section])
        assert st.planning_basis == "user_declaration" and st.text.startswith(USER_FRAME)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("claim", USER_PLANNING_CLAIMS)
async def test_declared_as_a_user_declaration_it_still_never_verifies(claim, section):
    records = [*CASE_RECORDS, answer(claim)]
    _, report, gated = await run(in_section(section, restated(claim), ["E30"], basis="user_declaration"), records)
    assert_never_verified(report, gated, (section, claim))


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("paraphrase", [
    "The property is located within the blue band.",
    "As the owner confirmed, the lot falls in the band reserved for housing.",
    "The Câmara has already confirmed the parcel's category.",
    "O imóvel situa-se na faixa azul, como indicou o proprietário.",
    "Segundo o proprietário, a parcela está classificada como espaço central.",
])
async def test_model_paraphrase_of_the_user_claim_never_verifies(paraphrase, section):
    records = [*CASE_RECORDS, answer(USER_PLANNING_CLAIMS[0])]
    _, report, gated = await run(in_section(section, paraphrase, ["E30"]), records)
    assert_never_verified(report, gated, (section, paraphrase))


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", [
    "the property belongs to the blue band.",
    "The property belongs to the blue band, and under the PDM urban land is intended for housing.",
    "O imóvel pertence à faixa azul; segundo o PDM, em solo urbano os espaços destinam-se à habitação.",
])
@pytest.mark.parametrize("basis", ["none", "general_planning_explanation", "user_declaration"])
async def test_user_claim_mixed_with_official_general_pdm_text_never_verifies(text, section, basis):
    records = [*CASE_RECORDS, answer(USER_PLANNING_CLAIMS[0])]
    _, report, gated = await run(in_section(section, text, ["E30", "E3"], basis=basis), records)
    assert_never_verified(report, gated, (section, text, basis))


async def test_an_official_url_inside_the_answer_is_not_evidence():
    """Only existing evidence IDs can be cited: the URL in the user's answer creates nothing citable."""
    records = [*CASE_RECORDS, answer(USER_PLANNING_CLAIMS[7])]
    _, report, _ = await run(in_section("claim", "Category X applies.", ["https://www.cascais.pt/pdm/planta-01-02"]),
                             records)
    assert report.outcome != "VERIFIED" and "unknown_evidence" in codes(report.issues)


async def test_the_reviewer_flag_also_binds_user_declarations():
    records = [*CASE_RECORDS, answer(PRIVATE_FACTS[0])]
    review = {**VERIFIED, "parcel_planning_statements": ["K1"]}
    _, report, _ = await run(in_section("claim", restated(PRIVATE_FACTS[0]), ["E30"]), records, Reviewer(review))
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


# --- legitimate private facts keep working ---------------------------------------------------------------------

@pytest.mark.parametrize("fact", PRIVATE_FACTS)
async def test_private_facts_declared_by_the_user_still_verify_as_findings(fact):
    records = [*CASE_RECORDS, answer(fact)]
    d, report, gated = await run(in_section("claim", restated(fact), ["E30"]), records)
    st = next(s for s in model_statements(d) if s.label == "K1")
    assert st.planning_basis == "user_declaration" and st.text == render_user_declaration([answer(fact)])
    assert report.outcome == "VERIFIED", report.issues
    assert gated.checks["final_gate_passed"] is True


@pytest.mark.parametrize("section", ["conclusion", "procedure", "risk", "next action"])
async def test_the_assessment_itself_can_never_rest_on_the_users_answers(section):
    records = [*CASE_RECORDS, answer(PRIVATE_FACTS[0])]
    _, report, _ = await run(in_section(section, restated(PRIVATE_FACTS[0]), ["E30"]), records)
    assert report.outcome == "REJECTED"


# --- end to end: the user answers with a planning claim, the model repeats it, the reviewer approves ------------

@pytest.mark.parametrize("claim", [USER_PLANNING_CLAIMS[0], USER_PLANNING_CLAIMS[9], USER_PLANNING_CLAIMS[6]])
def test_end_to_end_user_planning_claim_with_an_approving_reviewer(claim):
    answers = {"current_licensed_use": "One single-family dwelling (habitação).", "intended_use": claim,
               "ownership_status": "Single owner; not divided into fractions."}

    def repeating(payload):
        d = default_draft(payload)
        user_ids = [e["id"] for e in payload["evidence"] if e["type"] == "user_statement"]
        d["claims"].append({"text": restated(claim), "evidence_ids": user_ids, "planning_basis": "none", "quote": None})
        d["conclusion"]["summary"] = restated(claim) + " " + d["conclusion"]["summary"]
        return d

    with make_client(ScriptedModel(draft=repeating)) as client:  # the scripted reviewer approves everything
        ingest_regulamento(client)
        pid = resolve_cascais(client)
        created = client.post("/api/permit/matters", json={"property_id": pid, "question": CONVERSION_QUESTION}).json()
        mid, token = created["matter"]["matter_id"], created["access_token"]
        client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token))
        client.post(f"/api/permit/matters/{mid}/inputs", json={"inputs": answers}, headers=auth(token))
        client.post(f"/api/permit/matters/{mid}/continue", headers=auth(token))
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
        report = client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
        evidence = client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
        items = {i["key"]: i["status"] for i in client.get(f"/api/permit/matters/{mid}/checklist",
                                                            headers=auth(token)).json()["items"]}
    assert state != "VERIFIED" and report["checks"]["zoning_supported"] is False
    assert [e["structured"]["status"] for e in evidence if e["source_type"] == "planning_context"] == \
        ["requires_manual_confirmation"]
    assert items["planning_constraints"] == "blocked_external"
