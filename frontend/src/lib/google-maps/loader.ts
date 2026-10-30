/**
 * Loads the Maps JavaScript API once per page with the browser key, then exposes
 * `importLibrary`. Uses the documented `loading=async` + callback bootstrap, with
 * no wrapper dependency.
 *
 * Every call settles: auth failure rejects pending and future imports, and the
 * bootstrap and each library import have a deadline. A failed or timed-out load
 * can be retried; an auth failure is final for the page.
 */
import { config } from "@/lib/config";

export type MapsUnavailableReason = "not_configured" | "load_failed" | "auth_failed";

export class MapsUnavailableError extends Error {
  constructor(readonly reason: MapsUnavailableReason) {
    super(`Google Maps unavailable: ${reason}`);
  }
}

type MapsWindow = Window & {
  __habitaMapsReady?: () => void;
  gm_authFailure?: () => void;
};

export const LOAD_TIMEOUT_MS = 12_000;

let loadPromise: Promise<void> | null = null;
let authFailed = false;
const authFailureListeners = new Set<() => void>();

function withDeadline<T>(promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new MapsUnavailableError("load_failed")), LOAD_TIMEOUT_MS);
  });
  // Auth failure ends every pending import, not only the ones started afterwards.
  let off = () => {};
  const auth = new Promise<never>((_, reject) => {
    off = onMapsAuthFailure(() => reject(new MapsUnavailableError("auth_failed")));
  });
  // Whichever settles first, release the timer and the listener (no leak across retries).
  return Promise.race([promise, deadline, auth]).finally(() => {
    clearTimeout(timer);
    off();
  });
}

function load(): Promise<void> {
  if (!config.googleMapsApiKey) return Promise.reject(new MapsUnavailableError("not_configured"));
  if (loadPromise) return loadPromise;

  const w = window as MapsWindow;
  // Google calls this global when the key is invalid or the referrer isn't allowed.
  w.gm_authFailure = () => {
    authFailed = true;
    authFailureListeners.forEach((listener) => listener());
  };

  const script = document.createElement("script");
  const bootstrap = new Promise<void>((resolve, reject) => {
    w.__habitaMapsReady = () => resolve();
    script.onerror = () => reject(new MapsUnavailableError("load_failed"));
  });
  const params = new URLSearchParams({
    key: config.googleMapsApiKey,
    v: "weekly",
    loading: "async",
    callback: "__habitaMapsReady",
  });
  script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
  script.async = true;
  document.head.append(script);

  const settled = withDeadline(bootstrap);
  loadPromise = settled.then(
    () => {
      delete w.__habitaMapsReady;
    },
    (error: unknown) => {
      // Allow a later retry after a network failure or timeout.
      loadPromise = null;
      script.remove();
      delete w.__habitaMapsReady;
      throw error;
    },
  );
  return loadPromise;
}

export async function importMapsLibrary<K extends keyof MapsLibraries>(name: K): Promise<MapsLibraries[K]> {
  if (authFailed) throw new MapsUnavailableError("auth_failed");
  await load();
  if (authFailed) throw new MapsUnavailableError("auth_failed");
  const library = await withDeadline(google.maps.importLibrary(name) as Promise<MapsLibraries[K]>);
  if (authFailed) throw new MapsUnavailableError("auth_failed");
  return library;
}

/** Number of active auth-failure listeners (diagnostics and tests). */
export function authFailureListenerCount(): number {
  return authFailureListeners.size;
}

/** Subscribe to key/referrer rejection. Returns an unsubscribe function. */
export function onMapsAuthFailure(listener: () => void): () => void {
  if (authFailed) queueMicrotask(listener);
  authFailureListeners.add(listener);
  return () => authFailureListeners.delete(listener);
}

interface MapsLibraries {
  maps: google.maps.MapsLibrary;
  places: google.maps.PlacesLibrary;
  core: google.maps.CoreLibrary;
}
