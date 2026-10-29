"""MU-9 V2 addendum (owner, 2026-10-29): legal and numeric integrity of rules with limits.

Three levels, each verified as it must be:
- a literal transcription (planning_basis general_rule): proves what the source says, nothing about the property;
- a general explanation: a normative statement (a requirement, duty, permission, prohibition, number, limit or
  exception) only as the official sentence's own wording (owner decision after ACC-QO-09: a paraphrase keeps the
  words but not their roles); a paraphrase is shown, never VERIFIED;
- an application to this property: never VERIFIED from a general rule (no property-specific evidence exists).

Fixtures are synthetic official passages (TEST FIXTURE); no real Cascais article says this."""

import pytest

from app.schemas.permit import Conclusion
from app.services.permit.admissibility import render_draft
from app.services.permit.verifier import Verifier
from app.services.permit.claims import assess
from tests.mu9_acceptance import E13, RECORDS
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


# --- level 2: a general explanation of a single-limit rule is its own wording -----------------------------------------

def quote_only(report):
    return rejected(report) and any("literal quote" in i.message for i in report.issues)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text, eid", [(HEIGHT, "E33"), (PERCENT, "E36")])
async def test_a_single_limit_rule_in_its_own_wording_verifies(text, eid, section):
    report = await explained(text, eid, section)
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("text, eid", [
    (PERCENT.replace("Nas", "Em"), "E36"),  # one preposition changed
    ("Em solo urbano, salvo em edifícios classificados, a altura das edificações não pode exceder 9 m.", "E33"),
    ("Em solo urbano, a altura das edificações não pode exceder 9 m, com exceção dos edifícios classificados.", "E33"),
    ("Em solo urbano a altura das edificações não pode exceder 9 m salvo em edifícios classificados.", "E33"),  # commas
])
async def test_a_faithful_paraphrase_of_a_single_limit_rule_is_quote_only(text, eid, section):
    """Owner decision (ACC-QO-09): its meaning may be right, but which noun is the object and which the scope can't
    be read back from a paraphrase, so it must be quoted."""
    assert quote_only(await explained(text, eid, section))


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
async def test_round4_the_limits_object_dropped_and_found_in_the_exception_is_rejected(section):
    """Codex quote-only round 4: "das edificações" dropped; "edifícios" in the exception must not stand in for it."""
    text = "Em solo urbano, a altura não pode exceder 9 m, salvo em edifícios classificados."
    assert rejected(await explained(text, "E33", section))


# --- roles: a paraphrase keeps the words but not their roles (ACC-QO-09, ACC-ROLE-01; closed by quote-only) ---------

@pytest.mark.parametrize("section", SECTIONS)
async def test_a_single_limit_rule_with_swapped_roles_is_rejected(section):
    """Codex quote-only round 5 (exact wording): object and scope swapped, every word kept."""
    text = "Em edifícios urbanos, a altura do solo não pode exceder 9 m, salvo em edifícios classificados."
    assert rejected(await explained(text, "E33", section))


@pytest.mark.parametrize("text", [
    "Em solo classificado, a altura das edificações não pode exceder 9 m, salvo em edifícios urbanos.",
    "Em solo urbano, a altura dos edifícios classificados não pode exceder 9 m, salvo nas edificações.",
    "A altura das edificações em solo urbano não pode exceder 9 m, salvo em edifícios classificados.",
])
async def test_other_reorderings_of_the_same_words_are_rejected(text):
    assert rejected(await explained(text, "E33"))


@pytest.mark.parametrize("text", [
    "In urban land, the height of buildings may not exceed 9 m, except classified buildings.",  # translated
    "Em solo urbano, a altura da fachada não pode exceder 9 m.",  # one limit of a cumulative rule (E34)
    "a altura das edificações não pode exceder 9 m, salvo em edifícios classificados.",  # the scope dropped
    "Em solo urbano, a altura das edificações não pode exceder 9 m.",  # the exception dropped
    "Em solo urbano, a altura das edificações não pode exceder 9",  # the unit cut
    "edificações não pode exceder 9 m, salvo em edifícios classificados.",  # a fragment from mid-phrase
])
async def test_a_partial_or_translated_transcription_is_still_rejected(text):
    """Literal wording is necessary, not sufficient: the directional check still needs every restrictive part."""
    assert rejected(await explained(text, "E34" if "fachada" in text else "E33"))


