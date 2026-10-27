import { Skeleton } from "@/components/ui/Skeleton";

export function WorkspaceSkeleton() {
  return (
    <div role="status" aria-label="Loading property" style={{ display: "grid", gap: "var(--space-4)" }}>
      <Skeleton width="5rem" height="0.75rem" />
      <Skeleton width="85%" height="2.25rem" />
      <Skeleton width="60%" height="1.1rem" />
      <div style={{ height: "var(--space-6)" }} />
      <Skeleton width="6rem" height="0.75rem" />
      {[70, 55, 62].map((w) => (
        <Skeleton key={w} width={`${w}%`} height="1rem" />
      ))}
      <Skeleton height="5.5rem" style={{ marginTop: "var(--space-2)" }} />
    </div>
  );
}
