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


# --- Codex backlog review, round 1 (2026-10-29): negations are grounded ------------------------------------------

@pytest.mark.parametrize("text", [
    "Licensing of urban operations, including building permits (licenciamento urbanístico) is not handled by Câmara "
    "Municipal de Cascais.",
    "Câmara Municipal de Cascais handles no building permits.",
    "Câmara Municipal de Cascais never handles licensing of urban operations.",
])
async def test_a_negation_the_records_dont_state_is_never_verified(text):
    assert "VERIFIED" not in await outcomes(text)


async def test_the_reviews_exact_negation_against_an_affirmative_record():
    """Codex backlog review round 1 (exact): a record saying the Câmara handles applications doesn't support that it
    handles none; the affirmative restatement still verifies."""
    from tests.test_permit_admissibility import CASE_RECORDS, codes, draft, in_section, record, rendered_verify
    rec = record("E50", "authority_record", "Câmara Municipal de Cascais handles applications.", status="system_record",
                 title="Câmara Municipal de Cascais")
    address = record("E51", "property_record", "Rua no Centro, Cascais", status="system_record", title="Address")
    records = [*CASE_RECORDS, rec, address]  # an uncited PT "no" can't state the negation (round 2)
    negated = await rendered_verify(in_section("claim", "Câmara Municipal de Cascais handles no applications.",
                                               ["E50"]), records)
    assert negated.outcome != "VERIFIED" and "unverified_zoning" in codes(negated.issues)
    plain = await rendered_verify(in_section("claim", "Câmara Municipal de Cascais handles applications.", ["E50"]),
                                  records)
    assert plain.outcome == "VERIFIED", plain.issues


@pytest.mark.parametrize("text", ["Câmara Municipal de Cascais cannot handle applications.",
                                  "Câmara Municipal de Cascais can't handle applications.",
                                  "Câmara Municipal de Cascais doesn't handle applications."])
