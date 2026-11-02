import { msg } from "@/i18n/core";

/** The workspace areas (UX-REFINE-001): one at a time, so the panel is no longer one long column. */
export const AREAS = [
  { id: "question", label: msg("Question") },
  { id: "documents", label: msg("Photos & plans") },
  { id: "concepts", label: msg("Before / after") },
  { id: "costs", label: msg("Costs") },
  { id: "place", label: msg("Place") },
] as const;

export type AreaId = (typeof AREAS)[number]["id"];

export const DEFAULT_AREA: AreaId = "question";

/** The area named by a URL hash ("#costs"), or the default: a deep link opens the area it names. */
export function areaFromHash(hash: string): AreaId {
  const id = hash.replace(/^#/, "");
  return AREAS.find((a) => a.id === id)?.id ?? DEFAULT_AREA;
}
