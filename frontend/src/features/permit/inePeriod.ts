import type { Lang } from "@/i18n/core";

const MONTHS: Record<string, string> = {
  janeiro: "January", fevereiro: "February", "março": "March", marco: "March", abril: "April", maio: "May",
  junho: "June", julho: "July", agosto: "August", setembro: "September", outubro: "October", novembro: "November",
  dezembro: "December",
};

/** An INE period in the reader's language ("2.º Trimestre de 2026" -> "Q2 2026"); unknown shapes stay as written. */
export function inePeriod(text: string, lang: Lang): string {
  if (lang !== "en") return text;
  const quarter = /^\s*(\d)\.?\s*[ºo]\s*trimestre\s+de\s+(\d{4})\s*$/i.exec(text);
  if (quarter) return `Q${quarter[1]} ${quarter[2]}`;
  const month = /^\s*(\S+)\s+de\s+(\d{4})\s*$/.exec(text);
  if (month && MONTHS[month[1].toLowerCase()]) return `${MONTHS[month[1].toLowerCase()]} ${month[2]}`;
  return text;
}
