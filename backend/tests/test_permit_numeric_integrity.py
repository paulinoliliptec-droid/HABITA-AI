"""MU-9 V2 addendum (owner, 2026-10-29): legal and numeric integrity of rules with limits.

Three levels, each verified as it must be:
- a literal transcription (planning_basis general_rule): proves what the source says, nothing about the property;
- a supported general explanation (one sentence of official text, every limit, condition and exception kept;
  only for rules with a single numeric limit);
- an application to this property: never VERIFIED from a general rule (no property-specific evidence exists).

Fixtures are synthetic official passages (TEST FIXTURE); no real Cascais article says this."""

import pytest

from app.schemas.permit import Conclusion
from app.services.permit.admissibility import render_draft
from app.services.permit.verifier import Verifier
from tests.mu9_acceptance import RECORDS
from tests.test_permit_admissibility import TRUSTED, claim, draft, in_section, record
from tests.test_permit_verifier import CHAIN, VERIFIED, Reviewer, checklist, codes, matter

EXPLANATION = "general_planning_explanation"
SECTIONS = ("claim", "procedure", "risk", "next action")


def official(eid, text):
    return record(eid, "regulatory_source", text, source="cascais-pdm", basis="official_text",
                  authority_class="municipal_instrument", title="PDM-Cascais — Regulamento (TEST FIXTURE)",
                  status="official_text")


HEIGHT = ("Em solo urbano, a altura das edificações não pode exceder 9 m, salvo em edifícios classificados.")
CUMULATIVE = ("Em solo urbano, a altura da fachada não pode exceder 9 m e o número de pisos acima do solo não pode "
              "exceder 3.")
DATED = ("A partir de 1 de janeiro de 2026, as operações urbanísticas de edificação em solo urbano ficam sujeitas a "
         "comunicação prévia.")
PERCENT = "Nas habitações coletivas, é admitida a ampliação até 10 % da área existente."
FIXTURES = [official("E33", f"TEST FIXTURE Artigo 903.º Altura 1 - {HEIGHT}"),
            official("E34", f"TEST FIXTURE Artigo 904.º Cérceas 1 - {CUMULATIVE}"),
            official("E35", f"TEST FIXTURE Artigo 905.º Regime transitório 1 - {DATED}"),
            official("E36", f"TEST FIXTURE Artigo 906.º Ampliação 1 - {PERCENT}")]
RECS = [*RECORDS, *FIXTURES]


async def outcome(d):
    report = await Verifier(Reviewer(VERIFIED), TRUSTED).verify(matter(), checklist(), render_draft(d, RECS, matter()),
                                                               RECS, CHAIN)
    return report


async def explained(text, eid, section="claim"):
    return await outcome(in_section(section, text, [eid], basis=EXPLANATION))


async def quoted(quote, eid, section="claim"):
    return await outcome(in_section(section, "x", [eid], basis="general_rule", quote=quote))


def rejected(report):
    return report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues)


# --- level 2: a supported general explanation of a single-limit rule --------------------------------------------------

@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text, eid", [(HEIGHT, "E33"), (PERCENT.replace("Nas", "Em"), "E36")])
async def test_a_faithful_single_limit_explanation_verifies(text, eid, section):
    report = await explained(text, eid, section)
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    "Em solo urbano, a altura das edificações pode exceder 9 m, salvo em edifícios classificados.",  # negation lost
    "Em solo urbano, a altura das edificações não pode exceder 10 m, salvo em edifícios classificados.",  # number
    "Em solo urbano, a altura das edificações não pode exceder 9 pisos, salvo em edifícios classificados.",  # unit
    "Em solo urbano, a altura das edificações não pode ser inferior a 9 m, salvo em edifícios classificados.",  # comparator
    "Em solo urbano, a altura das edificações não pode exceder 9 m.",  # exception dropped
    "Em solo urbano, a altura das edificações não pode exceder 9 m, salvo em edifícios classificados e em zonas "
    "históricas.",  # exception invented
    "A altura das edificações não pode exceder 9 m, salvo em edifícios classificados.",  # scope (solo urbano) dropped
])
async def test_a_height_rule_with_a_changed_negation_number_unit_comparator_exception_or_scope_is_rejected(text):
    assert rejected(await explained(text, "E33"))


