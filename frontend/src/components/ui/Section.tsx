import type { ReactNode } from "react";
import styles from "./Section.module.css";

/** A titled region of a workspace panel. */
export function Section({ label, children, id }: { label: string; children: ReactNode; id?: string }) {
  const headingId = id ? `${id}-label` : undefined;
  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <h2 className={styles.label} id={headingId}>
        {label}
      </h2>
      {children}
    </section>
  );
}
