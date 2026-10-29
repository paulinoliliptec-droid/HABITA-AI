"""Codex HR-003 CX-1 (no parcel planning content can reach VERIFIED without an authoritative parcel determination)
and CX-2 (evidence admissibility is re-validated against the current registry, up to the final gate)."""

from types import SimpleNamespace

import pytest

from app.schemas.permit import Claim, Conclusion, Condition, Evidence, NextAction, ProcedureStep, Risk
from app.schemas.sources import SourceProvenance
from app.services.permit.admissibility import (
    EXPLANATION_FRAME, RENDERED_STEP, planning_condition, render_determination, render_draft,
)
from app.services.permit.verifier import Verifier, model_statements, rule_checks
from app.services.sources.registry import TrustPin
from tests.permit_fakes import ANSWERS, ScriptedModel, default_draft, make_client
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter
from tests.test_permit_verifier import (
    CHAIN, NOW, PLANNING_CONDITION, VERIFIED, Reviewer, checklist, codes, draft, ev, item, matter,
)

PROPERTY = "prp_0000000000000001"
CASCAIS = "pt/lisboa/cascais"
M = "pm_0000000000000001"

# Real wording of the records HABITA produces (curated references, official PDM text, FAQ, user facts, authority).
RJUE_TEXT = ("Urban operations, including building works and alterations, are subject to municipal prior control "
             "under the RJUE (licence or prior communication, depending on the operation).")
CIVIL_TEXT = ("Only autonomous units can be the object of horizontal property: units that are independent, distinct and "
              "isolated from each other, with their own exit to a common part of the building or to the public way.")
PDM_TEXT = ("Princípios gerais do solo urbano 1 - Em solo urbano os espaços destinam-se predominantemente à "
            "urbanização e edificação, designadamente de habitação, comércio e serviços.")
#: PDM_TEXT's rule in its own wording: the only form in which a restatement of it verifies, and the whole sentence a
#: quote must be (owner decision after ACC-QO-09 / ACC-ROLE-01).
PDM_SENTENCE = PDM_TEXT.split(" 1 - ", 1)[1]
PDM_QUOTE = PDM_SENTENCE.rstrip(".")
FAQ_TEXT = ("Q: Que entidades é necessário registar no MyCascais para iniciar um pedido de licenciamento ou "
            "comunicação prévia? R: Todas as entidades do pedido deverão estar registadas e validadas no MyCascais.")
PLANNING_TEXT = "Planning classification requires confirmation against the official map(s)."
CONDITION_TEXT = ("The land-use category applicable to this parcel has not yet been determined by HABITA. It must be "
                  "confirmed on the official PDM map or with the Câmara Municipal before concluding whether the "
                  "operation is admissible. Check against the official documents: Planta de "
                  "Ordenamento 01-02.")


class MutableTrust:
    """The registry's current trusted set; tests retire and restore sources between steps."""

    def __init__(self, *ids: str) -> None:
        self.ids = set(ids)

    async def trusted_ids(self, chain):
        return set(self.ids)

    async def pin(self, chain):
        """The final gate's single read (status, version); versions are not modelled by this fake."""
        return TrustPin({sid: ("trusted", 0) for sid in await self.trusted_ids(chain)})


def record(eid, source_type, excerpt, *, source=None, basis="curated_reference", authority_class=None,
           jurisdiction=CASCAIS, title="Source", structured=None, status="curated_reference", **kw) -> Evidence:
    provenance = None
    if source:
        provenance = SourceProvenance(source_id=source, basis=basis, trust_status="trusted",
                                      authority_class=authority_class,
                                      snapshot_id="ss_1" if basis == "official_text" else None,
                                      sha256="a" * 64 if basis == "official_text" else None)
    return Evidence(evidence_id=eid, matter_id=M, source_type=source_type, source_title=title, source_reference="r",
                    jurisdiction_id=jurisdiction, retrieved_at=NOW, claim_supported="x", excerpt=excerpt,
                    confidence="medium", verification_status=status, dedupe_key=eid,
                    structured=structured or ({"source_id": source} if source else {}), provenance=provenance, **kw)


def planning(eid: str, status="requires_manual_confirmation", property_id=PROPERTY, classification=None,
             source="cascais-pdm") -> Evidence:
    return record(eid, "planning_context", PLANNING_TEXT, source=source, basis="planning_context",
                  authority_class="municipal_instrument", title="Planning context", status="system_record",
                  structured={"status": status, "property_id": property_id, "classification": classification,
                              "authoritative_determination": status == "resolved",
                              "instrument": {"title": "PDM-Cascais"}})


def official(eid: str, source="cascais-pdm") -> Evidence:
    return record(eid, "regulatory_source", PDM_TEXT, source=source, basis="official_text",
                  authority_class="municipal_instrument", title="PDM-Cascais — Regulamento", status="official_text")


def rjue(eid="E1") -> Evidence:
    return record(eid, "regulatory_source", RJUE_TEXT, source="pt-rjue", jurisdiction="pt", authority_class="primary_law",
                  title="RJUE")


def civil(eid="E7") -> Evidence:
    return record(eid, "regulatory_source", CIVIL_TEXT, source="pt-codigo-civil-propriedade-horizontal",
                  jurisdiction="pt", authority_class="primary_law", title="Código Civil — propriedade horizontal")


def faq(eid="E5") -> Evidence:
    return record(eid, "regulatory_source", FAQ_TEXT, source="cascais-urbanismo-faq", authority_class="official_guidance",
                  title="Urbanismo — perguntas frequentes")


def user(eid="E8") -> Evidence:
    return record(eid, "user_statement", ANSWERS["intended_use"], status="user_declared", title="Information supplied")


def authority(eid="E9") -> Evidence:
    return record(eid, "authority_record", "Câmara Municipal de Cascais: decides on the licensing of urban operations.",
                  status="system_record", title="Câmara Municipal de Cascais")


def claim(text: str, *ids: str, basis="none", quote=None) -> Claim:
    return Claim(claim_id="K1", text=text, evidence_ids=list(ids), planning_basis=basis, quote=quote)


def rule_claim(eid="E3") -> Claim:
    """A general planning rule in the structured form: HABITA's text is the official passage itself."""
    return claim(PDM_QUOTE, eid, basis="general_rule", quote=PDM_QUOTE)


SECTIONS = ("conclusion", "claim", "procedure", "risk", "next action")
LABELS = {"conclusion": "conclusion", "claim": "K1", "procedure": "procedure 1", "risk": "risk 1",
          "next action": "next action 1"}


