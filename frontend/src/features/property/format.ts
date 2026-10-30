import type { BadgeTone } from "@/components/ui/Badge";
import { msg } from "@/i18n/core";
import type { Jurisdiction, LocationPrecision } from "./types";

/** "Praça 5 de Outubro, 2750-642 Cascais, Portugal" → headline + remainder. */
export function splitAddress(formatted: string): { headline: string; remainder: string | null } {
  const index = formatted.indexOf(",");
  if (index === -1) return { headline: formatted, remainder: null };
  return { headline: formatted.slice(0, index).trim(), remainder: formatted.slice(index + 1).trim() || null };
}

export const PRECISION: Record<LocationPrecision, { label: string; tone: BadgeTone; zoom: number }> = {
  rooftop: { label: msg("Rooftop precision"), tone: "positive", zoom: 18 },
  interpolated: { label: msg("Street-level precision"), tone: "neutral", zoom: 17 },
  area_center: { label: msg("Area centre"), tone: "warning", zoom: 15 },
  approximate: { label: msg("Approximate location"), tone: "warning", zoom: 13 },
};

export interface HierarchyLevel {
  id: string;
  label: string;
  value: string;
  detail?: string;
}

/** The administrative hierarchy as the backend reports it, country first. Overlays are not shown here. */
export function jurisdictionHierarchy(j: Jurisdiction): HierarchyLevel[] {
  return j.levels
    .filter((level) => level.type !== "overlay")
    .map((level) => ({
      id: level.id,
      label: level.label,
      value: level.name,
      detail: level.type === "country" ? j.country_code || undefined : undefined,
    }));
}

/** "Lisboa, Portugal"-style place line: the municipality when known, else the locality. */
export function placeLine(j: Jurisdiction): string {
  return [j.municipality ?? j.city, j.country].filter(Boolean).join(", ");
}

export function formatCoordinate(value: number, axis: "lat" | "lng"): string {
  const hemisphere = axis === "lat" ? (value >= 0 ? "N" : "S") : value >= 0 ? "E" : "W";
  return `${Math.abs(value).toFixed(6)}° ${hemisphere}`;
}
