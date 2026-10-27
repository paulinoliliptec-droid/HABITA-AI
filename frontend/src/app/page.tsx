import Link from "next/link";
import { ViewTransition } from "react";
import { AddressSearch } from "@/features/property/AddressSearch";
import styles from "./page.module.css";

const EXAMPLES = ["Praça 5 de Outubro, Cascais", "Avenida dos Aliados, Porto", "Largo da Sé, Funchal"] as const;

const OUTPUTS = [
  {
    title: "Location",
    body: "The address is geocoded to a precise point, with the precision Google Maps reports for it.",
  },
  {
    title: "Jurisdiction",
    body: "The administrative hierarchy that governs the property: country, region and municipality.",
  },
  {
    title: "Local authority",
    body: "The body competent for building permits, where HABITA models that country's system.",
  },
] as const;

export default function HomePage() {
  return (
    <ViewTransition exit="leave" default="none">
      <main className={styles.home}>
        <section className={styles.hero} aria-labelledby="home-title">
          <p className={styles.eyebrow}>Property intelligence</p>
          <h1 id="home-title" className={styles.title}>
            Every property begins with its place.
          </h1>
          <p className={styles.lead}>
            Enter an address. HABITA resolves where it is, which jurisdiction governs it, and the authority you would
            deal with for permits.
          </p>
          <div className={styles.search}>
            <AddressSearch variant="hero" autoFocus examples={EXAMPLES} />
          </div>
        </section>

        <section className={styles.outputs} aria-label="What HABITA resolves">
          <ol className={styles.outputList}>
            {OUTPUTS.map((output, i) => (
              <li key={output.title} className={styles.output}>
                <span className={styles.outputIndex}>{String(i + 1).padStart(2, "0")}</span>
                <h2 className={styles.outputTitle}>{output.title}</h2>
                <p className={styles.outputBody}>{output.body}</p>
              </li>
            ))}
          </ol>
          <p className={styles.legal}>
            Address lookups use Google Maps Platform. <Link href="/privacy">Privacy &amp; terms</Link>
          </p>
        </section>
      </main>
    </ViewTransition>
  );
}
