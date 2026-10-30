import { msg } from "@/i18n/core";
import { apiRequest } from "@/lib/api";
import type { BadgeTone } from "@/components/ui/Badge";

// Mirrors backend/app/schemas/sources.py (fields the UI uses).

export type PlanningStatus = "resolved" | "partial" | "requires_manual_confirmation" | "not_supported";

export interface DocumentToConsult {
  source_id: string;
  title: string;
  designation: string | null;
  official_url: string | null;
  reason: string;
}

export interface PlanningContext {
  status: PlanningStatus;
  instrument: { source_id: string; title: string; version: string | null; official_url: string | null } | null;
  classification: { label: string; land_class: string | null; category: string | null } | null;
  documents_to_consult: DocumentToConsult[];
  competent_authority: { id: string; name: string } | null;
  guidance: string;
  sources_verified_on: string | null;
  source_retrieved_at: string | null;
}

export interface OfficialSource {
  source_id: string;
  jurisdiction_id: string;
  title: string;
  official_url: string | null;
  designation: string | null;
  retrieval_method: string;
  snapshot_retrieved_at: string | null;
}

export interface PlanningContextResponse {
  planning_context: PlanningContext;
  sources: OfficialSource[];
}

export function getPlanningContext(propertyId: string, signal?: AbortSignal): Promise<PlanningContextResponse> {
  return apiRequest(`/api/property/${encodeURIComponent(propertyId)}/planning-context`, { signal });
}

export const PLANNING_STATUS: Record<PlanningStatus, { label: string; tone: BadgeTone }> = {
  resolved: { label: msg("From the official layer"), tone: "positive" },
  partial: { label: msg("Partly determined"), tone: "warning" },
  requires_manual_confirmation: { label: msg("Requires confirmation"), tone: "warning" },
  not_supported: { label: msg("Not yet modelled"), tone: "neutral" },
};

/** "PDM-Cascais" from "Plano Diretor Municipal de Cascais (PDM-Cascais) — Regulamento". */
export function instrumentName(title: string): string {
  return title.match(/\(([^)]+)\)/)?.[1] ?? title.split(" — ")[0];
}

/** What the official text was checked against, e.g. "Official text retrieved 28 Oct 2026". */
export function provenanceDate(iso: string | null, prefix: string, locale = "en-GB"): string | null {
  if (!iso) return null;
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${prefix} ${date.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}`;
}

/** The regulation's official text, if HABITA has retrieved and indexed it (machine-readable instruments only). */
export function officialTextSource(sources: OfficialSource[], instrumentId: string | undefined): OfficialSource | undefined {
  return sources.find((s) => s.source_id === instrumentId && s.snapshot_retrieved_at);
}