async def test_a_literal_transcription_is_about_its_source_not_the_property():
    """A rule in its own wording, applied to the works in the same statement, is still an application."""
    text = "Em solo urbano, a altura das edificações da obra não pode exceder 9 m, salvo em edifícios classificados."
    assert rejected(await explained(text, "E33"))
    report = await explained(f"If the works are in urban land, {HEIGHT[0].lower()}{HEIGHT[1:]}", "E33")
    assert rejected(report)


# --- Codex normative round 1 (2026-10-29): exact cases ------------------------------------------------------------

E78 = official("E78", "TEST FIXTURE Artigo 978.º Dispensa 1 - As operações urbanísticas de edificação até 200 m2 são "
                      "dispensadas de licenciamento, incluindo aquelas que envolvam edifícios classificados apenas se "
                      "tiverem parecer favorável da Câmara.")
RECS.append(E78)


async def test_normative_round1_an_act_that_removes_a_duty_is_normative():
    """'O PDM revoga …' removes a duty: held to the quote-only rule (and unsupported by E13 anyway)."""
    assert rejected(await explained("O PDM revoga a dotação de estacionamento.", "E13"))


async def test_normative_round1_an_inclusion_that_restricts_is_not_an_omissible_list():
    """'incluindo … apenas se …' carries a condition: a quote that leaves it out drops it."""
    short = "As operações urbanísticas de edificação até 200 m2 são dispensadas de licenciamento."
    assert rejected(await explained(short, "E78"))
    assert rejected(await quoted(short[:-1], "E78"))


# --- Codex normative round 2 (2026-10-29): exact cases, and the same mechanisms with other wording -----------------

E80 = official("E80", "TEST FIXTURE Artigo 980.º Dispensa 1 - As operações urbanísticas de edificação até 200 m2 são "
                      "dispensadas de licenciamento, incluindo aquelas que envolvam edifícios classificados desde que "
                      "tenham parecer favorável da Câmara.")
E86 = official("E86", "TEST FIXTURE Artigo 986.º Pareceres 1 - Nas operações urbanísticas de edificação, o "
                      "estacionamento carece de parecer favorável da Câmara.")
RECS.extend([E80, E86])
SWAPPED_E86 = "Nas operações urbanísticas de estacionamento, a edificação carece de parecer favorável da Câmara."


async def test_normative_round2_a_quote_is_the_whole_sentence():
    """'desde que …' (or any other wording of a condition) can't be left out: a part of the sentence never verifies."""
    short = "As operações urbanísticas de edificação até 200 m2 são dispensadas de licenciamento."
    assert rejected(await explained(short, "E80"))
    assert rejected(await quoted(short[:-1], "E80"))


@pytest.mark.parametrize("text", [
    SWAPPED_E86,  # exact
    "Segundo o PDM, nas operações urbanísticas de estacionamento, a edificação carece de parecer favorável da Câmara.",
    "Nas operações urbanísticas de estacionamento, a edificação necessita de parecer favorável da Câmara.",
    "In urban building operations, parking needs a favourable opinion of the Câmara.",  # translated, roles kept
])
async def test_normative_round2_a_restatement_is_held_to_the_wording_whatever_its_verbs(text):
    assert rejected(await explained(text, "E86"))


@pytest.mark.parametrize("section", SECTIONS)
async def test_normative_round2_the_sentence_itself_verifies(section):
    report = await explained(E86.excerpt.split(" 1 - ", 1)[1], "E86", section)
    assert report.outcome == "VERIFIED", report.issues
    report = await quoted(E80.excerpt.split(" 1 - ", 1)[1], "E80", section)
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    "Em solo urbano os espaços destinam-se predominantemente à habitação e edificação, designadamente de urbanização, "
    "comércio e serviços.",  # roles swapped, every word kept
    "Em solo urbano os espaços destinam-se sempre à habitação.",  # a word added
])
async def test_normative_round2_a_use_designation_is_normative(text):
    from tests.test_permit_admissibility import rendered_verify
    report = await rendered_verify(in_section("claim", text, ["E3"], basis=EXPLANATION))
    assert report.outcome != "VERIFIED" and "unsupported_legal_claim" in codes(report.issues)


