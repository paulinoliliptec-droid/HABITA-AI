"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { useI18n } from "@/i18n/useI18n";
import { ApiError, apiRequest } from "@/lib/api";
import styles from "@/features/permit/Permit.module.css";
import { claim, release as releaseLock } from "./lock";
import { MAX_SECONDS, SPEECH_RMS, concat, downsample, encodeWav, rms } from "./wav";

type State = "idle" | "recording" | "transcribing";

function transcribe(audio: Blob, signal: AbortSignal): Promise<{ text: string; model_id: string }> {
  return apiRequest("/api/voice/transcribe", { method: "POST", body: audio, signal, headers: { "Content-Type": "audio/wav" } });
}

/**
 * Dictation (owner, 2026-11-01): the user speaks and the text is added to the box they are typing in, to review before
 * sending. Muse Voice Transcribe writes it; the recording is not kept. Typing always stays possible.
 */
export function DictateButton({ onText, disabled, stopAfterSilence }: {
  onText: (text: string) => void;
  disabled?: boolean;
  /** Ends the recording by itself once the speaker has been silent this many seconds (the copilot's hands-free mode). */
  stopAfterSilence?: number;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  // stop(true) discards the recording; stop(false) sends it. Set while the microphone is open.
  const stopRef = useRef<((discard: boolean) => void) | null>(null);
  const mounted = useRef(true);
  const starting = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const owner = useRef({});

  useEffect(() => {
    mounted.current = true;
    const ownerAtMount = owner.current;
    return () => {
      // Leaving the page: the microphone is released and nothing is sent (Codex voice-r1).
      mounted.current = false;
      stopRef.current?.(true);
      pending.current?.abort();
      releaseLock(ownerAtMount);
    };
  }, []);

  async function start() {
    if (starting.current || stopRef.current) return; // one recording at a time, even with repeated clicks
    starting.current = true;
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch {
      starting.current = false;
      if (mounted.current) setError(t("HABITA can't use the microphone. Allow it in the browser, or type your text."));
      return;
    }
    starting.current = false;
    if (!mounted.current) {
      stream.getTracks().forEach((track) => track.stop()); // permission came after the user left
      return;
    }
    // The page lock is taken only once the microphone is open (Codex voice-r4): an unanswered permission prompt
    // never blocks the other boxes.
    if (!claim(owner.current)) {
      stream.getTracks().forEach((track) => track.stop());
      setError(t("Finish the other dictation first."));
      return;
    }
    let context: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode;
    let processor: ScriptProcessorNode;
    try {
      context = new AudioContext();
      source = context.createMediaStreamSource(stream);
      // ScriptProcessorNode is deprecated but works in every browser without a separate worklet file.
      processor = context.createScriptProcessor(4096, 1, 1);
      source.connect(processor);
      processor.connect(context.destination);
    } catch {
      // Codex voice-r2: if the audio can't be set up, the microphone is released at once.
      stream.getTracks().forEach((track) => track.stop());
      void context?.close();
      release();
      setError(t("HABITA can't use the microphone. Allow it in the browser, or type your text."));
      return;
    }
    const ctx = context;
    const chunks: Float32Array[] = [];
    let captured = 0;
    let heard = false; // silence counts only after the first words, so a slow start is not cut off
    let silent = 0;
    processor.onaudioprocess = (e) => {
      const chunk = new Float32Array(e.inputBuffer.getChannelData(0));
      chunks.push(chunk);
      captured += chunk.length;
      if (stopAfterSilence) {
        if (rms(chunk) >= SPEECH_RMS) {
          heard = true;
          silent = 0;
        } else if (heard) {
          silent += chunk.length;
          if (silent / ctx.sampleRate >= stopAfterSilence) {
            stopRef.current?.(false);
            return;
          }
        }
      }
      // The limit follows the audio captured, not timers a background tab may slow down.
      const s = captured / ctx.sampleRate;
      setSeconds(Math.floor(s));
      if (s >= MAX_SECONDS) stopRef.current?.(false);
    };
    // Codex voice-r4: a microphone unplugged or a permission revoked ends the recording like Stop.
    stream.getTracks().forEach((track) => track.addEventListener("ended", () => stopRef.current?.(false)));
    stopRef.current = (discard: boolean) => {
      stopRef.current = null;
      processor.onaudioprocess = null;
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      const rate = ctx.sampleRate;
      void ctx.close();
      if (discard) {
        release();
        return;
      }
      const all = concat(chunks);
      let samples: Float32Array;
      try {
        samples = downsample(all.subarray(0, Math.min(all.length, Math.floor(MAX_SECONDS * rate))), rate);
      } catch {
        // Codex voice-r3: a microphone below 16 kHz can't be used; the lock is released and the user told.
        release();
        if (mounted.current) {
          setState("idle");
          setError(t("This microphone's format isn't supported. Please type your text."));
        }
        return;
      }
      void finish(samples);
    };
    setSeconds(0);
    setState("recording");
  }

  async function finish(samples: Float32Array) {
    if (samples.length < 16000 * 0.5) {
      release();
      setState("idle");
      setError(t("The recording was too short. Hold on a little longer."));
      return;
    }
    setState("transcribing");
    const controller = new AbortController();
    pending.current = controller;
    try {
      const { text } = await transcribe(encodeWav(samples), controller.signal);
      if (!mounted.current) return;
      if (text.trim()) onText(text.trim());
      else setError(t("No words were heard. Please try again, or type your text."));
    } catch (err) {
      if (!mounted.current || controller.signal.aborted) return;
      setError(err instanceof ApiError ? t(err.message) : t("Something went wrong. Please try again."));
    } finally {
      pending.current = null;
      release();
      if (mounted.current) setState("idle");
    }
  }

  function release() {
    releaseLock(owner.current);
  }

  return (
    <div className={styles.dictate}>
      {state === "recording" ? (
        <Button type="button" variant="secondary" onClick={() => stopRef.current?.(false)} aria-live="polite">
          {t("Stop dictating")} · {seconds}s / {MAX_SECONDS}s
        </Button>
      ) : (
        <Button type="button" variant="ghost" onClick={() => void start()} disabled={disabled || state === "transcribing"}>
          {state === "transcribing" ? t("Writing what you said…") : `🎤 ${t("Dictate")}`}
        </Button>
      )}
      <span className={styles.fieldHint}>
        {t("Your voice is sent to Meta (Muse Voice Transcribe) to be written as text and is not kept. Check the text before sending.")}
      </span>
      {error && (
        <span className={styles.error} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