async def test_contracted_and_fused_negations_are_grounded_too(text):
    """Codex backlog review round 3 (P2)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "Câmara Municipal de Cascais handles applications.", status="system_record",
                 title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED"


def in_section_claim(text):
    from tests.test_permit_admissibility import in_section
    return in_section("claim", text, ["E50"])


@pytest.mark.parametrize("record_text,text", [
    ("Only Câmara Municipal de Cascais can handle applications.",
     "Câmara Municipal de Cascais cannot handle applications."),
    ("Only Câmara Municipal de Cascais can handle applications.",
     "Câmara Municipal de Cascais can’t handle applications."),
    ("Not only Câmara Municipal de Cascais can handle applications.",
     "Câmara Municipal de Cascais can't handle applications."),
    ("Apenas a Câmara Municipal de Cascais pode tratar pedidos.",
     "A Câmara Municipal de Cascais não pode tratar pedidos."),
    ("Câmara Municipal de Cascais handles applications, except appeals.",
     "Câmara Municipal de Cascais never handles applications."),
])
async def test_td003_a_restriction_never_grounds_the_opposite_negation(record_text, text):
    """TD-003 (Codex 2026-11-01, P1): a restrictive word in the cited record granted *any* negation in the statement,
    so 'Only X can V' verified 'X cannot V'. A negation must now be the record's own."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("Câmara Municipal de Cascais cannot handle appeals. Câmara Municipal de Cascais can handle applications.",
     "Câmara Municipal de Cascais cannot handle applications."),
    ("A Câmara Municipal de Cascais não trata recursos. A Câmara Municipal de Cascais trata pedidos.",
     "A Câmara Municipal de Cascais não trata pedidos."),
    ("Câmara Municipal de Cascais handles applications and documents.",
     "Câmara Municipal de Cascais handles applications without documents."),
    ("Câmara Municipal de Cascais transfers ownership. Câmara Municipal de Cascais cannot inspect deeds.",
     "Câmara Municipal de Cascais cannot transfer ownership."),
    ("A Câmara Municipal de Cascais trata pedidos e documentos.",
     "A Câmara Municipal de Cascais trata pedidos sem documentos."),
])
async def test_td003_r2_a_negation_is_grounded_only_by_the_sentence_that_states_it(record_text, text):
    """TD-003 round 2 (Codex 2026-11-01, P1): a negation in an unrelated sentence of the record, or an unlisted
    negation ('without', 'sem'), verified the opposite claim."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


async def test_td003_r2_the_records_own_negated_sentence_still_verifies():
    """Control: a negation restated from the very sentence that states it keeps verifying."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "Câmara Municipal de Cascais cannot handle appeals.",
                 status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim("Câmara Municipal de Cascais cannot handle appeals."),
                                   [*CASE_RECORDS, rec])
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,title,text", [
    ("Câmara Municipal de Cascais cannot transfer ownership, but can inspect deeds.", "Câmara Municipal de Cascais",
     "Câmara Municipal de Cascais can transfer ownership, but cannot inspect deeds."),
    ("Câmara Municipal de Cascais cannot transfer ownership. Câmara Municipal de Cascais can inspect deeds.",
     "Câmara Municipal de Cascais inspect deeds", "Câmara Municipal de Cascais cannot inspect deeds."),
    ("A Câmara Municipal de Cascais não transfere a propriedade, mas inspeciona escrituras.",
     "Câmara Municipal de Cascais", "A Câmara Municipal de Cascais transfere a propriedade, mas não inspeciona escrituras."),
])
async def test_td003_r3_a_negation_cannot_move_between_clauses_or_borrow_title_words(record_text, title, text):
    """TD-003 round 3 (Codex 2026-11-01, P1/P2): a negated sentence verifies only as a verbatim restatement."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title=title)
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


async def test_td003_r4_numbers_are_part_of_a_negated_sentence():
    """TD-003 round 4 (Codex 2026-11-01, P1): swapping the numbers of a negated sentence reversed the prohibition."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "Application 1 cannot be processed, but application 2 can be processed.",
                 status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(
        in_section_claim("Application 2 cannot be processed, but application 1 can be processed."), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The application fee is not < 10 euros.", "The application fee is not > 10 euros."),
    ("The application fee is not ≤ 10 euros.", "The application fee is not ≥ 10 euros."),
])
async def test_td003_r5_comparison_signs_are_part_of_a_negated_sentence(record_text, text):
    """TD-003 round 5 (Codex 2026-11-02, P1): '<' and '>' were dropped from the sequence. Fixed after the last
    review round: not re-reviewed by Codex."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("Only the owner can transfer ownership.", "The owner can only transfer ownership."),
    ("The owner can transfer ownership.", "Only the owner can transfer ownership."),
    ("The owner can transfer ownership.", "The owner must transfer ownership."),
    ("O dono pode transferir a propriedade.", "O dono deve transferir a propriedade."),
    ("The fee is more than 10 euros and less than 20 euros.", "The fee is less than 10 euros and more than 20 euros."),
    ("The fee is 10 euros or 20 dollars.", "The fee is 10 dollars or 20 euros."),
    ("A taxa é superior a 10 euros e inferior a 20 euros.", "A taxa é inferior a 10 euros e superior a 20 euros."),
    ("A área mínima é 10 m2 e a área máxima é 20 m2.", "A área máxima é 10 m2 e a área mínima é 20 m2."),
    ("The fee is not −10 euros.", "The fee is not 10 euros."),
    ("The owner can transfer ownership.", "The owner can transfer ownership, except to the tenant."),
])
async def test_td003_final_operators_change_the_rule_only_verbatim(record_text, text):
    """TD-003 final review (Codex 2026-11-02, P1): restriction placement, modality, thresholds, units and signs."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("text", [
    "The fee is more than 10 euros and less than 20 euros.",
    "O dono pode transferir a propriedade.",
])
async def test_td003_final_a_verbatim_operator_sentence_still_verifies(text):
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The owner can transfer ownership.", "The owner has to transfer ownership."),
    ("The owner can transfer ownership.", "The owner is to transfer ownership."),
    ("O dono pode transferir a propriedade.", "O dono tem de transferir a propriedade."),
    ("O dono pode transferir a propriedade.", "O dono precisa de transferir a propriedade."),
    ("Transfer of ownership must be possible.", "Transfer of ownership may be possible."),
    ("The fee is 10 euros.", "The fee is - 10 euros."),
    ("The north unit is 10 m2. The south unit is 20 m2.", "The south unit is 10 m2."),
])
async def test_td003_final_r2_obligations_hedges_signs_and_numbers(record_text, text):
    """TD-003 final review round 2 (Codex 2026-11-02, P1)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


# --- Patch (j): a reservation that contradicts its own cited record for the same fact ------------------------------

@pytest.mark.parametrize("record_text,text", [
    ("The deed is verified.", "The deed is not verified."),
    ("The deed is verified.", "The deed has not been confirmed."),
    ("The deed is verified.", "The deed is still unconfirmed."),
    ("A escritura foi verificada.", "A escritura não foi confirmada."),
    ("A escritura está confirmada.", "A escritura ainda não está verificada."),
])
async def test_j_a_reservation_contradicting_its_record_for_the_same_fact_is_refused(record_text, text):
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The deed is verified. The licence is on file.", "The licence is not verified."),  # another fact
    ("The deed is verified. The deed's registration is on file.",
     "The deed's registration is not verified."),  # another scope of the same object
    ("The deed is not verified.", "The deed is not verified."),            # agrees with the record
    ("The deed exists.", "The deed is not verified."),                    # the record establishes nothing
])
async def test_j_a_legitimate_reservation_about_a_different_fact_still_verifies(record_text, text):
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome == "VERIFIED", report.issues


@pytest.mark.parametrize("source_type,record_text,text", [
    ("property_record", "North Street 10. South Street 20.", "South Street 10."),
    ("authority_record", "The transfer must be allowed.", "The transfer may be possible."),
    ("authority_record", "The owner must transfer ownership. The owner is able to sell it.",
     "The owner is able to transfer ownership."),
    ("authority_record", "The fee is 10 euros.", "The fee is – 10 euros."),
])
async def test_td003_final_r3_addresses_hedges_ability_and_dashes(source_type, record_text, text):
    """TD-003 final review round 3 (Codex 2026-11-02, P1)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", source_type, record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("source_type,record_text,text", [
    ("authority_record", "The deed is not verified.", "The deed is verified."),
    ("authority_record", "The owner cannot transfer ownership.", "The owner transfers ownership."),
    ("property_record", "North Street 10, Cascais. South Street 20, Porto.", "North Street 10, Porto."),
])
async def test_td003_final_r4_dropped_operators_and_mixed_addresses(source_type, record_text, text):
    """TD-003 final review round 4 (Codex 2026-11-02, P1)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", source_type, record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


async def test_j_r4_a_negation_in_another_clause_does_not_hide_the_established_fact():
    """Patch (j) review (Codex 2026-11-02, P1)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "The deed is verified, but the plan is not verified.",
                 status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim("The deed is not verified."), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


