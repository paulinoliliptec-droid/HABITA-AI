// NEXT_PUBLIC_* values are inlined at build time. Only public configuration belongs here:
// the browser Maps key is public by design and must be restricted by HTTP referrer.
export const config = {
  apiBaseUrl: (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, ""),
  googleMapsApiKey: process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || null,
} as const;
