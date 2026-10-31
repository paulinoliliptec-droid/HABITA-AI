import type { Lang } from "@/i18n/core";
import { ApiError, apiRequest, parseErrorResponse } from "@/lib/api";
import { config } from "@/lib/config";
import type { Evidence, PermitIntent, PermitMatter, VerificationReport } from "./types";

const base = "/api/permit";

/** Matter operations carry the matter's capability; it never goes into the URL. */
const withToken = (token: string, init: RequestInit = {}): RequestInit => ({
  ...init,
  headers: { ...init.headers, Authorization: `Bearer ${token}` },
});

export function permitStatus(): Promise<{ available: boolean; model: string }> {
  return apiRequest(`${base}/status`);
}

export function createMatter(
  propertyId: string,
  question: string,
  intent?: PermitIntent,
): Promise<{ matter: PermitMatter; access_token: string; detected_language: Lang | null }> {
  return apiRequest(`${base}/matters`, { method: "POST", body: JSON.stringify({ property_id: propertyId, question, intent }) });
}

export function getMatter(matterId: string, token: string, signal?: AbortSignal): Promise<PermitMatter> {
  return apiRequest(`${base}/matters/${matterId}`, withToken(token, { signal }));
}

/** Runs the matter until it waits for input, is verified, escalates, is rejected or fails. Can take a minute. */
export function continueMatter(matterId: string, token: string): Promise<PermitMatter> {
  return apiRequest(`${base}/matters/${matterId}/continue`, withToken(token, { method: "POST" }));
}

export function supplyInputs(matterId: string, token: string, inputs: Record<string, string>): Promise<PermitMatter> {
  return apiRequest(`${base}/matters/${matterId}/inputs`, withToken(token, { method: "POST", body: JSON.stringify({ inputs }) }));
}

export function getEvidence(matterId: string, token: string): Promise<Evidence[]> {
  return apiRequest(`${base}/matters/${matterId}/evidence`, withToken(token));
}

export interface MatterTranslation {
  lang: Lang;
  available: boolean;
  verified: boolean;
  kept_original: number;
  note: string | null;
  texts: Record<string, string>;
}

/** A labelled reading view of the matter's texts. The verified text stays the English one in the matter. */
export function getTranslation(matterId: string, token: string, lang: Lang): Promise<MatterTranslation> {
  return apiRequest(`${base}/matters/${matterId}/translation?lang=${lang}`, withToken(token));
}

export function getVerification(matterId: string, token: string): Promise<VerificationReport> {
  return apiRequest(`${base}/matters/${matterId}/verification`, withToken(token));
}

/** HR-010: a photo, plan or document added to the matter, and what HABITA read in it (never verified). */
export interface MatterFile {
  file_id: string;
  kind: "photo" | "plan" | "document";
  content_type: string;
  size: number;
  sha256: string;
  added_at: string;
  captured_at: string | null;
  gps_check: "none" | "near" | "far";
  gps_distance_m: number | null;
  read_status: "reading" | "read" | "unreadable" | "failed";
  observations: string[];
}

/** The consent text version the user accepts in the files panel. */
export const FILE_CONSENT = "v1";

export function listFiles(matterId: string, token: string): Promise<MatterFile[]> {
  return apiRequest(`${base}/matters/${matterId}/files`, withToken(token));
}

/** The file is sent as the request body, never in the URL; the server checks its content, not its name. */
export function addFile(matterId: string, token: string, file: File, kind: MatterFile["kind"]): Promise<MatterFile> {
  return apiRequest(
    `${base}/matters/${matterId}/files?kind=${kind}&consent=${FILE_CONSENT}`,
    withToken(token, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  );
}

async function fileRequest(path: string, token: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, withToken(token, init));
  } catch {
    throw new ApiError("network_error", "HABITA can't reach its server right now. Check your connection and try again.", 0);
  }
  if (!response.ok) throw await parseErrorResponse(response);
  return response;
}

export async function deleteFile(matterId: string, token: string, fileId: string): Promise<void> {
  await fileRequest(`${base}/matters/${matterId}/files/${fileId}`, token, { method: "DELETE" });
}

/** The kept copy, as a blob the browser can show; the token stays in a header. */
export async function fileContent(matterId: string, token: string, fileId: string): Promise<Blob> {
  return (await fileRequest(`${base}/matters/${matterId}/files/${fileId}/content`, token)).blob();
}
