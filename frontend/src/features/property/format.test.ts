import { describe, expect, it } from "vitest";
import { formatCoordinate, jurisdictionHierarchy, placeLine, splitAddress } from "./format";
import type { Jurisdiction } from "./types";

const cascais: Jurisdiction = {
  id: "pt/lisboa/cascais",
  country_code: "PT",
  levels: [
    { type: "country", id: "pt", name: "Portugal", label: "Country" },
    { type: "region", id: "pt/lisboa", name: "Lisboa", label: "District" },
    { type: "municipality", id: "pt/lisboa/cascais", name: "Cascais", label: "Municipality" },
    { type: "subdivision", id: "pt/lisboa/cascais/cascais-e-estoril", name: "Cascais e Estoril", label: "Parish" },
  ],
  local_authority: null,
  coverage: "modelled",
  source: "google_maps",
  country: "Portugal",
  region: "Lisboa",
  municipality: "Cascais",
  city: "Parede",
};

describe("splitAddress", () => {
  it("separates the street line from the rest", () => {
    expect(splitAddress("Praça 5 de Outubro, 2750-642 Cascais, Portugal")).toEqual({
      headline: "Praça 5 de Outubro",
      remainder: "2750-642 Cascais, Portugal",
    });
  });

  it("keeps single-part addresses whole", () => {
    expect(splitAddress("Portugal")).toEqual({ headline: "Portugal", remainder: null });
  });
});

describe("jurisdictionHierarchy", () => {
  it("renders the backend's levels with their local labels", () => {
    expect(jurisdictionHierarchy(cascais).map((l) => [l.label, l.value])).toEqual([
      ["Country", "Portugal"],
      ["District", "Lisboa"],
      ["Municipality", "Cascais"],
      ["Parish", "Cascais e Estoril"],
    ]);
    expect(jurisdictionHierarchy(cascais)[0].detail).toBe("PT");
  });

  it("does not list overlays in the administrative hierarchy", () => {
    const withOverlay = {
      ...cascais,
      levels: [...cascais.levels, { type: "overlay" as const, id: "pt/x/zone", name: "Zone", label: "Overlay" }],
    };
    expect(jurisdictionHierarchy(withOverlay)).toHaveLength(4);
  });
});

describe("placeLine", () => {
  it("prefers the municipality and falls back to the locality", () => {
    expect(placeLine(cascais)).toBe("Cascais, Portugal");
    expect(placeLine({ ...cascais, municipality: null, city: "Mountain View", country: "United States" })).toBe(
      "Mountain View, United States",
    );
  });
});

describe("formatCoordinate", () => {
  it("formats hemispheres", () => {
    expect(formatCoordinate(38.6969, "lat")).toBe("38.696900° N");
    expect(formatCoordinate(-9.4215, "lng")).toBe("9.421500° W");
  });
});
