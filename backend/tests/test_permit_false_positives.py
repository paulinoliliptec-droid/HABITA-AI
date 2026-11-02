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
    # TD-003 structural (2026-11-02): the canonical competence sentence keeps the whole activity, parentheses
    # included; without them it is refused (availability cost, registered).
    text = ("Câmara Municipal de Cascais is responsible for licensing of urban operations, including building permits "
            "(licenciamento urbanístico).")
    assert await outcomes(text, bases=("none",)) == {"VERIFIED"}
    shorter = "Câmara Municipal de Cascais is responsible for licensing of urban operations, including building permits."
    assert "VERIFIED" not in await outcomes(shorter, bases=("none",))


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


async def test_td003_final_r5_two_addresses_in_one_cited_sentence():
    """TD-003 final review round 5 (Codex 2026-11-02, P1). Fixed after the last round: not re-reviewed."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "property_record", "North Street 10, Cascais, South Street 20, Porto",
                 status="system_record", title="HABITA property record")
    report = await rendered_verify(in_section_claim("North Street 10, Porto."), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The owner can transfer ownership, except to the tenant.", "The owner can transfer ownership."),
    ("Except to the tenant, the owner can transfer ownership.", "The owner can transfer ownership."),
    ("O dono pode transferir a propriedade, exceto para o inquilino.", "O dono pode transferir a propriedade."),
    ("The fee is 10 euros.", "The fee is euros."),
    ("The owner can transfer ownership.", "Transfer is necessary."),
    ("O dono pode transferir a propriedade.", "A transferência é necessária."),
    ("The owner can transfer ownership.", "The owner could transfer ownership."),
    ("Higher fees apply to the north unit. Lower fees apply to the south unit.", "Lower fees apply to the north unit."),
])
async def test_muse_r1_affix_deletion_dropped_numbers_and_unlisted_modals(record_text, text):
    """Muse Code review of the TD-003 hotfix, round 1 (2026-11-02): P0 affix deletion, P1/P2 findings."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The north unit has a balcony. The south unit has a garage.", "The north unit has a garage."),
    ("The north unit is large. The south unit is small.", "The north unit is small."),
    ("North Street, Cascais. South Street, Porto.", "North Street, Porto."),
    ("A unidade norte tem varanda. A unidade sul tem garagem.", "A unidade norte tem garagem."),
    ("The owner transferred ownership to Ana. The tenant leased the shop.", "The owner leased the shop."),
    ("The building has two floors. The annex has three floors.", "The building has three floors."),
    ("O edifício tem dois pisos. O anexo tem três pisos.", "O edifício tem três pisos."),
    ("The building has two floors.", "The building has floors."),
])
async def test_muse_r2_recombination_across_sentences_and_number_words(record_text, text):
    """Muse Code review of the TD-003 hotfix, round 2 (2026-11-02, P0)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The north unit has a balcony and the south unit has a garage.", "The north unit has a garage."),
    ("The north unit has a balcony, the south unit has a garage.", "The north unit has a garage."),
    ("The north unit is large and the south unit is small.", "The north unit is small."),
    ("The owner transferred ownership to Ana and the tenant leased the shop.", "The owner leased the shop."),
    ("North Street, Cascais, South Street, Porto.", "North Street, Porto."),
    ("A unidade norte tem varanda e a unidade sul tem garagem.", "A unidade norte tem garagem."),
    ("A unidade norte é grande e a unidade sul é pequena.", "A unidade norte é pequena."),
    ("O dono transferiu a propriedade para a Ana e o inquilino arrendou a loja.", "O dono arrendou a loja."),
])
async def test_muse_r3_recombination_within_one_cited_sentence(record_text, text):
    """Muse Code review of the TD-003 hotfix, round 3 (2026-11-02, P0)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


