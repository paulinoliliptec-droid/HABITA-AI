import { apiRequest } from "@/lib/api";
import type { ResolvedProperty, ResolveLocationInput } from "./types";

/**
 * Properties resolved or fetched in this tab, so the workspace renders immediately
 * after navigation and updates when the same property is resolved again.
 * Entries are short-lived; the backend remains the source of truth.
 */
const MAX_AGE_MS = 10 * 60 * 1000;

interface Entry {
  property: ResolvedProperty;
  storedAt: number;
}

const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();

export function getCachedProperty(propertyId: string, now = Date.now()): ResolvedProperty | undefined {
  const entry = entries.get(propertyId);
  if (!entry) return undefined;
  const expired = now - entry.storedAt > MAX_AGE_MS || Date.parse(entry.property.expires_at) <= now;
  return expired ? undefined : entry.property;
}

export function subscribeToProperties(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function rememberProperty(property: ResolvedProperty, now = Date.now(), alsoAs?: string): void {
  entries.set(property.property_id, { property, storedAt: now });
  // A merged duplicate's ID resolves to its canonical property; keep it findable under the requested ID.
  if (alsoAs && alsoAs !== property.property_id) entries.set(alsoAs, { property, storedAt: now });
  listeners.forEach((listener) => listener());
}

export async function resolveLocation(input: ResolveLocationInput, signal?: AbortSignal): Promise<ResolvedProperty> {
  const property = await apiRequest<ResolvedProperty>("/api/property/resolve-location", {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
  rememberProperty(property);
  return property;
}

export async function getProperty(propertyId: string, signal?: AbortSignal): Promise<ResolvedProperty> {
  const property = await apiRequest<ResolvedProperty>(`/api/property/${encodeURIComponent(propertyId)}`, { signal });
  rememberProperty(property, Date.now(), propertyId);
  return property;
}