E87 = official("E87", "TEST FIXTURE Artigo 987.º Qualificação 1 - A qualificação do solo urbano consta da Planta de "
                      "Ordenamento.")
RECS.append(E87)


async def test_normative_round2_a_role_swap_in_neutral_words_is_a_restatement():
    """No deontic word at all: the swap is caught because every concept comes from the cited sentence."""
    assert rejected(await explained("A qualificação da Planta de Ordenamento consta do solo urbano.", "E87"))
    report = await explained("A qualificação do solo urbano consta da Planta de Ordenamento.", "E87")
    assert report.outcome == "VERIFIED", report.issues


E88 = official("E88", "TEST FIXTURE Artigo 988.º Licença 1 - As operações urbanísticas de edificação carecem de "
                      "licença, incluindo obras de ampliação.")
RECS.append(E88)


async def test_normative_round2_a_prefix_of_the_sentence_is_not_a_quote():
    """Even when what it leaves out is only a list of covered cases ("incluindo …")."""
    prefix = "As operações urbanísticas de edificação carecem de licença"
    assert rejected(await explained(prefix + ".", "E88"))
    assert rejected(await quoted(prefix, "E88"))
    report = await quoted(prefix + ", incluindo obras de ampliação", "E88")
    assert report.outcome == "VERIFIED", report.issues


# --- Codex normative round 3 (2026-10-29): exact cases ------------------------------------------------------------

E91 = official("E91", "TEST FIXTURE Artigo 991.º Edificação 1 - Em solo urbano, as edificações são permitidas; apenas "
                      "se tiverem parecer favorável da Câmara.")
RECS.append(E91)
WHOLE_E91 = E91.excerpt.split(" 1 - ", 1)[1]


@pytest.mark.parametrize("text", [
    "Em solo urbano, a edificação é consentida.",  # exact (E33)
    "Em solo urbano, as edificações são autorizadas.",
    "In urban land, building is allowed.",
    "Em solo urbano, o uso habitacional é admissível.",
])
async def test_normative_round3_a_state_given_by_a_copula_is_normative_whatever_the_word(text):
    assert rejected(await explained(text, "E33"))


async def test_normative_round3_a_clause_ending_in_a_semicolon_is_not_the_sentence():
    clause = "Em solo urbano, as edificações são permitidas;"
    assert rejected(await explained(clause, "E91"))
    assert rejected(await quoted(clause, "E91"))


@pytest.mark.parametrize("section", SECTIONS)
async def test_normative_round3_the_whole_sentence_with_its_semicolon_verifies(section):
    for report in (await explained(WHOLE_E91, "E91", section), await quoted(WHOLE_E91, "E91", section)):
        assert report.outcome == "VERIFIED", report.issues


# --- Codex normative round 4 (2026-10-29): exact cases ------------------------------------------------------------

E97 = official("E97", "TEST FIXTURE Artigo 997.º Usos 1 - O estacionamento é um uso.")
RECS.append(E97)


@pytest.mark.parametrize("text, eid", [
    ("O estacionamento é lícito.", "E13"),  # exact: unsupported, no known legal word
    ("O estacionamento é facultativo.", "E13"),
    ("O PDM classifica o estacionamento como lícito.", "E13"),  # a structural verb with a predicative complement
    ("The PDM defines parking as optional.", "E13"),
    ("O PDM define que o estacionamento é facultativo.", "E13"),  # a content clause
])
async def test_normative_round4_an_unsupported_statement_is_a_shadow_only_when_it_describes_structure(text, eid):
    assert rejected(await explained(text, eid))