def in_section(section: str, text: str, ids: list[str], basis="none", quote=None, step="Next step"):
    """A draft whose ``section`` holds the statement (the other sections stay empty or neutral)."""
    common = {"evidence_ids": ids, "planning_basis": basis, "quote": quote}
    planning_condition = [Condition(item_key="planning_constraints", text=CONDITION_TEXT)]
    if section == "conclusion":
        return draft(claim("t", "E1"), conclusion=Conclusion(answer="conditional", summary=text, **common),
                     conditions=planning_condition)
    neutral = Conclusion(answer="conditional", summary="s", evidence_ids=["E1"])
    sections = {"claim": {"claims": None}, "procedure": {"procedure": [ProcedureStep(step=step, description=text, **common)]},
                "risk": {"risks": [Risk(text=text, **common)]},
                "next action": {"next_actions": [NextAction(text=text, **common)]}}[section]
    if section == "claim":
        return draft(Claim(claim_id="K1", text=text, **common), conclusion=neutral, conditions=planning_condition)
    return draft(claim("t", "E1"), conclusion=neutral, conditions=planning_condition, **sections)


CENTRAL = {"label": "Espaço central histórico", "land_class": "Solo urbano", "category": "Espaço central histórico"}
TRUSTED = MutableTrust("pt-rjue", "pt-codigo-civil-propriedade-horizontal", "cascais-pdm", "cascais-urbanismo-faq")
#: Everything a manual-state Cascais matter can cite: general law, PDM text, FAQ, user facts, authority, manual context.
MANUAL_RECORDS = [rjue("E1"), planning("E2"), official("E3"), faq("E5"), civil("E7"), user("E8"), authority("E9")]
CITATION_SETS = [["E1"], ["E3"], ["E5"], ["E7"], ["E8"], ["E9"], ["E2"], ["E1", "E7", "E8", "E9"]]


async def verify(d, records=MANUAL_RECORDS, reviewer=None, planning_state=None):
    async def state(_matter):
        return planning_state
    return await Verifier(reviewer or Reviewer(VERIFIED), TRUSTED, state).verify(matter(), checklist(), d, records, CHAIN)


def resolved_state(label="Espaço central histórico"):
    return SimpleNamespace(status="resolved", classification=SimpleNamespace(label=label))


# --- CX-1: parcel planning statements ------------------------------------------------------------

ADVERSARIAL = [
    # The owner's cases.
    "This site sits within an area intended for residential development.",
    "The land here is governed by the residential development provisions.",
    "For this address, the applicable spatial regime is the one intended for housing.",
    "Este prédio encontra-se numa área destinada predominantemente a habitação.",
    "Neste local aplicam-se as regras urbanísticas previstas para áreas residenciais.",
    "Para este imóvel, o regime territorial aplicável admite uso habitacional.",
    # Semantically varied, avoiding planning vocabulary where possible.
    "Each floor of this building may serve as a home under the norms for its part of town.",
    "Its permitted function is dwellings, as for the rest of the street.",
    "Two flats per floor are what the local norms for this street allow.",
    "The house stands where living use is the expected purpose.",
    "Given its location, a second dwelling is in line with what the municipality foresees there.",
    "A casa fica num sítio onde morar é a função prevista.",
    "O edifício está numa parte da vila onde só se admitem casas.",
    "Pela sua localização, o imóvel pode ter dois fogos.",
    "Each floor has its own street door, as the rules for this location require.",
    "You state each floor has its own street door, which is allowed here.",
]


async def test_codex_scenario_zoning_claim_with_manual_context_and_trusted_law_is_rejected():
    reviewer = Reviewer(VERIFIED)
    d = draft(claim("This parcel is zoned Espaços centrais.", "E1"), conditions=PLANNING_CONDITION)
    report = await verify(d, reviewer=reviewer)
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)
    assert reviewer.calls == 0  # rejected by code before any model review


@pytest.mark.parametrize("text", ADVERSARIAL)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("cites", CITATION_SETS, ids="+".join)
async def test_free_text_planning_paraphrases_never_verify(text, section, cites):
    """Free text (basis none), whatever it cites, with a reviewer that approves everything and flags nothing."""
    report = await verify(in_section(section, text, cites))
    assert report.outcome != "VERIFIED", (section, text, cites)
    assert "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("text", ADVERSARIAL[:6])
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("basis", ["general_rule", "authority_confirmation", "parcel_determination"])
async def test_a_structured_basis_cannot_carry_model_wording(text, section, basis):
    """Declaring a structured basis but keeping its own words (or a quote that isn't verbatim) fails closed."""
    quote = text if basis == "general_rule" else None
    report = await verify(in_section(section, text, ["E1", "E2", "E3"], basis=basis, quote=quote))
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues), (section, basis)


@pytest.mark.parametrize("section", SECTIONS)
async def test_rendering_replaces_model_wording_with_habita_content(section):
    """The structured bases are rendered by HABITA: the paraphrase disappears; what verifies is HABITA's text."""
    paraphrase = ADVERSARIAL[0]
    for basis, ids, quote, expected in (
        ("general_rule", ["E3"], PDM_QUOTE, PDM_QUOTE),
        ("authority_confirmation", ["E2"], None, CONDITION_TEXT),
    ):
        rendered = render_draft(in_section(section, paraphrase, ids, basis=basis, quote=quote), MANUAL_RECORDS, matter())
        st = next(s for s in model_statements(rendered) if s.label == LABELS[section])
        assert st.text == expected and paraphrase not in st.display
        if section == "procedure":
            assert st.step == RENDERED_STEP[basis]
        report = await verify(rendered)
        assert report.outcome == "VERIFIED", (section, basis, report.issues)


@pytest.mark.parametrize("section", SECTIONS)
async def test_positive_control_a_genuine_parcel_determination_verifies(section):
    determination = planning("E4", status="resolved", classification=CENTRAL)
    records = [*MANUAL_RECORDS, determination]
    d = render_draft(in_section(section, ADVERSARIAL[0], ["E4"], basis="parcel_determination"), records, matter())
    st = next(s for s in model_statements(d) if s.label == LABELS[section])
    assert st.text == render_determination(determination) and "Espaço central histórico" in st.text
    review = {**VERIFIED, "parcel_planning_statements": [LABELS[section]]}
    report = await verify(d, records, Reviewer(review), resolved_state())
    assert report.outcome == "VERIFIED", report.issues
    assert report.checks["zoning_supported"] and report.checks["final_gate_passed"]


@pytest.mark.parametrize("state", [None, SimpleNamespace(status="requires_manual_confirmation", classification=None),
                                   resolved_state("Espaços habitacionais")], ids=["no-resolver", "manual", "different"])
