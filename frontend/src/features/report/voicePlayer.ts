// Speaks a script one sentence at a time. Pausing cancels and restarts the sentence, because the browsers' own pause
// does nothing on several phones. A cancelled sentence still fires its end event, so each run carries a number and
// events from an older run are ignored.

export type VoiceState = "idle" | "playing" | "paused" | "failed";

export interface VoiceLike {
  lang: string;
  localService: boolean;
}

export interface UtteranceLike<V> {
  lang: string;
  voice: V | null;
  rate: number;
  onend: ((this: never, event: never) => unknown) | null;
  onerror: ((this: never, event: never) => unknown) | null;
}

export interface SynthLike<V, U> {
  speak(utterance: U): void;
  cancel(): void;
  getVoices(): V[];
}

const LOCALE = { pt: "pt-PT", en: "en-GB" } as const;
export const SPOKEN_RATE = 0.95;

/** The closest voice: the exact locale, then the language; on-device voices first, so the text stays on the device. */
export function pickVoice<V extends VoiceLike>(voices: V[], lang: "en" | "pt"): V | null {
  const local = (v: V[]) => v.find((x) => x.localService) ?? v[0] ?? null;
  const exact = voices.filter((v) => v.lang.replace("_", "-").toLowerCase() === LOCALE[lang].toLowerCase());
  return local(exact) ?? local(voices.filter((v) => v.lang.toLowerCase().startsWith(lang)));
}

export class VoicePlayer<V extends VoiceLike, U extends UtteranceLike<V>> {
  private script: string[] = [];
  private lang: "en" | "pt" = "en";
  private at = 0;
  private run = 0;

  constructor(
    private readonly synth: SynthLike<V, U>,
    private readonly utterance: (text: string) => U,
    private readonly onChange: (state: VoiceState, line: string | null) => void,
  ) {}

  play(script: string[], lang: "en" | "pt") {
    this.script = script;
    this.lang = lang;
    this.at = 0;
    this.speak();
  }

  pause() {
    this.run += 1;
    this.synth.cancel();
    this.onChange("paused", this.script[this.at] ?? null);
  }

  resume() {
    this.speak();
  }

  repeat() {
    this.at = 0;
    this.speak();
  }

  stop() {
    this.run += 1;
    this.synth.cancel();
    this.at = 0;
    this.onChange("idle", null);
  }

  private speak() {
    this.run += 1;
    const run = this.run;
    this.synth.cancel();
    const line = this.script[this.at];
    if (line === undefined) {
      this.at = 0;
      this.onChange("idle", null);
      return;
    }
    const u = this.utterance(line);
    u.lang = LOCALE[this.lang];
    u.voice = pickVoice(this.synth.getVoices(), this.lang);
    u.rate = SPOKEN_RATE;
    const next = () => {
      if (run !== this.run) return;
      this.at += 1;
      this.speak();
    };
    u.onend = next;
    // Audio that skips a sentence could skip a warning, so a failure stops it; the written report is unaffected.
    u.onerror = () => {
      if (run !== this.run) return;
      this.run += 1;
      this.at = 0;
      this.onChange("failed", null);
    };
    this.onChange("playing", line);
    this.synth.speak(u);
  }
}
