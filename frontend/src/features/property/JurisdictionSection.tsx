"use client";

import { Notice } from "@/components/ui/Notice";
import { Section } from "@/components/ui/Section";
import { useI18n } from "@/i18n/useI18n";
import { jurisdictionHierarchy } from "./format";
import { PlanningContextBlock } from "./PlanningContextBlock";
import type { Jurisdiction } from "./types";
import styles from "./JurisdictionSection.module.css";

export function JurisdictionSection({ jurisdiction, propertyId }: { jurisdiction: Jurisdiction; propertyId: string }) {
  const { t } = useI18n();
  const levels = jurisdictionHierarchy(jurisdiction);
  const authority = jurisdiction.local_authority;

  return (
    <Section label={t("Jurisdiction")} id="jurisdiction">
      <ol className={styles.hierarchy}>
        {levels.map((level, i) => (
          <li key={level.id} className={styles.level} data-last={i === levels.length - 1 || undefined}>
            <span className={styles.node} aria-hidden="true" />
            <span className={styles.levelName}>{t(level.label)}</span>
            <span className={styles.levelValue}>
              {level.value}
              {level.detail && <span className={styles.levelDetail}>{level.detail}</span>}
            </span>
          </li>
        ))}
      </ol>

      {authority ? (
        <div className={styles.authority}>
          <p className={styles.authorityLabel}>{t("Competent local authority")}</p>
          <p className={styles.authorityName}>{authority.name}</p>
          <p className={styles.authorityNote}>{t(authority.competence)}</p>
          {authority.sources.length > 0 && (
            <p className={styles.authoritySource}>
              {t("Basis:")}{" "}
              {authority.sources.map((s) => [s.title, s.reference].filter(Boolean).join(", ")).join("; ")}
            </p>
          )}
        </div>
      ) : jurisdiction.coverage === "modelled" ? (
        <Notice title={t("Local authority not identified")}>
          {t("Google Maps didn't return the municipality for this address, so HABITA can't name the competent authority. Try a more complete address.")}
        </Notice>
      ) : (
        <Notice title={t("Local authority not yet modelled")}>
          {t("HABITA doesn't yet identify the permitting authority for {country}. The hierarchy above is taken directly from Google Maps.", { country: jurisdiction.country })}
        </Notice>
      )}

      {authority && <PlanningContextBlock propertyId={propertyId} />}
    </Section>
  );
}
