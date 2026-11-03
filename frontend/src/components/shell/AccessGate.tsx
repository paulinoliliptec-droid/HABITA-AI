"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/Button";
import { useI18n } from "@/i18n/useI18n";
import styles from "./AccessGate.module.css";

const KEY = "habita-access-v1";
/** Meta Model API Geographic Use Policy (2026-10-12), §3 Restricted Territories, in its own order. */
export const RESTRICTED_TERRITORIES = [
  "Afghanistan", "Belarus", "Cambodia", "People's Republic of China (including Hong Kong and Macau)", "Cuba",
  "Eritrea", "Ethiopia", "Haiti", "Iran", "Iraq", "Libya", "Myanmar", "Nicaragua", "North Korea", "Pakistan", "Russia",
  "Somalia", "Syria", "the Crimea, Donetsk and Luhansk regions of Ukraine", "Venezuela", "Western Sahara",
] as const;

function readStored(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "yes";
  } catch {
    return false;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/**
 * Meta's terms for the models HABITA uses (afinamentos 2026-11-03): end users must be 18 or older and HABITA may not
 * knowingly admit users in Meta's restricted territories (and Muse Image, for the concepts, not in India). Before the
 * demo and the workspace, the visitor confirms both; the answer is kept in this browser only. Blocking by network
 * address would need a load balancer (owner decision); this is the notice and confirmation.
 */
export function AccessGate() {
  const { t } = useI18n();
  const pathname = usePathname();
  // Stored in this browser; nothing on the server render (the server snapshot says "accepted").
  const stored = useSyncExternalStore(subscribe, readStored, () => true);
  const [justAccepted, setJustAccepted] = useState(false);
  const gated = pathname.startsWith("/demo") || pathname.startsWith("/property");
  if (stored || justAccepted || !gated) return null;

  function accept() {
    try {
      window.localStorage.setItem(KEY, "yes");
    } catch {
      // private mode: the confirmation lasts for this page only
    }
    setJustAccepted(true);
  }

  return (
    <div className={styles.backdrop}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="access-title">
        <h2 id="access-title" className={styles.title}>
          {t("Before you start")}
        </h2>
        <p>{t("HABITA uses Meta's AI models, whose terms allow only people aged 18 or older, outside the territories Meta restricts.")}</p>
        <p className={styles.small}>
          {t("Restricted territories:")} {RESTRICTED_TERRITORIES.map((name) => t(name)).join(", ")}.{" "}
          {t("Before / after images (Muse Image) are also not available in India.")}
        </p>
        <div className={styles.actions}>
          <Button variant="primary" onClick={accept}>
            {t("I am 18 or older and not in any of these territories")}
          </Button>
          <Link href="/privacy">{t("Privacy & terms")}</Link>
        </div>
      </div>
    </div>
  );
}
