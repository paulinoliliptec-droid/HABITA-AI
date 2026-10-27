"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Section } from "@/components/ui/Section";
import { formatCoordinate } from "./format";
import type { ResolvedProperty } from "./types";
import styles from "./LocationSection.module.css";

export function LocationSection({ property }: { property: ResolvedProperty }) {
  const { lat, lng } = property.coordinates;
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 1800);
    return () => clearTimeout(id);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
      setCopied(true);
    } catch {
      // Clipboard can be blocked (permissions, insecure context); the values stay visible.
    }
  }

  const resolvedAt = new Date(property.resolved_at);

  return (
    <Section label="Location" id="location">
      <dl className={styles.grid}>
        <div>
          <dt>Latitude</dt>
          <dd>{formatCoordinate(lat, "lat")}</dd>
        </div>
        <div>
          <dt>Longitude</dt>
          <dd>{formatCoordinate(lng, "lng")}</dd>
        </div>
      </dl>
      <div className={styles.footer}>
        <p className={styles.source}>
          Google Maps ·{" "}
          <time dateTime={property.resolved_at}>
            {resolvedAt.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
          </time>{" "}
          · <Link href="/privacy">Privacy &amp; terms</Link>
        </p>
        <Button variant="ghost" onClick={copy} aria-live="polite">
          <Icon name={copied ? "check" : "copy"} size={16} />
          {copied ? "Copied" : "Copy coordinates"}
        </Button>
      </div>
    </Section>
  );
}
