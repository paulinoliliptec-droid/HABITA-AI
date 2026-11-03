"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { recallMatter } from "@/features/permit/capability";
import { askCopilot, getCopilotSpeech, onReportChanged, type CopilotEngine, type CopilotTurn } from "@/features/report/api";
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
 * spoken in the ElevenLabs voice of the reader's language (the browser's own voice only when that audio can't be had).
 * Dictation sends the question by itself after a pause (owner 2026-11-03); typing stays. An explanation, never a
 * verification or legal advice.
 */
export const SEND_AFTER_SILENCE_SECONDS = 10;

/** A readable name for the model id the server reports. */
export function modelName(id: string): string {
  if (id.includes("muse-spark-open")) return "Muse Spark Open";
  if (id.startsWith("muse-spark")) return "Muse Spark";
  return id;
}

export function ReportCopilot({ propertyId }: { propertyId: string }) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false); // read by the dictation callback, which may run after a render
  // The latest typed text and the "speak / open" choices, read when an answer or a transcription arrives later
  // (Codex copilot-voice r2): a panel closed or speech turned off meanwhile stays silent, and newer typing is kept.
  const questionRef = useRef("");
  const speakRef = useRef(true);
  const [turns, setTurns] = useState<
    (CopilotTurn & {
      inReport: boolean; sections: string[]; status: string | null; speechId: string | null; modelId: string | null;
    })[]
  >([]);
  // One answer is heard at a time; a newer one, a report change or "off" silences it, whichever voice is speaking.
  const audio = useRef<HTMLAudioElement | null>(null);
  const speaking = useRef(0);

  // Declared before the effects that call it.
  function hush() {
    speaking.current += 1;
    audio.current?.pause();
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  // The conversation belongs to one report: a new or changed report (or question) starts it again (Codex copilot r1).
  const [context, setContext] = useState<string | null>(null);
  // Bumped on every report change: an answer still in flight from the earlier report is dropped (Codex copilot r2).
  const generation = useRef(0);
  useEffect(
    () =>
      onReportChanged(() => {
        generation.current += 1;
        setTurns([]);
        busyRef.current = false;
        setBusy(false); // a question about the old report no longer blocks one about the new (Codex copilot r5)
        // Nothing about the old report keeps being read aloud (Codex copilot r3).
        hush();
      }),
    [],
  );
  const [error, setError] = useState<string | null>(null);
  // Live mode (owner 2026-11-03): each answer is spoken as it arrives, like a conversation; the reader can turn it off.
  const [live, setLive] = useState(true);
  // Which Meta model answers (owner 2026-11-03): Muse Spark, or Muse Spark Open on Meta's open weights.
  const [engine, setEngine] = useState<CopilotEngine>("muse");

  useEffect(
    () => () => {
      speakRef.current = false; // an answer arriving after leaving the page stays silent (Codex copilot-voice r3)
      hush();
    },
    [],
  );

  async function ask(text?: string) {
    const q = (text ?? question).trim();
    if (!q || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    const asked = generation.current;
    try {
      const own = recallMatter(propertyId);
      const now = own?.matterId ?? "property";
      const history = now === context ? turns.map(({ q: tq, a }) => ({ q: tq, a })) : [];
      const out = await askCopilot(propertyId, own, lang, q, history, engine);
      if (asked !== generation.current) return; // the report changed meanwhile: this answer is about the old one
      const turn = {
        q, a: out.answer, inReport: out.in_report, sections: out.sections, status: out.report_status,
        speechId: out.speech_id ?? null, modelId: out.model_id ?? null,
      };
      setTurns((prev) => (now === context ? [...prev, turn] : [turn]));
      setContext(now);
      if (questionRef.current.trim() === q) {
        questionRef.current = ""; // a dictation or typing that arrived meanwhile stays in the box
        setQuestion("");
      }
      if (speakRef.current) void speak(out.answer, turn.speechId);
    } catch (err) {
      setError(err instanceof ApiError ? t(err.message) : t("Something went wrong. Please try again."));
    } finally {
      // An answer about an older report doesn't free the box for a question already asked about the new one (r3).
      if (asked === generation.current) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  function browserVoice(text: string) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang === "pt" ? "pt-PT" : "en-GB";
    window.speechSynthesis.speak(utterance);
  }

  async function speak(text: string, speechId: string | null) {
    hush();
    const mine = speaking.current;
    if (speechId) {
      try {
        const blob = await getCopilotSpeech(speechId);
        if (mine !== speaking.current) return; // silenced or replaced while the audio was on its way
        const url = URL.createObjectURL(blob);
        const player = new Audio(url);
        player.addEventListener("ended", () => URL.revokeObjectURL(url));
        audio.current = player;
        await player.play();
        return;
      } catch {
        if (mine !== speaking.current) return;
      }
    }
    browserVoice(text); // the server's voice is unavailable (or the answer expired): the browser reads it instead
  }

  if (!open) {
    return (
      <button type="button" className={styles.launcher} onClick={() => {
          speakRef.current = live;
          setOpen(true);
        }}>
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
        <button type="button" className={styles.close} onClick={() => {
            setOpen(false);
            speakRef.current = false;
            hush(); // closing the copilot silences it (Codex copilot-voice r1)
          }} aria-label={t("Close")}>
          ×
        </button>
      </header>
      <p className={styles.note}>
        {t("Talk to it by voice or text: it answers live, out loud, and only from this report. An explanation, not a verification or legal advice.")}
      </p>
      <div className={styles.engines} role="radiogroup" aria-label={t("Model that answers")}>
        {(["muse", "open"] as const).map((e) => (
          <label key={e} className={engine === e ? styles.engineOn : styles.engine}>
            <input type="radio" name="copilot-engine" value={e} checked={engine === e} disabled={busy}
              onChange={() => setEngine(e)} />
            {e === "muse" ? t("Muse Spark (Meta API)") : t("Muse Spark Open (open weights · Baseten)")}
          </label>
        ))}
      </div>
      <label className={styles.toggle}>
        <input type="checkbox" checked={live} onChange={(e) => {
          setLive(e.target.checked);
          speakRef.current = e.target.checked;
          if (!e.target.checked) hush();
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
              {turn.modelId && <>{t("Answered by {model}", { model: modelName(turn.modelId) })}{" · "}</>}
              {t("Report status: {status}", { status: turn.status ? t(turn.status) : t("no question asked yet") })}
              {" · "}
              {turn.inReport
                ? turn.sections.length > 0 && `${t("From the report:")} ${turn.sections.map((s) => t(SECTION_LABEL[s] ?? s)).join(", ")}`
                : t("Not in the report")}
              {" · "}
              <button type="button" className={styles.link} onClick={() => void speak(turn.a, turn.speechId)}>
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
          onChange={(e) => {
            questionRef.current = e.target.value;
            setQuestion(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask();
            }
          }}
        />
        <div className={styles.actions}>
          <DictateButton
            stopAfterSilence={SEND_AFTER_SILENCE_SECONDS}
            disabled={busy}
            onText={(text) => {
              // Hands-free: what was said (after anything already typed) is sent at once. While another question is
              // being answered it waits in the box instead of being dropped (Codex copilot-voice r1).
              const typed = questionRef.current.trim();
              const q = typed ? `${typed} ${text}` : text;
              questionRef.current = q;
              setQuestion(q);
              if (!busyRef.current) void ask(q);
            }}
          />
          <Button type="submit" variant="primary" disabled={busy || !question.trim()}>
            {busy ? t("Reading the report…") : t("Ask")}
          </Button>
        </div>
      </form>
    </aside>
  );
}