@pytest.mark.parametrize("text", [
    # The owner's example: "aumento até 10 % da área existente" is not "área final até 10 % superior".
    "Em habitações coletivas, a área final pode ser até 10 % superior à área existente.",
    "Em habitações coletivas, é admitida a ampliação para no máximo 10 % da área existente.",  # target, not amount
    "Em habitações coletivas, é admitida a ampliação até 10 % da área.",  # "existing" dropped
    "Em habitações coletivas, é admitida a ampliação até 20 % da área existente.",  # percentage changed
    "Em habitações coletivas, é admitida a ampliação até 10 m2 da área existente.",  # unit changed
])
async def test_a_percentage_rule_restated_with_another_meaning_is_rejected(text):
    assert rejected(await explained(text, "E36"))


# --- level 1: rules with several limits (or a date and a rule) only as literal transcription --------------------------

@pytest.mark.parametrize("text, eid", [
    (CUMULATIVE, "E34"),  # the passage's own words, but outside a quotation
    ("In urban land, façade height may not exceed 9 m and the number of floors above ground may not exceed 3.", "E34"),
    ("Em solo urbano, a altura da fachada não pode exceder 9 m.", "E34"),  # one cumulative limit dropped
    ("Em solo urbano, a altura da fachada não pode exceder 9 m ou o número de pisos acima do solo não pode exceder 3.",
     "E34"),  # cumulative turned into an alternative
    (DATED, "E35"),
    ("As operações urbanísticas de edificação em solo urbano ficam sujeitas a comunicação prévia.", "E35"),  # date gone
    ("A partir de 1 de janeiro de 2025, as operações urbanísticas de edificação em solo urbano ficam sujeitas a "
     "comunicação prévia.", "E35"),  # year changed
])
@pytest.mark.parametrize("section", SECTIONS)
async def test_multi_limit_and_dated_rules_are_not_admitted_as_paraphrase(text, eid, section):
    assert rejected(await explained(text, eid, section))


@pytest.mark.parametrize("quote, eid", [(CUMULATIVE, "E34"), (DATED, "E35"), (HEIGHT, "E33")])
@pytest.mark.parametrize("section", SECTIONS)
async def test_the_literal_transcription_verifies_with_its_source(quote, eid, section):
    report = await quoted(quote, eid, section)
    assert report.outcome == "VERIFIED", report.issues
    assert any(a.supported_by == [eid] and a.bearer == "source" for a in report.claim_atoms)


@pytest.mark.parametrize("quote, eid", [
    ("Em solo urbano, a altura da fachada não pode exceder 9 m", "E34"),  # one limit cut off
    ("as operações urbanísticas de edificação em solo urbano ficam sujeitas a comunicação prévia.", "E35"),  # date
    ("Em solo urbano, a altura das edificações não pode exceder 9 m", "E33"),  # exception cut off
])
async def test_a_partial_transcription_that_drops_a_limit_date_or_exception_is_rejected(quote, eid):
    assert rejected(await quoted(quote, eid))


# --- level 3: a quotation is not an authorisation for this property ------------------------------------------------

async def test_a_quoted_rule_as_the_conclusion_cannot_give_a_definitive_answer():
    d = draft(claim("t", "E1"), conclusion=Conclusion(answer="likely_possible", summary="x", evidence_ids=["E34"],
                                                      planning_basis="general_rule", quote=CUMULATIVE), conditions=[])
    report = await outcome(d)
    assert report.outcome == "REJECTED" and "definitive_without_property_evidence" in codes(report.issues)
    assert not report.checks["conclusion_proportionate"]


async def test_a_quoted_rule_as_a_conditional_conclusion_still_verifies():
    d = draft(claim("t", "E1"), conclusion=Conclusion(answer="conditional", summary="x", evidence_ids=["E34"],
                                                      planning_basis="general_rule", quote=CUMULATIVE), conditions=[])
    assert (await outcome(d)).outcome == "VERIFIED"


@pytest.mark.parametrize("text, eid", [
    ("This property may be enlarged by up to 10 % of its existing area.", "E36"),
    ("Esta moradia pode ter até 9 m de altura.", "E33"),
    ("O imóvel cumpre o limite de 3 pisos acima do solo.", "E34"),
    ("The building's façade height of 9 m is therefore permitted.", "E34"),
    ("The works are admissible because the property is in urban land and below 9 m.", "E33"),
])
@pytest.mark.parametrize("section", SECTIONS)
async def test_applying_a_rule_to_this_property_is_never_verified_from_the_rule(text, eid, section):
    report = await explained(text, eid, section)
    assert report.outcome == "REJECTED", report.issues


