import { describe, expect, it } from "vitest";
import { bboxBounds, mercatorToLatLng } from "./mapLayers";

describe("map layers", () => {
  it("converts Web Mercator metres to degrees", () => {
    const origin = mercatorToLatLng(0, 0);
    expect(origin.lat).toBeCloseTo(0, 9);
    expect(origin.lng).toBeCloseTo(0, 9);
    // Cascais, Praça 5 de Outubro: about 38.6968 N, 9.4215 W.
    const p = mercatorToLatLng(-1048796.6, 4678333.4);
    expect(p.lng).toBeCloseTo(-9.4215, 3);
    expect(p.lat).toBeCloseTo(38.6968, 3);
  });

  it("gives the bounds of a bbox, south-west to north-east", () => {
    const b = bboxBounds([-1048900, 4677500, -1048700, 4677700]);
    expect(b.west).toBeLessThan(b.east);
    expect(b.south).toBeLessThan(b.north);
    expect(b.east - b.west).toBeCloseTo((200 / 6378137) * (180 / Math.PI), 9);
  });
});
