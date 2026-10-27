import { Suspense, ViewTransition } from "react";
import { PropertyWorkspace } from "@/features/property/PropertyWorkspace";

// The property ID is only known at request time, so the param is read inside Suspense.
export default function PropertyPage({ params }: PageProps<"/property/[propertyId]">) {
  return (
    <ViewTransition enter="arrive" default="none">
      <main>
        <Suspense>
          {params.then(({ propertyId }) => (
            <PropertyWorkspace key={propertyId} propertyId={propertyId} />
          ))}
        </Suspense>
      </main>
    </ViewTransition>
  );
}