async def test_a_determination_the_current_resolver_does_not_confirm_fails_closed(state):
    determination = planning("E4", status="resolved", classification=CENTRAL)
    records = [*MANUAL_RECORDS, determination]
    d = render_draft(in_section("claim", "x", ["E4"], basis="parcel_determination"), records, matter())
    report = await verify(d, records, planning_state=state)
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("record_", [
    planning("E4", status="resolved", classification=CENTRAL, property_id="prp_ffffffffffffffff"),  # other property
    planning("E4", status="resolved", classification=CENTRAL, source="cascais-geocascais"),  # untrusted source
    planning("E4"),  # manual, not a determination
], ids=["other-property", "untrusted", "manual"])
async def test_determinations_must_be_applicable_and_trusted(record_):
    records = [*MANUAL_RECORDS, record_]
    d = render_draft(in_section("claim", "x", ["E4"], basis="parcel_determination"), records, matter())
    report = await verify(d, records, planning_state=resolved_state())
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


async def test_free_text_citing_planning_evidence_is_rejected():
    report = await verify(in_section("claim", "A second dwelling may be possible.", ["E2"]))
    assert "unverified_zoning" in codes(report.issues)


async def test_the_reviewer_flag_is_enforced_by_code():
    review = {**VERIFIED, "parcel_planning_statements": ["K1"]}
    report = await verify(in_section("claim", "The Câmara Municipal de Cascais is the competent authority.", ["E9"]),
                          reviewer=Reviewer(review))
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("text, cites", [
    ("The Câmara Municipal de Cascais is the competent authority.", ["E9"]),
    ("Each new unit must be autonomous with its own exit.", ["E7"]),
    ("You state each floor has its own street door.", ["E8"]),
    ("Confirm the conditions with the Câmara Municipal de Cascais before you apply.", ["E9"]),
    ("Confirm with the Câmara whether the works need a licence or prior communication.", ["E1"]),
])
@pytest.mark.parametrize("section", SECTIONS)
async def test_grounded_non_planning_statements_verify(text, cites, section):
    # Rendered first: the user's answer (E8) is shown verbatim as their declaration — a finding only (HR-003 MU-3);
    # the conclusion, procedure, risks and next actions can't rest on the user's answers alone.
    report = await verify(render_draft(in_section(section, text, cites, step="Apply"), MANUAL_RECORDS, matter()))
    expected = "REJECTED" if cites == ["E8"] and section != "claim" else "VERIFIED"
    assert report.outcome == expected, (section, report.issues)


@pytest.mark.parametrize("text", [
    "Building works and alterations need municipal prior control under the RJUE.",
    "A licence or prior communication may be required, depending on the operation.",
])
@pytest.mark.parametrize("section", SECTIONS)
async def test_a_legal_requirement_resting_on_a_curated_summary_is_not_verified(text, section):
    """MU-9 (C1): a curated summary is context only, and a paraphrase of a legal requirement needs an official passage
    that supports it in the direction stated. Until 98af6af these verified with the curated RJUE (E1) alone."""
    report = await verify(render_draft(in_section(section, text, ["E1"], step="Apply"), MANUAL_RECORDS, matter()))
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


def test_the_property_address_is_a_case_fact_not_a_zone():
    prop = record("E6", "property_record", "Praça 5 de Outubro, Centro Historico, 2750-427 Cascais, Portugal",
                  status="system_record", title="HABITA property record")
    issues, _ = rule_checks(matter(), checklist(), draft(claim("The property is at Praça 5 de Outubro, Cascais.", "E6")),
                            [*MANUAL_RECORDS, prop], CHAIN, TRUSTED.ids)
    assert "unverified_zoning" not in codes(issues)


def test_a_paraphrase_draft_never_reaches_verified_in_the_cascais_workflow():
    def paraphrasing(payload):
        d = default_draft(payload)
        d["claims"].append({"text": "This site sits within an area intended for residential development.",
                            "evidence_ids": d["claims"][0]["evidence_ids"], "planning_basis": "none", "quote": None})
        return d

    with make_client(ScriptedModel(draft=paraphrasing)) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
        report = client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
    assert state == "REJECTED" and "unverified_zoning" in {i["code"] for i in report["issues"]}


def test_a_persisted_verified_cascais_draft_contains_no_model_authored_planning():
    """Manual state: what is persisted as VERIFIED is grounded free text plus HABITA-rendered planning content."""
    def disguised(payload):
        d = default_draft(payload)
        # The model tries to smuggle a paraphrase through a structured basis; HABITA replaces the wording.
        d["next_actions"].append({"text": "This site sits within an area intended for residential development.",
                                  "evidence_ids": [e["id"] for e in payload["evidence"] if e["type"] == "planning_context"],
                                  "planning_basis": "authority_confirmation", "quote": None})
        return d

    with make_client(ScriptedModel(draft=disguised)) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        persisted = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
    assert persisted["state"] == "VERIFIED"
    texts = [persisted["draft"]["conclusion"]["summary"]] + [s.get("text") or s.get("description") for section in
             ("claims", "procedure", "risks", "next_actions") for s in persisted["draft"][section]]
    assert not any("residential development" in t for t in texts)
    planning_condition = next(c["text"] for c in persisted["draft"]["conditions"] if c["item_key"] == "planning_constraints")
    rendered = [a for a in persisted["draft"]["next_actions"] if a["planning_basis"] == "authority_confirmation"]
    assert rendered and all(a["text"] == planning_condition and "Planta de Ordenamento 01-02" in a["text"] for a in rendered)


# --- CX-2: current admissibility ------------------------------------------------------------------


async def test_trusted_then_retired_then_restored():
    """1 + 2: evidence created while trusted; retired → not VERIFIED; restored → usable again."""
    trust = MutableTrust("pt-rjue", "cascais-pdm")
    c = checklist(item("jurisdiction"), item("planning_constraints", status="blocked_external", owner="AUTHORITY"))
    d = draft(rule_claim("E3"), conditions=PLANNING_CONDITION,
              conclusion=Conclusion(answer="conditional", summary="Possible, subject to the conditions.",
                                    evidence_ids=["E1"]))
    records = [ev("E1"), official("E3")]
    assert (await Verifier(Reviewer(VERIFIED), trust).verify(matter(), c, d, records, CHAIN)).outcome == "VERIFIED"

    trust.ids.discard("cascais-pdm")
    retired = await Verifier(Reviewer(VERIFIED), trust).verify(matter(), c, d, records, CHAIN)
    assert retired.outcome == "REJECTED" and "untrusted_source" in codes(retired.issues)
    assert {"evidence_id": "E3", "reason": "comes from cascais-pdm, which is not currently a trusted official source "
            "for this jurisdiction"} in retired.excluded_evidence

    trust.ids.add("cascais-pdm")
    restored = await Verifier(Reviewer(VERIFIED), trust).verify(matter(), c, d, records, CHAIN)
    assert restored.outcome == "VERIFIED" and restored.excluded_evidence == []


