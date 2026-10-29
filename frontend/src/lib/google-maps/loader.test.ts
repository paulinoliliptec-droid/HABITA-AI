import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Loader = typeof import("./loader");

interface FakeScript {
  src: string;
  async: boolean;
  onerror: (() => void) | null;
  remove: () => void;
}

let scripts: FakeScript[];
let win: Record<string, unknown>;

async function freshLoader(key: string | null = "browser-key"): Promise<Loader> {
  vi.resetModules();
  vi.doMock("@/lib/config", () => ({ config: { apiBaseUrl: "", googleMapsApiKey: key } }));
  return import("./loader");
}

function installGoogle(importLibrary: (name: string) => Promise<unknown>) {
  vi.stubGlobal("google", { maps: { importLibrary } });
}

beforeEach(() => {
  scripts = [];
  win = {};
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", {
    createElement: () => {
      const script: FakeScript = { src: "", async: false, onerror: null, remove: () => {} };
      scripts.push(script);
      return script;
    },
    head: { append: () => {} },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

const ready = () => (win.__habitaMapsReady as () => void)();
const authFailure = () => (win.gm_authFailure as () => void)();

describe("importMapsLibrary", () => {
  it("loads once and imports libraries after the bootstrap callback", async () => {
    const loader = await freshLoader();
    installGoogle(async (name) => ({ name }));
    const a = loader.importMapsLibrary("maps");
    const b = loader.importMapsLibrary("places");
    ready();
    await expect(a).resolves.toEqual({ name: "maps" });
    await expect(b).resolves.toEqual({ name: "places" });
    expect(scripts).toHaveLength(1);
    expect(scripts[0].src).toContain("loading=async");
  });

  it("rejects as not_configured without a browser key", async () => {
    const loader = await freshLoader(null);
    await expect(loader.importMapsLibrary("maps")).rejects.toMatchObject({ reason: "not_configured" });
  });

  it("settles pending imports when auth fails before the API is ready", async () => {
    const loader = await freshLoader();
    const pending = loader.importMapsLibrary("places");
    authFailure();
    await expect(pending).rejects.toMatchObject({ reason: "auth_failed" });
    await expect(loader.importMapsLibrary("maps")).rejects.toMatchObject({ reason: "auth_failed" });
  });

  it("settles an import in flight when auth fails after readiness", async () => {
    const loader = await freshLoader();
    installGoogle(() => new Promise(() => {}));
    const pending = loader.importMapsLibrary("maps");
    ready();
    await Promise.resolve();
    authFailure();
    await expect(pending).rejects.toMatchObject({ reason: "auth_failed" });
  });

  it("times out a bootstrap that never calls back, then allows a retry", async () => {
    vi.useFakeTimers();
    const loader = await freshLoader();
    const pending = loader.importMapsLibrary("maps");
    const assertion = expect(pending).rejects.toMatchObject({ reason: "load_failed" });
    await vi.advanceTimersByTimeAsync(loader.LOAD_TIMEOUT_MS + 1);
    await assertion;

    // Codex re-verification CX-11: the timed-out race must not leave its auth listener behind.
    expect(loader.authFailureListenerCount()).toBe(0);

    installGoogle(async (name) => ({ name }));
    const retry = loader.importMapsLibrary("maps");
    ready();
    await expect(retry).resolves.toEqual({ name: "maps" });
    expect(scripts).toHaveLength(2);
    expect(loader.authFailureListenerCount()).toBe(0);
  });

  it("rejects on a network error and allows a retry", async () => {
    const loader = await freshLoader();
    const pending = loader.importMapsLibrary("maps");
    scripts[0].onerror!();
    await expect(pending).rejects.toMatchObject({ reason: "load_failed" });
    loader.importMapsLibrary("maps").catch(() => {});
    expect(scripts).toHaveLength(2);
  });
});
