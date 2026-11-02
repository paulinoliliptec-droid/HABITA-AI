"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Notice } from "@/components/ui/Notice";
import { PermitSection } from "@/features/permit/PermitSection";
import { AerialSection } from "@/features/aerial/AerialSection";
import { MapPostIts } from "@/features/report/MapPostIts";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { AddressSearch } from "./AddressSearch";
import { getCachedProperty, getProperty, subscribeToProperties } from "./api";
import { placeLine, PRECISION, splitAddress } from "./format";
import { JurisdictionSection } from "./JurisdictionSection";
import { LocationSection } from "./LocationSection";
import { PropertyIdentity } from "./PropertyIdentity";
import { PropertyMap } from "./PropertyMap";
import { WorkspaceSkeleton } from "./WorkspaceSkeleton";
import { WorkspaceTabs } from "./WorkspaceTabs";
import { areaFromHash, DEFAULT_AREA, type AreaId } from "./areas";
import styles from "./PropertyWorkspace.module.css";

const noProperty = () => undefined;

export function PropertyWorkspace({ propertyId }: { propertyId: string }) {
  const { t } = useI18n();
  // Re-renders whenever this property is resolved or fetched again anywhere in the tab.
  const property = useSyncExternalStore(subscribeToProperties, () => getCachedProperty(propertyId), noProperty);
  // undefined: no failure; null: failure without a structured error.
  const [error, setError] = useState<ApiError | null | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);
  // Set by the search that opened this workspace; a later reload keeps it via the URL.
  const partialMatch = useSearchParams().get("match") === "partial";
  // The area shown (UX-REFINE-001): kept in the URL hash, so a link or a reload opens the same area.
  const [area, setArea] = useState<AreaId>(DEFAULT_AREA);
  useEffect(() => {
    const sync = () => setArea(areaFromHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const go = (next: AreaId) => {
    setArea(next);
    window.history.replaceState(null, "", `#${next}`);
  };

  useEffect(() => {
    if (property) return;
    const controller = new AbortController();
    getProperty(propertyId, controller.signal).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof ApiError ? err : null);
    });
    return () => controller.abort();
  }, [propertyId, property, attempt]);

  const failed = !property && error !== undefined;

  return (
    <div className={styles.workspace}>
      <aside className={styles.panel} aria-label={t("Property details")}>
        <div className={styles.panelSearch}>
          <AddressSearch variant="compact" />
        </div>
        <div className={styles.panelBody}>
          {property ? (
            <>
              <title>{`${splitAddress(property.formatted_address).headline} · HABITA AI`}</title>
              <PropertyIdentity property={property} partialMatch={partialMatch} />
              <WorkspaceTabs area={area} onChange={go} />
              {/* Every area stays mounted (hidden when not shown): switching never loses a question, an upload or
                  a calculation in progress. */}
              <PermitSection
                propertyId={property.property_id}
                authorityName={property.jurisdiction.local_authority?.name ?? null}
                area={area}
                onGo={go}
              />
              <div role="tabpanel" id="area-place" aria-labelledby="area-tab-place" hidden={area !== "place"}>
                <JurisdictionSection jurisdiction={property.jurisdiction} propertyId={property.property_id} />
                <AerialSection propertyId={property.property_id} precision={property.precision} />
                <LocationSection property={property} />
              </div>
            </>
          ) : failed ? (
            <LoadError
              error={error}
              onRetry={() => {
                setError(undefined);
                setAttempt((n) => n + 1);
              }}
            />
          ) : (
            <WorkspaceSkeleton />
          )}
        </div>
      </aside>

      <div className={styles.mapArea}>
        {property && <MapPostIts propertyId={property.property_id} />}
        {property ? (
          <div className={styles.mapCanvas}>
            <PropertyMap
              coordinates={property.coordinates}
              zoom={PRECISION[property.precision].zoom}
              label={property.formatted_address}
              card={{
                lines: [placeLine(property.jurisdiction), t(PRECISION[property.precision].label)],
                onOpen: () => {
                  go("question");
                  document.getElementById("area-question")?.scrollIntoView({ behavior: "smooth", block: "start" });
                },
              }}
            />
          </div>
        ) : (
          <div className={styles.mapPlaceholder} aria-hidden="true" />
        )}
      </div>
    </div>
  );
}

function LoadError({ error, onRetry }: { error: ApiError | null; onRetry: () => void }) {
  const { t } = useI18n();
  // A malformed ID (validation_error) is just as unknown as a missing one.
  if (error?.code === "not_found" || error?.code === "validation_error") {
    return (
      <Notice
        title={t("This property isn't in HABITA yet")}
        action={
          <ButtonLink href="/demo" variant="secondary">
            <Icon name="arrowLeft" size={16} />
            {t("Search for an address")}
          </ButtonLink>
        }
      >
        {t("The link may be out of date. Search for the address to resolve it again.")}
      </Notice>
    );
  }
  return (
    <Notice
      tone="danger"
      title={t("We couldn't load this property")}
      live
      action={
        <Button variant="secondary" onClick={onRetry}>
          {t("Try again")}
        </Button>
      }
    >
      {error?.message ?? t("Something went wrong. Please try again.")}
    </Notice>
  );
}
