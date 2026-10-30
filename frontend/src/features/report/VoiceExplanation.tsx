"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { useI18n } from "@/i18n/useI18n";
import type { PermitReport } from "./types";
import { buildVoiceScript } from "./voiceScript";
import { pickVoice, VoicePlayer, type VoiceState } from "./voicePlayer";
import styles from "./VoiceExplanation.module.css";

type BrowserPlayer = VoicePlayer<SpeechSynthesisVoice, SpeechSynthesisUtterance>;

/** HR-007: listen to the report, with the sentence being said on screen. */
export function VoiceExplanation({ report }: { report: PermitReport }) {
  const { lang, t } = useI18n();
  const player = useRef<BrowserPlayer | null>(null);
  const [state, setState] = useState<VoiceState>("idle");
  const [line, setLine] = useState<string | null>(null);
  const [noVoice, setNoVoice] = useState(false);

  // A report that changed is never read on from the old one.
  useEffect(() => () => player.current?.stop(), [report]);

  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return <p className={styles.note}>{t("This browser cannot read the report aloud.")}</p>;
  }

  function listen() {
    player.current ??= new VoicePlayer(
      window.speechSynthesis,
      (text) => new SpeechSynthesisUtterance(text),
      (next, sentence) => {
        setState(next);
        setLine(sentence);
      },
    );
    setNoVoice(!pickVoice(window.speechSynthesis.getVoices(), lang));
    player.current.play(buildVoiceScript(report, t), lang);
  }

  return (
    <div className={styles.voice}>
      <div className={styles.controls}>
        {(state === "idle" || state === "failed") && (
          <Button variant="secondary" onClick={listen}>
            {t("Listen")}
          </Button>
        )}
        {state === "playing" && (
          <Button variant="secondary" onClick={() => player.current?.pause()}>
            {t("Pause")}
          </Button>
        )}
        {state === "paused" && (
          <Button variant="secondary" onClick={() => player.current?.resume()}>
            {t("Resume")}
          </Button>
        )}
        {(state === "playing" || state === "paused") && (
          <>
            <Button variant="secondary" onClick={() => player.current?.repeat()}>
              {t("Repeat")}
            </Button>
            <Button variant="ghost" onClick={() => player.current?.stop()}>
              {t("Stop")}
            </Button>
          </>
        )}
      </div>
      {line && <p className={styles.line}>{line}</p>}
      {state === "failed" && <p className={styles.note}>{t("The audio stopped. The written report is unaffected.")}</p>}
      {noVoice && state !== "idle" && <p className={styles.note}>{t("This device has no voice for this language; the accent may be wrong.")}</p>}
    </div>
  );
}
