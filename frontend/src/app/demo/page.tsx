"use client";

import Link from "next/link";
import { ViewTransition } from "react";
import { AddressSearch } from "@/features/property/AddressSearch";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import styles from "./demo.module.css";

// The guided scenario starts with a Cascais address that reaches every feature, the aerial view included (a street
// number, so Google returns a precise point); Praça 5 de Outubro geocodes as a square's centre.
const EXAMPLES = ["Rua Frederico Arouca 30, Cascais", "Praça 5 de Outubro, Cascais"] as const;
// Partial coverage (afinamentos 2026-11-02): authority and official sources named, rules not verified.
const OTHER_EXAMPLES = ["350 5th Ave, New York", "10 Rue de Rivoli, Paris", "1 Raffles Place, Singapore"] as const;

/** The guided Cascais path (UX-REFINE-001 §4): what to try, in order. Nothing runs until the visitor acts. */
const GUIDE = [
  {
    title: msg("Open the property"),
    body: msg("Choose “Rua Frederico Arouca 30, Cascais” below. HABITA places it, names its municipality and the Câmara competent for permits, and can show it from the air."),
  },
  {
    title: msg("Ask a question"),
    body: msg("In the Question area, ask “Can I convert this property into two residential units?” and answer the follow-up questions."),
  },
  {
    title: msg("Read the verified answer"),
    body: msg("Open the PDF report, listen to the summary, and look at the reasoning graph and the property profile."),
  },
  {
    title: msg("Go further"),
    body: msg("Add photos and plans, see before / after concepts and estimate costs, each in its own area."),
  },
] as const;

export default function DemoPage() {
  const { t } = useI18n();
  return (
    <ViewTransition exit="leave" default="none">
      <main className={styles.home}>
        <section className={styles.hero} aria-labelledby="demo-title">
          <p className={styles.eyebrow}>{t("Live demo")}</p>
          <h1 id="demo-title" className={styles.title}>
            {t("Every property begins with its place.")}
          </h1>
          <p className={styles.lead}>
            {t("Cascais is where HABITA is most complete, so test there: Rua Frederico Arouca 30 is the reference address, but you can enter any other. No account is needed, and nothing is charged or generated until you ask for it.")}
          </p>
          <div className={styles.search}>
            <AddressSearch
              variant="hero"
              autoFocus
              examples={EXAMPLES}
              otherExamples={{ label: t("Other jurisdictions (partial coverage)"), items: OTHER_EXAMPLES }}
            />
          </div>
        </section>

        <section className={styles.outputs} aria-labelledby="guide-title">
          <h2 id="guide-title" className={styles.guideTitle}>
            {t("Guided scenario: Cascais")}
          </h2>
          <ol className={styles.outputList}>
            {GUIDE.map((step, i) => (
              <li key={step.title} className={styles.output}>
                <span className={styles.outputIndex}>{String(i + 1).padStart(2, "0")}</span>
                <h3 className={styles.outputTitle}>{t(step.title)}</h3>
                <p className={styles.outputBody}>{t(step.body)}</p>
              </li>
            ))}
          </ol>
          <p className={styles.legal}>
            {t("A demonstration, not legal advice: a VERIFIED statement is grounded in its cited official records; it is not a licence or a decision of the Câmara.")}{" "}
            {t("Address lookups use Google Maps Platform.")} <Link href="/privacy">{t("Privacy & terms")}</Link>
          </p>
        </section>
      </main>
    </ViewTransition>
  );
}
