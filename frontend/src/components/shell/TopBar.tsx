"use client";

import Link from "next/link";
import { msg, type Lang } from "@/i18n/core";
import { setLanguage, useI18n } from "@/i18n/useI18n";
import styles from "./TopBar.module.css";

// Only modules that actually exist are listed. Permit and Afford join when they ship.
const MODULES = [{ label: msg("Property"), href: "/" }] as const;
const LANGUAGES: { lang: Lang; label: string }[] = [
  { lang: "en", label: "EN" },
  { lang: "pt", label: "PT" },
];

export function TopBar() {
  const { lang, t } = useI18n();
  return (
    <header className={styles.topbar}>
      <Link href="/" className={styles.identity} aria-label={t("HABITA AI, home")}>
        <span className={styles.wordmark}>
          HABITA<span className={styles.ai}>AI</span>
        </span>
        <span className={styles.divider} aria-hidden="true" />
        <span className={styles.subtitle}>{t("Global Property Intelligence & Permitting OS")}</span>
      </Link>

      <nav aria-label={t("Modules")} className={styles.nav}>
        {MODULES.map((module) => (
          <Link key={module.href} href={module.href} className={styles.navItem} aria-current="page">
            {t(module.label)}
          </Link>
        ))}
      </nav>

      <div className={styles.languages} role="group" aria-label={t("Language")}>
        {LANGUAGES.map((option) => (
          <button
            key={option.lang}
            type="button"
            className={styles.language}
            aria-pressed={lang === option.lang}
            onClick={() => setLanguage(option.lang)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </header>
  );
}
