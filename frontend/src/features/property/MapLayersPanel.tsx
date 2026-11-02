"use client";

import { useId, useRef, useState } from "react";
import { useI18n } from "@/i18n/useI18n";
import styles from "./PropertyMap.module.css";

export type MapMode = "roadmap" | "hybrid";

/** One switchable layer drawn over the base map (HR-004 §4). `available` false explains how to get it. */
export interface OverlayOption {
  id: string;
  label: string;
  on: boolean;
  available: boolean;
  /** Why it is off, when not available ("Run the aerial analysis in Place first."). */
  hint?: string;
  /** Shown while the layer is on: source, date, and what it is not. */
  note?: string;
  /** The same in a few words, for phones, where the full note would hide the map. */
  shortNote?: string;
  onToggle: (on: boolean) => void;
}

/** "Layers": the base map and the overlays, in one standard button (replaces the Map / Satellite switch). */
export function MapLayersPanel({
  mode,
  onMode,
  overlays,
}: {
  mode: MapMode;
  onMode: (mode: MapMode) => void;
  overlays: OverlayOption[];
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const name = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const active = overlays.filter((o) => o.on);

  return (
    <div
      className={styles.layers}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          setOpen(false);
          toggle.current?.focus();
        }
      }}
    >
      <button
        ref={toggle}
        type="button"
        className={styles.layersButton}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        {t("Layers")}
        {active.length > 0 && <span className={styles.layersCount}>{active.length}</span>}
      </button>
      {open && (
        <div id={panelId} className={styles.layersPanel} role="group" aria-label={t("Layers")}>
          <fieldset className={styles.layersSet}>
            <legend className={styles.layersLegend}>{t("Base map")}</legend>
            {(["roadmap", "hybrid"] as const).map((m) => (
              <label key={m} className={styles.layersOption}>
                <input type="radio" name={name} checked={mode === m} onChange={() => onMode(m)} />
                {m === "roadmap" ? t("Map") : t("Satellite")}
              </label>
            ))}
          </fieldset>
          <fieldset className={styles.layersSet}>
            <legend className={styles.layersLegend}>{t("On the map")}</legend>
            {overlays.map((o) => (
              <div key={o.id}>
                <label className={styles.layersOption} data-disabled={!o.available || undefined}>
                  <input
                    type="checkbox"
                    checked={o.on}
                    disabled={!o.available}
                    onChange={(e) => o.onToggle(e.target.checked)}
                  />
                  {o.label}
                </label>
                {!o.available && o.hint && <p className={styles.layersHint}>{o.hint}</p>}
                {o.on && o.note && <p className={styles.layersHint}>{o.note}</p>}
              </div>
            ))}
          </fieldset>
        </div>
      )}
      {/* The notes of the layers that are on stay visible with the panel closed: a layer is never shown without
          its source and what it is not. */}
      {active.map((o) =>
        o.note ? (
          <p key={o.id} className={styles.layersNote}>
            <span className={styles.layersNoteFull}>{o.note}</span>
            <span className={styles.layersNoteShort}>{o.shortNote ?? o.note}</span>
          </p>
        ) : null,
      )}
    </div>
  );
}
