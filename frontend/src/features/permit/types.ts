export type PermitIntent = "unit_conversion" | "change_of_use" | "interior_works" | "general_overview";

// Mirrors backend/app/schemas/permit.py (fields the UI uses).

export type MatterState =
  | "PLANNING"
  | "INVESTIGATING"
  | "NEEDS_INPUT"
  | "DRAFT_READY"
  | "VERIFYING"
  | "VERIFIED"
  | "ESCALATE"
  | "REJECTED"
  | "FAILED";

export const STABLE_STATES: ReadonlySet<MatterState> = new Set(["NEEDS_INPUT", "VERIFIED", "ESCALATE", "REJECTED", "FAILED"]);

export type ConclusionAnswer = "likely_possible" | "conditional" | "likely_not_possible" | "undetermined";

export interface MissingInput {
  input_key: string;
  question: string;
  reason: string;
  required: boolean;
  owner: "USER";
}

export interface Claim {
  claim_id: string;
  text: string;
  material: boolean;
  evidence_ids: string[];
}

export interface Draft {
  status: "UNVERIFIED";
  revision: number;
  conclusion: { answer: ConclusionAnswer; summary: string; evidence_ids: string[] };
  claims: Claim[];
  /** What only the authority can settle; derived from the checklist by HABITA. */
  conditions: { item_key: string; text: string }[];
  procedure: { step: string; description: string; evidence_ids: string[] }[];
  risks: { text: string; evidence_ids: string[] }[];
  next_actions: { text: string; evidence_ids: string[] }[];
}

export interface ProgressEvent {
  state: MatterState;
  label: string;
  at: string;
}

export interface PermitMatter {
  matter_id: string;
  property_id: string;
  question: string;
  state: MatterState;
  intent: PermitIntent | "out_of_scope" | null;
  requested_intent: PermitIntent | null;
  missing_inputs: MissingInput[];
  draft: Draft | null;
  escalation_reason: string | null;
  unresolved_items: string[];
  progress: ProgressEvent[];
  error: { code: string; message: string; failed_state: MatterState } | null;
  latest_verification_id: string | null;
  created_at: string;
  /** "verified_assessment" means HABITA's checks passed, never that a permit was granted. */
  assessment_status: string;
  authority_approval: "not_obtained";
  outcome_note: string | null;
}

export interface SourceProvenance {
  source_id: string;
  basis: "official_text" | "curated_reference" | "planning_context";
  trust_status: "candidate" | "validated" | "trusted" | "retired";
  version: string | null;
  locator: string | null;
  snapshot_id: string | null;
  sha256: string | null;
  retrieved_at: string | null;
}

export interface Evidence {
  evidence_id: string;
  source_type:
    | "property_record"
    | "jurisdiction_record"
    | "authority_record"
    | "regulatory_source"
    | "planning_context"
    | "user_statement";
  source_title: string;
  source_reference: string;
  source_url: string | null;
  jurisdiction_id: string;
  excerpt: string;
  verification_status: "system_record" | "curated_reference" | "official_text" | "user_declared";
  /** Registry source behind regulatory and planning evidence. */
  provenance?: SourceProvenance | null;
}

export interface VerificationReport {
  outcome: "VERIFIED" | "NEEDS_INPUT" | "ESCALATE" | "REJECTED";
  issues: { code: string; message: string }[];
  checks: Record<string, boolean>;
}
