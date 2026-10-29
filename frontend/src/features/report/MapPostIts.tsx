"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { recallMatter } from "@/features/permit/capability";
import { ApiError } from "@/lib/api";
import { downloadReportPdf, getReport, onReportChanged } from "./api";
import { buildPostIts } from "./postits";
import type { PermitReport } from "./types";
import styles from "./MapPostIts.module.css";

/** HR-004 post-its over the map and the HR-006 PDF download, both from the same report. */
export function MapPostIts({ propertyId }: { propertyId: string }) {
  const [report, setReport] = useState<PermitReport | null>(null);
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onReportChanged(() => setVersion((v) => v + 1)), []);

  useEffect(() => {
    const controller = new AbortController();
    const own = recallMatter(propertyId);
    // A capability the server no longer accepts still leaves the public property report.
    getReport(propertyId, own, controller.signal)
      .catch((err: unknown) => {
        if (own && err instanceof ApiError && [401, 403, 404].includes(err.status)) {
          return getReport(propertyId, null, controller.signal);
        }
        throw err;
      })
      .then(setReport)
      .catch(() => !controller.signal.aborted && setReport(null));
    return () => controller.abort();
  }, [propertyId, version]);

  if (!report) return null;

  async function download() {
    setDownloading(true);
    setError(null);
    try {
      await downloadReportPdf(propertyId, recallMatter(propertyId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The report couldn't be generated.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <aside className={styles.board} aria-label="Property notes" data-open={open}>
      <div className={styles.header}>
        <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          Notes {open ? "▾" : "▸"}
        </button>
        <Button variant="secondary" onClick={download} disabled={downloading}>
          {downloading ? "Preparing…" : "PDF report"}
        </Button>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {open && (
        <ul className={styles.notes}>
          {report.demo && <li className={styles.demo}>Demonstration data</li>}
          {buildPostIts(report).map((n) => (
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
