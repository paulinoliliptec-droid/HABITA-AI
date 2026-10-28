import { apiRequest } from "@/lib/api";
import type { Evidence, PermitMatter, VerificationReport } from "./types";

const base = "/api/permit";

/** Matter operations carry the matter's capability; it never goes into the URL. */
const withToken = (token: string, init: RequestInit = {}): RequestInit => ({
  ...init,
  headers: { ...init.headers, Authorization: `Bearer ${token}` },
});

export function permitStatus(): Promise<{ available: boolean; model: string }> {
  return apiRequest(`${base}/status`);
}

export function createMatter(propertyId: string, question: string): Promise<{ matter: PermitMatter; access_token: string }> {
  return apiRequest(`${base}/matters`, { method: "POST", body: JSON.stringify({ property_id: propertyId, question }) });
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

export function getVerification(matterId: string, token: string): Promise<VerificationReport> {
  return apiRequest(`${base}/matters/${matterId}/verification`, withToken(token));
}
