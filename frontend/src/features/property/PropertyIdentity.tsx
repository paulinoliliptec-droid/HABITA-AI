import { Badge } from "@/components/ui/Badge";
import { Notice } from "@/components/ui/Notice";
import { placeLine, PRECISION, splitAddress } from "./format";
import type { ResolvedProperty } from "./types";
import styles from "./PropertyIdentity.module.css";

export function PropertyIdentity({ property, partialMatch }: { property: ResolvedProperty; partialMatch: boolean }) {
  const { headline, remainder } = splitAddress(property.formatted_address);
  const precision = PRECISION[property.precision];

  return (
    <header className={styles.identity}>
      <p className={styles.eyebrow}>Property</p>
      <h1 className={styles.address}>
        {headline}
        {remainder && <span className={styles.remainder}>{remainder}</span>}
      </h1>
      <div className={styles.meta}>
        <span className={styles.place}>{placeLine(property.jurisdiction)}</span>
        <Badge tone={precision.tone}>{precision.label}</Badge>
      </div>
      {partialMatch && (
        <Notice tone="warning" title="Closest match">
          Google Maps couldn&apos;t match every part of the address you entered. Check that this is the right property.
        </Notice>
      )}
    </header>
  );
}
