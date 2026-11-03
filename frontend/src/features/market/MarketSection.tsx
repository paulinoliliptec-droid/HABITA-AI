"use client";

import { useEffect, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { Section } from "@/components/ui/Section";
import { useI18n } from "@/i18n/useI18n";
import { apiRequest } from "@/lib/api";
import styles from "./MarketSection.module.css";

interface MarketFigure {
  label: string;
  value: number;
  unit: string;
  area: string;
  period: string;
  count: number;
  source: string;
  url: string;
  note: string;
}

/**
 * Partial coverage (afinamentos 2026-11-03): official market prices for New York City, Paris and Singapore, and what
 * is not built there yet. Every number is a median HABITA computed from an open official dataset, never a valuation.
 */
export function MarketSection({ propertyId }: { propertyId: string }) {
  const { t, lang } = useI18n();
  const [figures, setFigures] = useState<MarketFigure[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<{ figures: MarketFigure[] }>(`/api/property/${propertyId}/market`, { signal: controller.signal })
      .then((r) => setFigures(r.figures))
      .catch(() => setFigures([]));
    return () => controller.abort();
  }, [propertyId]);

  const number = new Intl.NumberFormat(lang === "pt" ? "pt-PT" : "en-GB");
  return (
    <>
      <Section label={t("Market prices (official statistics)")} id="market">
        {figures === null ? null : figures.length === 0 ? (
          <p className={styles.hint}>{t("No official price statistics are available for this address.")}</p>
        ) : (
          figures.map((f) => (
            <div key={f.source} className={styles.figure}>
              <p className={styles.label}>
                {t(f.label)} · {f.area} · {f.period}
              </p>
              <p className={styles.value}>
                {number.format(f.value)} <span className={styles.unit}>{f.unit}</span>
              </p>
              <p className={styles.hint}>
                {t("{n} sales.", { n: number.format(f.count) })} {t(f.note)}{" "}
                <a href={f.url} target="_blank" rel="noopener noreferrer">
                  {f.source}
                </a>
              </p>
            </div>
          ))
        )}
        <p className={styles.hint}>
          {t("A median of past sales in the area, computed by HABITA from the official open data: not a valuation of this property.")}
        </p>
      </Section>
      <Notice title={t("What is not built here yet")}>
        {t("For this place HABITA shows the jurisdiction, the competent authority with its official sources, the aerial view where an official orthophoto allows it, and official prices. Verified permit answers, the request catalogue, works costs and financing, and the PDF's aerial figure exist for Portugal only: they need this place's official sources ingested and checked, and its law reviewed. These cities show that the same architecture extends to other legal systems; they are a proof of scale, with these limitations.")}
      </Notice>
    </>
  );
}