async def test_mixed_trusted_and_retired_support():
    """3: an item keeps its trusted support; only citations of the retired record fail."""
    trust = MutableTrust("pt-rjue")  # cascais-pdm retired
    mixed = item("licensing_procedure").model_copy(update={"evidence_ids": ["E1", "E3"]})
    c = checklist(item("jurisdiction"), mixed)
    issues, checks = rule_checks(matter(), c, draft(), [ev("E1"), official("E3")], CHAIN, trust.ids)
    assert "inadmissible_support" not in codes(issues) and checks["support_admissible"]
    report = await Verifier(Reviewer(VERIFIED), trust).verify(matter(), c, draft(), [ev("E1"), official("E3")], CHAIN)
    assert report.outcome == "VERIFIED"
    cites_retired = draft(claim("Article 61.º applies.", "E1", "E3"))
    issues, _ = rule_checks(matter(), c, cites_retired, [ev("E1"), official("E3")], CHAIN, trust.ids)
    assert "untrusted_source" in codes(issues)


async def test_codex_scenario_item_supported_only_by_retired_evidence_is_not_verified():
    """4: a required item satisfied solely by a retired source; the draft cites another trusted record."""
    reviewer = Reviewer(VERIFIED)
    trust = MutableTrust("pt-rjue")  # cascais-pdm retired
    only_retired = item("licensing_procedure").model_copy(update={"evidence_ids": ["E3"]})
    report = await Verifier(reviewer, trust).verify(
        matter(), checklist(item("jurisdiction"), only_retired), draft(), [ev("E1"), official("E3")], CHAIN)
    assert report.outcome == "ESCALATE" and "inadmissible_support" in codes(report.issues)
    assert report.checks["support_admissible"] is False and report.checks["no_evidence_gaps"] is False
    assert reviewer.calls == 0


async def test_conclusion_citing_retired_evidence_is_rejected():
    """5."""
    trust = MutableTrust("pt-rjue")
    d = draft(conclusion=Conclusion(answer="conditional", summary="Conditional on the PDM.", evidence_ids=["E1", "E3"]))
    report = await Verifier(Reviewer(VERIFIED), trust).verify(matter(), checklist(), d, [ev("E1"), official("E3")], CHAIN)
    assert report.outcome == "REJECTED" and "untrusted_source" in codes(report.issues)


def test_reconciliation_ignores_retired_evidence_and_restoring_brings_it_back():
    """Workflow level: a source retired between investigation and verification can't satisfy an item."""
    with make_client(ScriptedModel()) as client:
        registry = client.app.state.official_sources
        model = client.app.state.permit_workflow._model

        def retire_during_draft(payload):
            # Retirement lands after the investigation, right before verification (in-memory store).
            registry.repository.sources["pt-codigo-civil-propriedade-horizontal"].status = "retired"
            return default_draft(payload)

        model.draft = retire_during_draft
        mid, token = run_matter(client)
        items = {i["key"]: i for i in client.get(f"/api/permit/matters/{mid}/checklist", headers=auth(token)).json()["items"]}
        reports = client.app.state.permit_workflow._repo.verifications[mid]
        assert items["unit_conversion"]["status"] == "open"  # its only sources (Código Civil) are retired
        assert all(r.outcome != "VERIFIED" for r in reports)
        assert any("unit_conversion" in r.unresolved for r in reports)
        history = client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
        assert any((e.get("provenance") or {}).get("source_id") == "pt-codigo-civil-propriedade-horizontal" for e in history)

        # Restored through the operator lifecycle: the source supports new assessments again.
        for status in ("candidate", "validated", "trusted"):
            client.portal.call(lambda s=status: registry.change_status(
                "pt-codigo-civil-propriedade-horizontal", s, operator="ops", reason="restored after review"))
        model.draft = default_draft
        mid2, token2 = run_matter(client)
        assert client.get(f"/api/permit/matters/{mid2}", headers=auth(token2)).json()["state"] == "VERIFIED"


# --- CX-2: trust changes while verification is running (the Codex race) ------------------------------


class RetiringTrust(MutableTrust):
    """Trusted on the verifier's first read, retired from then on (a retirement during rule checking)."""

    def __init__(self, retire: str, *ids: str) -> None:
        super().__init__(retire, *ids)
        self.retire, self.reads = retire, 0

    async def trusted_ids(self, chain):
        self.reads += 1
        current = set(self.ids)
        self.ids.discard(self.retire)
        return current


class RetiringReviewer(Reviewer):
    """Approves, but the source is retired while it is reviewing (the exact Codex sequence)."""

    def __init__(self, trust: MutableTrust, source: str) -> None:
        super().__init__(VERIFIED)
        self.trust, self.source = trust, source

    async def chat(self, messages, **kwargs):
        self.trust.ids.discard(self.source)
        return await super().chat(messages, **kwargs)


def relying_on_pdm():
    c = checklist(item("jurisdiction"), item("licensing_procedure").model_copy(update={"evidence_ids": ["E3"]}))
    d = draft(rule_claim("E3"),
              conclusion=Conclusion(answer="conditional", summary="Conditional.", evidence_ids=["E1"]))
    return c, d, [ev("E1"), official("E3")]


async def test_retired_during_verifier_execution_is_not_verified():
    trust = RetiringTrust("cascais-pdm", "pt-rjue")
    c, d, records = relying_on_pdm()
    report = await Verifier(Reviewer(VERIFIED), trust).verify(matter(), c, d, records, CHAIN)
    assert trust.reads == 2  # initial rules, then the final gate
    assert report.outcome != "VERIFIED" and report.checks["final_gate_passed"] is False
    assert {"untrusted_source", "inadmissible_support"} <= codes(report.issues)
    assert any(x["evidence_id"] == "E3" for x in report.excluded_evidence)


async def test_retired_during_model_review_is_not_verified():
    trust = MutableTrust("pt-rjue", "cascais-pdm")
    reviewer = RetiringReviewer(trust, "cascais-pdm")
    c, d, records = relying_on_pdm()
    report = await Verifier(reviewer, trust).verify(matter(), c, d, records, CHAIN)
    assert reviewer.calls == 1 and report.model_review["outcome"] == "VERIFIED"  # the stale approval
    assert report.outcome == "REJECTED" and report.checks["final_gate_passed"] is False
    assert all(i.message.startswith("Final check: ") for i in report.issues if i.code == "untrusted_source")


