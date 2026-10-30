import pt from "./pt.json";

// Fixed texts are written in English in the code; pt.json is generated from them with Google Translate and pinned
// reviewed wording for statuses and warnings (backend/app/services/i18n/generate.py). A text without an entry stays
// English, so nothing is ever blank.

export type Lang = "en" | "pt";
export type Translate = (text: string, values?: Record<string, string | number>) => string;

const PT: Record<string, string> = pt;

/** Marks a fixed text where it is defined; `t` translates it where it is shown. */
export const msg = <S extends string>(text: S): S => text;

export function translator(lang: Lang): Translate {
  return (text, values) => {
    const shown = (lang === "pt" ? PT[text] : undefined) ?? text;
    return Object.entries(values ?? {}).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), shown);
  };
}

export const english = translator("en");

export const dateLocale = (lang: Lang) => (lang === "pt" ? "pt-PT" : "en-GB");