async def test_td003_final_r5_two_addresses_in_one_cited_sentence():
    """TD-003 final review round 5 (Codex 2026-11-02, P1). Fixed after the last round: not re-reviewed."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "property_record", "North Street 10, Cascais, South Street 20, Porto",
                 status="system_record", title="HABITA property record")
    report = await rendered_verify(in_section_claim("North Street 10, Porto."), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The deed is verified. The plan is pending.", "The plan is not verified and the deed is not verified."),
    ("The deed and title are verified.", "The deed is not verified."),
])
async def test_j_r5_every_reservation_and_conjunct_subjects(record_text, text):
    """Patch (j) review round 5 (Codex 2026-11-02, P1). Fixed after the last round: not re-reviewed."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The deed is not verified and the title is verified.", "The title is not verified."),
    ("The deed is verified. The title is pending.", "The deed and title are not verified."),
])
async def test_j_final_r1_nearest_clause_and_conjoined_reservations(record_text, text):
    """Patch (j) final review r1 (Codex 2026-11-02, P1)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


async def test_j_final_r2_a_listed_subject_is_established_item_by_item():
    """Patch (j) final review r2 (Codex 2026-11-02, P1)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "The deed, title and plan are verified.", status="system_record",
                 title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim("The deed is not verified."), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


async def test_j_final_r3_a_reservation_listed_with_commas():
    """Patch (j) final review r3 (Codex 2026-11-02, P1). Codex's own wording ("… and plan …") is rewritten by HABITA
    into its fixed planning condition (the word "plan"), so this test uses a listed subject without it."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "The deed is verified. The title and the registration are on file.",
                 status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim("The deed, title and registration are not verified."),
                                   [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("established", ["The deed is now verified.", "The deed has now been verified.",
                                         "A escritura foi entretanto verificada."])
async def test_j_final_r4_an_adverb_does_not_hide_the_established_fact(established):
    """Patch (j) final review r4 (Codex 2026-11-02, P1): any word between the verb and the predicate."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", established, status="system_record", title="Câmara Municipal de Cascais")
    claim = "The deed is not verified." if established.startswith("The") else "A escritura não foi verificada."
    report = await rendered_verify(in_section_claim(claim), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues
