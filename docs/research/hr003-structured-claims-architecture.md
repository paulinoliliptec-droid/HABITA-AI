# Structured legal claims — experimental architecture (proposal, not built)

Owner direction 2026-11-02: legal text freely produced by the model can't be certified by word matching alone. This
design replaces free legal prose in VERIFIED answers with typed claims that HABITA checks field by field and renders
itself. It keeps MU-9's rule: nothing a model writes can raise a verdict.

## 1. The claim object (what the model may propose)
```json
{
  "claim_id": "K1",
  "kind": "norm | case_fact | authority | reservation | instruction",
  "subject":   {"text": "moradias unifamiliares", "span": [s, e]},
  "operator":  "PERMITTED | OBLIGATORY | PROHIBITED | EXEMPT | NOT_DETERMINED",
  "action":    {"text": "ampliação até 20 % da área existente", "span": [s, e]},
  "conditions":[{"text": "área de construção até 200 m2", "span": [s, e]}],
  "exceptions":[{"text": "edifícios classificados", "span": [s, e]}],
  "quantities":[{"value": 20, "unit": "%", "relation": "<=", "span": [s, e]}],
  "scope":     {"jurisdiction": "pt/lisboa/cascais", "applies_to": "general | this_parcel"},
  "source":    {"evidence_id": "E30", "source_id": "cascais-pdm", "snapshot_id": "ss_…", "article": "900.º",
                "paragraph": "1", "trust_version": 0},
  "version":   {"in_force_from": "…", "in_force_to": null, "checked_at": "…"},
  "proof":     [{"evidence_id": "E30", "sentence_index": 0, "char_span": [s, e]}]
}
```
Every text field is a **span** of the cited official sentence, never free text. Spans are verified by offsets, so
"moved" or "recombined" words are impossible by construction (closes the residual P2 class).

## 2. Deterministic checks (each must pass, else REJECTED or ESCALATE)
1. **Provenance:** evidence admissible (TrustPin, jurisdiction chain, official text, snapshot sha256); article and
   paragraph from the structural parser (TD-002), not from text guesses.
2. **Spans:** every span lies inside the one cited sentence; subject, action, conditions and exceptions do not
   overlap; **every** exception and condition span present in the sentence must be listed (no dropped exception).
3. **Operator:** the operator is computed by HABITA from a closed, reviewed lexicon on the sentence's modal span
   (deve/é obrigatório → OBLIGATORY, pode/é admitido → PERMITTED, é proibido/não pode → PROHIBITED); the model's
   operator must equal it. Ambiguity → NOT_DETERMINED → never VERIFIED.
4. **Quantities:** value, unit and relation parsed from the span; must match exactly.
5. **Version:** the snapshot is the source's current one at commit time; a revoked/superseded article (registry
   status, `in_force_to` set) → INAPPLICABLE.
6. **Scope:** `applies_to: this_parcel` requires an authoritative parcel determination (resolved planning context) and
   the parcel facts the conditions name (area, classification…) from admissible records; user declarations can fill
   only private facts and are labelled as such; otherwise the claim is shown as a general rule with a condition, not
   as applying to the property.
7. **Rendering:** the answer text is rendered by HABITA from the verified fields (PT and EN templates), quoting the
   spans; the model's own wording is never shown as verified.

## 3. Where NLI fits
The NLI auditor (shadow) scores the model's optional free-text explanation against the cited sentence and flags
CONTRADICTED; it can only add a warning or an escalation, never a VERIFIED.

## 4. Experiment plan (isolated, no production change)
- `experiments/hr003_structured_claims/`: schema (pydantic), span checker, operator lexicon, renderer.
- Inputs: the dev set + the holdout, plus hand-made structured versions of the E13/E30/E1/E7 records.
- Metrics: false VERIFIED (target 0), coverage of SUPPORTED cases, cases where the operator lexicon returns
  NOT_DETERMINED, latency.
- Prerequisites: the structural parser of articles/paragraphs (TD-002), version metadata in the source registry.
- Decision gate: adopt only if it reaches 0 false VERIFIED on dev + holdout with coverage ≥ the current verifier's.

## 5. Owner decision 2026-11-02: fields every claim carries, and the path from the TD-003 hotfix

The lexical fix loop is closed (five Codex rounds on patch (j) and TD-061, five Muse rounds on the TD-003 hotfix, each
finding a new wording). The TD-003 hotfix candidate (`hr003/td003-hotfix-candidate`) is the first step of this design:
a free sentence verifies only as one whole cited sentence or as a canonical sentence HABITA derives from a structured
record (competence, location). The next steps replace free text with claims carrying these typed fields:

| Field | Meaning | Checked against |
|---|---|---|
| `legal_subject` | who or what the rule or fact is about (span) | the cited sentence's subject span; never moved between phrases (TD-003 attachment class) |
| `predicate` + `deontic_operator` | OBLIGATORY / PERMITTED / PROHIBITED / EXEMPT / NOT_DETERMINED | HABITA's operator lexicon on the modal span (§2.3) |
| `fact_or_action` | what is permitted, required, or stated (span) | the cited sentence |
| `conditions`, `exceptions` | every one present in the sentence (spans) | none may be dropped (§2.2) |
| `jurisdiction` + `in_force` (from, to) | where and when the rule applies | the source registry version metadata; a superseded rule is INAPPLICABLE |
| `time` (case facts) | when a case fact held ("before the fire", "until the sale") | the record's own time phrase; a fact without its time is not the record's fact |
| `official_evidence` | evidence id, source id, snapshot id + sha256, article, paragraph | TrustPin and the structural parser (TD-002) |
| `parcel_identity` | the property the claim applies to (property id, binding version) | C2 identity binding; `applies_to: this_parcel` needs an authoritative parcel determination |
| `trust_state` | `official_text` / `system_record` / `user_declared` / `unverified` | the evidence status; a user declaration never fills an official field |

Case facts (property, authority, jurisdiction records) become typed records with roles: `{agent, action, object,
attachments: [{role: "of" | "for" | "in", head, dependent}], time, place}`. HABITA renders them; the model can cite
them by id but cannot rephrase them. Structured inputs already exist for the user's answers (TD-061 typed criteria:
unit areas bound to units, ownership kind, work elements).

### NLI / open-weight model
The NLI model (multilingual, PT-PT) runs in shadow on every free-text explanation and on every verifier decision: it
labels SUPPORTED / CONTRADICTED / NOT_ENOUGH_INFO. It can add a warning or escalate; it can never raise a verdict and
never replaces an MU-9 rule. Shadow data feed the benchmark (dev + independent holdout) before any gate uses it.

### Order of work
1. TD-003 hotfix candidate (structural containment, this branch's twin) — owner review, then publication decision.
2. Case-fact records with roles and time (property, authority, jurisdiction): rendering only, no free restatement.
3. Structured norm claims with spans (§1–2) behind an experiment flag; benchmark: false VERIFIED = 0 on dev + holdout.
4. NLI shadow measurement; TD-001 / TD-031 / TD-033 gates as in `hr003-stage2-protocols.md`.
