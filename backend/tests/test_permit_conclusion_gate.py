"""HR-003 MU-9 Phase 2, conclusion gate (final candidate §5.5), ACC-CONC-01..03.

HABITA has no capability that proves a property's own facts or legal status, so the gate is stricter than §5.5: a
definitive answer is never VERIFIED, and a conditional answer whose text gives the property a permission or capacity
is rejected; a conditional conclusion that only defers verifies. The final gate never rewrites the conclusion."""

import pytest

import tests.mu9_acceptance as A
from app.schemas.permit import Conclusion
from app.services.permit.admissibility import render_draft
from app.services.permit.verifier import Verifier
from tests.test_permit_admissibility import claim, draft


async def verify(answer, summary):
    d = draft(claim("The Câmara Municipal de Cascais is the competent authority.", "E3"),
              conclusion=Conclusion(answer=answer, summary=summary, evidence_ids=["E3"]))
    rendered = render_draft(d, A.RECORDS, A.matter())
    report = await Verifier(A.Reviewer(A.VERIFIED), A.TRUSTED, None).verify(A.matter(), A.checklist(), rendered,
                                                                         A.RECORDS, A.CHAIN)
    return rendered, report


@pytest.mark.parametrize("answer", ["likely_possible", "likely_not_possible"])
async def test_acc_conc_01_a_definitive_answer_is_never_verified(answer):
    _, report = await verify(answer, "Possible, subject to the conditions.")
    assert report.outcome != "VERIFIED"


@pytest.mark.parametrize("summary", ["The proposed use is permitted for this property.",
                                     "A habitação é permitida neste imóvel.", "This property can be enlarged."])
async def test_acc_conc_01_a_conditional_answer_that_grants_the_property_something_is_rejected(summary):
    _, report = await verify("conditional", summary)
    assert report.outcome == "REJECTED"


async def test_acc_conc_02_a_conditional_conclusion_that_defers_verifies():
    _, report = await verify("conditional", "Possible, subject to the conditions.")
    assert report.outcome == "VERIFIED"


async def test_acc_conc_03_the_gate_does_not_rewrite_the_conclusion():
    rendered, report = await verify("conditional", "Possible, subject to the conditions.")
    assert rendered.conclusion.summary == "Possible, subject to the conditions." and report.outcome == "VERIFIED"
