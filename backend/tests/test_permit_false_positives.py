"""HR-003 MU-9 Phase 2: grounding false positives FP-3..5 (V2 report, known limitations), kept fail-closed.

- FP-3 (ACC-LEG-COMP-02): an authority's competence restated in its record's own words with a neutral competence
  predicate ("… is handled by the Câmara") is a case fact, not a planning explanation. Admitted.
- FP-4 (ACC-LEG-DEF-01): a deferral's embedded question ("Whether the property is licensed …") asserts nothing, so its
  words aren't grounded; labelled an explanation without anything an explanation could rest on, it is free text.
  Admitted.
- FP-5 (ACC-LEG-REQ-02): the object of an instruction to check presupposes its content ("Confirm the 3 documents …"),
  so it stays grounded: not admitted (known limitation, no vocabulary filter).
Also closed: a number in free text was never grounded."""

import pytest

import tests.mu9_acceptance as A

BASES = ("none", "general_planning_explanation")
SECTIONS = ("claim", "procedure", "risk", "next action")


async def outcomes(text, evidence_set="auth", bases=BASES):
    return {await A.outcome(text, evidence_set, b, s) for b in bases for s in SECTIONS}


async def test_fp3_competence_in_the_records_words_verifies():
    text = "Licensing of urban operations, including building permits (licenciamento urbanístico) is handled by " \
           "Câmara Municipal de Cascais."
    assert await outcomes(text, bases=("none",)) == {"VERIFIED"}


async def test_fp4_a_deferral_with_an_embedded_question_verifies_in_both_bases():
    text = "Whether the property is licensed must be confirmed with the Câmara Municipal de Cascais."
    assert await outcomes(text) == {"VERIFIED"}


@pytest.mark.parametrize("text", [
    "The property is handled by Câmara Municipal de Cascais.",
    "Licensing of urban operations is handled by Câmara Municipal de Cascais, which licensed this property.",
    "Building permits are not handled by Câmara Municipal de Cascais.",
    "Whether the property is licensed must be confirmed with the Câmara Municipal de Cascais; it is licensed.",
    "Whether the property is licensed must be confirmed with the Câmara Municipal de Cascais, but it was approved.",
    "Confirm the licence of the property with the Câmara Municipal de Cascais.",
    "Confirm the 3 documents with the Câmara Municipal de Cascais.",  # a number was never grounded
    "Confirm the free parking with the Câmara Municipal de Cascais.",
    "Licensing takes 30 days at the Câmara Municipal de Cascais.",
])
async def test_what_the_new_admission_paths_must_not_admit(text):
    assert "VERIFIED" not in await outcomes(text)


async def test_fp5_stays_a_known_limitation():
    text = "Confirm the full list of application documents with the Câmara Municipal de Cascais before applying."
    assert "VERIFIED" not in await outcomes(text, bases=("none",))


# --- Codex FP review, round 1 (2026-10-29): exact case ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Whether the property is licensed must be confirmed with the Câmara Municipal de Cascais and the property is "
    "approved for 3 floors.",  # exact
    "It must be confirmed with the Câmara Municipal de Cascais whether the works need licensing and the property is "
    "licensed.",
    "Confirm with the Câmara Municipal de Cascais whether licensing applies, but the works were approved.",
])
async def test_a_clause_coordinated_after_a_deferral_is_asserted(text):
    assert "VERIFIED" not in await outcomes(text)


async def test_only_the_closed_status_question_is_deferred():
    """Round 3: a question is left ungrounded only in the closed shape 'whether <the property> <is> <status>'; a compound
    or subordinate question is grounded as written (fail-closed; cost: legitimate compound questions are rejected)."""
    for text in ("Whether the property is licensed and its works approved must be confirmed with the Câmara Municipal "
                 "de Cascais.",
                 "Whether the property is licensed although it was approved for 3 floors must be confirmed with the "
                 "Câmara Municipal de Cascais."):  # exact (Codex round 3)
        assert "VERIFIED" not in await outcomes(text)
    assert await outcomes("Se o imóvel está licenciado deve ser confirmado com a Câmara Municipal de Cascais.",
                          bases=("none",)) == {"VERIFIED"}


# --- Codex FP review, round 2 (2026-10-29): exact cases ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "It must be confirmed with the Câmara Municipal de Cascais whether the property is licensed despite the fact that "
    "it was approved for 3 floors.",  # exact: only a question that is the deferral's subject is deferred
    "Câmara Municipal de Cascais is handled by licensing of urban operations, including building permits.",  # exact
    "Licensing of urban operations is responsible for Câmara Municipal de Cascais.",
])
async def test_only_the_records_orientation_and_a_subject_question_are_admitted(text):
    assert "VERIFIED" not in await outcomes(text)


async def test_the_competence_record_restated_with_the_authority_as_subject_verifies():
    text = "Câmara Municipal de Cascais is responsible for licensing of urban operations, including building permits."
    assert await outcomes(text, bases=("none",)) == {"VERIFIED"}


async def test_a_reversed_inclusion_is_not_the_records_competence():
    """Codex FP review round 3 (exact): the record's activity is restated only as a run of the record, in order."""
    text = "Câmara Municipal de Cascais handles building permits, including licensing of urban operations."
    assert "VERIFIED" not in await outcomes(text)


# --- Codex FP review, round 4 (2026-10-29): exact case ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Whether the property is licensed must be confirmed with Câmara Municipal de Cascais, which confirms this "
    "property's building permits.",  # exact
    "Whether the property is licensed must be confirmed with Câmara Municipal de Cascais before the works start.",
])
async def test_the_deferral_shape_ends_with_the_authority(text):
    assert "VERIFIED" not in await outcomes(text)


@pytest.mark.parametrize("text", [
    "Licensing must be confirmed with Câmara Municipal de Cascais, which confirms this property's building permits.",
    "Licensing must be confirmed with Câmara Municipal de Cascais and the property holds a permit.",
    "Confirm the licensing with Câmara Municipal de Cascais, that already approved the works.",
])
async def test_a_clause_after_a_deferral_is_an_assertion_of_its_own(text):
    """Found while checking round 4 (pre-existing in claims): a relative or coordinated clause after a deferral was
    read as part of it, so a legal claim about the property verified with every word grounded."""
    assert "VERIFIED" not in await outcomes(text)


async def test_a_negated_competence_is_never_the_records():
    """Codex FP review round 5 (exact, P2); fixed after the last round, not re-reviewed."""
    text = "No licensing of urban operations, including building permits, is handled by Câmara Municipal de Cascais."
    assert "VERIFIED" not in await outcomes(text)
