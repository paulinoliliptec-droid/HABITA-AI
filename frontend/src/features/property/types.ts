// Mirrors backend/app/schemas/property.py.

export type LocationPrecision = "rooftop" | "interpolated" | "area_center" | "approximate";

export interface Coordinates {
  lat: number;
  lng: number;
}

export type JurisdictionLevelType = "country" | "region" | "subregion" | "municipality" | "subdivision" | "overlay";

export interface JurisdictionLevel {
  type: JurisdictionLevelType;
  /** Stable, language-independent ID, e.g. "pt/lisboa/cascais". */
  id: string;
  name: string;
  /** Local term for display, e.g. "District". */
  label: string;
}

export interface SourceRef {
  title: string;
  reference: string | null;
  url: string | null;
}

export interface Authority {
  id: string;
  name: string;
  kind: string;
  jurisdiction_id: string;
  competence: string;
  sources: SourceRef[];
}

export interface Jurisdiction {
  id: string;
  country_code: string;
  levels: JurisdictionLevel[];
  local_authority: Authority | null;
  /** "unmodelled": HABITA has no adapter for this country yet. */
  coverage: "modelled" | "unmodelled";
  source: "google_maps";
  country: string;
  region: string | null;
  municipality: string | null;
  city: string | null;
}

export interface ResolvedProperty {
  property_id: string;
  formatted_address: string;
  coordinates: Coordinates;
  precision: LocationPrecision;
  place_id: string;
  jurisdiction: Jurisdiction;
  resolved_at: string;
  expires_at: string;
  /** Only on a resolve response: match quality of that request. Never stored. */
  partial_match?: boolean;
}

export type ResolveLocationInput = { address: string } | { place_id: string };
