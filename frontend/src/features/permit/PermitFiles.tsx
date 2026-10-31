"use client";

import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { reportChanged } from "@/features/report/api";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { addFile, CHECK_TEXT, deleteFile, fileContent, listFiles, type MatterFile } from "./api";
import styles from "./Permit.module.css";

const MAX_FILES = 10;
const KIND_LABEL = { photo: msg("Photo"), plan: msg("Plan"), document: msg("Document") } as const;
const READ_NOTE = {
  read: null,
  reading: msg("HABITA is still reading this file, or the upload was interrupted."),
  unreadable: msg("HABITA found no image to read in this file."),
  failed: msg("HABITA could not read this file right now. It is kept; you can delete it and add it again."),
} as const;

/** HR-010: photos and plans for this matter. What HABITA reads in them is never verified and never changes the assessment. */
export function PermitFiles({ matterId, token, onChange }: { matterId: string; token: string; onChange?: () => void }) {
  const { t } = useI18n();
  const id = useId();
  const [files, setFiles] = useState<MatterFile[] | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [kind, setKind] = useState<MatterFile["kind"]>("photo");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [listFailed, setListFailed] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // A failed list stays unknown (null), never empty: adding stays closed until the count is known.
    listFiles(matterId, token)
      .then((list) => !cancelled && setFiles(list))
      .catch(() => !cancelled && setListFailed(true));
    return () => {
      cancelled = true;
    };
  }, [matterId, token, attempt]);

  /** Several files at once: sent one after the other, so each is read in turn and one failure doesn't stop the rest. */
  async function add(chosen: File[]) {
    if (files === null) return; // the list isn't known yet, so the room left isn't either (the button waits too)
    const room = MAX_FILES - files.length;
    const batch = chosen.slice(0, Math.max(room, 0));
    setBusy(true);
    setError(null);
    const problems: string[] = [];
    if (chosen.length > batch.length) {
      problems.push(t("Only the first {count} files were added: a matter holds at most 10.", { count: String(batch.length) }));
    }
    for (const [n, file] of batch.entries()) {
      setProgress({ done: n, total: batch.length });
      try {
        const added = await addFile(matterId, token, file, kind);
        setFiles((list) => [...(list ?? []), added]);
      } catch (err) {
        problems.push(`${file.name}: ${err instanceof ApiError ? err.message : t("Something went wrong. Please try again.")}`);
      }
    }
    if (problems.length) setError(problems.join(" "));
    setProgress(null);
    setBusy(false);
    reportChanged();
    onChange?.();
  }

  async function remove(fileId: string) {
    setError(null);
    try {
      await deleteFile(matterId, token, fileId);
      setFiles((list) => (list ?? []).filter((f) => f.file_id !== fileId));
      reportChanged();
      onChange?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
    }
  }

  async function view(fileId: string) {
    try {
      const url = URL.createObjectURL(await fileContent(matterId, token, fileId));
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
    }
  }

  const full = files === null || files.length >= MAX_FILES; // also closed while the list is loading
  return (
    <div className={styles.files}>
      <h3 className={styles.filesTitle}>{t("Your photos and plans")}</h3>
      <p className={styles.filesPurpose}>
        {t("Add photos or plans of the property so HABITA can see it from the inside and tell you what to confirm with the Câmara before the works.")}
      </p>
      <p className={styles.fieldHint}>
        {t("HABITA describes what it sees. That reading is not verified and never changes the assessment.")}
      </p>

      <label className={styles.consent}>
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        <span>
          {t(
            "Files you add are sent to Meta's Muse Spark to be read. HABITA keeps a private copy without location or device data, visible only with this matter's access. Don't add photos of people or documents with personal data. You can delete a file at any time.",
          )}
        </span>
      </label>

      <div className={styles.fileForm}>
        <label htmlFor={`${id}-kind`} className={styles.fieldLabel}>
          {t("Type of file")}
        </label>
        <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value as MatterFile["kind"])}>
          {(Object.keys(KIND_LABEL) as MatterFile["kind"][]).map((k) => (
            <option key={k} value={k}>
              {t(KIND_LABEL[k])}
            </option>
          ))}
        </select>
        <label className={styles.fileButton} aria-disabled={!agreed || busy || full}>
          <input
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            multiple
            disabled={!agreed || busy || full}
            onChange={(e) => {
              const chosen = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (chosen.length) void add(chosen);
            }}
          />
          {progress
            ? t("Reading file {n} of {total}…", { n: String(progress.done + 1), total: String(progress.total) })
            : t("Add photos or plans")}
        </label>
        <p className={styles.fieldHint}>{t("You can choose several at once. JPEG, PNG or PDF, up to 10 MB each; at most 10 files.")}</p>
      </div>

      {listFailed && (
        <div className={styles.actions}>
          <p className={styles.error} role="alert">
            {t("Your files could not be loaded, so adding is paused.")}
          </p>
          <Button
            variant="secondary"
            onClick={() => {
              setListFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            {t("Try again")}
          </Button>
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      {files && files.length > 0 && (
        <ul className={styles.fileList}>
          {files.map((f) => (
            <li key={f.file_id} className={styles.fileItem}>
              <p className={styles.fieldLabel}>
                {t(KIND_LABEL[f.kind])} · {new Date(f.added_at).toLocaleDateString()}
              </p>
              {f.observations.length > 0 && (
                <ul className={styles.observations}>
                  {f.observations.map((o, n) => (
                    <li key={n}>{o}</li>
                  ))}
                </ul>
              )}
              {f.checks.length > 0 && (
                <div className={styles.fileChecks}>
                  <p className={styles.fieldLabel}>{t("What to confirm")}</p>
                  <ul>
                    {f.checks.map((c) => (
                      <li key={c}>{t(CHECK_TEXT[c])}</li>
                    ))}
                  </ul>
                </div>
              )}
              {READ_NOTE[f.read_status] && <p className={styles.fieldHint}>{t(READ_NOTE[f.read_status]!)}</p>}
              {f.gps_check === "far" && (
                <p className={styles.fieldHint}>
                  {t("The location data in this file is far from this property. It proves nothing either way.")}
                </p>
              )}
              <div className={styles.actions}>
                <Button variant="ghost" onClick={() => void view(f.file_id)}>
                  {t("View")}
                </Button>
                <Button variant="ghost" onClick={() => void remove(f.file_id)}>
                  {t("Delete")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