async def test_normative_round4_a_two_concept_definition_reversed_is_a_restatement():
    assert rejected(await explained("O uso é estacionamento.", "E97"))  # exact
    report = await explained("O estacionamento é um uso.", "E97")
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    "O PDM regula o estacionamento.",
    "A dotação de estacionamento varia consoante a zona.",
    "Em solo urbano, cada zona ou distrito segue as regras do plano municipal.",
])
async def test_normative_round4_a_structural_description_keeps_its_contract(text):
    report = await explained(text, "E13")
    assert report.outcome == "VERIFIED", report.issues


# --- builder probes before the last Codex round: structural descriptions that state content ------------------------

@pytest.mark.parametrize("text", [
    "O PDM não se aplica ao solo urbano.",
    "The PDM does not apply to urban land.",
    "Em solo urbano, a edificação segue o regime do solo rústico.",
    "Urban land follows the rustic land regime.",
    "O PDM não regula o estacionamento.",  # a negation alone
])
async def test_a_negated_or_specific_applicability_is_content_not_structure(text):
    assert rejected(await explained(text, "E13"))


# --- Codex normative round 5 (ACC-NRM-10/11), fixed in the authorised follow-up task ------------------------------

E201 = official("E201", "TEST FIXTURE Artigo 201.º Multifuncionalidade 1 - A multifuncionalidade do solo depende de "
                        "parecer favorável da Câmara.")
RECS.append(E201)


@pytest.mark.parametrize("section", SECTIONS)
async def test_nrm10_a_distant_predicative_complement_is_content(section):
    assert rejected(await explained("O PDM define a dotação de estacionamento como facultativa.", "E13", section))


async def test_nrm11_a_partial_quote_is_never_certified():
    assert rejected(await quoted("A multifuncionalidade", "E201"))


@pytest.mark.parametrize("quote", [
    "A multifuncionalidade do solo depende de parecer",  # the essential element cut
    "A multifuncionalidade do solo",
    "parecer favorável da Câmara",  # a tail fragment
])
async def test_nrm11_no_fragment_of_the_sentence_is_certified(quote):
    assert rejected(await quoted(quote, "E201"))


@pytest.mark.parametrize("section", SECTIONS)
async def test_nrm11_the_whole_sentence_quoted_verifies(section):
    report = await quoted(E201.excerpt.split(" 1 - ", 1)[1], "E201", section)
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    # Criterion 1: a duty (E13: "deve ser assegurada") never becomes a faculty, however the complement is worded.
    "O PDM define a dotação de estacionamento nas operações urbanísticas de edificação como facultativa.",
    "O PDM classifica a dotação de estacionamento das operações urbanísticas como opcional.",
    "The PDM defines the parking provision of urban building operations subject to licensing as optional.",
    "A dotação de estacionamento é facultativa.",
    "A dotação de estacionamento pode ser assegurada.",
])
async def test_nrm10_a_duty_is_never_turned_into_a_faculty(text):
    assert rejected(await explained(text, "E13"))


async def test_nrm11_a_whole_quote_still_proves_nothing_about_the_property():
    """Criterion 3: the quote verifies as what the source says; a definitive answer on it does not."""
    whole = E201.excerpt.split(" 1 - ", 1)[1]
    d = draft(claim("t", "E1"), conclusion=Conclusion(answer="likely_possible", summary="x", evidence_ids=["E201"],
                                                      planning_basis="general_rule", quote=whole), conditions=[])
    report = await outcome(d)
    assert report.outcome == "REJECTED" and "definitive_without_property_evidence" in codes(report.issues)


# --- NRM-10/11 task, Codex round 1 (2026-10-29): exact cases --------------------------------------------------------

@pytest.mark.parametrize("text", [
    "O PDM define a dotação de estacionamento facultativa.",  # exact: no "como"
    "O PDM estabelece uma dotação de estacionamento opcional.",
    "The PDM sets an optional parking provision.",
    "O PDM define a dotação de estacionamento como voluntária.",
])
async def test_nrm_task_r1_a_deontic_qualifier_turns_no_duty_into_a_faculty(text):
    assert rejected(await explained(text, "E13"))