async def test_a_literal_quote_next_to_an_application_to_the_property_does_not_make_it_verified():
    d = in_section("claim", "x", ["E36"], basis="general_rule", quote=PERCENT)
    d = d.model_copy(update={"claims": [*d.claims, claim("Therefore the property may be enlarged by 10 %.", "E36")
                                        .model_copy(update={"planning_basis": EXPLANATION, "claim_id": "K2"})]})
    report = await outcome(d)
    assert report.outcome == "REJECTED" and "unsupported_legal_claim" in codes(report.issues), report.issues


@pytest.mark.parametrize("text", [
    "In houses like this one, two dwellings are permitted.",  # the class names this matter
    "Em moradias como esta, são permitidos dois fogos.",
    "Em moradias, são permitidos dois fogos.",  # a general permission, but E13 doesn't say it
    "In single-family houses, enlargement by up to 50 % is permitted.",
])
async def test_a_class_scope_does_not_make_an_unsupported_permission_verifiable(text):
    report = await explained(text, "E36")
    assert report.outcome == "REJECTED", report.issues


# --- Codex review of the quote-only task, round 1 (2026-10-29): exact cases ------------------------------------------

@pytest.mark.parametrize("section", SECTIONS)
async def test_round1_exception_and_scope_swapped_is_rejected(section):
    text = "Em edifícios classificados, a altura das edificações não pode exceder 9 m, salvo em solo urbano."
    assert rejected(await explained(text, "E33", section))


async def test_round1_a_definitive_answer_from_a_general_explanation_is_rejected():
    d = draft(claim("t", "E1"), conclusion=Conclusion(answer="likely_possible", summary=HEIGHT, evidence_ids=["E33"],
                                                      planning_basis=EXPLANATION), conditions=[])
    report = await outcome(d)
    assert report.outcome == "REJECTED" and "definitive_without_property_evidence" in codes(report.issues)


QUOTE_E30 = ("Nas moradias unifamiliares com área de construção até 200 m2, é admitida a ampliação até 20 % da área "
             "existente, exceto em edifícios classificados.")


async def test_round2_a_quote_plus_the_parcel_determination_gives_no_definitive_answer():
    """Codex quote-only round 2: the determination proves the parcel's classification, not the dwelling type,
    construction area or exception status the quoted rule needs; no record proves them."""
    from tests.test_permit_admissibility import resolved_state

    async def state(_matter):
        return resolved_state()
    d = draft(claim("t", "E1"), conclusion=Conclusion(answer="likely_possible", summary="x", evidence_ids=["E30", "E20"],
                                                      planning_basis="general_rule", quote=QUOTE_E30), conditions=[])
    report = await Verifier(Reviewer(VERIFIED), TRUSTED, state).verify(matter(), checklist(),
                                                                       render_draft(d, RECS, matter()), RECS, CHAIN)
    assert report.outcome == "REJECTED" and "definitive_without_property_evidence" in codes(report.issues)


@pytest.mark.parametrize("section", SECTIONS)
async def test_round2_an_exception_placed_before_the_main_clause_verifies(section):
    text = "Em solo urbano, salvo em edifícios classificados, a altura das edificações não pode exceder 9 m."
    report = await explained(text, "E33", section)
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("section", SECTIONS)
async def test_round1_a_pt_definite_plural_class_scope_verifies(section):
    report = await explained("Nas habitações coletivas, é admitida a ampliação até 10 % da área existente.", "E36",
                             section)
    assert report.outcome == "VERIFIED", report.issues


# --- Codex quote-only round 3 (2026-10-29): exact cases ---------------------------------------------------------------

@pytest.mark.parametrize("section", SECTIONS)
async def test_round3_a_concept_of_the_exception_moved_into_the_scope_is_rejected(section):
    text = "Em solo urbano classificado, a altura das edificações não pode exceder 9 m, salvo em edifícios classificados."
    assert rejected(await explained(text, "E33", section))


@pytest.mark.parametrize("section", SECTIONS)
async def test_round3_an_exception_worded_com_excecao_de_verifies(section):
    text = "Em solo urbano, a altura das edificações não pode exceder 9 m, com exceção dos edifícios classificados."
    report = await explained(text, "E33", section)
    assert report.outcome == "VERIFIED", report.issues
