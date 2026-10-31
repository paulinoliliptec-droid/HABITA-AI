import { ApiError } from "@/lib/api";
import type { SynthLike, UtteranceLike, VoiceLike } from "./voicePlayer";

// The server's voice behind the same interface as the browser's, so the player keeps one way of pausing, repeating and
// stopping. When the audio cannot be had, this sentence and the rest are read by the browser's voice: nothing is skipped.

export interface AudioLike {
  src: string;
  onended: ((this: never, event: never) => unknown) | null;
  onerror: ((this: never, event: never) => unknown) | string | null;
  play(): Promise<void>;
  pause(): void;
}

type Numbered<V> = UtteranceLike<V> & { index: number };
const call = (handler: unknown) => (handler as (() => void) | null)?.();

export class RemoteSynth<V extends VoiceLike, U extends Numbered<V>> implements SynthLike<V, U> {
  private urls = new Map<number, Promise<string>>();
  private session = 0;
  private usingBrowser = false;

  constructor(
    private readonly load: (index: number) => Promise<string>,
    private readonly lines: number,
    private readonly audio: AudioLike,
    private readonly browser: SynthLike<V, U> | null,
    private readonly onFallback: () => void,
    private readonly revoke: (url: string) => void = () => {},
  ) {}

  getVoices() {
    return this.browser?.getVoices() ?? [];
  }

  cancel() {
    this.session += 1;
    this.audio.pause();
    this.browser?.cancel();
  }

  speak(u: U) {
    if (this.usingBrowser) {
      this.browser?.speak(u);
      return;
    }
    const session = this.session;
    const failed = (err?: unknown) => {
      if (session !== this.session) return;
      // A changed report is not read on from the old script, by any voice.
      if ((err instanceof ApiError && err.status === 409) || !this.browser) {
        call(u.onerror);
        return;
      }
      this.usingBrowser = true;
      this.onFallback();
      this.browser.speak(u);
    };
    this.url(u.index)
      .then((url) => {
        if (session !== this.session) return;
        this.audio.onended = () => {
          if (session === this.session) call(u.onend);
        };
        this.audio.onerror = () => failed();
        this.audio.src = url;
        return this.audio.play();
      })
      .catch(failed);
    if (u.index + 1 < this.lines) this.url(u.index + 1).catch(() => {}); // the next sentence starts without a gap
  }

  dispose() {
    this.cancel();
    this.urls.forEach((url) => url.then(this.revoke, () => {}));
    this.urls.clear();
  }

  private url(index: number): Promise<string> {
    let url = this.urls.get(index);
    if (!url) {
      url = this.load(index);
      this.urls.set(index, url);
    }
    return url;
  }
}
