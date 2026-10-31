"use client";

import { useCallback, useEffect, useRef } from "react";
import { useModal } from "@/features/report/useModal";
import { useI18n } from "@/i18n/useI18n";
import styles from "./Permit.module.css";

/** A picture shown large over the page; Escape, the close button or a click outside closes it. */
export function ImageViewer({ src, alt, caption, onClose }: { src: string; alt: string; caption?: string; onClose: () => void }) {
  const { t } = useI18n();
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  // A stable close, so a parent re-render never re-runs the modal's focus handling.
  const latest = useRef(onClose);
  useEffect(() => {
    latest.current = onClose;
  }, [onClose]);
  const close = useCallback(() => latest.current(), []);
  useModal(dialog, close); // records the opener first …
  useEffect(() => closeButton.current?.focus(), []); // … then focus moves into the dialog
  return (
    <div className={styles.viewerBackdrop} onClick={close}>
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label={alt}
        className={styles.viewer}
        onClick={(e) => e.stopPropagation()}
      >
        <button ref={closeButton} type="button" className={styles.viewerClose} onClick={close}>
          {t("Close")}
        </button>
        {/* Above the picture, so a short phone screen shows it first; the notice is also burned into the image. */}
        {caption && <p className={styles.fieldHint}>{caption}</p>}
        {/* eslint-disable-next-line @next/next/no-img-element -- a private blob, not an optimisable URL */}
        <img src={src} alt={alt} />
      </div>
    </div>
  );
}
