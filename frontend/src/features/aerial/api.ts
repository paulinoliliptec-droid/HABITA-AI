import { msg } from "@/i18n/core";
import { ApiError, apiRequest } from "@/lib/api";
import { config } from "@/lib/config";

/** Seen from the air: the DGT orthophoto around a property, segmented by Meta SAM 3.1 (observations only). */
export interface AerialObject {
  kind: "building" | "small_building" | "pool";
  area_m2: number;
  distance_m: number;
  at_point: boolean;
}

export interface AerialReport {
  aerial_id: string;
  property_id: string;
  created_at: string;
  source: { provider: "DGT"; layer: string; year: number; metres_per_pixel: number; retrieved_at: string };
  model_id: string;
  radius_m: number;
  objects: AerialObject[];
  checks: ("aerial_small_building" | "aerial_pool")[];
}

/** HABITA's fixed wording, the same as the backend's (and the report's conditions). */
export const AERIAL_CHECK_TEXT = {
  aerial_small_building: msg(
    "A small separate building is visible from the air near the property. Confirm with the Câmara Municipal that it is licensed.",
  ),
  aerial_pool: msg(
    "A swimming pool is visible from the air near the property. Confirm with the Câmara Municipal that it is licensed.",
  ),
} as const;

const path = (id: string) => `/api/property/${encodeURIComponent(id)}/aerial`;

export async function getAerial(propertyId: string, signal?: AbortSignal): Promise<AerialReport | null> {
  try {
    return await apiRequest<AerialReport>(path(propertyId), { signal });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function createAerial(propertyId: string): Promise<AerialReport> {
  return apiRequest<AerialReport>(path(propertyId), { method: "POST" });
}

export function aerialImageUrl(report: AerialReport): string {
  return `${config.apiBaseUrl}${path(report.property_id)}/image?v=${report.aerial_id}`;
}