@pytest.mark.parametrize("record_text,text", [
    ("The north unit has a balcony and the south unit has a garage.", "The north unit has a balcony."),
    ("A unidade norte é grande e a unidade sul é pequena.", "A unidade sul é pequena."),
])
async def test_td003_structural_a_clause_restated_on_its_own_no_longer_verifies(record_text, text):
    """TD-003 structural containment (owner 2026-11-02): availability cost, registered. A clause of a cited sentence
    is not certified on its own (the rest of the sentence may scope it); the whole sentence still verifies."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues
    whole = await rendered_verify(in_section_claim(record_text), [*CASE_RECORDS, rec])
    assert whole.outcome == "VERIFIED", whole.issues


@pytest.mark.parametrize("source_type,record_text,text", [
    ("property_record", "North Street, Cascais, South Street, Porto.", "North Street, Porto."),
    ("authority_record", "The north unit has a balcony plus the south unit has a garage.", "The north unit has a garage."),
    ("authority_record", "The north unit has a balcony, with the south unit having a garage.", "The north unit has a garage."),
    ("authority_record", "The tenant who leased the shop owns the north unit.", "The tenant owns the shop."),
    ("authority_record", "A unidade norte tem varanda, com a unidade sul a ter garagem.", "A unidade norte tem garagem."),
])
async def test_muse_r4_numberless_addresses_and_more_joiners(source_type, record_text, text):
    """Muse Code review of the TD-003 hotfix, round 4 (2026-11-02, P0)."""
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", source_type, record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", report.issues


#: TD-003 structural containment (owner 2026-11-02). Muse r5 P0-1/P0-2 and the same class written for the battery:
#: attachment ("of", "for", participles, PT "de/do/da"), dropped conditions, times and scopes, and a passive swap.
STRUCTURAL_ATTACKS = [
    ("The owner of the south unit sold the north unit.", "The owner sold the south unit."),
    ("The owner of the north unit leased the shop.", "The owner leased the north unit."),
    ("O dono da unidade sul vendeu a unidade norte.", "O dono vendeu a unidade sul."),
    ("The tenant leasing the shop owns the north unit.", "The tenant owns the shop."),
    ("The owner of the south unit sold the north unit.", "The south unit sold the north unit."),
    ("The lawyer for the tenant signed the deed.", "The tenant signed the deed."),
    ("O inquilino arrendando a loja é dono da unidade norte.", "O inquilino é dono da loja."),
    ("O advogado do inquilino assinou a escritura.", "O inquilino assinou a escritura."),
    ("If the works are approved, the owner can sell the shop.", "The owner can sell the shop."),
    ("Se as obras forem aprovadas, o dono pode vender a loja.", "O dono pode vender a loja."),
    ("Before the fire, the building had three floors.", "The building had three floors."),
    ("Until the sale, the tenant occupied the shop.", "The tenant occupied the shop."),
    ("In the north unit, the owner removed the wall.", "The owner removed the wall."),
    ("The north unit was sold by the owner to the tenant.", "The tenant was sold the north unit by the owner."),
    ("Only autonomous units can be the object of horizontal property: units that are independent.",
     "Only autonomous units can be the object of horizontal property."),
    ("Câmara Municipal de Cascais: Licensing of urban operations, including building permits.",
     "Câmara Municipal de Cascais handles building permits."),
    ("Câmara Municipal de Cascais: Licensing of urban operations, including building permits.",
     "Building permits is handled by Câmara Municipal de Cascais."),
]


@pytest.mark.parametrize("section", ["conclusion", "claim", "procedure", "risk", "next action"])
@pytest.mark.parametrize("record_text,text", STRUCTURAL_ATTACKS)
async def test_td003_structural_a_free_sentence_verifies_only_whole(record_text, text, section):
    from tests.test_permit_admissibility import CASE_RECORDS, in_section, record, rendered_verify
    rec = record("E50", "authority_record", record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section(section, text, ["E50"]), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", (section, report.issues)


@pytest.mark.parametrize("text", [
    "Licensing of urban operations, including building permits is handled by Câmara Municipal de Cascais.",
    "Câmara Municipal de Cascais handles licensing of urban operations, including building permits.",
    "Câmara Municipal de Cascais is responsible for licensing of urban operations, including building permits.",
    "The owner of the south unit sold the north unit.",
])
async def test_td003_structural_whole_and_canonical_sentences_still_verify(text):
    from tests.test_permit_admissibility import CASE_RECORDS, record, rendered_verify
    rec = record("E50", "authority_record", "Câmara Municipal de Cascais: Licensing of urban operations, including "
                 "building permits. The owner of the south unit sold the north unit.", status="system_record",
                 title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section_claim(text), [*CASE_RECORDS, rec])
    assert report.outcome == "VERIFIED", report.issues


#: TD-003 candidate review r1 (Codex 2026-11-02): location records, parentheses, semicolons and address prefixes.
CANDIDATE_R1_ATTACKS = [
    ("property_record", "The owner of the south unit sold the north unit.", "The owner sold the south unit."),
    ("jurisdiction_record", "The owner of the south unit sold the north unit.", "The owner sold the south unit."),
    ("property_record", "The tenant leasing the shop owns the north unit.", "The tenant owns the shop."),
    ("jurisdiction_record", "The tenant leasing the shop owns the north unit.", "The tenant owns the shop."),
    ("property_record", "O inquilino da loja possui a unidade norte.", "O inquilino possui a loja."),
    ("authority_record", "Câmara Municipal de Cascais: licensing of urban operations (except alterations).",
     "Licensing of urban operations is handled by Câmara Municipal de Cascais."),
    ("authority_record", "Câmara Municipal de Cascais: licensing of urban operations (only after approval).",
     "Licensing of urban operations is handled by Câmara Municipal de Cascais."),
    ("regulatory_source", "The owner can sell; except to the tenant.", "The owner can sell."),
    ("authority_record", "The owner can sell; only after approval.", "The owner can sell."),
    ("authority_record", "The owner can sell; if the tenant agrees.", "The owner can sell."),
    ("authority_record", "The owner can sell; in the north district.", "The owner can sell."),
    ("property_record", "Old North Street 10, Porto.", "North Street 10, Porto."),
    ("property_record", "Old North Street, Porto.", "North Street, Porto."),
    ("property_record", "Old North Street 10, Porto.", "The property is located at North Street 10, Porto."),
    # Muse candidate review r1 (P0-1, P1-1): the same on location records, and parentheses that restrict.
    ("property_record", "In the north unit, the owner removed the wall.", "The owner removed the wall."),
    ("jurisdiction_record", "The north unit was sold by the owner to the tenant.",
     "The north unit was sold by the tenant to the owner."),
    ("property_record", "After the inspection, the tenant occupied the shop.", "The tenant occupied the shop."),
    ("property_record", "Urban land rules for housing.", "Housing land rules for urban."),
    ("jurisdiction_record", "The lawyer for the tenant signed the deed.", "The tenant signed the deed."),
    ("authority_record", "Câmara Municipal de Cascais: Licensing of urban operations (only appeals).",
     "Câmara Municipal de Cascais handles licensing of urban operations."),
    ("authority_record", "Câmara Municipal de Cascais: Licensing of urban operations (not building permits).",
     "Licensing of urban operations is handled by Câmara Municipal de Cascais."),
]


@pytest.mark.parametrize("section", ["conclusion", "claim", "procedure", "risk", "next action"])
@pytest.mark.parametrize("source_type,record_text,text", CANDIDATE_R1_ATTACKS)
async def test_td003_candidate_r1_no_false_verified(source_type, record_text, text, section):
    from tests.test_permit_admissibility import CASE_RECORDS, in_section, record, rendered_verify
    rec = record("E50", source_type, record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section(section, text, ["E50"]), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", (section, report.issues)


#: TD-003 candidate review r1 (Muse 2026-11-02, P0-2/P0-3): a question or reservation carrying a recombined case fact,
#: a swapped number, a dropped exception, threshold or condition.
CARRIED_ATTACKS = [
    ("authority_record", "The owner of the south unit sold the north unit.",
     "The owner sold the south unit must be confirmed with the Câmara Municipal de Cascais."),
    ("authority_record", "The owner of the south unit sold the north unit.",
     "Confirm the owner sold the south unit with the Câmara Municipal de Cascais."),
    ("authority_record", "The owner of the south unit sold the north unit.", "The owner sold the south unit requires confirmation."),
    ("authority_record", "The owner of the south unit sold the north unit.", "The owner sold the south unit has not yet been determined."),
    ("authority_record", "O dono da unidade sul vendeu a unidade norte.", "O dono vendeu a unidade sul deve ser confirmado."),
    ("authority_record", "The tenant leasing the shop owns the north unit.", "The tenant owns the shop must be confirmed."),
    ("authority_record", "The north unit is 10 m2. The south unit is 20 m2.",
     "Confirm whether the south unit is 10 m2 with the Câmara Municipal de Cascais."),
    ("authority_record", "The north unit is 10 m2. The south unit is 20 m2.",
     "Whether the south unit is 10 m2 must be confirmed with the Câmara Municipal de Cascais."),
    ("regulatory_source", "The owner can transfer ownership, except to the tenant.", "Confirm whether the owner can transfer ownership."),
    ("regulatory_source", "The fee is more than 10 euros and less than 20 euros.", "Confirm whether the fee is less than 10 euros."),
    ("regulatory_source", "If the works are approved, the owner can sell the shop.", "Confirm whether the owner can sell the shop."),
]


@pytest.mark.parametrize("section", ["conclusion", "claim", "procedure", "risk", "next action"])
@pytest.mark.parametrize("source_type,record_text,text", CARRIED_ATTACKS)
async def test_td003_candidate_r1_a_question_or_reservation_carries_no_false_statement(source_type, record_text,
                                                                                       text, section):
    from tests.test_permit_admissibility import CASE_RECORDS, in_section, record, rendered_verify
    rec = record("E50", source_type, record_text, status="system_record", title="Câmara Municipal de Cascais")
    report = await rendered_verify(in_section(section, text, ["E50"]), [*CASE_RECORDS, rec])
    assert report.outcome != "VERIFIED", (section, report.issues)