async def test_an_unaffected_retirement_during_review_still_verifies():
    trust = MutableTrust("pt-rjue", "cascais-pdm", "pt-rgeu")
    c, d, records = relying_on_pdm()
    report = await Verifier(RetiringReviewer(trust, "pt-rgeu"), trust).verify(matter(), c, d, records, CHAIN)
    assert report.outcome == "VERIFIED" and report.checks["final_gate_passed"]


def test_workflow_race_source_retired_while_the_reviewer_approves():
    """trusted source → evidence created → model review begins → source retired → reviewer approves."""
    retired = "pt-codigo-civil-propriedade-horizontal"
    with make_client(ScriptedModel()) as client:
        registry = client.app.state.official_sources

        def approve_while_retiring(payload):
            registry.repository.sources[retired].status = "retired"
            return VERIFIED

        client.app.state.permit_workflow._model.verification = approve_while_retiring
        mid, token = run_matter(client)
        final = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        reports = client.app.state.permit_workflow._repo.verifications[mid]
        history = client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
    assert final["state"] != "VERIFIED"
    first = reports[0]
    assert first.model_review["outcome"] == "VERIFIED" and first.outcome != "VERIFIED"
    assert first.checks["final_gate_passed"] is False
    # Historical records stay visible, and are reported as inadmissible rather than deleted.
    kept = {e["evidence_id"] for e in history if (e.get("provenance") or {}).get("source_id") == retired}
    assert kept and kept <= {x["evidence_id"] for x in reports[-1].excluded_evidence}


# --- CX-1 (live false positive): general planning explanations vs parcel-specific determinations ------------------
# What makes a statement a parcel determination is that it is about this property (a subject), not its vocabulary:
# the same words ("urbano", "urbanístico", "habitação", "district", "zone") pass in a general explanation and fail
# in a statement about the parcel, unless an authoritative, admissible parcel determination backs it.

ADDRESS = record("E6", "property_record", "Praça 5 de Outubro, Centro Historico, 2750-427 Cascais, Portugal",
                 status="system_record", title="HABITA property record",
                 structured={"formatted_address": "Praça 5 de Outubro, Centro Historico, 2750-427 Cascais, Portugal"})
JURISDICTION = record("E10", "jurisdiction_record", "Country: Portugal → District: Lisboa → Municipality: Cascais",
                      status="system_record", title="HABITA jurisdiction resolution",
                      structured={"levels": [{"name": "Portugal"}, {"name": "Lisboa"}, {"name": "Cascais"}]})
CASE_RECORDS = [*MANUAL_RECORDS, ADDRESS, JURISDICTION]
#: A general planning explanation's normative part needs admissible official text (E3: PDM passage); curated
#: references (E1 RJUE, E5 FAQ summary, E7 Código Civil) may accompany it.
REGULATORY_SETS = [["E3"], ["E3", "E1"], ["E3", "E5"], ["E1", "E3", "E7"]]

GENERAL_EXPLANATIONS = [
    "The PDM classifies and qualifies municipal land.",
    "Urban parameters must be checked against the applicable plan.",
    "Housing use may depend on the applicable plan.",
    "Each zone or district defined by a municipal plan has specific land-use rules.",
    PDM_SENTENCE,
    "O PDM classifica e qualifica o solo do município.",
    "Os parâmetros urbanísticos têm de ser verificados no plano aplicável.",
    "O uso habitacional pode depender da categoria de espaço definida no plano.",
    "Em solo urbano, cada zona ou distrito segue as regras do plano municipal.",
    "A habitação em solo urbano depende das regras urbanísticas aplicáveis.",
]
PARCEL_ASSERTIONS = [
    "This parcel is classified as urban residential.",
    "The property lies in an urban housing category.",
    "This parcel is within district Y of the urban zone.",
    "The site falls in the zone where housing is admitted.",
    "Housing is admitted here under the urban zone rules.",
    "Your plot is in the residential district.",
    "Este imóvel está classificado como solo urbano habitacional.",
    "A parcela insere-se numa zona urbanística de habitação.",
    "O lote situa-se no distrito urbano Y.",
    "Neste local, o uso habitacional é o previsto no plano.",
    "Esta zona é de habitação, segundo o PDM.",
    # The property's own place name (or its cognate) next to a general rule makes it about this place.
    "In the Centro Histórico, urban land is a central space for housing.",
    "Properties in the historic centre are zoned for housing.",
    # Codex's map-based paraphrases.
    "The council's map shows this property in the blue band for housing.",
    "A carta municipal assinala este lote na faixa azul, onde são admitidas duas habitações.",
]


async def rendered_verify(d, records=CASE_RECORDS, reviewer=None, planning_state=None):
    """The production path: HABITA renders the draft, then the verifier (and its final gate) checks it."""
    return await verify(render_draft(d, records, matter()), records, reviewer, planning_state)


def statement(d, section):
    return next(s for s in model_statements(d) if s.label == LABELS[section])


@pytest.mark.parametrize("basis", ["general_planning_explanation", "none"])
@pytest.mark.parametrize("cites", REGULATORY_SETS, ids="+".join)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", GENERAL_EXPLANATIONS)
async def test_general_planning_explanations_are_not_rejected_for_their_vocabulary(text, section, cites, basis):
    """Declared, or written as free text and reclassified by HABITA: verified, framed as not about this property."""
    d = render_draft(in_section(section, text, cites, basis=basis, step="Background"), CASE_RECORDS, matter())
    st = statement(d, section)
    assert st.planning_basis == "general_planning_explanation"
    assert st.text.startswith(EXPLANATION_FRAME) and st.text.endswith(text)
    report = await verify(d, CASE_RECORDS)
    assert report.outcome == "VERIFIED", (section, text, report.issues)
    assert report.checks["zoning_supported"] and report.checks["final_gate_passed"]


