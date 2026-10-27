import { Notice } from "@/components/ui/Notice";
import { Section } from "@/components/ui/Section";
import { jurisdictionHierarchy } from "./format";
import type { Jurisdiction } from "./types";
import styles from "./JurisdictionSection.module.css";

export function JurisdictionSection({ jurisdiction }: { jurisdiction: Jurisdiction }) {
  const levels = jurisdictionHierarchy(jurisdiction);
  const authority = jurisdiction.local_authority;

  return (
    <Section label="Jurisdiction" id="jurisdiction">
      <ol className={styles.hierarchy}>
        {levels.map((level, i) => (
          <li key={level.id} className={styles.level} data-last={i === levels.length - 1 || undefined}>
            <span className={styles.node} aria-hidden="true" />
            <span className={styles.levelName}>{level.label}</span>
            <span className={styles.levelValue}>
              {level.value}
              {level.detail && <span className={styles.levelDetail}>{level.detail}</span>}
            </span>
          </li>
        ))}
      </ol>

      {authority ? (
        <div className={styles.authority}>
          <p className={styles.authorityLabel}>Competent local authority</p>
          <p className={styles.authorityName}>{authority.name}</p>
          <p className={styles.authorityNote}>{authority.competence}</p>
          {authority.sources.length > 0 && (
            <p className={styles.authoritySource}>
              Basis:{" "}
              {authority.sources.map((s) => [s.title, s.reference].filter(Boolean).join(", ")).join("; ")}
            </p>
          )}
        </div>
      ) : jurisdiction.coverage === "modelled" ? (
        <Notice title="Local authority not identified">
          Google Maps didn&apos;t return the municipality for this address, so HABITA can&apos;t name the competent
          authority. Try a more complete address.
        </Notice>
      ) : (
        <Notice title="Local authority not yet modelled">
          HABITA doesn&apos;t yet identify the permitting authority for {jurisdiction.country}. The hierarchy above
          is taken directly from Google Maps.
        </Notice>
      )}
    </Section>
  );
}
