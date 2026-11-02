/** Map layers (HR-004): pure helpers, tested without Google Maps. */

const R = 6378137; // Web Mercator sphere radius, metres

/** EPSG:3857 metres to WGS84 degrees. */
export function mercatorToLatLng(x: number, y: number): { lat: number; lng: number } {
  const lng = (x / R) * (180 / Math.PI);
  const lat = (2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * (180 / Math.PI);
  return { lat, lng };
}

/** The bounds of an EPSG:3857 bbox (minx, miny, maxx, maxy) as Google Maps LatLngBounds literal. */
export function bboxBounds(bbox: readonly [number, number, number, number]): {
  north: number;
  south: number;
  east: number;
  west: number;
} {
  const sw = mercatorToLatLng(bbox[0], bbox[1]);
  const ne = mercatorToLatLng(bbox[2], bbox[3]);
  return { north: ne.lat, south: sw.lat, east: ne.lng, west: sw.lng };
}

/**
 * The bounds for an image whose top `photoHeight` pixel rows are the orthophoto of `bbox` and whose remaining rows
 * (an attribution band) hang below it: the bbox is stretched down by the band's share, so the photo's pixels sit
 * exactly on their own extent (Codex HR-004 r1, P1).
 */
export function imageBounds(
  bbox: readonly [number, number, number, number],
  photoHeight: number,
  imageHeight: number,
): { north: number; south: number; east: number; west: number } {
  const metresPerRow = (bbox[3] - bbox[1]) / photoHeight;
  const below = Math.max(0, imageHeight - photoHeight) * metresPerRow;
  return bboxBounds([bbox[0], bbox[1] - below, bbox[2], bbox[3]]);
}
