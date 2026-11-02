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
