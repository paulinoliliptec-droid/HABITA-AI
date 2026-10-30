import type { Lang } from "@/i18n/core";
import { apiRequest, ApiError, parseErrorResponse } from "@/lib/api";
import { config } from "@/lib/config";
import type { MatterCapability } from "@/features/permit/capability";
import type { PermitReport } from "./types";

/** The matter's report when this browser holds its capability; otherwise the public property report. */
function reportPath(propertyId: string, own: MatterCapability | null): { path: string; init: RequestInit } {
  return own
    ? { path: `/api/permit/matters/${own.matterId}/report`, init: { headers: { Authorization: `Bearer ${own.token}` } } }
    : { path: `/api/property/${encodeURIComponent(propertyId)}/report`, init: {} };
}

export function getReport(propertyId: string, own: MatterCapability | null, lang: Lang, signal?: AbortSignal): Promise<PermitReport> {
  const { path, init } = reportPath(propertyId, own);
  return apiRequest<PermitReport>(`${path}?lang=${lang}`, { ...init, signal });
}

/** Downloads the PDF of the same report. The capability travels in the header, never in a URL. */
export async function downloadReportPdf(propertyId: string, own: MatterCapability | null, lang: Lang): Promise<void> {
  const { path, init } = reportPath(propertyId, own);
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}.pdf?lang=${lang}`, init);
  } catch {
    throw new ApiError("network_error", "HABITA can't reach its server right now. Check your connection and try again.", 0);
  }
  if (!response.ok) throw await parseErrorResponse(response);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `habita-${own?.matterId ?? propertyId}.pdf`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Lets the map refresh its post-its when the permit matter on this page changes. */
const listeners = new Set<() => void>();
export function onReportChanged(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function reportChanged(): void {
  listeners.forEach((listener) => listener());
}
