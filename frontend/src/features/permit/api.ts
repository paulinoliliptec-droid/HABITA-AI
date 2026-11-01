import type { Lang } from "@/i18n/core";
import { msg } from "@/i18n/core";
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
  checks: FileCheck[];
  people_visible: boolean | null;
  is_plan: boolean | null;
}

/** What a file can point out; the server sends the key, and this is HABITA's fixed wording for it. */
export const CHECK_TEXT = {
  several_entrances: msg(
    "Your file seems to show more than one entrance. If you plan to divide the property, confirm with the Câmara Municipal that each unit would have its own exit to a common part or the street.",
  ),
  possible_structural_wall: msg(
    "Your file shows walls that may carry weight. Before removing or opening any wall, confirm with a structural engineer and the Câmara Municipal.",
  ),
  kitchen_or_bathroom: msg(
    "Your file shows a kitchen or a bathroom. If you plan to move water or drainage points, confirm with the Câmara Municipal whether that needs prior control.",
  ),
  facade_or_window: msg(
    "Your file shows a facade, a window or a balcony. Before changing them, confirm with the Câmara Municipal whether the works need prior control.",
  ),
  several_floors: msg("Your file shows more than one floor. Confirm the licensed use of each floor with the Câmara Municipal."),
} as const;
export type FileCheck = keyof typeof CHECK_TEXT;

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

/** HR-011: the user's own figures; every one is optional and labelled as declared. */
export interface AffordInputs {
  area_m2: number | null;
  property_type: "apartment" | "house" | null;
  quote_low: number | null;
  quote_high: number | null;
  budget: number | null;
  rate_percent: number | null;
  years: number | null;
  down_payment: number | null;
}

export interface AffordFigure {
  label: string;
  low: number;
  high: number;
  likely: number | null;
  per_m2_low: number | null;
  per_m2_high: number | null;
  source: string;
  author: string | null;
  source_kind: "reference_table" | "user_declared" | "official_statistics" | "computed";
  as_of: string | null;
  url: string | null;
}

export interface AffordScenario {
  key: "lower" | "likely" | "higher";
  cost: number;
  monthly_payment: number | null;
  financed: number | null;
  within_budget: boolean | null;
  assumptions: string[];
  moves_it: string[];
}

export interface AffordReport {
  inputs: AffordInputs;
  costs: AffordFigure[];
  costs_note: string | null;
  fees_note: string;
  scenarios: AffordScenario[];
  financing_note: string | null;
  formula: string;
  valuation: AffordFigure[];
  valuation_note: string | null;
  disclaimer: string;
}

export function getAfford(matterId: string, token: string): Promise<AffordReport> {
  return apiRequest(`${base}/matters/${matterId}/afford`, withToken(token));
}

export function saveAfford(matterId: string, token: string, inputs: AffordInputs): Promise<AffordReport> {
  return apiRequest(`${base}/matters/${matterId}/afford`, withToken(token, { method: "PUT", body: JSON.stringify(inputs) }));
}

/** HR-012: a before/after concept made from one of the user's photos; an illustration only. */
export interface Concept {
  concept_id: string;
  file_id: string;
  change: string;
  change_label: string;
  created_at: string;
  /** The room the user chose to divide (one-more-bedroom view only); `label` is as read on the plan. */
  room?: { id: string; label: string; type_label: string; place_label: string; floor: number | null } | null;
}

/** HR-012: a room of a plan the user may choose to divide for the one-more-bedroom view. */
export interface OfferedRoom {
  id: string;
  label: string;
  type_label: string;
  area: number | null;
  place_label: string;
  floor: number | null;
  largest: boolean;
  small: boolean;
}

export interface RoomOffer {
  status: "ok" | "unreadable" | "none";
  floors: (number | null)[];
  rooms: OfferedRoom[];
  excluded: { label: string; type: string; reason: "type" | "no_place" | "same_as_another" }[];
}

export function conceptRooms(matterId: string, token: string, fileId: string): Promise<RoomOffer> {
  return apiRequest(`${base}/matters/${matterId}/concepts/rooms/${fileId}`, withToken(token));
}

export function conceptOptions(
  matterId: string,
  token: string,
): Promise<{ key: string; label: string; source: "photo" | "plan" }[]> {
  return apiRequest(`${base}/matters/${matterId}/concepts/options`, withToken(token));
}

export function listConcepts(matterId: string, token: string): Promise<Concept[]> {
  return apiRequest(`${base}/matters/${matterId}/concepts`, withToken(token));
}

export function createConcept(
  matterId: string,
  token: string,
  fileId: string,
  change: string,
  roomId?: string,
): Promise<Concept> {
  return apiRequest(`${base}/matters/${matterId}/concepts`, withToken(token, {
    method: "POST", body: JSON.stringify({ file_id: fileId, change, ...(roomId ? { room_id: roomId } : {}) }),
  }));
}

export async function conceptImage(matterId: string, token: string, conceptId: string): Promise<Blob> {
  return (await fileRequest(`${base}/matters/${matterId}/concepts/${conceptId}/content`, token)).blob();
}

export async function deleteConcept(matterId: string, token: string, conceptId: string): Promise<void> {
  await fileRequest(`${base}/matters/${matterId}/concepts/${conceptId}`, token, { method: "DELETE" });
}
