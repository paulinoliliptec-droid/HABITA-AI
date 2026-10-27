"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { config } from "@/lib/config";
import { importMapsLibrary } from "@/lib/google-maps/loader";

export interface PlaceSuggestion {
  placeId: string;
  primary: string;
  secondary: string | null;
  full: string;
}

export interface SuggestionResult {
  /** The trimmed query these suggestions were fetched for. */
  query: string;
  items: readonly PlaceSuggestion[];
}

const MIN_QUERY_LENGTH = 3;
const DEBOUNCE_MS = 180;
const NONE: readonly PlaceSuggestion[] = [];
const EMPTY: SuggestionResult = { query: "", items: NONE };

/** Suggestions are only ever shown for the exact query that produced them. */
export function suggestionsFor(result: SuggestionResult, query: string): readonly PlaceSuggestion[] {
  return result.query === query.trim() ? result.items : NONE;
}

/**
 * Address suggestions from Places API (New) via the Maps JavaScript API.
 * Degrades to `available: false` when the browser key is missing or rejected,
 * leaving free-text entry (resolved server-side) as the path.
 */
export function usePlaceSuggestions(query: string) {
  const [result, setResult] = useState<SuggestionResult>(EMPTY);
  const [available, setAvailable] = useState(Boolean(config.googleMapsApiKey));
  const sessionToken = useRef<google.maps.places.AutocompleteSessionToken | null>(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    const input = query.trim();
    const seq = ++requestSeq.current;
    if (!available || input.length < MIN_QUERY_LENGTH) return;

    const timer = setTimeout(async () => {
      try {
        const places = await importMapsLibrary("places");
        sessionToken.current ??= new places.AutocompleteSessionToken();
        const { suggestions } = await places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
          input,
          sessionToken: sessionToken.current,
        });
        if (seq !== requestSeq.current) return;
        setResult({
          query: input,
          items: suggestions.flatMap(({ placePrediction: p }) =>
            p
              ? [
                  {
                    placeId: p.placeId,
                    primary: p.mainText?.text ?? p.text.text,
                    secondary: p.secondaryText?.text ?? null,
                    full: p.text.text,
                  },
                ]
              : [],
          ),
        });
      } catch {
        if (seq !== requestSeq.current) return;
        setResult(EMPTY);
        setAvailable(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [query, available]);

  /** Close the autocomplete session after a choice so the next search starts a new one. */
  const endSession = useCallback(() => {
    sessionToken.current = null;
    requestSeq.current++;
    setResult(EMPTY);
  }, []);

  return { suggestions: suggestionsFor(result, query), available, endSession };
}
