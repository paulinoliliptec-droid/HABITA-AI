"use client";

import { useRef, type KeyboardEvent } from "react";
import { useI18n } from "@/i18n/useI18n";
import { AREAS, type AreaId } from "./areas";
import styles from "./WorkspaceTabs.module.css";

/** The workspace's area tabs (WAI-ARIA tabs: arrow keys move between them). */
export function WorkspaceTabs({ area, onChange }: { area: AreaId; onChange: (area: AreaId) => void }) {
  const { t } = useI18n();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + AREAS.length) % AREAS.length;
    onChange(AREAS[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div className={styles.tabs} role="tablist" aria-label={t("Areas")}>
      {AREAS.map((a, i) => (
        <button
          key={a.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          id={`area-tab-${a.id}`}
          aria-controls={`area-${a.id}`}
          aria-selected={area === a.id}
          tabIndex={area === a.id ? 0 : -1}
          className={styles.tab}
          onClick={() => onChange(a.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
        >
          {t(a.label)}
        </button>
      ))}
    </div>
  );
}
