import { Spinner } from "@/components/ui/Spinner";
import { useI18n } from "@/i18n/useI18n";
import { PHASES, phaseOf } from "./present";
import type { PermitMatter } from "./types";
import styles from "./Permit.module.css";

/** Goal → Investigation → Evidence → Result, with the current operational step (never model reasoning). */
export function PermitProgress({ matter, running }: { matter: PermitMatter; running: boolean }) {
  const { t } = useI18n();
  const { phase, done, waiting } = phaseOf(matter.state, matter.error?.failed_state);
  const current = PHASES.indexOf(phase);
  const latest = matter.progress[matter.progress.length - 1];

  return (
    <div className={styles.progress}>
      <ol className={styles.phases} aria-label={t("Permit workflow")}>
        {PHASES.map((name, i) => {
          const status = i < current || (i === current && done) ? "done" : i === current ? "active" : "todo";
          return (
            <li key={name} className={styles.phase} data-status={status} aria-current={status === "active" ? "step" : undefined}>
              <span className={styles.phaseMark} aria-hidden="true" />
              {t(name)}
              {status === "active" && waiting && <span className={styles.substate}>{t("Waiting for you")}</span>}
            </li>
          );
        })}
      </ol>
      {latest && (
        <p className={styles.status} aria-live="polite">
          {running && <Spinner size={14} />}
          {matter.state === "FAILED" && matter.error ? matter.error.message : t(latest.label)}
        </p>
      )}
    </div>
  );
}
