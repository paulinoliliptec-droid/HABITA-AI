"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Section } from "@/components/ui/Section";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { ImageViewer } from "@/features/permit/ImageViewer";
import { reportChanged } from "@/features/report/api";
import { AERIAL_CHECK_TEXT, type AerialObject, type AerialReport, aerialImageUrl, createAerial, getAerial } from "./api";
import styles from "./AerialSection.module.css";

const KIND = {
  building: "Building",
  small_building: "Small separate building",
  pool: "Swimming pool",
} as const;

/**
 * Seen from the air (owner, 2026-11-01): the official DGT orthophoto around the property, segmented by Meta SAM 3.1.
 * Observations only: what is visible may need confirming with the Câmara; it is never a parcel boundary or a licence.
 */
export function AerialSection({ propertyId, precision }: { propertyId: string; precision: string }) {
  const { t } = useI18n();
  const [report, setReport] = useState<AerialReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [large, setLarge] = useState(false);
  const precise = precision === "rooftop" || precision === "interpolated";

  useEffect(() => {
    const controller = new AbortController();
    getAerial(propertyId, controller.signal)
      .then(setReport)
      .catch(() => undefined);
    return () => controller.abort();
  }, [propertyId]);

  async function analyse() {
    setBusy(true);
    setError(null);
    try {
      setReport(await createAerial(propertyId));
      reportChanged(); // the map notes, PDF and voice pick up the new conditions (Codex aerial-r1)
    } catch (err) {
      setError(err instanceof ApiError ? t(err.message) : t("Something went wrong. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const line = (o: AerialObject) =>
    [
      t(KIND[o.kind]),
      `≈${o.area_m2} m²`,
      o.at_point ? t("at the address point") : t("{n} m from the address point", { n: o.distance_m }),
    ].join(" · ");

  return (
    <Section label={t("Seen from the air")} id="aerial">
      <p className={styles.purpose}>
        {t("HABITA looks at the official DGT orthophoto around this address with Meta SAM 3.1 and lists the buildings and pools it sees. It is an observation to confirm, not a survey, a parcel boundary or proof of a licence.")}
      </p>
      {!report && precise && (
        <Button variant="primary" onClick={() => void analyse()} disabled={busy}>
          {busy ? t("Analysing the aerial image… this can take a minute") : `🛰️ ${t("Analyse the aerial image")}`}
        </Button>
      )}
      {!report && !precise && (
        // No dead button (owner, 2026-11-01: "o botão está seco"): say why and what to do instead.
        <div className={styles.check} role="note">
          <p>
            {t("The aerial view needs an exact address, with the door number. This address points to an area (a square or a street), not to one building, so HABITA can't say which buildings belong to it.")}
          </p>
          <p className={styles.hint}>{t("Search for the address with its number, for example “Rua Frederico Arouca 30, Cascais”.")}</p>
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {report && (
        <div className={styles.result}>
          <button type="button" className={styles.thumb} onClick={() => setLarge(true)}>
            {/* eslint-disable-next-line @next/next/no-img-element -- served by the API with its own headers */}
            <img src={aerialImageUrl(report)} alt={t("Aerial image with the outlines HABITA found")} />
          </button>
          <p className={styles.legend}>
            <span className={styles.swatchBuilding} /> {t("Building")} <span className={styles.swatchSmall} />{" "}
            {t("Small separate building")} <span className={styles.swatchPool} /> {t("Swimming pool")} ·{" "}
            {t("yellow circle: {n} m around the address point", { n: report.radius_m })}
          </p>
          {report.objects.length === 0 ? (
            <p className={styles.hint}>{t("Nothing was found within the circle.")}</p>
          ) : (
            <ul className={styles.list}>
              {report.objects.map((o, i) => (
                <li key={i}>{line(o)}</li>
              ))}
            </ul>
          )}
          {report.checks.map((c) => (
            <p key={c} className={styles.check}>
              {t(AERIAL_CHECK_TEXT[c])}
            </p>
          ))}
          <p className={styles.hint}>
            {t("Seen from the air on the DGT orthophoto of {year}, segmented by Meta SAM 3.1. Outlines and areas are approximate, may miss recent works, are not a survey or a parcel boundary, and prove no licence.", { year: report.source.year })}
          </p>
          <p className={styles.hint}>
            Informação geográfica cedida pela Direção-Geral do Território (CC BY 4.0) · {t("outlines added by HABITA")}
          </p>
          {large && (
            <ImageViewer
              src={aerialImageUrl(report)}
              alt={t("Aerial image with the outlines HABITA found")}
              caption={`Informação geográfica cedida pela Direção-Geral do Território (CC BY 4.0) · Ortos ${report.source.year} · Meta SAM 3.1`}
              onClose={() => setLarge(false)}
            />
          )}
        </div>
      )}
    </Section>
  );
}
