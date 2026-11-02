"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import { HABITA_MAP_STYLE } from "@/lib/google-maps/mapStyle";
import { importMapsLibrary, MapsUnavailableError, onMapsAuthFailure } from "@/lib/google-maps/loader";
import { formatCoordinate } from "./format";
import type { Coordinates } from "./types";
import styles from "./PropertyMap.module.css";

type MapState = { status: "loading" | "ready" } | { status: "unavailable"; reason: MapsUnavailableError["reason"] };
type MapMode = "roadmap" | "hybrid";

const UNAVAILABLE_COPY: Record<MapsUnavailableError["reason"], { title: string; devHint?: string }> = {
  not_configured: { title: msg("Map not configured"), devHint: "Set NEXT_PUBLIC_GOOGLE_MAPS_API_KEY in frontend/.env.local." },
  auth_failed: {
    title: msg("Map access was refused"),
    devHint: "Check the browser key's HTTP-referrer and API restrictions (Maps JavaScript API).",
  },
  load_failed: { title: msg("The map couldn't load") },
};

/** What the marker's card shows (UX-REFINE-001 §5): facts of the location only, never zoning or a licence. */
export interface MarkerCard {
  lines: string[];
  onOpen?: () => void;
}

export function PropertyMap({
  coordinates,
  zoom,
  label,
  card,
}: {
  coordinates: Coordinates;
  zoom: number;
  label: string;
  card?: MarkerCard;
}) {
  const { t } = useI18n();
  // The marker's DOM node: its label and card are rendered into it by React (a portal), so they translate and
  // take keyboard focus like the rest of the page.
  const [markerEl, setMarkerEl] = useState<HTMLElement | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const [state, setState] = useState<MapState>({ status: "loading" });
  const [mode, setMode] = useState<MapMode>("roadmap");

  useEffect(() => {
    let cancelled = false;
    let marker: google.maps.OverlayView | null = null;
    const unsubscribe = onMapsAuthFailure(() => setState({ status: "unavailable", reason: "auth_failed" }));

    (async () => {
      try {
        const { Map, OverlayView } = await importMapsLibrary("maps");
        if (cancelled || !containerRef.current) return;

        const coarsePointer = window.matchMedia("(pointer: coarse)").matches;
        const map =
          mapRef.current ??
          new Map(containerRef.current, {
            center: coordinates,
            zoom,
            styles: HABITA_MAP_STYLE,
            disableDefaultUI: true,
            zoomControl: true,
            zoomControlOptions: { position: google.maps.ControlPosition.RIGHT_BOTTOM },
            gestureHandling: coarsePointer ? "cooperative" : "greedy",
            clickableIcons: false,
            backgroundColor: "#f2f0eb",
          });
        mapRef.current = map;
        map.setCenter(coordinates);
        map.setZoom(zoom);

        const created = createLocationMarker(OverlayView, coordinates, label);
        marker = created.overlay;
        marker.setMap(map);
        setMarkerEl(created.el);
        setState({ status: "ready" });
      } catch (error) {
        if (cancelled) return;
        setState({
          status: "unavailable",
          reason: error instanceof MapsUnavailableError ? error.reason : "load_failed",
        });
      }
    })();

    return () => {
      cancelled = true;
      unsubscribe();
      marker?.setMap(null);
    };
  }, [coordinates, zoom, label]);

  useEffect(() => {
    mapRef.current?.setMapTypeId(mode);
  }, [mode]);

  if (state.status === "unavailable") {
    const copy = UNAVAILABLE_COPY[state.reason];
    return (
      <div className={`${styles.frame} ${styles.unavailable}`} role="img" aria-label={t("Map unavailable. {label}", { label })}>
        <div className={styles.unavailableCard}>
          <p className={styles.unavailableTitle}>{t(copy.title)}</p>
          <p className={styles.unavailableCoords}>
            {formatCoordinate(coordinates.lat, "lat")} · {formatCoordinate(coordinates.lng, "lng")}
          </p>
          {process.env.NODE_ENV !== "production" && copy.devHint && (
            <p className={styles.unavailableHint}>{copy.devHint}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.frame} data-status={state.status}>
      <div ref={containerRef} className={styles.map} role="region" aria-label={t("Map of {label}", { label })} />
      {state.status === "ready" && (
        <div className={styles.modes} role="radiogroup" aria-label={t("Map view")}>
          {(["roadmap", "hybrid"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              className={styles.mode}
              onClick={() => setMode(m)}
            >
              {m === "roadmap" ? t("Map") : t("Satellite")}
            </button>
          ))}
        </div>
      )}
      {markerEl && card && createPortal(<MarkerLabel label={label} card={card} />, markerEl)}
    </div>
  );
}

/** "Property under analysis" beside the point; a click or Enter opens a small card. */
function MarkerLabel({ label, card }: { label: string; card: MarkerCard }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.markerLabelWrap}>
      <button
        type="button"
        className={styles.markerLabel}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        {t("Property under analysis")}
      </button>
      {open && (
        <div className={styles.markerCard} role="dialog" aria-label={t("Property under analysis")}>
          <p className={styles.markerCardTitle}>{label}</p>
          {card.lines.map((line) => (
            <p key={line} className={styles.markerCardLine}>
              {line}
            </p>
          ))}
          <p className={styles.markerCardNote}>{t("Approximate location: a point, not a parcel boundary.")}</p>
          {card.onOpen && (
            <button
              type="button"
              className={styles.markerCardAction}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                card.onOpen?.();
              }}
            >
              {t("Open the analysis")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** An HTML marker drawn with an OverlayView, so it needs neither a Map ID nor the legacy Marker. */
function createLocationMarker(
  OverlayView: typeof google.maps.OverlayView,
  position: Coordinates,
  label: string,
): { overlay: google.maps.OverlayView; el: HTMLElement } {
  // Built once here, never in onAdd: the label and card are a React portal inside this node, and rewriting its
  // HTML when the map attaches it would remove them.
  const el = document.createElement("div");
  el.className = styles.marker;
  el.setAttribute("aria-label", label);
  el.innerHTML = `<span class="${styles.markerHalo}"></span><span class="${styles.markerDot}"></span>`;
  class LocationMarker extends OverlayView {
    private el = el;

    onAdd() {
      this.getPanes()?.overlayMouseTarget.append(this.el);
    }

    draw() {
      const point = this.getProjection()?.fromLatLngToDivPixel(new google.maps.LatLng(position));
      if (point) this.el.style.transform = `translate(${point.x}px, ${point.y}px)`;
    }

    onRemove() {
      this.el.remove();
    }
  }
  return { overlay: new LocationMarker(), el };
}
