# HR-003 semantic benchmark — protocol (frozen 2026-11-01)

Correlation: HABITA-HR003-EMPIRICAL-IMPLEMENT-20261101. Instruction: Drive `20261101-HR003-CLAUDE-001`.
Study: Drive `20261101-HR003-SOTA-EMPIRICO`. This protocol is frozen before any holdout case exists.

## What is measured
The **unchanged** MU-9 verifier (render → reconcile citations → rules → final gate, with an always-approving model
reviewer so that a VERIFIED can only come from HABITA's deterministic checks). No model, network or database.
Nothing here changes a verdict or the production runtime.

## Gold classes (4)
| Class | Meaning | Correct system outcome |
|---|---|---|
| SUPPORTED_CONDITIONAL | the cited admissible text states it, for the matter, as a conditional internal assessment | VERIFIED (through the literal-quote path when it is normative content) |
| CONTRADICTED | the cited text says otherwise (negation, number, threshold, exception, deontic operator, subject) | never VERIFIED |
| INSUFFICIENT_INPUT | needs parcel/building facts or a determination HABITA does not hold | never VERIFIED |
| UNTRUSTED_OR_INAPPLICABLE | wrong municipality, authority, instrument or scope; untrusted source; user declaration presented as official | never VERIFIED |

## Typology (frozen; every holdout case must carry one of these `cat` values)
literal_rule · literal_rule_numeric_exception · authority_competence · restriction_literal · negation_flip ·
number_changed · threshold_changed · exception_reversed · exception_omitted · condition_omitted ·
deontic_permission_to_obligation · deontic_obligation_to_permission · exemption_claim · restriction_to_negation ·
restriction_complement_inference · user_fact_contradicted · user_declared_gap · user_declared_as_official ·
parcel_fact_no_evidence · applicability_without_parcel_facts · procedure_without_operation_facts · licence_confusion ·
classification_to_permission · other_municipality_source · untrusted_source · wrong_authority ·
wrong_municipality_instrument · scope_overreach · critical_licence_confirmed · critical_exemption ·
citation_true_proposition_wrong · same_word_other_subject · translation_pt_en.
Not yet covered (need fixtures that do not exist offline): article in force on the wrong date (no temporal
versions in the fixtures), TrustPin retired / change during commit / rollback (covered instead by the C2 replica-set
suite `backend/tests/test_permit_commit_c2_replica.py`), area_center vs rooftop address, free answer "yes"/"areas" to a
structured question (TD-061, workflow level, not verifier level).

## Splits
- **dev** (`experiments/hr003_semantic_benchmark/cases_dev.json`, 40 cases): written by the builder (Claude Code).
  Used to build and debug. Results on dev are not evidence of generalisation.
- **holdout** (≥ 40 cases): to be written by an annotator independent of the builder (Muse Code / ChatGPT / a jurist),
  in the same JSON shape, with the typology above, and kept out of the builder's sight until the final evaluation.
  **Not created yet.** The builder must not write it.

## Annotation
Dev labels: single annotator (builder), not double-reviewed, not reviewed by a lawyer. Holdout: two independent
annotators on a blind sample; disagreement → `UNKNOWN/REVIEW`, excluded from metrics and listed.

## Runs per case
5 sections (claim, procedure, risk, next action, conclusion where applicable) × 2 bases (`none`,
`general_planning_explanation`) as free text; plus 5 literal-quote runs (`general_rule`) when the case has a `quote`.
A negative is a **false VERIFIED** if any run verifies. A positive is **correctly handled** if every literal-quote
run verifies (when it has a quote) or every free-text run verifies (when it has none).

## Metrics
false VERIFIED (absolute and per category), its exact one-sided 95 % upper bound when 0 are seen
(1 − 0.05^(1/n) ≈ 3/n), false REJECTED / coverage of positives, metamorphic pairs whose verdict moved the right way,
issue codes per case, latency (deterministic pipeline, ms per run). '0 false VERIFIED observed' is a gate for this
set, never a universal guarantee.

## Cost
CPU only; ~1 s per 40 cases. No paid call. An NLI shadow arm (B5) would add a local model download (see the decision
matrix) and is not run without the owner's decision.