@pytest.mark.parametrize("text", [
    "O PDM define a dotação de estacionamento e as regras aplicáveis.",  # exact: PT article "as"
    "O PDM regula as operações urbanísticas e as respetivas regras.",
])
async def test_nrm_task_r1_the_portuguese_article_as_is_not_a_predicative_complement(text):
    report = await explained(text, "E13")
    assert report.outcome == "VERIFIED", report.issues


# --- NRM-10/11 task, Codex round 2 (2026-10-29): exact cases --------------------------------------------------------

E202 = official("E202", "TEST FIXTURE Artigo 202.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. "
                        "Essa permissão depende de parecer favorável da Câmara.")
RECS.append(E202)


@pytest.mark.parametrize("text", [
    "O PDM define a dotação de estacionamento ao critério do promotor.",  # exact
    "The Plano Diretor Municipal de Cascais defines parking provision as an option.",  # exact
    "O PDM regula a dotação de estacionamento segundo a vontade do requerente.",
    "The PDM sets parking provision at the developer's discretion.",
])
async def test_nrm_task_r2_a_structural_description_that_adds_a_claim_is_enforced(text):
    assert rejected(await explained(text, "E13"))


async def test_nrm_task_r2_a_sentence_taken_up_by_the_next_is_quoted_with_it():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E202"))  # exact
    report = await quoted(E202.excerpt.split(" 1 - ", 1)[1], "E202")
    assert report.outcome == "VERIFIED", report.issues


# --- NRM-10/11 task, Codex round 3 (2026-10-29): exact cases --------------------------------------------------------

E299 = official("E299", "TEST FIXTURE Artigo 299.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. A "
                        "permissão depende de parecer favorável da Câmara.")
E298 = official("E298", "TEST FIXTURE Artigo 298.º Dotação 1 - A dotação de estacionamento deve ser assegurada. Esta secção "
                        "define os parâmetros de altura das edificações.")
RECS.extend([E299, E298])


@pytest.mark.parametrize("text", [
    "The PDM de Cascais defines parking provision as allowed for building operations.",  # exact
    "The PDM defines parking provision as permitted.",
    "The Plano Diretor Municipal sets parking provision only for some operations.",  # a restrictive concept added
])
async def test_nrm_task_r3_a_deontic_concept_added_to_a_description_is_a_claim(text):
    assert rejected(await explained(text, "E13"))


async def test_nrm_task_r3_a_sentence_whose_subject_takes_up_the_previous_one_belongs_to_it():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E299"))  # exact: "A permissão …"
    report = await quoted(E299.excerpt.split(" 1 - ", 1)[1], "E299")
    assert report.outcome == "VERIFIED", report.issues


async def test_nrm_task_r3_a_sentence_with_a_new_subject_is_quoted_with_its_excerpt():
    """Policy change (owner rule after ACC-NRM-36): "Esta secção …" is a second unit, so the excerpt is quoted whole."""
    assert rejected(await quoted("A dotação de estacionamento deve ser assegurada.", "E298"))
    report = await quoted(E298.excerpt.split(" 1 - ", 1)[1], "E298")
    assert report.outcome == "VERIFIED", report.issues


async def test_nrm_task_r3_each_layer_on_its_own():
    # A deontic concept with no predicative complement ("permitida" attributive, not in E13).
    assert rejected(await explained("Nas operações urbanísticas, o PDM regula a dotação de estacionamento permitida.", "E13"))
    # A predicative "as" with no deontic word, after a PT source name ("de").
    assert rejected(await explained("The PDM de Cascais defines parking provision as a use.", "E13"))


# --- NRM-10/11 task, Codex round 4 (2026-10-29): exact cases --------------------------------------------------------

E301 = official("E301", "TEST FIXTURE Artigo 301.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. "
                        "Para exercer esta permissão, é necessário parecer favorável da Câmara.")
RECS.append(E301)


