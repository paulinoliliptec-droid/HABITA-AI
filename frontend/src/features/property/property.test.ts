import { describe, expect, it, vi } from "vitest";
import { getCachedProperty, rememberProperty, subscribeToProperties } from "./api";
import type { ResolvedProperty } from "./types";
import { suggestionsFor, type SuggestionResult } from "./usePlaceSuggestions";

function property(id: string, expiresAt = "2999-01-01T00:00:00Z"): ResolvedProperty {
  return { property_id: id, expires_at: expiresAt } as ResolvedProperty;
}

describe("property store", () => {
  it("notifies subscribers when a property is resolved again", () => {
    const listener = vi.fn();
    const off = subscribeToProperties(listener);
    rememberProperty(property("prp_a"));
    rememberProperty(property("prp_a"));
    off();
    rememberProperty(property("prp_a"));
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("drops entries after ten minutes or once the snapshot expires", () => {
    const now = Date.parse("2026-10-27T12:00:00Z");
    rememberProperty(property("prp_b"), now);
    expect(getCachedProperty("prp_b", now + 9 * 60_000)).toBeDefined();
    expect(getCachedProperty("prp_b", now + 11 * 60_000)).toBeUndefined();

    rememberProperty(property("prp_c", "2026-10-27T12:05:00Z"), now);
    expect(getCachedProperty("prp_c", now + 6 * 60_000)).toBeUndefined();
  });
});

describe("merged property IDs", () => {
  it("keeps a canonical property findable under the ID that was requested", () => {
    rememberProperty(property("prp_canonical"), Date.now(), "prp_merged");
    expect(getCachedProperty("prp_merged")?.property_id).toBe("prp_canonical");
  });
});

describe("suggestionsFor", () => {
  const porto: SuggestionResult = {
    query: "Porto",
    items: [{ placeId: "p1", primary: "Porto", secondary: "Portugal", full: "Porto, Portugal" }],
  };

  it("shows suggestions only for the query that produced them", () => {
    expect(suggestionsFor(porto, " Porto ")).toBe(porto.items);
    expect(suggestionsFor(porto, "Cascais")).toEqual([]);
    expect(suggestionsFor(porto, "Port")).toEqual([]);
  });
});
