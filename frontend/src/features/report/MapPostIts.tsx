"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { recallMatter, type MatterCapability } from "@/features/permit/capability";
import type { Lang } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { downloadReportPdf, getReport, onReportChanged } from "./api";
import { buildPostIts } from "./postits";
import { profileSummary } from "./profile";
import { ProfilePanel } from "./ProfilePanel";
import { ReasoningGraph } from "./ReasoningGraph";
import { VoiceExplanation } from "./VoiceExplanation";
import type { PermitReport } from "./types";
import styles from "./MapPostIts.module.css";

/** HR-004 post-its over the map and the HR-006 PDF download, both from the same report. */
export function MapPostIts({ propertyId }: { propertyId: string }) {
  const { lang, t } = useI18n();
  // The report shown and the capability it was read with: the PDF always downloads that same report.
  const [shown, setShown] = useState<{ report: PermitReport; own: MatterCapability | null; version: number; lang: Lang } | null>(null);
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onReportChanged(() => setVersion((v) => v + 1)), []);

  useEffect(() => {
    const controller = new AbortController();
    const own = recallMatter(propertyId);
    // A capability the server no longer accepts still leaves the public property report.
    getReport(propertyId, own, lang, controller.signal)
      .then((report) => ({ report, own, version, lang }))
      .catch((err: unknown) => {
        if (own && err instanceof ApiError && [401, 403, 404].includes(err.status)) {
          return getReport(propertyId, null, lang, controller.signal).then((report) => ({ report, own: null, version, lang }));
        }
        throw err;
      })
      .then(setShown)
      .catch(() => !controller.signal.aborted && setShown(null));
    return () => controller.abort();
  }, [propertyId, version, lang]);

  // A report read before the matter changed is never shown next to the new matter's PDF.
  if (!shown || shown.version !== version) return null;
  const { report, own, lang: reportLang } = shown;

  async function download() {
    setDownloading(true);
    setError(null);
    try {
      await downloadReportPdf(propertyId, own, reportLang);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("The report couldn't be generated."));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <aside className={styles.board} aria-label={t("Property notes")} data-open={open}>
      <div className={styles.header}>
        <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {t("Notes")} {open ? "▾" : "▸"}
        </button>
        <Button variant="secondary" onClick={download} disabled={downloading}>
          {downloading ? t("Preparing…") : t("PDF report")}
        </Button>
        <Button variant="secondary" onClick={() => setGraphOpen(true)}>
          {t("Reasoning graph")}
        </Button>
        <Button variant="secondary" onClick={() => setProfileOpen(true)}>
          {t("Property profile")}
        </Button>
      </div>
      {graphOpen && <ReasoningGraph report={report} onClose={() => setGraphOpen(false)} />}
      {profileOpen && <ProfilePanel report={report} onClose={() => setProfileOpen(false)} />}
      {report.profile.length ? (
        <button type="button" className={styles.summary} onClick={() => setProfileOpen(true)}>
          {profileSummary(report, t)}
        </button>
      ) : null}
      <VoiceExplanation report={report} own={own} />
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {open && (
        <ul className={styles.notes}>
          {report.demo && <li className={styles.demo}>{t("Demonstration data")}</li>}
          {report.translation?.note && <li className={styles.demo}>{report.translation.note}</li>}
          {buildPostIts(report, t).map((n) => (
            <li key={n.id} className={styles.note} data-tone={n.tone}>
              <p className={styles.title}>
                {n.title}
                {n.badge && <span className={styles.badge}>{n.badge}</span>}
              </p>
              {n.lines.map((line, i) => (
                <p key={i} className={styles.line}>
                  {line}
                </p>
              ))}
              {n.links.length > 0 && (
                <p className={styles.links}>
                  {n.links.map((l) => (
                    <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer">
                      {l.label}
                    </a>
                  ))}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