@pytest.mark.parametrize("basis", ["general_planning_explanation", "none"])
@pytest.mark.parametrize("cites", REGULATORY_SETS, ids="+".join)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", PARCEL_ASSERTIONS)
async def test_parcel_assertions_without_a_determination_are_rejected(text, section, cites, basis):
    """Same vocabulary, but about this property: rejected by code with an approving, non-flagging reviewer."""
    report = await rendered_verify(in_section(section, text, cites, basis=basis))
    assert report.outcome == "REJECTED", (section, text, cites)
    assert "unverified_zoning" in codes(report.issues) and not report.checks["zoning_supported"]


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", PARCEL_ASSERTIONS[:11])
async def test_a_parcel_assertion_with_a_trusted_admissible_determination_proceeds(text, section):
    """With an authoritative determination the statement proceeds, as HABITA's rendering of the determination."""
    determination = planning("E4", status="resolved", classification=CENTRAL)
    records = [*CASE_RECORDS, determination]
    d = render_draft(in_section(section, text, ["E4"], basis="parcel_determination"), records, matter())
    assert statement(d, section).text == render_determination(determination)
    review = {**VERIFIED, "parcel_planning_statements": [LABELS[section]]}
    report = await verify(d, records, Reviewer(review), resolved_state())
    assert report.outcome == "VERIFIED", report.issues
    # ...but the model's own parcel wording, without the structured basis, still can't ride on it.
    report = await rendered_verify(in_section(section, text, ["E3", "E4"], basis="general_planning_explanation"),
                                   records, planning_state=resolved_state())
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", [
    "Housing may be admissible, depending on the land category set by the plan.",
    "A second dwelling may depend on the urban zone and its parameters.",
    "A habitação pode ser admissível consoante a categoria de solo definida no plano.",
])
async def test_ambiguous_general_wording_stays_conditional_never_parcel_zoning(text, section):
    """Hedged, subject-less wording passes only as a framed general explanation: the matter stays conditional, the
    planning condition stays, and nothing becomes a parcel classification."""
    d = render_draft(in_section(section, text, ["E3"]), CASE_RECORDS, matter())
    st = statement(d, section)
    assert st.planning_basis == "general_planning_explanation" and st.text.startswith(EXPLANATION_FRAME)
    report = await verify(d, CASE_RECORDS)
    assert report.outcome == "VERIFIED", report.issues
    assert d.conclusion.answer == "conditional" and planning_condition(d.conditions) == CONDITION_TEXT
    assert not any(s.planning_basis == "parcel_determination" for s in model_statements(d))


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", [
    "The property may fall within an urban housing category.",
    "This plot is probably in a residential zone.",
    "O imóvel poderá estar numa zona habitacional.",
    "Provavelmente, este lote está em solo urbano.",
])
async def test_ambiguous_wording_about_the_property_is_rejected(text, section):
    report = await rendered_verify(in_section(section, text, ["E3"]))
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("cites", [["E2"], ["E8"], ["E6"], ["E9"], ["E3", "E2"], []], ids=str)
async def test_a_general_explanation_needs_regulatory_support_and_never_the_planning_context(cites):
    """Without an admissible regulatory record (only user facts, the property, the authority), or citing the
    planning context: rejected. (Case records alongside regulatory support are fine: see the B cases below.)"""
    report = await rendered_verify(in_section("claim", GENERAL_EXPLANATIONS[2], cites,
                                              basis="general_planning_explanation"))
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


async def test_an_unframed_general_explanation_is_not_certified():
    """The final gate accepts an explanation only in HABITA's frame (a draft that skipped rendering fails)."""
    report = await verify(in_section("claim", GENERAL_EXPLANATIONS[0], ["E3"], basis="general_planning_explanation"),
                          CASE_RECORDS)
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


async def test_the_reviewer_flag_also_binds_general_explanations():
    review = {**VERIFIED, "parcel_planning_statements": ["K1"]}
    report = await rendered_verify(in_section("claim", GENERAL_EXPLANATIONS[2], ["E3"]), reviewer=Reviewer(review))
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


def test_the_cascais_workflow_verifies_a_general_explanation_but_not_a_parcel_assertion():
    """End to end (manual planning context): general PDM prose verifies, framed; the parcel version is rejected."""
    def with_statement(text):
        def drafting(payload):
            d = default_draft(payload)
            regulatory = [e["id"] for e in payload["evidence"] if e["type"] == "regulatory_source"]
            d["claims"].append({"text": text, "evidence_ids": regulatory, "planning_basis": "none", "quote": None})
            return d
        return drafting

    general = "The PDM classifies and qualifies municipal land; urban parameters must be checked."
    with make_client(ScriptedModel(draft=with_statement(general))) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        persisted = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        evidence = client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
    assert persisted["state"] == "VERIFIED"
    assert EXPLANATION_FRAME + general in [c["text"] for c in persisted["draft"]["claims"]]
    assert [e["structured"]["status"] for e in evidence if e["source_type"] == "planning_context"] == \
        ["requires_manual_confirmation"]

    with make_client(ScriptedModel(draft=with_statement("This parcel is classified as urban residential."))) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
    assert state == "REJECTED"


@pytest.mark.parametrize("text", ADVERSARIAL + PARCEL_ASSERTIONS[-2:])
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("cites", CITATION_SETS, ids="+".join)
async def test_reclassification_opens_no_path_for_the_earlier_paraphrases(text, section, cites):
    """The earlier adversarial matrix, through HABITA's rendering (where free planning prose becomes an explanation)."""
    report = await rendered_verify(in_section(section, text, cites))
    assert report.outcome != "VERIFIED", (section, text, cites)
    assert "unverified_zoning" in codes(report.issues)


# --- CX-1 (second live false positive): the normative part needs regulatory support; case facts may accompany it;
# only an attribution of planning content to the property makes a statement parcel-specific ---------------------

# A. General explanation + official source; E. the same vocabulary is not, by itself, a reason to reject.
GENERAL_A_E = [
    PDM_SENTENCE,
    "Zoning in a municipal plan sets which uses each district or zone admits.",
    "Housing use in urban land may depend on the urban parameters of the applicable plan.",
    PDM_SENTENCE.rstrip("."),
    "O zonamento do plano municipal define os usos admitidos em cada distrito ou zona urbanística.",
    "A habitação em solo urbano depende dos parâmetros urbanísticos do plano aplicável.",
]
# A restatement of PDM_TEXT in other words (translated, reordered, abridged, attributed) is quote-only: its words can
# be checked, not their roles (owner decision after ACC-QO-09 / ACC-ROLE-01).
RESTATEMENTS = [
    "Urban land is intended mainly for building, including housing, commerce and services.",
    "Under the PDM, urban land is intended mainly for building, including housing, commerce and services.",
    "Segundo o PDM, em solo urbano os espaços destinam-se sobretudo à urbanização e à habitação.",
    "Under the PDM, urban land is intended mainly for housing.",
    "Under the PDM, urban land is intended mainly for urbanisation and building, including housing.",
    "Segundo o PDM, o solo urbano destina-se predominantemente à urbanização e edificação.",
]


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", RESTATEMENTS)
async def test_a_restatement_of_an_official_sentence_is_quote_only(text, section):
    report = await rendered_verify(in_section(section, text, ["E3"], basis="general_planning_explanation"))
    assert report.outcome != "VERIFIED" and "unsupported_legal_claim" in codes(report.issues), report.issues


