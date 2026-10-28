import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forgetMatter, recallMatter, rememberMatter } from "./capability";

describe("matter capability storage", () => {
  let store: Map<string, string>;

  beforeEach(() => {
    store = new Map();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps one capability per property, locally", () => {
    rememberMatter("prp_a", { matterId: "pm_1", token: "secret" });
    expect(recallMatter("prp_a")).toEqual({ matterId: "pm_1", token: "secret" });
    expect(recallMatter("prp_b")).toBeNull();
    forgetMatter("prp_a");
    expect(recallMatter("prp_a")).toBeNull();
  });

  it("ignores malformed entries and unavailable storage", () => {
    store.set("habita.permit.prp_a", "{not json");
    expect(recallMatter("prp_a")).toBeNull();
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    });
    expect(recallMatter("prp_a")).toBeNull();
    expect(() => rememberMatter("prp_a", { matterId: "pm_1", token: "t" })).not.toThrow();
  });
});