@pytest.mark.parametrize("text", [
    "Nas operações urbanísticas, o PDM define a dotação de estacionamento admissível.",  # exact
    "Nas operações urbanísticas, o PDM regula a dotação de estacionamento admitida.",
])
async def test_nrm_task_r4_admissibility_qualifies_only_a_category_of_uses(text):
    assert rejected(await explained(text, "E13"))


async def test_nrm_task_r4_a_later_anaphor_takes_up_the_previous_sentence():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E301"))  # exact
    report = await quoted(E301.excerpt.split(" 1 - ", 1)[1], "E301")
    assert report.outcome == "VERIFIED", report.issues


async def test_nrm_task_r4_a_statement_is_not_merged_with_its_next_sentence():
    """'The property holds that licence.' takes up the rule's words but is the statement's own claim: the quote stays
    literal and the property claim is judged on its own."""
    text = (E13.excerpt.split(" 1 - ", 1)[1] + " The property already holds that licence.")
    atoms = assess(text, EXPLANATION, None, [E13])
    assert [a.kind for a in atoms] == ["general_rule", "legal_status"]


# --- NRM-10/11 task, Codex round 5 (ACC-NRM-22..24), fixed in the authorised NRM-22..24 task --------------------

E904 = official("E904", "TEST FIXTURE Artigo 904.º Estacionamento 1 - A dotação de estacionamento deve ser assegurada. "
                        "As obras são permitidas.")
E901 = official("E901", "TEST FIXTURE Artigo 901.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. Ela "
                        "depende de parecer favorável da Câmara.")
E905 = official("E905", "TEST FIXTURE Artigo 905.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. 2 - "
                        "Essa permissão depende de parecer favorável da Câmara.")
RECS.extend([E904, E901, E905])


async def test_nrm22_a_concept_from_another_sentence_is_not_the_descriptions():
    text = "Nas operações urbanísticas, o PDM regula a dotação de estacionamento permitida."
    assert rejected(await explained(text, "E904"))


async def test_nrm23_a_pronoun_takes_up_the_previous_sentence():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E901"))


async def test_nrm24_a_condition_in_the_next_numbered_paragraph():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E905"))


async def test_nrm23_24_the_whole_unit_quoted_verifies():
    for e in (E901, E905):
        report = await quoted(e.excerpt.split(" 1 - ", 1)[1], e.evidence_id)
        assert report.outcome == "VERIFIED", (e.evidence_id, report.issues)


async def test_nrm23_a_demonstrative_standing_alone_takes_up_the_previous_sentence():
    e = official("E906", "TEST FIXTURE Artigo 906.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. "
                         "Esta depende de parecer favorável da Câmara.")
    RECS.append(e)
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E906"))


async def test_nrm22_a_description_carrying_a_deontic_concept_is_quote_only():
    """Even when the permission sits in the parking sentence itself: a description that carries a duty, permission or
    limit is its content, held to the wording (Codex NRM-22..24 round 1)."""
    e = official("E907", "TEST FIXTURE Artigo 907.º Estacionamento 1 - Nas operações urbanísticas, a dotação de "
                         "estacionamento é permitida. As obras devem ser comunicadas.")
    RECS.append(e)
    assert rejected(await explained("Nas operações urbanísticas, o PDM regula a dotação de estacionamento permitida.",
                                    "E907"))


# --- NRM-22..24 task, Codex round 1 (2026-10-29): exact cases -------------------------------------------------------

W990 = ("A multifuncionalidade do solo é permitida. Ela depende de parecer favorável da Câmara. Esse parecer exige "
        "fundamentação técnica. Essa fundamentação deve descrever impactos urbanísticos. Ela deve integrar o processo.")
E991 = official("E991", "TEST FIXTURE Artigo 991.º Estacionamento 1 - Nas operações urbanísticas, a dotação de "
                        "estacionamento deve ser assegurada e as obras são permitidas.")
E994 = official("E994", "TEST FIXTURE Artigo 994.º Estacionamento 1 - Nas operações urbanísticas de uso habitacional, a "
                        "dotação de estacionamento deve ser assegurada.")