# B. General explanation + the property's facts (as context) + official source: (text, cited ids).
GENERAL_WITH_FACTS_B = [
    ("The property is at Praça 5 de Outubro, Cascais. " + PDM_SENTENCE, ["E6", "E3"]),
    # The user's answer may accompany the rule as context (HR-003 MU-3: never restated in HABITA's voice).
    ("Housing use may depend on the urban parameters of the plan.", ["E8", "E3"]),
    ("The parcel's planning classification must be confirmed; zoning rules set the uses each district admits.",
     ["E6", "E3"]),
    ("O imóvel fica na Praça 5 de Outubro, em Cascais. Em solo urbano, a habitação depende dos parâmetros do plano.",
     ["E6", "E3"]),
    ("A classificação deste lote deve ser confirmada pela Câmara; o zonamento define os usos de cada zona.",
     ["E9", "E3"]),
]
# C / D. Parcel-specific, without a parcel determination (also when mixed with a valid general explanation).
PARCEL_C_D = [
    "This parcel is urban residential.",
    "This property lies in an urban housing zone.",
    "The applicable zoning category for this parcel is X.",
    "According to the PDM, this property belongs to urban housing zone X.",
    "Under the PDM, urban land is intended for housing, and this parcel is urban residential.",
    "The property is at Praça 5 de Outubro. It is in the urban housing district.",
    "This property is in the blue band. Under the PDM, blue-band land admits two dwellings.",
    "Esta parcela é urbana residencial.",
    "Segundo o PDM, este imóvel pertence à zona habitacional urbana X.",
    "A categoria de zonamento aplicável a esta parcela é X.",
    "Em solo urbano a habitação é admitida, e este lote está em solo urbano habitacional.",
    "Se for preciso, este lote insere-se no distrito urbano Y.",
    # Implies which parameters apply to this property (not a deferral).
    "Converting this property into two units depends on the urban parameters of the applicable plan.",
    "A divisão deste imóvel em duas frações depende dos parâmetros urbanísticos do plano aplicável.",
]


@pytest.mark.parametrize("basis", ["general_planning_explanation", "none"])
@pytest.mark.parametrize("cites", REGULATORY_SETS, ids="+".join)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", GENERAL_A_E)
async def test_a_e_general_explanation_with_an_official_source_verifies(text, section, cites, basis):
    report = await rendered_verify(in_section(section, text, cites, basis=basis, step="Background"))
    assert report.outcome == "VERIFIED", (section, text, report.issues)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text, cites", GENERAL_WITH_FACTS_B, ids=lambda x: x if isinstance(x, str) else "")
async def test_b_general_explanation_with_property_facts_and_an_official_source_verifies(text, cites, section):
    d = render_draft(in_section(section, text, cites, step="Background"), CASE_RECORDS, matter())
    assert statement(d, section).planning_basis == "general_planning_explanation"
    report = await verify(d, CASE_RECORDS)
    assert report.outcome == "VERIFIED", (section, text, report.issues)
    assert report.checks["zoning_supported"] and report.checks["final_gate_passed"]


@pytest.mark.parametrize("cites", [["E3"], ["E3", "E6"], ["E3", "E8"], ["E1", "E3", "E6", "E8", "E9"]], ids="+".join)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", PARCEL_C_D)
async def test_c_d_parcel_specific_statements_without_a_determination_are_rejected(text, section, cites):
    """Property records / user facts cited next to the law never make a parcel classification admissible."""
    for basis in ("general_planning_explanation", "none"):
        report = await rendered_verify(in_section(section, text, cites, basis=basis))
        assert report.outcome == "REJECTED", (section, text, cites, basis)
        assert "unverified_zoning" in codes(report.issues) and not report.checks["zoning_supported"]


async def test_mixed_statement_is_rejected_for_the_unsupported_determination_only():
    report = await rendered_verify(in_section("claim", PARCEL_C_D[4], ["E3", "E6"]))
    [issue] = [i for i in report.issues if i.code == "unverified_zoning"]
    assert "states or implies planning content for this property" in issue.message
    assert "this parcel is urban residential" in issue.message


@pytest.mark.parametrize("text, cites, retired", [
    (GENERAL_A_E[0], ["E3"], "cascais-pdm"),
    (GENERAL_WITH_FACTS_B[0][0], ["E6", "E3"], "cascais-pdm"),
    (GENERAL_A_E[3], ["E3", "E8"], "cascais-pdm"),
    (GENERAL_A_E[1], ["E1"], "pt-rjue"),
], ids=["pdm-only", "pdm+property", "pdm+user-pt", "rjue-only"])
async def test_f_retired_or_untrusted_support_is_not_admissible(text, cites, retired):
    """The explanation's only regulatory support is retired: not admissible, so it has no support at all."""
    trust = MutableTrust(*(TRUSTED.ids - {retired}))
    d = render_draft(in_section("claim", text, cites), CASE_RECORDS, matter())
    report = await Verifier(Reviewer(VERIFIED), trust, None).verify(matter(), checklist(), d, CASE_RECORDS, CHAIN)
    assert report.outcome != "VERIFIED"
    assert {"untrusted_source", "unverified_zoning"} <= codes(report.issues)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", PARCEL_C_D[:4] + PARCEL_C_D[7:10])
async def test_g_a_valid_official_parcel_determination_supports_the_category(text, section):
    determination = planning("E4", status="resolved", classification=CENTRAL)
    records = [*CASE_RECORDS, determination]
    d = render_draft(in_section(section, text, ["E4"], basis="parcel_determination"), records, matter())
    assert statement(d, section).text == render_determination(determination)
    review = {**VERIFIED, "parcel_planning_statements": [LABELS[section]]}
    report = await verify(d, records, Reviewer(review), resolved_state())
    assert report.outcome == "VERIFIED", report.issues
    assert report.checks["zoning_supported"] and report.checks["final_gate_passed"]


# --- CX-1 (third live run): regression for the real Muse Spark output -------------------------------------------
# K1-K3 were general planning explanations without admissible official text; K12 and risk 1 turned the general rule
# into a statement about "the land-use category of the parcel". (Reconstructed in EN and PT from the run's report.)

