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
