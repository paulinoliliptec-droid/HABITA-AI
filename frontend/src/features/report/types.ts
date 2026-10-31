// Mirrors backend/app/schemas/report.py: the one report model the map post-its (HR-004) and the PDF (HR-006) share.

export type ReportStatus = "VERIFIED" | "REJECTED" | "PENDING_CONFIRMATION";

export interface ReportEvidence {
  evidence_id: string;
  title: string;
  reference: string;
  url: string | null;
  source_type: string;
  verification_status: string;
  source_id: string | null;
  version: string | null;
  snapshot_id: string | null;
  sha256: string | null;
}

export interface ReportStatement {
  section: "finding" | "procedure" | "risk" | "next_action";
  label: string;
  text: string;
  step: string | null;
  evidence_ids: string[];
}

export interface PermitReport {
  generated_at: string;
  property: {
    property_id: string;
    address: string;
    lat: number;
    lng: number;
    precision: string;
    jurisdiction: string[];
    authority: string | null;
  };
  planning: {
    status: string;
    verified_zoning: boolean;
    classification: string | null;
    instrument: string | null;
    instrument_version: string | null;
    reasons: string[];
    documents_to_consult: { title: string; designation: string | null; url: string | null; reason: string }[];
    guidance: string;
  };
  sources: { source_id: string; title: string; publisher: string | null; url: string | null; version: string | null; status: string }[];
  assessment: {
    matter_id: string;
    question: string;
    status: ReportStatus;
    status_reason: string;
    content_verified: boolean;
    conclusion_answer: string | null;
    conclusion_summary: string | null;
    conclusion_evidence_ids: string[];
    statements: ReportStatement[];
    conditions: string[];
    issues: string[];
    verification?: { outcome: string; current: boolean } | null;
    evidence: ReportEvidence[];
  } | null;
  pending: string[];
  demo: boolean;
  disclaimer: string;
  language?: "en" | "pt";
  translation?: { available: boolean; kept_original: number; note: string | null } | null;
}

/** HR-007: the sentences spoken from a report. `audio`: synthesised speech exists for this language. */
export interface VoiceScript {
  version: string;
  lines: string[];
  audio: boolean;
}