K_GENERAL = [
    "The PDM classifies municipal land and qualifies it into categories of space.",
    "Each land-use category sets the admissible uses and the urban parameters for building.",
    PDM_SENTENCE,
    "O PDM classifica o solo e qualifica-o em categorias de espaço.",
    "Cada categoria de uso do solo define os usos admissíveis e os parâmetros urbanísticos.",
    PDM_SENTENCE.rstrip("."),
]
K_PARCEL = [
    "The land-use category of the parcel conditions the admissible uses and urban parameters.",
    "The land-use category of the parcel determines whether a second dwelling is admissible.",
    "The land-use category of the parcel may not admit a second dwelling.",
    "Given the land-use category of the parcel, the urban parameters for housing apply.",
    "The land-use category of the parcel must be confirmed, but it is urban residential.",
    "A categoria de uso do solo da parcela condiciona os usos admissíveis e os parâmetros urbanísticos.",
    "A categoria de uso do solo desta parcela admite habitação, pelo que são possíveis dois fogos.",
    "A categoria desta parcela deve ser confirmada, mas é solo urbano.",
]
K_CONDITIONAL = [
    "The land-use category applicable to this parcel has not yet been determined by HABITA. It must be confirmed on "
    "the official PDM map or with the Câmara before concluding whether the operation is admissible.",
    "The applicable category for the parcel must be confirmed on the official PDM map before concluding.",
    "The parcel's land-use category is still unknown and must be confirmed with the Câmara.",
    "A categoria de uso do solo aplicável a esta parcela ainda não foi determinada pelo HABITA. Deve ser confirmada "
    "na planta oficial do PDM / junto da Câmara antes de concluir se a operação é admissível.",
    "A categoria aplicável à parcela tem de ser confirmada na planta oficial do PDM.",
    "A categoria de uso do solo desta parcela está por confirmar junto da Câmara.",
    # Instructions to check (next actions / procedure steps) about the parcel's planning.
    "Check whether this parcel is in an urban housing zone before you apply.",
    "Confirm the parcel's land-use category on the official PDM map with the Câmara.",
    "Verifique na planta oficial do PDM a categoria de uso do solo da parcela.",
]


@pytest.mark.parametrize("basis", ["general_planning_explanation", "none"])
@pytest.mark.parametrize("cites", [[], ["E6"], ["E8"], ["E2"], ["E9"], ["E1"], ["E5"], ["E6", "E8", "E9"]], ids=str)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", K_GENERAL)
async def test_k1_k3_general_explanations_without_official_text_are_rejected(text, section, cites, basis):
    """No evidence, or only property / user / planning-context / authority / curated records: rejected."""
    report = await rendered_verify(in_section(section, text, cites, basis=basis))
    assert report.outcome == "REJECTED", (section, text, cites)
    assert "unverified_zoning" in codes(report.issues)


@pytest.mark.parametrize("basis", ["general_planning_explanation", "none"])
@pytest.mark.parametrize("cites", [["E3"], ["E3", "E6"], ["E3", "E8"], ["E3", "E1", "E9"]], ids=str)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", K_GENERAL)
async def test_k1_k3_the_same_explanations_with_trusted_official_text_are_accepted(text, section, cites, basis):
    d = render_draft(in_section(section, text, cites, basis=basis), CASE_RECORDS, matter())
    st = statement(d, section)
    assert st.planning_basis == "general_planning_explanation" and st.text == EXPLANATION_FRAME + text
    report = await verify(d, CASE_RECORDS)
    assert report.outcome == "VERIFIED", (section, text, report.issues)


@pytest.mark.parametrize("basis", ["general_planning_explanation", "none"])
@pytest.mark.parametrize("cites", [["E3"], ["E3", "E2"], ["E2"], ["E3", "E6"]], ids=str)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", K_PARCEL)
async def test_k12_risk_the_parcels_land_use_category_without_a_determination_is_rejected(text, section, cites, basis):
    report = await rendered_verify(in_section(section, text, cites, basis=basis))
    assert report.outcome == "REJECTED", (section, text, cites)
    assert "unverified_zoning" in codes(report.issues) and not report.checks["zoning_supported"]


@pytest.mark.parametrize("basis, cites", [("none", ["E2"]), ("general_planning_explanation", ["E3", "E6"]),
                                          ("none", ["E2", "E3"])], ids=str)
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", K_CONDITIONAL)
async def test_conditional_wording_is_accepted_as_the_condition_not_as_a_determination(text, section, basis, cites):
    """"The applicable category must be confirmed …": shown as HABITA's planning condition, never as model prose."""
    d = render_draft(in_section(section, text, cites, basis=basis), CASE_RECORDS, matter())
    st = statement(d, section)
    assert st.planning_basis == "authority_confirmation" and st.text == CONDITION_TEXT, st
    assert not any(s.planning_basis == "parcel_determination" for s in model_statements(d))
    report = await verify(d, CASE_RECORDS)
    assert report.outcome == "VERIFIED", (section, text, report.issues)
    assert d.conclusion.answer == "conditional"


async def test_without_a_planning_condition_conditional_wording_is_not_promoted():
    """No HABITA condition to show: the deferral stays model wording and needs official support like any explanation."""
    d = in_section("claim", K_CONDITIONAL[2], ["E2"])
    d = render_draft(d.model_copy(update={"conditions": []}), CASE_RECORDS, matter())
    assert statement(d, "claim").planning_basis == "general_planning_explanation"
    report = await verify(d, CASE_RECORDS)
    assert report.outcome == "REJECTED" and "unverified_zoning" in codes(report.issues)


def test_the_cascais_workflow_reproduces_the_live_draft_shape():
    """The live draft's shape end to end: K1 without official text and K12 about the parcel → REJECTED; the corrected
    draft (K1 citing the PDM passage, the parcel's category as a deferral) → VERIFIED conditional, manual planning."""
    def drafting(k1_ids, k12):
        def draft_(payload):
            d = default_draft(payload)
            official = [e["id"] for e in payload["evidence"] if e["basis"] == "official_text"]
            planning_ids = [e["id"] for e in payload["evidence"] if e["type"] == "planning_context"]
            d["claims"].append({"text": K_GENERAL[1], "evidence_ids": k1_ids(official, planning_ids),
                                "planning_basis": "general_planning_explanation", "quote": None})
            d["risks"].append({"text": k12, "evidence_ids": planning_ids, "planning_basis": "none", "quote": None})
            return d
        return draft_

    with make_client(ScriptedModel(draft=drafting(lambda official, planning_ids: planning_ids, K_PARCEL[2]))) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        state = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["state"]
        report = client.get(f"/api/permit/matters/{mid}/verification", headers=auth(token)).json()
    assert state == "REJECTED" and not report["checks"]["zoning_supported"]

    with make_client(ScriptedModel(draft=drafting(lambda official, planning_ids: official, K_CONDITIONAL[0]))) as client:
        ingest_regulamento(client)
        mid, token = run_matter(client)
        persisted = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        evidence = client.get(f"/api/permit/matters/{mid}/evidence", headers=auth(token)).json()
    assert persisted["state"] == "VERIFIED" and persisted["draft"]["conclusion"]["answer"] == "conditional"
    condition = next(c["text"] for c in persisted["draft"]["conditions"] if c["item_key"] == "planning_constraints")
    assert any(r["text"] == condition and r["planning_basis"] == "authority_confirmation"
               for r in persisted["draft"]["risks"])
    assert [e["structured"]["status"] for e in evidence if e["source_type"] == "planning_context"] == \
        ["requires_manual_confirmation"]
