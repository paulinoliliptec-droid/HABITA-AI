"""MU-9 Phase 1: atomic legal claims (``app/services/permit/claims.py``)."""

import pytest

from app.services.permit.admissibility import evidence_capabilities, render_draft
from app.services.permit.claims import CAN_PROVE, KINDS, assess
from app.services.permit.verifier import PROTOCOL, Verifier
from tests.mu9_acceptance import E1, E2, E3, E13, E18, E20, E30, RECORDS
from tests.test_permit_admissibility import SECTIONS, TRUSTED, in_section, record, resolved_state
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, codes, matter

EXPLANATION = "general_planning_explanation"


async def verify(text, cites, section="claim", basis=EXPLANATION):
    d = render_draft(in_section(section, text, cites, basis=basis), RECORDS, matter())

    async def state(_matter):
        return resolved_state() if "E20" in cites else None
    return await Verifier(Reviewer(VERIFIED), TRUSTED, state).verify(matter(), checklist(), d, RECORDS, CHAIN)


# --- the owner's rule: no property legal status from general law, the PDM, the RJUE or a competence record --------

LEGAL_STATUS = [
    "The property has a valid licence.",
    "O imóvel tem licença de utilização.",
    "The works received prior communication approval.",
    "A comunicação prévia do projeto foi aceite.",
    "The site is authorised for two dwellings.",
    "Licensing completed by the Câmara.",
    "The building's licence remains in force.",
    "O imóvel está legal.",
]


@pytest.mark.parametrize("cites", [["E13"], ["E1"], ["E3"], ["E2"], ["E3", "E13"], ["E1", "E3"], ["E20"],
                                   ["E20", "E13"]], ids="+".join)
@pytest.mark.parametrize("basis", [EXPLANATION, "none"])
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text", LEGAL_STATUS)
async def test_no_general_or_competence_source_proves_a_property_legal_status(text, section, basis, cites):
    report = await verify(text, cites, section, basis)
    assert report.outcome == "REJECTED", report.issues


@pytest.mark.parametrize("text", LEGAL_STATUS)
async def test_the_atomic_check_itself_rejects_legal_status_with_the_pdm(text):
    """Not a side effect of another rule: the rejection is the atomic legal-claim check's."""
    report = await verify(text, ["E13"])
    assert "unsupported_legal_claim" in codes(report.issues) and not report.checks["legal_claims_supported"]
    atom = next(a for a in report.claim_atoms if a.verdict == "rejected")
    assert atom.kind in {"legal_status", "unsupported"} and atom.bearer == "matter" and atom.enforced


def test_no_record_type_carries_the_property_legal_status_capability():
    forged = [
        record("F1", "regulatory_source", "Licence issued for this property.", source="cascais-pdm",
               basis="official_text", authority_class="municipal_instrument", status="official_text"),
        record("F2", "authority_record", "Licence issued.", status="system_record"),
        record("F3", "planning_context", "Licensed.", status="user_declared"),
        record("F4", "user_statement", "Licensed.", status="system_record"),
    ]
    for e in [E1, E2, E3, E13, E18, E20, E30, *forged]:
        assert "property_legal_status" not in evidence_capabilities(e), e.evidence_id
    assert {k for ks in CAN_PROVE.values() for k in ks} <= set(KINDS)
    assert [c for c, ks in CAN_PROVE.items() if "legal_status" in ks] == ["property_legal_status"]
    assert CAN_PROVE["rule_summary"] == frozenset()  # curated summaries are context only (C1)


# --- directional support -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, cites", [
    ("Nas operações urbanísticas de edificação, incluindo obras de ampliação e alteração de uso, sujeitas a "
     "licenciamento ou comunicação prévia, deve ser assegurada a dotação de estacionamento.", ["E13"]),  # whole
])
@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_a_rule_in_its_own_wording_verifies(text, cites, section):
    report = await verify(text, cites, section)
    assert report.outcome == "VERIFIED", report.issues
    assert any(a.kind == "general_rule" and a.supported_by == cites for a in report.claim_atoms)


