import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { pickVoice, VoicePlayer, voiceNotes, type UtteranceLike, type VoiceLike, type VoiceState } from "./voicePlayer";
import { RemoteSynth, type AudioLike } from "./voiceAudio";

type V = VoiceLike & { name: string };
class FakeSynth {
  spoken: FakeUtterance[] = [];
  cancels = 0;
  voices: V[] = [];
  speak(u: FakeUtterance) {
    this.spoken.push(u);
  }
  cancel() {
    this.cancels += 1;
  }
  getVoices() {
    return this.voices;
  }
}
class FakeUtterance implements UtteranceLike<V> {
  lang = "";
  voice: V | null = null;
  rate = 1;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly text: string) {}
}

function setup() {
  const synth = new FakeSynth();
  const states: [VoiceState, string | null][] = [];
  const player = new VoicePlayer<V, FakeUtterance>(synth, (t) => new FakeUtterance(t), (s, l) => states.push([s, l]));
  return { synth, player, states, last: () => states[states.length - 1] };
}

describe("voice player (HR-007)", () => {
  it("speaks each sentence in order and ends idle", () => {
    const { synth, player, last } = setup();
    player.play(["one", "two"], "en");
    expect(last()).toEqual(["playing", "one"]);
    synth.spoken[0].onend!();
    expect(last()).toEqual(["playing", "two"]);
    synth.spoken[1].onend!();
    expect(last()).toEqual(["idle", null]);
    expect(synth.spoken.map((u) => u.lang)).toEqual(["en-GB", "en-GB"]);
  });

  it("pauses and resumes at the same sentence", () => {
    const { synth, player, last } = setup();
    player.play(["one", "two"], "pt");
    synth.spoken[0].onend!();
    player.pause();
    expect(last()).toEqual(["paused", "two"]);
    player.resume();
    expect(last()).toEqual(["playing", "two"]);
    expect(synth.spoken.at(-1)!.lang).toBe("pt-PT");
  });

  it("ignores the end event of a cancelled sentence", () => {
    const { synth, player, last } = setup();
    player.play(["one", "two"], "en");
    const first = synth.spoken[0];
    player.pause();
    first.onend!();
    expect(last()).toEqual(["paused", "one"]);
  });

  it("repeats from the start and stops silently", () => {
    const { synth, player, last } = setup();
    player.play(["one", "two"], "en");
    synth.spoken[0].onend!();
    player.repeat();
    expect(last()).toEqual(["playing", "one"]);
    const current = synth.spoken.at(-1)!;
    player.stop();
    current.onend!();
    expect(last()).toEqual(["idle", null]);
  });

  it("stops when a sentence fails, so a warning is never skipped", () => {
    const { synth, player, last } = setup();
    player.play(["warning", "two"], "en");
    synth.spoken[0].onerror!();
    expect(last()).toEqual(["failed", null]);
    expect(synth.spoken).toHaveLength(1);
    synth.spoken[0].onend!(); // browsers may still fire it
    expect(synth.spoken).toHaveLength(1);
  });

  it("prefers the exact locale, then the language, and on-device voices", () => {
    const voice = (lang: string, localService: boolean, name = lang): V => ({ lang, localService, name });
    const remote = voice("pt-PT", false, "remote");
    const local = voice("pt-PT", true, "local");
    expect(pickVoice([remote, local], "pt")).toBe(local);
    expect(pickVoice([voice("pt-BR", true), remote], "pt")).toBe(remote);
    expect(pickVoice([voice("pt-BR", true, "br")], "pt")!.name).toBe("br");
    expect(pickVoice([voice("en-GB", true)], "pt")).toBeNull();
  });

  it("warns unless the voice is known to stay on the device", () => {
    const voice = (lang: string, localService: boolean): V => ({ lang, localService, name: lang });
    expect(voiceNotes([voice("pt-PT", true)], "pt")).toEqual({ noVoice: false, mayLeaveDevice: false });
    expect(voiceNotes([voice("pt-PT", false)], "pt")).toEqual({ noVoice: false, mayLeaveDevice: true });
    expect(voiceNotes([voice("en-GB", true)], "pt")).toEqual({ noVoice: true, mayLeaveDevice: true });
    expect(voiceNotes([], "pt")).toEqual({ noVoice: false, mayLeaveDevice: true }); // voices not loaded yet
  });
});

