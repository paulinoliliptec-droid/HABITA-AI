"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { recallMatter } from "@/features/permit/capability";
import { askCopilot, type CopilotTurn } from "@/features/report/api";
import { DictateButton } from "@/features/voice/DictateButton";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import styles from "./ReportCopilot.module.css";

const SECTION_LABEL: Record<string, string> = {
  property: "Property",
  planning: "Planning",
  assessment: "Assessment",
  profile: "Property profile",
  pending: "Pending items",
  sources: "Sources",
  afford: "Costs",
  concepts: "Concepts",
};

/**
 * The report copilot (owner 2026-11-03: only to talk about the report and clear doubts about it). Questions by text or
 * dictation; answers come only from this property's report (the question's report when this browser holds it),
 * spoken with the browser's own voice on request. An explanation, never a verification or legal advice.
 */
export function ReportCopilot({ propertyId }: { propertyId: string }) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<(CopilotTurn & { inReport: boolean; sections: string[] })[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Live mode (owner 2026-11-03): each answer is spoken as it arrives, like a conversation; the reader can turn it off.
  const [live, setLive] = useState(true);

  async function ask() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      const out = await askCopilot(propertyId, recallMatter(propertyId), lang, q,
        turns.map(({ q: tq, a }) => ({ q: tq, a })));
      setTurns((prev) => [...prev, { q, a: out.answer, inReport: out.in_report, sections: out.sections }]);
      setQuestion("");
      if (live) speak(out.answer);
    } catch (err) {
      setError(err instanceof ApiError ? t(err.message) : t("Something went wrong. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  function speak(text: string) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang === "pt" ? "pt-PT" : "en-GB";
    window.speechSynthesis.speak(utterance);
  }

  if (!open) {
    return (
      <button type="button" className={styles.launcher} onClick={() => setOpen(true)}>
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.liveLabel}>{t("Live")}</span>
        {t("Ask about this report")}
      </button>
    );
  }

  return (
    <aside className={styles.panel} aria-label={t("Report copilot")}>
      <header className={styles.head}>
        <strong>
          <span className={styles.dot} aria-hidden="true" /> {t("Report copilot")} ·{" "}
          <span className={styles.liveLabel}>{t("Live")}</span>
        </strong>
        <button type="button" className={styles.close} onClick={() => setOpen(false)} aria-label={t("Close")}>
          ×
        </button>
      </header>
      <p className={styles.note}>
        {t("Talk to it by voice or text: it answers live, out loud, and only from this report. An explanation, not a verification or legal advice.")}
      </p>
      <label className={styles.toggle}>
        <input type="checkbox" checked={live} onChange={(e) => {
          setLive(e.target.checked);
          if (!e.target.checked && typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
        }} />{" "}
        {t("Speak the answers")}
      </label>
      <div className={styles.turns} aria-live="polite">
        {turns.length === 0 && (
          <p className={styles.hint}>{t("For example: why isn't the zoning verified? What is still pending?")}</p>
        )}
        {turns.map((turn, i) => (
          <div key={i} className={styles.turn}>
            <p className={styles.q}>{turn.q}</p>
            <p className={styles.a}>{turn.a}</p>
            <p className={styles.meta}>
              {turn.inReport
                ? turn.sections.length > 0 && `${t("From the report:")} ${turn.sections.map((s) => t(SECTION_LABEL[s] ?? s)).join(", ")}`
                : t("Not in the report")}
              {" · "}
              <button type="button" className={styles.link} onClick={() => speak(turn.a)}>
                {t("Listen")}
              </button>
            </p>
          </div>
        ))}
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
      >
        <textarea
          className={styles.input}
          value={question}
          maxLength={500}
          rows={2}
          placeholder={t("Ask about this report…")}
          aria-label={t("Your question about this report")}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask();
            }
          }}
        />
        <div className={styles.actions}>
          <DictateButton onText={(text) => setQuestion((q) => (q ? `${q} ${text}` : text))} disabled={busy} />
          <Button type="submit" variant="primary" disabled={busy || !question.trim()}>
            {busy ? t("Reading the report…") : t("Ask")}
          </Button>
        </div>
      </form>
    </aside>
  );
}