@pytest.mark.parametrize("text", [
    "In urban building operations, including enlargement and change of use, subject to licensing or prior "
    "communication, parking provision must be ensured.",  # translated
    "If the works are an urban building operation subject to licensing or prior communication, parking provision "
    "must be ensured.",  # applied as a condition
    "Nas operações urbanísticas de edificação sujeitas a licenciamento ou comunicação prévia, deve ser assegurada a "
    "dotação de estacionamento.",  # abridged: its inclusion list left out (a whole sentence or nothing)
    "Nas operações urbanísticas de estacionamento sujeitas a licenciamento ou comunicação prévia, deve ser assegurada "
    "a dotação de edificação.",  # ACC-ROLE-01: objects swapped
    "Nas operações urbanísticas de edificação sujeitas a licenciamento ou comunicação prévia, a dotação de "
    "estacionamento deve ser assegurada.",  # reordered
])
@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_a_requirement_in_other_words_is_quote_only(text, section):
    """Owner decision (ACC-QO-09 / ACC-ROLE-01): a normative statement verifies only in the passage's own wording."""
    report = await verify(text, ["E13"], section)
    assert report.outcome == "REJECTED"
    assert any(i.code == "unsupported_legal_claim" for i in report.issues)


@pytest.mark.parametrize("text, cites", [
    ("Urban building operations must ensure parking provision.", ["E13"]),  # the regimes dropped
    ("In urban building operations subject to licensing, parking provision must be ensured.", ["E13"]),  # one branch
    ("In urban building operations subject to licensing or prior communication, parking provision may be ensured.",
     ["E13"]),  # modality changed
    ("In urban building operations subject to licensing or prior communication, parking provision was ensured.",
     ["E13"]),  # tense changed
    ("If the works are an urban building operation subject to licensing or prior communication, the works must "
     "ensure parking provision.", ["E13"]),  # the matter in the consequence
    ("Single-family houses with a construction area of up to 300 m2 may be enlarged by up to 20 % of the existing "
     "area, except classified buildings.", ["E30"]),  # number changed
    ("Single-family houses with a construction area of up to 200 m2 may be enlarged by up to 20 % of the existing "
     "area.", ["E30"]),  # exception dropped
    ("Single-family houses with a construction area of up to 200 m2 may be enlarged by up to 20 % of the existing "
     "area, except classified buildings and listed façades.", ["E30"]),  # exception invented
])
async def test_a_rule_with_a_changed_or_missing_slot_does_not_verify(text, cites):
    report = await verify(text, cites)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


# --- legitimate forms that assert nothing about the matter ---------------------------------------------------------

@pytest.mark.parametrize("text, cites, basis", [
    ("Whether the property is licensed must be confirmed with the Câmara.", ["E13"], EXPLANATION),
    ("O uso licenciado do imóvel deve ser confirmado junto da Câmara.", ["E13"], EXPLANATION),
    ("Confirm with the Câmara whether the works need licensing or prior communication.", ["E13"], EXPLANATION),
    ("The Câmara Municipal de Cascais is competent for licensing of urban operations, including building permits.",
     ["E3"], "none"),
    ("Contact the Câmara Municipal de Cascais about licensing of urban operations including building permits.",
     ["E3"], "none"),
    ("Requirements not confirmed may delay the works.", ["E3"], "none"),
])
async def test_deferrals_recommendations_and_competence_pass_the_atomic_check(text, cites, basis):
    report = await verify(text, cites, basis=basis)
    assert "unsupported_legal_claim" not in codes(report.issues), report.issues


@pytest.mark.parametrize("text", [
    "Confirm with the Câmara that the licence was issued.",
    "The licence is valid and must be confirmed with the Câmara.",
    "Licenciamento confirmado pela Câmara; deve ser verificado junto da Câmara.",
])
async def test_a_deferral_cannot_carry_a_status_claim(text):
    for basis, cites in ((EXPLANATION, ["E13"]), ("none", ["E3"])):
        report = await verify(text, cites, basis=basis)
        assert report.outcome == "REJECTED", (basis, report.issues)


def test_atoms_follow_sentences_and_keep_each_verdict():
    atoms = assess(EXPLANATION_TEXT, EXPLANATION, None, [E13])
    assert [a.kind for a in atoms] == ["general_rule", "legal_status"]
    assert atoms[1].bearer == "matter" and atoms[1].problem


