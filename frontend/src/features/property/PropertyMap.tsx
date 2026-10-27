"use client";

import { useEffect, useRef, useState } from "react";
import { HABITA_MAP_STYLE } from "@/lib/google-maps/mapStyle";
import { importMapsLibrary, MapsUnavailableError, onMapsAuthFailure } from "@/lib/google-maps/loader";
import { formatCoordinate } from "./format";
import type { Coordinates } from "./types";
import styles from "./PropertyMap.module.css";

type MapState = { status: "loading" | "ready" } | { status: "unavailable"; reason: MapsUnavailableError["reason"] };
type MapMode = "roadmap" | "hybrid";

const UNAVAILABLE_COPY: Record<MapsUnavailableError["reason"], { title: string; devHint?: string }> = {
  not_configured: { title: "Map not configured", devHint: "Set NEXT_PUBLIC_GOOGLE_MAPS_API_KEY in frontend/.env.local." },
  auth_failed: {
    title: "Map access was refused",
    devHint: "Check the browser key's HTTP-referrer and API restrictions (Maps JavaScript API).",
  },
  load_failed: { title: "The map couldn't load" },
};

export function PropertyMap({ coordinates, zoom, label }: { coordinates: Coordinates; zoom: number; label: string }) {
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

        marker = createLocationMarker(OverlayView, coordinates, label);
        marker.setMap(map);
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
      <div className={`${styles.frame} ${styles.unavailable}`} role="img" aria-label={`Map unavailable. ${label}`}>
        <div className={styles.unavailableCard}>
          <p className={styles.unavailableTitle}>{copy.title}</p>
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
      <div ref={containerRef} className={styles.map} role="region" aria-label={`Map of ${label}`} />
      {state.status === "ready" && (
        <div className={styles.modes} role="radiogroup" aria-label="Map view">
          {(["roadmap", "hybrid"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              className={styles.mode}
              onClick={() => setMode(m)}
            >
              {m === "roadmap" ? "Map" : "Satellite"}
            </button>
          ))}
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
): google.maps.OverlayView {
  class LocationMarker extends OverlayView {
    private el = document.createElement("div");

    onAdd() {
      this.el.className = styles.marker;
      this.el.title = label;
      this.el.innerHTML = `<span class="${styles.markerHalo}"></span><span class="${styles.markerDot}"></span>`;
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
  return new LocationMarker();
}
