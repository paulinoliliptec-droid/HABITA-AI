/**
 * The browser keeps the capability for the permit matter it created, per property, so a reload resumes it.
 * It lives only in this browser's localStorage, is sent only in the Authorization header, and never appears
 * in URLs. Storage can be unavailable (private mode, blocked site data): everything degrades to "no matter".
 */
export interface MatterCapability {
  matterId: string;
  token: string;
}

const key = (propertyId: string) => `habita.permit.${propertyId}`;

export function recallMatter(propertyId: string): MatterCapability | null {
  try {
    const raw = localStorage.getItem(key(propertyId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<MatterCapability>;
    return typeof value.matterId === "string" && typeof value.token === "string"
      ? { matterId: value.matterId, token: value.token }
      : null;
  } catch {
    return null;
  }
}

export function rememberMatter(propertyId: string, capability: MatterCapability): void {
  try {
    localStorage.setItem(key(propertyId), JSON.stringify(capability));
  } catch {
    // Not persisted: the matter still works for this page view.
  }
}

export function forgetMatter(propertyId: string): void {
  try {
    localStorage.removeItem(key(propertyId));
  } catch {
    // Nothing stored.
  }
}
