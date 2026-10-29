// Warm, low-contrast cartography matching the HABITA neutrals. POI and transit
// noise is removed so the property and street fabric carry the composition.
export const HABITA_MAP_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#f2f0eb" }] },
  { elementType: "labels.icon", stylers: [{ visibility: "off" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#6b6f6b" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#f6f5f1" }, { weight: 3 }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#cdc8bd" }] },
  { featureType: "administrative.land_parcel", elementType: "labels.text.fill", stylers: [{ color: "#9a9d98" }] },
  { featureType: "landscape.man_made", elementType: "geometry.fill", stylers: [{ color: "#e9e6de" }] },
  { featureType: "landscape.man_made", elementType: "geometry.stroke", stylers: [{ color: "#d9d4c9" }] },
  { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "poi", elementType: "geometry", stylers: [{ color: "#ebe9e2" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#e1e6db" }] },
  { featureType: "road", elementType: "geometry.fill", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#e2ded5" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#7d817c" }] },
  { featureType: "road.highway", elementType: "geometry.fill", stylers: [{ color: "#fbfaf7" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#d6d1c6" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#d3dcdf" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#8a979c" }] },
];