E997 = official("E997", "TEST FIXTURE Artigo 997.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. 2 - "
                        "O exercício dessa faculdade depende de parecer favorável da Câmara.")
E990 = official("E990", f"TEST FIXTURE Artigo 990.º Multifuncionalidade 1 - {W990}")
E989 = official("E989", "TEST FIXTURE Artigo 989.º Solo urbano 1 - A dotação de estacionamento deve ser assegurada. 2 - A "
                        "qualificação do solo urbano consta da Planta de Ordenamento.")
RECS.extend([E991, E994, E997, E990, E989])


@pytest.mark.parametrize("text, eid", [
    ("Nas operações urbanísticas, o PDM regula a dotação de estacionamento permitida.", "E991"),  # exact
    ("Nas operações urbanísticas, o PDM regula a dotação de estacionamento admissível para o uso habitacional.",
     "E994"),  # exact
])
async def test_nrm_r1_a_description_carrying_a_deontic_concept_is_content(text, eid):
    assert rejected(await explained(text, eid))


async def test_nrm_r1_with_several_normative_units_a_quote_is_the_whole_excerpt():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E997"))  # exact: "dessa faculdade"
    report = await quoted(E997.excerpt.split(" 1 - ", 1)[1], "E997")
    assert report.outcome == "VERIFIED", report.issues


async def test_nrm_r1_a_long_linked_quote_verifies():
    report = await quoted(W990, "E990")  # exact: five linked sentences
    assert report.outcome == "VERIFIED", report.issues


async def test_nrm_r1_an_excerpt_of_several_units_is_quoted_whole_even_beside_a_description():
    """Owner rule after ACC-NRM-36 (policy change from 'quoted alone'): more than one unit → the whole excerpt."""
    assert rejected(await quoted("A dotação de estacionamento deve ser assegurada.", "E989"))
    report = await quoted(E989.excerpt.split(" 1 - ", 1)[1], "E989")
    assert report.outcome == "VERIFIED", report.issues


# --- NRM-22..24 task, Codex round 2 (2026-10-29): exact cases -------------------------------------------------------

E973 = official("E973", "TEST FIXTURE Artigo 973.º Área 1 - Nas operações urbanísticas, o uso da área é obrigatório.")
E970 = official("E970", "TEST FIXTURE Artigo 970.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. 2 - "
                        "O exercício depende de anuência da Câmara.")
RECS.extend([E973, E970])


async def test_nrm_r2_admissibility_reaching_back_past_another_noun_qualifies_that_noun():
    assert rejected(await explained("Nas operações urbanísticas, o PDM regula os usos da área admissível.", "E973"))


async def test_nrm_r2_an_official_dependency_is_a_condition():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E970"))  # exact
    report = await quoted(E970.excerpt.split(" 1 - ", 1)[1], "E970")
    assert report.outcome == "VERIFIED", report.issues


async def test_nrm_r2_an_unmarked_exception_in_the_next_paragraph_needs_the_whole_excerpt():
    """Builder probe: 'Excetuam-se …' carries no known marker; only structural units may be left out of a quote."""
    e = official("E960", "TEST FIXTURE Artigo 960.º Altura 1 - Em solo urbano, a altura das edificações não pode "
                         "exceder 9 m. 2 - Excetuam-se os edifícios classificados.")
    RECS.append(e)
    assert rejected(await quoted("Em solo urbano, a altura das edificações não pode exceder 9 m.", "E960"))
    report = await quoted(e.excerpt.split(" 1 - ", 1)[1], "E960")
    assert report.outcome == "VERIFIED", report.issues


# --- NRM-22..24 task, Codex round 3 (2026-10-29): exact cases -------------------------------------------------------

E998 = official("E998", "TEST FIXTURE Artigo 998.º Multifuncionalidade 1 - A multifuncionalidade do solo é permitida. 2 - "
                        "O exercício dessa faculdade depende de parecer favorável da Câmara")  # no closing stop
E988 = official("E988", "TEST FIXTURE Artigo 988.º Solo 1 - A multifuncionalidade do solo é permitida. Ela consta da "
                        "Planta de Ordenamento.")