class FakeAudio implements AudioLike {
  src = "";
  onended: (() => unknown) | null = null;
  onerror: (() => unknown) | null = null;
  played: string[] = [];
  blocked = false;
  async play() {
    if (this.blocked) throw new Error("not allowed");
    this.played.push(this.src);
  }
  pause() {}
}

describe("server voice (HR-007)", () => {
  const settle = () => new Promise((resolve) => setTimeout(resolve));
  const numbered = (text: string, index: number) => Object.assign(new FakeUtterance(text), { index });
  type U = ReturnType<typeof numbered>;
  function setup(load: (index: number) => Promise<string>, lines = 3, withBrowser = true) {
    const browser = new FakeSynth();
    const audio = new FakeAudio();
    const onFallback = vi.fn();
    const synth = new RemoteSynth<V, U>(load, lines, audio, withBrowser ? (browser as never) : null, onFallback);
    const states: [VoiceState, string | null][] = [];
    const player = new VoicePlayer<V, U>(synth, numbered, (s, l) => states.push([s, l]));
    return { browser, audio, onFallback, synth, player, states };
  }

  it("plays each sentence in order and loads the next ahead", async () => {
    const load = vi.fn(async (i: number) => `blob:${i}`);
    const { audio, player, states } = setup(load);
    player.play(["a", "b", "c"], "pt");
    await settle();
    expect(audio.played).toEqual(["blob:0"]);
    expect(load.mock.calls.map((c) => c[0])).toEqual([0, 1]);
    audio.onended!();
    await settle();
    audio.onended!();
    await settle();
    expect(audio.played).toEqual(["blob:0", "blob:1", "blob:2"]);
    expect(load).toHaveBeenCalledTimes(3); // nothing past the end, nothing twice
    audio.onended!();
    expect(states.at(-1)).toEqual(["idle", null]);
  });

  it("pauses without playing what was still loading", async () => {
    let release: (url: string) => void = () => {};
    const { audio, player } = setup(() => new Promise((resolve) => (release = resolve)), 1);
    player.play(["a"], "pt");
    player.pause();
    release("blob:0");
    await settle();
    expect(audio.played).toEqual([]);
  });

  it.each([
    ["the server fails", (s: ReturnType<typeof setup>) => s],
    ["the browser blocks playing", (s: ReturnType<typeof setup>) => ((s.audio.blocked = true), s)],
  ])("keeps the same sentence in the browser's voice when %s", async (name, prepare) => {
    const load = name === "the server fails" ? () => Promise.reject(new Error("503")) : async () => "blob:0";
    const s = prepare(setup(load));
    s.player.play(["warning", "b", "c"], "pt");
    await settle();
    expect(s.onFallback).toHaveBeenCalledOnce();
    expect(s.browser.spoken.map((u) => u.text)).toEqual(["warning"]);
    s.browser.spoken[0].onend!();
    expect(s.browser.spoken.map((u) => u.text)).toEqual(["warning", "b"]);
  });

  it("stops on a changed report, and with no browser voice to fall back on", async () => {
    const changed = setup(() => Promise.reject(new ApiError("network_error", "changed", 409)));
    changed.player.play(["a", "b"], "pt");
    await settle();
    expect(changed.states.at(-1)).toEqual(["failed", null]);
    expect(changed.browser.spoken).toEqual([]);

    const alone = setup(() => Promise.reject(new Error("503")), 2, false);
    alone.player.play(["a", "b"], "pt");
    await settle();
    expect(alone.states.at(-1)).toEqual(["failed", null]);
  });
});

