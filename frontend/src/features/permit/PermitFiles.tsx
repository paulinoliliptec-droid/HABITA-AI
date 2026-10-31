"use client";

import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { reportChanged } from "@/features/report/api";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { addFile, deleteFile, fileContent, listFiles, type MatterFile } from "./api";
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
export function PermitFiles({ matterId, token }: { matterId: string; token: string }) {
  const { t } = useI18n();
  const id = useId();
  const [files, setFiles] = useState<MatterFile[] | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [kind, setKind] = useState<MatterFile["kind"]>("photo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listFiles(matterId, token)
      .then((list) => !cancelled && setFiles(list))
      .catch(() => !cancelled && setFiles([]));
    return () => {
      cancelled = true;
    };
  }, [matterId, token]);

  async function add(file: File) {
    setBusy(true);
    setError(null);
    try {
      const added = await addFile(matterId, token, file, kind);
      setFiles((list) => [...(list ?? []), added]);
      reportChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(fileId: string) {
    setError(null);
    try {
      await deleteFile(matterId, token, fileId);
      setFiles((list) => (list ?? []).filter((f) => f.file_id !== fileId));
      reportChanged();
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

  const full = (files?.length ?? 0) >= MAX_FILES;
  return (
    <div className={styles.files}>
      <h3 className={styles.filesTitle}>{t("Your photos and plans")}</h3>
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
            disabled={!agreed || busy || full}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void add(file);
            }}
          />
          {busy ? t("Reading the file…") : t("Add a photo or plan")}
        </label>
        <p className={styles.fieldHint}>{t("JPEG, PNG or PDF, up to 10 MB; at most 10 files.")}</p>
      </div>

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
