"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import {
  getPlanningContext,
  instrumentName,
  officialTextSource,
  PLANNING_STATUS,
  provenanceDate,
  type PlanningContextResponse,
} from "./planning";
import styles from "./JurisdictionSection.module.css";

/**
 * The planning instrument and zoning status at the property, from HABITA's official source registry.
 * Zoning is shown only when an official layer determined it; otherwise the exact official maps to check.
 */
export function PlanningContextBlock({ propertyId }: { propertyId: string }) {
  // Keyed by property, so a previous property's context is never shown while the next one loads.
  const [result, setResult] = useState<{ propertyId: string; data?: PlanningContextResponse } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getPlanningContext(propertyId, controller.signal)
      .then((data) => setResult({ propertyId, data }))
      .catch(() => {
        if (!controller.signal.aborted) setResult({ propertyId });
      });
    return () => controller.abort();
  }, [propertyId]);

  const current = result?.propertyId === propertyId ? result : null;
  const data = current?.data ?? null;
  if (current && !data) return <p className={styles.planningQuiet}>Planning context is unavailable right now.</p>;
  if (!data) return null;

  const context = data.planning_context;
  const status = PLANNING_STATUS[context.status];
  if (context.status === "not_supported" || !context.instrument) {
    return <p className={styles.planningQuiet}>{context.guidance}</p>;
  }
  const officialText = officialTextSource(data.sources, context.instrument.source_id);
  const dates = [
    provenanceDate(context.sources_verified_on, "Sources verified"),
    provenanceDate(officialText?.snapshot_retrieved_at ?? null, "Regulation text retrieved"),
  ].filter(Boolean);

  return (
    <div className={styles.planning}>
      <div className={styles.planningHead}>
        <p className={styles.authorityLabel}>Planning context</p>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      <p className={styles.planningInstrument}>
        {context.instrument.official_url ? (
          <a href={context.instrument.official_url} target="_blank" rel="noopener noreferrer">
            {instrumentName(context.instrument.title)}
          </a>
        ) : (
          instrumentName(context.instrument.title)
        )}
        {context.classification && <span className={styles.planningClass}> · {context.classification.label}</span>}
      </p>
      <p className={styles.authorityNote}>{context.guidance}</p>

      {context.documents_to_consult.length > 0 && (
        <details className={styles.planningDocs}>
          <summary>Official maps and documents to check ({context.documents_to_consult.length})</summary>
          <ul>
            {context.documents_to_consult.map((doc) => (
              <li key={doc.source_id}>
                {doc.official_url ? (
                  <a href={doc.official_url} target="_blank" rel="noopener noreferrer">
                    {doc.designation ?? doc.title}
                  </a>
                ) : (
                  (doc.designation ?? doc.title)
                )}
                <span className={styles.planningReason}>{doc.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {dates.length > 0 && <p className={styles.authoritySource}>{dates.join(" · ")}</p>}
    </div>
  );
}