EXPLANATION_TEXT = ("Nas operações urbanísticas de edificação, incluindo obras de ampliação e alteração de uso, "
                    "sujeitas a licenciamento ou comunicação prévia, deve ser "
                    "assegurada a dotação de estacionamento. The property already holds that licence.")


# --- audit and protocol ----------------------------------------------------------------------------------------------

async def test_the_report_records_every_atom_and_the_protocol_and_the_final_gate_recomputes_them():
    report = await verify("Whether the property is licensed must be confirmed with the Câmara.", ["E13"])
    assert report.outcome == "VERIFIED" and report.protocol == PROTOCOL == "atomic-v1"
    assert [(a.kind, a.verdict) for a in report.claim_atoms if a.statement == "K1"] == [("deferral",
                                                                                        "no_support_needed")]
    d = render_draft(in_section("claim", "Whether the property is licensed must be confirmed with the Câmara.",
                                ["E13"], basis=EXPLANATION), RECORDS, matter())
    tampered = report.model_copy(update={"claim_atoms": [], "protocol": "statement-v1"})
    gated = await Verifier(Reviewer(VERIFIED), TRUSTED).final_gate(tampered, matter(), checklist(), d, RECORDS, CHAIN)
    assert gated.protocol == PROTOCOL and gated.claim_atoms == report.claim_atoms


def test_a_report_from_before_mu9_reads_as_statement_v1():
    from app.schemas.permit import VerificationReport
    old = {"verification_id": "v", "matter_id": "m", "draft_revision": 0, "outcome": "VERIFIED", "issues": [],
           "checks": {}, "created_at": "2026-10-01T00:00:00Z"}
    assert VerificationReport.model_validate(old).protocol == "statement-v1"


async def test_a_curated_summary_copied_verbatim_is_not_support_even_beside_official_text():
    """C1: a curated excerpt is context only. Copying it word for word, next to an unrelated official passage that
    satisfies the explanation's citation rule, does not make the legal requirement proven."""
    from tests.test_permit_admissibility import RJUE_TEXT
    report = await verify(RJUE_TEXT, ["E1", "E13"])
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues
    assert all(a.supported_by != ["E1"] for a in report.claim_atoms)


# --- Codex Phase 1 review (2026-10-29, gpt-6-sol): exact cases, reproduced before the fix -----------------------------

PT_RULE = record("E31", "regulatory_source", "Artigo 901.º Regime 1 - A ampliação de moradias está sujeita a "
                 "licenciamento.", source="cascais-pdm", basis="official_text", authority_class="municipal_instrument",
                 status="official_text")


@pytest.mark.parametrize("text, cites, basis, quote", [
    # F1: a deferral carried a licence assertion in a coordinated clause.
    ("The property remains licensed and must be confirmed with the Câmara.", ["E13"], EXPLANATION, None),
    # F2: an unsupported general permission was only a shadow verdict.
    ("In urban land, building operations may proceed.", ["E13"], EXPLANATION, None),
    # F3: concepts compared as a set: "ou" ↔ "e" swapped between the alternatives and the inclusion list…
    ("Nas operações urbanísticas de edificação, incluindo obras de ampliação ou alteração de uso, sujeitas a "
     "licenciamento e comunicação prévia, deve ser assegurada a dotação de estacionamento.", ["E13"], EXPLANATION,
     None),
    # …and the two limits swapped between their units.
    ("Single-family houses with a construction area of up to 20 m2 may be enlarged by up to 200 % of the existing "
     "area, except classified buildings.", ["E30"], EXPLANATION, None),
    # F4: a partial verbatim quote dropped the rule's scope and alternatives.
    ("x", ["E13"], "general_rule", "deve ser assegurada a dotação de estacionamento."),
])
@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_phase1_bypasses_are_rejected(text, cites, basis, quote, section):
    d = render_draft(in_section(section, text, cites, basis=basis, quote=quote), RECORDS, matter())
    report = await Verifier(Reviewer(VERIFIED), TRUSTED).verify(matter(), checklist(), d, RECORDS, CHAIN)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_phase1_false_positive_a_verbatim_pt_rule_with_esta_verifies(section):
    """F8: accent folding read "está" (is) as "esta" (this), so a verbatim rule looked like a claim about the matter."""
    records = [*RECORDS, PT_RULE]
    d = render_draft(in_section(section, "A ampliação de moradias está sujeita a licenciamento.", ["E31"],
                                basis=EXPLANATION), records, matter())
    report = await Verifier(Reviewer(VERIFIED), TRUSTED).verify(matter(), checklist(), d, records, CHAIN)
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    "The PDM classifies and qualifies municipal land.",
    "Each land-use category sets the admissible uses and the urban parameters for building.",
    "Housing use may depend on the applicable plan.",
])
def test_attributive_or_epistemic_permission_wording_stays_a_shadow_verdict(text):
    """F2's fix enforces permissions asserted as the predicate; naming or hedging one is not asserting it."""
    from tests.test_permit_admissibility import official
    atoms = assess(text, EXPLANATION, None, [official("E3")])
    assert atoms and not any(a.enforced and a.problem for a in atoms)


