import { msg, type Translate } from "@/i18n/core";
import type { PermitReport, ProfileItem } from "./types";

// HR-008: the groups of the property profile. What has no value is its own group, whatever kind it would have been, so
// an unknown never reads as a fact.
export type ProfileGroup = ProfileItem["kind"] | "unconfirmed";

export const GROUPS: { id: ProfileGroup; label: string }[] = [
  { id: "official", label: msg("Official") },
  { id: "observation", label: msg("Observations") },
  { id: "declaration", label: msg("Declarations") },
  { id: "unconfirmed", label: msg("Not confirmed") },
];

export const groupOf = (item: ProfileItem): ProfileGroup => (item.value === null ? "unconfirmed" : item.kind);

export function profileCounts(report: PermitReport): Record<ProfileGroup, number> {
  const counts: Record<ProfileGroup, number> = { official: 0, observation: 0, declaration: 0, unconfirmed: 0 };
  for (const item of report.profile) counts[groupOf(item)] += 1;
  return counts;
}

/** The map's short line: "1 Official · 4 Observations · 2 Not confirmed". */
export function profileSummary(report: PermitReport, t: Translate): string {
  const counts = profileCounts(report);
  return GROUPS.filter((g) => counts[g.id] > 0)
    .map((g) => `${counts[g.id]} ${t(g.label)}`)
    .join(" · ");
}
