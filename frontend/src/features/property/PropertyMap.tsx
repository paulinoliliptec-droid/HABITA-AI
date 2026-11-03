"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import { HABITA_MAP_STYLE } from "@/lib/google-maps/mapStyle";
import { importMapsLibrary, MapsUnavailableError, onMapsAuthFailure } from "@/lib/google-maps/loader";
import { getAerial, aerialImageUrl, type AerialReport } from "@/features/aerial/api";
import { onReportChanged } from "@/features/report/api";
import { formatCoordinate } from "./format";
import { imageBounds } from "./mapLayers";
import { MapLayersPanel, type MapMode } from "./MapLayersPanel";
import type { Coordinates } from "./types";
import styles from "./PropertyMap.module.css";

type MapState = { status: "loading" | "ready" } | { status: "unavailable"; reason: MapsUnavailableError["reason"] };

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
  /** What this property holds in other areas (HR-004 point 3), each opening its area. */
  links?: { label: string; onClick: () => void }[];
}

export function PropertyMap({
  coordinates,
  zoom,
  label,
  card,
  propertyId,
}: {
  coordinates: Coordinates;
  zoom: number;
  label: string;
  card?: MarkerCard;
  /** When given, the map offers this property's layers (the aerial view). */
  propertyId?: string;
}) {
  const { t } = useI18n();
  // The marker's DOM node: its label and card are rendered into it by React (a portal), so they translate and
  // take keyboard focus like the rest of the page.
  const [markerEl, setMarkerEl] = useState<HTMLElement | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const [state, setState] = useState<MapState>({ status: "loading" });
  const [mode, setMode] = useState<MapMode>("roadmap");
  // HR-004 layers: the aerial view (DGT orthophoto with HABITA's SAM outlines) placed at its own bbox.
  const [aerial, setAerial] = useState<AerialReport | null>(null);
  const [aerialOn, setAerialOn] = useState(false);
  const [reportVersion, setReportVersion] = useState(0);
  useEffect(() => onReportChanged(() => setReportVersion((v) => v + 1)), []);
  useEffect(() => {
    if (!propertyId) return;
    const controller = new AbortController();
    getAerial(propertyId, controller.signal)
      .then((report) => {
        if (!controller.signal.aborted) setAerial(report);
      })
      .catch(() => {
        // The layer stays unavailable; the map itself never fails because of it.
      });
    return () => controller.abort();
  }, [propertyId, reportVersion]);

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

        const created = createLocationMarker(OverlayView, coordinates);
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

  const aerialBbox = aerial?.source.bbox;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || state.status !== "ready" || !aerialOn || !aerial || !aerialBbox) return;
    // The served image is the photo plus an attribution band below it: measure it, then hang the band below the
    // photo's own extent so outlines sit where SAM found them (Codex HR-004 r1, P1).
    let overlay: google.maps.GroundOverlay | null = null;
    let cancelled = false;
    const url = aerialImageUrl(aerial);
    const img = new Image();
    img.onload = () => {
      if (cancelled) return;
      const photoHeight = aerial.source.height ?? img.naturalWidth; // the orthophoto is square
      overlay = new google.maps.GroundOverlay(url, imageBounds(aerialBbox, photoHeight, img.naturalHeight), {
        clickable: false,
        opacity: 0.92,
      });
      overlay.setMap(map);
    };
    img.src = url;
    return () => {
      cancelled = true;
      overlay?.setMap(null);
    };
  }, [aerialOn, aerial, aerialBbox, state.status]);

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
        <MapLayersPanel
          mode={mode}
          onMode={setMode}
          overlays={[
            {
              id: "aerial",
              label: !aerial
                ? t("Aerial view (official orthophoto · SAM 3.1)")
                : aerial.source.provider === "DGT"
                  ? t("Aerial view (DGT {year} · SAM 3.1)", { year: aerial.source.year ?? "" })
                  : t("Aerial view ({source} · SAM 3.1)", { source: aerial.source.provider }),
              on: aerialOn && Boolean(aerial?.source.bbox),
              available: Boolean(aerial?.source.bbox),
              hint: t("Run the aerial analysis in the Place area first."),
              note: !aerial
                ? undefined
                : aerial.source.provider === "DGT"
                  ? t("Aerial view: DGT orthophoto of {year}, outlines by Meta SAM 3.1. Approximate observations, not a survey or a parcel boundary, and no proof of a licence. Informação geográfica cedida pela DGT (CC BY 4.0).", { year: aerial.source.year ?? "" })
                  : `${t("Aerial view: official orthophoto, outlines by Meta SAM 3.1. Approximate observations, not a survey or a parcel boundary, and no proof of a licence.")} ${aerial.source.attribution ?? ""}`,
              shortNote: !aerial
                ? undefined
                : aerial.source.provider === "DGT"
                  ? t("DGT {year} · SAM 3.1: approximate, not a parcel boundary. © DGT (CC BY 4.0)", { year: aerial.source.year ?? "" })
                  : `${t("{source} · SAM 3.1: approximate, not a parcel boundary.", { source: aerial.source.provider })} ${aerial.source.attribution ?? ""}`,
              onToggle: setAerialOn,
            },
            {
              // HR-004 point 1: no documented official map service publishes Cascais's PDM plans (SNIG catalogue,
              // DGT, GeoCascais checked 2026-11-02); HABITA never probes undocumented endpoints, so it says so.
              id: "pdm",
              label: t("Municipal plan (PDM) maps"),
              on: false,
              available: false,
              hint: t("No official map service publishes these plans yet: open the official PDF plans listed in the notes."),
              onToggle: () => {},
            },
          ]}
        />
      )}
      {markerEl && card && createPortal(<MarkerLabel label={label} card={card} />, markerEl)}
    </div>
  );
}

/** "Property under analysis" beside the point; a click or Enter opens a small card. */
function MarkerLabel({ label, card }: { label: string; card: MarkerCard }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const cardId = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  return (
    <div
      className={styles.markerLabelWrap}
      onKeyDown={(e) => {
        // Esc closes the card and gives focus back to its button (Muse UX-B r1).
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
        className={styles.markerLabel}
        aria-expanded={open}
        aria-controls={open ? cardId : undefined}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        {t("Property under analysis")}
      </button>
      {open && (
        <div id={cardId} className={styles.markerCard} role="group" aria-label={t("Property under analysis")}>
          <p className={styles.markerCardTitle}>{label}</p>
          {card.lines.map((line, i) => (
            <p key={i} className={styles.markerCardLine}>
              {line}
            </p>
          ))}
          <p className={styles.markerCardNote}>{t("Approximate location: a point, not a parcel boundary.")}</p>
          {card.links && card.links.length > 0 && (
            <div className={styles.markerCardLinks}>
              {card.links.map((l) => (
                <button
                  key={l.label}
                  type="button"
                  className={styles.markerCardLink}
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen(false);
                    l.onClick();
                  }}
                >
                  {l.label}
                </button>
              ))}
            </div>
          )}
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
): { overlay: google.maps.OverlayView; el: HTMLElement } {
  // Built once here, never in onAdd: the label and card are a React portal inside this node, and rewriting its
  // HTML when the map attaches it would remove them.
  const el = document.createElement("div");
  el.className = styles.marker;
  el.innerHTML = `<span class="${styles.markerHalo}" aria-hidden="true"></span><span class="${styles.markerDot}" aria-hidden="true"></span>`;
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
