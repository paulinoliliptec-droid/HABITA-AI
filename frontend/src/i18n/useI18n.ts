"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { dateLocale, translator, type Lang } from "./core";

// English by default (the server renders it, and the hackathon jury reads it); the choice is a per-browser convenience.
const STORAGE_KEY = "habita.lang";
const listeners = new Set<() => void>();
let chosen: Lang | null = null;

function currentLanguage(): Lang {
  if (chosen) return chosen;
  try {
    chosen = localStorage.getItem(STORAGE_KEY) === "pt" ? "pt" : "en";
  } catch {
    chosen = "en";
  }
  return chosen;
}

export function setLanguage(lang: Lang): void {
  chosen = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Blocked storage: the choice lasts until the page is reloaded.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useI18n() {
  const lang = useSyncExternalStore(subscribe, currentLanguage, () => "en" as const);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const t = useMemo(() => translator(lang), [lang]);
  return { lang, t, locale: dateLocale(lang) };
}