RECS.extend([E998, E988])


async def test_nrm_r3_a_dependency_clause_hedges_only_a_modal_possibility():
    text = ("Nas operações urbanísticas de uso habitacional, o PDM regula a dotação de estacionamento admissível "
            "consoante a zona.")
    assert rejected(await explained(text, "E994"))


async def test_nrm_r3_a_last_paragraph_without_a_stop_is_not_a_heading():
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E998"))


async def test_nrm_r3_a_two_sentence_excerpt_is_quoted_whole():
    """Policy change (owner rule after ACC-NRM-36): even when the second sentence only says where the rule is mapped."""
    assert rejected(await quoted("A multifuncionalidade do solo é permitida.", "E988"))
    report = await quoted(E988.excerpt.split(" 1 - ", 1)[1], "E988")
    assert report.outcome == "VERIFIED", report.issues


# --- NRM-22..24 task, Codex round 4 (2026-10-29): exact cases -------------------------------------------------------

PX11 = official("PX11", "TEST FIXTURE Artigo 11.º Obras 1 - Em solo urbano, as obras são permitidas. 2 - O PDM define "
                        "como excluídas desta permissão as obras de demolição.")
PX13 = official("PX13", "TEST FIXTURE Artigo 13.º Estacionamento 1 - Nas operações urbanísticas, a dotação de "
                        "estacionamento deve ser assegurada.")
RECS.extend([PX11, PX13])


async def test_nrm_r4_a_structural_verb_with_a_predicative_exclusion_is_content():
    assert rejected(await quoted("Em solo urbano, as obras são permitidas.", "PX11"))
    report = await quoted(PX11.excerpt.split(" 1 - ", 1)[1], "PX11")
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    "Nas operações urbanísticas, o PDM define os usos admissíveis, incluindo estacionamento.",  # exact
    "Nas operações urbanísticas, o PDM define os usos admissíveis, como o estacionamento.",
    "The PDM sets the admissible uses, such as parking.",
])
async def test_nrm_r4_naming_a_use_beside_the_admissible_uses_admits_it(text):
    assert rejected(await explained(text, "PX13"))


async def test_nrm_r4_a_predicative_complement_alone_makes_a_unit_content():
    e = official("PX12", "TEST FIXTURE Artigo 12.º Obras 1 - Em solo urbano, as obras são permitidas. 2 - O PDM classifica "
                         "como solo rústico a faixa costeira.")
    RECS.append(e)
    assert rejected(await quoted("Em solo urbano, as obras são permitidas.", "PX12"))


# --- NRM-22..24 task, Codex round 5 (ACC-NRM-36..37), closed by the two owner rules ------------------------------

RCOND = official("RCOND", "TEST FIXTURE Artigo 999.º Obras 1 - Em solo urbano, as obras são permitidas. 2 - O PDM "
                          "condiciona a permissão à vistoria municipal.")
REXC = official("REXC", "TEST FIXTURE Artigo 998.º Obras 1 - Em solo urbano, as obras são permitidas. 2 - O PDM define "
                        "exceção para as obras de demolição.")
D2 = official("D2", "TEST FIXTURE Artigo 995.º Residência 1 - Nas operações urbanísticas, o uso residencial é obrigatório.")
RECS.extend([RCOND, REXC, D2])


@pytest.mark.parametrize("eid", ["RCOND", "REXC"])
async def test_nrm36_a_structural_verb_stating_a_condition_or_exception(eid):
    assert rejected(await quoted("Em solo urbano, as obras são permitidas.", eid))


async def test_nrm37_a_use_named_by_an_adjective():
    assert rejected(await explained("Nas operações urbanísticas, o PDM define os usos admissíveis residenciais.", "D2"))


@pytest.mark.parametrize("eid", ["RCOND", "REXC"])
async def test_nrm36_the_whole_excerpt_quoted_verifies(eid):
    e = next(r for r in RECS if r.evidence_id == eid)
    report = await quoted(e.excerpt.split(" 1 - ", 1)[1], eid)
    assert report.outcome == "VERIFIED", report.issues
