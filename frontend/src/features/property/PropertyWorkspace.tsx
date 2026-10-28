"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Notice } from "@/components/ui/Notice";
import { PermitSection } from "@/features/permit/PermitSection";
import { ApiError } from "@/lib/api";
import { AddressSearch } from "./AddressSearch";
import { getCachedProperty, getProperty, subscribeToProperties } from "./api";
import { PRECISION, splitAddress } from "./format";
import { JurisdictionSection } from "./JurisdictionSection";
import { LocationSection } from "./LocationSection";
import { PropertyIdentity } from "./PropertyIdentity";
import { PropertyMap } from "./PropertyMap";
import { WorkspaceSkeleton } from "./WorkspaceSkeleton";
import styles from "./PropertyWorkspace.module.css";

const noProperty = () => undefined;

export function PropertyWorkspace({ propertyId }: { propertyId: string }) {
  // Re-renders whenever this property is resolved or fetched again anywhere in the tab.
  const property = useSyncExternalStore(subscribeToProperties, () => getCachedProperty(propertyId), noProperty);
  // undefined: no failure; null: failure without a structured error.
  const [error, setError] = useState<ApiError | null | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);
  // Set by the search that opened this workspace; a later reload keeps it via the URL.
  const partialMatch = useSearchParams().get("match") === "partial";

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
      <aside className={styles.panel} aria-label="Property details">
        <div className={styles.panelSearch}>
          <AddressSearch variant="compact" />
        </div>
        <div className={styles.panelBody}>
          {property ? (
            <>
              <title>{`${splitAddress(property.formatted_address).headline} · HABITA AI`}</title>
              <PropertyIdentity property={property} partialMatch={partialMatch} />
              <JurisdictionSection jurisdiction={property.jurisdiction} propertyId={property.property_id} />
              <PermitSection
                propertyId={property.property_id}
                authorityName={property.jurisdiction.local_authority?.name ?? null}
              />
              <LocationSection property={property} />
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
        {property ? (
          <PropertyMap
            coordinates={property.coordinates}
            zoom={PRECISION[property.precision].zoom}
            label={property.formatted_address}
          />
        ) : (
          <div className={styles.mapPlaceholder} aria-hidden="true" />
        )}
      </div>
    </div>
  );
}

function LoadError({ error, onRetry }: { error: ApiError | null; onRetry: () => void }) {
  // A malformed ID (validation_error) is just as unknown as a missing one.
  if (error?.code === "not_found" || error?.code === "validation_error") {
    return (
      <Notice
        title="This property isn't in HABITA yet"
        action={
          <ButtonLink href="/" variant="secondary">
            <Icon name="arrowLeft" size={16} />
            Search for an address
          </ButtonLink>
        }
      >
        The link may be out of date. Search for the address to resolve it again.
      </Notice>
    );
  }
  return (
    <Notice
      tone="danger"
      title="We couldn't load this property"
      live
      action={
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      }
    >
      {error?.message ?? "Something went wrong. Please try again."}
    </Notice>
  );
}