# --- Codex Phase 1 re-review (2026-10-29, gpt-6-sol): exact cases ---------------------------------------------------

@pytest.mark.parametrize("text, cites", [
    # R1: a relative clause before the deferral still asserts the licence.
    ("The property holds a licence, which must be confirmed with the Câmara.", ["E13"]),
    ("The project lacks a permit, which must be confirmed with the Câmara.", ["E13"]),
    ("O imóvel tem licença, que deve ser confirmada junto da Câmara.", ["E13"]),
    # R2: number–unit pairs kept intact but moved to the other limit.
    ("Single-family houses with a construction area up to 20 % of the existing area may be enlarged up to 200 m2, "
     "except classified buildings.", ["E30"]),
])
@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_phase1_rereview_bypasses_are_rejected(text, cites, section):
    report = await verify(text, cites, section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


# --- Codex bounded verification pass (2026-10-29, gpt-6-sol, on d3372dd): exact variants --------------------------

@pytest.mark.parametrize("text, cites", [
    # V1: a pronoun between the clause boundary and the deferral hid the boundary.
    ("The property holds a licence and it must be confirmed with the Câmara.", ["E13"]),
    ("O imóvel tem licença e isso deve ser confirmado junto da Câmara.", ["E13"]),
    # V2: a number's head shared one concept with the passage's but added another.
    ("Single-family houses with a construction area for enlargement up to 20 % of the existing area may be enlarged "
     "up to 200 m2, except classified buildings.", ["E30"]),
])
@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_bounded_pass_variants_are_rejected(text, cites, section):
    report = await verify(text, cites, section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


async def test_boundaries_inside_the_deferred_question_do_not_split_it():
    report = await verify("Whether the works need licensing and parking provision must be confirmed with the Câmara.",
                          ["E13"])
    assert "unsupported_legal_claim" not in codes(report.issues), report.issues


# --- V2 (Codex confirmation pass on c6e3be4): a rule with several numeric limits -----------------------------------

V2B = ("Single-family houses with a construction area for enlargement up to 20 % of the existing area may be enlarged "
       "to a construction area of up to 200 m2, except classified buildings.")


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_a_limit_attached_to_another_quantity_is_rejected(section):
    report = await verify(V2B, ["E30"], section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


E30_SENTENCE = ("Nas moradias unifamiliares com área de construção até 200 m2, é admitida a ampliação até 20 % da área "
                "existente, exceto em edifícios classificados.")


@pytest.mark.parametrize("text", [
    # Owner decision (2026-10-29): a rule with several numeric limits is never admitted as a paraphrase, however
    # faithful: legitimate restatements, reorderings, adjective swaps and the passage's own words outside a quote.
    "Single-family houses with a construction area of up to 200 m2 may be enlarged by up to 20 % of the existing area, "
    "except classified buildings.",
    "Single-family houses with a construction area of up to 200 m2 may be enlarged by a maximum of 20 % of the "
    "existing area, except classified buildings.",
    "Single-family houses may be enlarged by up to 20 % of the existing area if their construction area is up to "
    "200 m2, except classified buildings.",
    "Single-family houses with up to 200 m2 of construction area may be enlarged by up to 20 % of the existing area, "
    "except classified buildings.",
    E30_SENTENCE,
])
@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_a_multi_limit_rule_is_never_admitted_as_a_paraphrase(text, section):
    report = await verify(text, ["E30"], section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


async def test_a_multi_limit_paraphrase_is_told_to_quote_the_rule():
    atoms = assess("Single-family houses with a construction area of up to 200 m2 may be enlarged by up to 20 % of "
                   "the existing area, except classified buildings.", EXPLANATION, None, [E30])
    assert atoms[0].problem and "literal quote" in atoms[0].problem and "general_rule" in atoms[0].problem


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_a_multi_limit_rule_quoted_literally_verifies(section):
    d = render_draft(in_section(section, "x", ["E30"], basis="general_rule", quote=E30_SENTENCE), RECORDS, matter())
    report = await Verifier(Reviewer(VERIFIED), TRUSTED).verify(matter(), checklist(), d, RECORDS, CHAIN)
    assert report.outcome == "VERIFIED", report.issues
    assert [(a.kind, a.bearer, a.supported_by) for a in report.claim_atoms if a.verdict == "supported"] == [
        ("general_rule", "source", ["E30"])]


async def test_a_partial_quote_of_a_multi_limit_rule_does_not_verify():
    partial = "Nas moradias unifamiliares com área de construção até 200 m2, é admitida a ampliação"
    d = render_draft(in_section("claim", "x", ["E30"], basis="general_rule", quote=partial), RECORDS, matter())
    report = await Verifier(Reviewer(VERIFIED), TRUSTED).verify(matter(), checklist(), d, RECORDS, CHAIN)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


async def test_a_pt_generic_definite_plural_is_a_general_scope():
    """L-6, fixed (Codex quote-only round 1, P2): "nas moradias" names a class, not this property."""
    record_ = record("E32", "regulatory_source", "Artigo 902.º Ampliação 1 - Nas moradias unifamiliares é admitida a "
                     "ampliação até 20 % da área existente.", source="cascais-pdm", basis="official_text",
                     authority_class="municipal_instrument", status="official_text")
    records = [*RECORDS, record_]
    d = render_draft(in_section("claim", "Nas moradias unifamiliares é admitida a ampliação até 20 % da área existente.",
                                ["E32"], basis=EXPLANATION), records, matter())
    report = await Verifier(Reviewer(VERIFIED), TRUSTED).verify(matter(), checklist(), d, records, CHAIN)
    assert report.outcome == "VERIFIED"


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_v2_round1_a_limit_moved_onto_the_enlarged_area_is_rejected(section):
    """Codex V2 review, round 1: 200 m2 applied to the area after enlargement instead of the existing area."""
    text = ("Single-family houses whose construction area is enlarged up to 200 m2 may be enlarged by up to 20 % of "
            "the existing area, except classified buildings.")
    report = await verify(text, ["E30"], section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_v2_round2_a_limit_on_the_enlarged_area_is_rejected(section):
    """Codex V2 review, round 2: "enlarged" placed before the limited quantity, outside any fixed window."""
    text = ("Single-family houses whose enlarged construction area is up to 200 m2 may be enlarged by up to 20 % of the "
            "existing area, except classified buildings.")
    report = await verify(text, ["E30"], section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_v2_round3_a_modifier_moved_into_the_exception_is_rejected(section):
    """Codex V2 review, round 3: "existing" moved from the 20 % quantity onto the exception."""
    text = ("Single-family houses with a construction area of up to 200 m2 may be enlarged by up to 20 % of the area, "
            "except existing classified buildings.")
    report = await verify(text, ["E30"], section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


@pytest.mark.parametrize("section", ["claim", "procedure", "risk", "next action"])
async def test_codex_v2_round4_a_target_limit_is_not_an_amount_limit(section):
    """Codex V2 review, round 4: "enlarged to a maximum of 20 %" (resulting size) vs E30's amount of enlargement."""
    text = ("Single-family houses with a construction area of up to 200 m2 may be enlarged to a maximum of 20 % of the "
            "existing area, except classified buildings.")
    report = await verify(text, ["E30"], section)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues
