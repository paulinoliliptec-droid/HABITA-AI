"use client";

import Link from "next/link";
import { ViewTransition } from "react";
import { ButtonLink } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import heroImage from "./landing-hero.jpg";
import styles from "./landing.module.css";

const GITHUB = "https://github.com/paulinoliliptec-droid/HABITA-AI";
const HERO_SOURCE =
  "https://commons.wikimedia.org/wiki/File:Pra%C3%A7a_5_de_Outubro,_Cascais,_Portugal,_20250606_1659_0328.jpg";

/** How it works (UX-REFINE-001 §3): only what the demo really does. */
const STEPS = [
  {
    title: msg("Address"),
    body: msg("Geocoded with Google Maps, with the precision it reports. A point, never a parcel boundary."),
  },
  {
    title: msg("Jurisdiction"),
    body: msg("Country, district and municipality, and the authority competent for permits."),
  },
  {
    title: msg("Official evidence"),
    body: msg("Trusted official sources (municipal plan, RJUE, RGEU…), snapshotted and cited by version."),
  },
  {
    title: msg("Conditional assessment"),
    body: msg("Muse Spark plans and drafts; HABITA's verifier certifies only what the cited records say. The model can never mark its own answer verified."),
  },
  {
    title: msg("Plans & 3D"),
    body: msg("Your photos and plans read by Muse Spark; before / after concepts and plan views with Muse Image, labelled as concepts."),
  },
  {
    title: msg("Financial feasibility"),
    body: msg("Costs, financing and price from official statistics, with their source and date."),
  },
  {
    title: msg("Report"),
    body: msg("Map notes, a PDF with its verification record, a reasoning graph and a spoken summary, in English or Portuguese."),
  },
] as const;

const META = [
  { name: "Muse Spark", body: msg("Planning, tool calls over official sources, drafting and a review that can only make a verdict stricter; reading photos and plans.") },
  { name: "Muse Image", body: msg("Before / after concepts and views from a plan, from HABITA's fixed instruction, with notices burned in.") },
  { name: "SAM 3.1", body: msg("Buildings, annexes and pools seen from the air on official orthophotos: observations, never cadastral proof.") },
  { name: "Muse Voice Transcribe", body: msg("Dictating a question or an answer; the text is shown to check before it is sent.") },
] as const;

export default function LandingPage() {
  const { t } = useI18n();
  return (
    <ViewTransition exit="leave" default="none">
      <main className={styles.landing}>
        <section className={styles.hero} aria-labelledby="landing-title">
          {/* Praça 5 de Outubro, Cascais: the demo's own address (photo: Jakub Hałun, CC BY 4.0, cropped). */}
          {/* A plain <img>: the production image has no runtime optimiser, and the file is already sized and compressed. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className={styles.heroImage} src={heroImage.src} alt="" width={heroImage.width} height={heroImage.height}
               fetchPriority="high" decoding="async" />
          <div className={styles.heroShade} aria-hidden="true" />
          <div className={styles.heroInner}>
            <div className={styles.heroText}>
              <p className={styles.eyebrow}>{t("Property intelligence · Meta Global AI Developer Hackathon")}</p>
              <h1 id="landing-title" className={styles.title}>
                {t("One address. A clearer path to what's possible.")}
              </h1>
              <p className={styles.lead}>
                {t("Explore property regulations, official evidence, financial feasibility and AI-powered visual transformations — in one workspace.")}
              </p>
              <div className={styles.juryCard}>
                <p className={styles.juryLabel}>{t("Jury: start here")}</p>
                <ButtonLink href="/demo" variant="primary" size="lg" className={styles.demoButton}>
                  {t("Try the live demo")}
                  <Icon name="arrowRight" size={20} />
                </ButtonLink>
                <p className={styles.juryNote}>
                  {t("Test in Cascais, where HABITA is most complete. Rua Frederico Arouca 30 is the reference address, but any Cascais address works: from the address to an answer checked against official sources, with the map, the aerial view, the reasoning graph, the PDF and the voice. No account is needed, and nothing is charged or generated until you ask for it.")}
                </p>
              </div>
              <div className={styles.actions}>
                <ButtonLink href="#how" variant="secondary" size="md">
                  {t("How it works")}
                </ButtonLink>
                <ButtonLink href={GITHUB} target="_blank" rel="noopener noreferrer" variant="secondary" size="md">
                  GitHub <span aria-hidden="true">↗</span>
                </ButtonLink>
              </div>
            </div>
            <ul className={styles.notes} aria-label={t("What HABITA checks for this address")}>
              <li className={styles.note}>
                <span className={styles.noteLabel}>{t("Jurisdiction")}</span>
                {t("Cascais · Câmara Municipal de Cascais")}
              </li>
              <li className={styles.note}>
                <span className={styles.noteLabel}>{t("Official evidence")}</span>
                {t("Municipal plan, RJUE, RGEU — cited by version")}
              </li>
              <li className={styles.note}>
                <span className={styles.noteLabel}>MU-9</span>
                {t("Verified only when the official sources say so")}
              </li>
            </ul>
          </div>
          <p className={styles.credit}>
            {t("Cascais. Photo:")}{" "}
            <a href={HERO_SOURCE} target="_blank" rel="noopener noreferrer">Jakub Hałun</a>,{" "}
            <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">CC BY 4.0</a>
            {t(", cropped.")}
          </p>
        </section>
        <p className={styles.scopeBar}>
          {t("No account needed. Cascais (Portugal) has verified coverage; New York City, Paris and Singapore show their permitting authority and official sources (partial coverage); other places show their location and jurisdiction.")}
        </p>

        <section id="how" className={styles.section} aria-labelledby="how-title">
          <h2 id="how-title" className={styles.sectionTitle}>
            {t("How it works")}
          </h2>
          <ol className={styles.steps}>
            {STEPS.map((step, i) => (
              <li key={step.title} className={styles.step}>
                <span className={styles.stepIndex}>{String(i + 1).padStart(2, "0")}</span>
                <h3 className={styles.stepTitle}>{t(step.title)}</h3>
                <p className={styles.stepBody}>{t(step.body)}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section} aria-labelledby="meta-title">
          <h2 id="meta-title" className={styles.sectionTitle}>
            {t("Built with Meta models")}
          </h2>
          <ul className={styles.cards}>
            {META.map((m) => (
              <li key={m.name} className={styles.card}>
                <h3 className={styles.cardTitle}>{m.name}</h3>
                <p className={styles.cardBody}>{t(m.body)}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="limits-title">
          <h2 id="limits-title" className={styles.sectionTitle}>
            {t("What it is not")}
          </h2>
          <p className={styles.limits}>
            {t("A demonstration, not legal advice. VERIFIED means a statement is grounded in its cited official records; it is not a licence, a municipal decision or a confirmed zoning. Zoning is shown only from a validated official layer, otherwise it is marked as not verified.")}
          </p>
        </section>

        <footer className={styles.footer}>
          <Link href="/privacy">{t("Privacy & terms")}</Link>
          <a href={GITHUB} target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
          <span>{t("Address lookups use Google Maps Platform.")}</span>
        </footer>
      </main>
    </ViewTransition>
  );
}
