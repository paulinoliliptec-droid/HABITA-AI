import { describe, expect, it } from "vitest";
import { translator } from "@/i18n/core";
import verified from "./fixtures/verified-report.json";
import type { PermitReport } from "./types";
import { pickVoice, VoicePlayer, type UtteranceLike, type VoiceLike, type VoiceState } from "./voicePlayer";
import { buildVoiceScript, speakable } from "./voiceScript";

const report = verified as unknown as PermitReport;
const a = report.assessment!;
const withAssessment = (over: Partial<NonNullable<PermitReport["assessment"]>>) =>
  ({ ...report, assessment: { ...a, ...over } }) as PermitReport;
const said = (r: PermitReport) => buildVoiceScript(r).join(" ");

describe("voice script (HR-007)", () => {
  it("opens by saying audio is not proof and closes with the disclaimer", () => {
    const script = buildVoiceScript(report);
    expect(script.slice(0, 2).join(" ")).toContain("not legal proof");
    expect(script.join(" ")).toContain(speakable(report.disclaimer).at(-1));
    expect(script.at(-1)).toBe(speakable(report.disclaimer).at(-1));
  });

  it("says the report's status, and that verified is HABITA's own check", () => {
    expect(said(report)).toContain("Status: Verified.");
    expect(said(report)).toContain("not a municipal approval");
    expect(said(withAssessment({ status: "REJECTED", content_verified: false }))).toContain("Status: Rejected.");
  });

  it.each([
    ["content not verified", { content_verified: false }],
    ["superseded record", { verification: { current: false, outcome: "VERIFIED" } }],
    ["no record", { verification: null }],
  ])("never says verified with %s", (_, over) => {
    const text = said(withAssessment(over));
    expect(text).toContain("Status: Pending confirmation.");
    expect(text).not.toContain("Status: Verified");
    expect(text).toContain("must not be relied on");
  });

  it("never keeps the reason of a status it corrected", () => {
    const text = said(withAssessment({ verification: { current: false, outcome: "VERIFIED" } }));
    expect(text).not.toContain(a.status_reason);
    expect(text).toContain("does not support a verified result");
  });

  it("says every open item, not a count", () => {
    const text = said({ ...report, pending: ["Confirm the land-use category."] });
    expect(text).toContain("Pending confirmation");
    expect(text).toContain("Confirm the land-use category.");
  });

  it("says every section of statements: nothing is left out of the summary", () => {
    const text = said(report);
    for (const s of a.statements) expect(text).toContain(speakable(s.text)[0]);
  });

  it("keeps a request for an answer that repeats a condition's words", () => {
    const r = { ...withAssessment({ conditions: ["Confirm the exits."] }), pending: ["Your answer is needed: Confirm the exits."] };
    expect(said(r)).toContain("Your answer is needed");
  });

  it("says why zoning is not verified", () => {
    const r = { ...report, planning: { ...report.planning, reasons: ["The property lies near a boundary between zoning classes."] } };
    expect(said(r)).toContain("near a boundary");
  });

  it("says what each official map covers", () => {
    const text = said(report);
    for (const d of report.planning.documents_to_consult) expect(text).toContain(speakable(d.reason)[0]);
  });

  it("says conditions once", () => {
    const script = buildVoiceScript(withAssessment({ conditions: ["Confirm the exits."] }));
    const pending = { ...withAssessment({ conditions: ["Confirm the exits."] }), pending: ["Condition: Confirm the exits."] };
    expect(script.filter((l) => l === "Confirm the exits.")).toHaveLength(1);
    expect(buildVoiceScript(pending).filter((l) => l.includes("Confirm the exits."))).toHaveLength(1);
  });

  it("states unverified zoning and names a class only from a verified layer", () => {
    expect(said(report)).toContain("Zoning not verified");
    const claimed = { ...report, planning: { ...report.planning, verified_zoning: false, classification: "Espaço Central" } };
    expect(said(claimed)).not.toContain("Espaço Central");
    const zoned = { ...report, planning: { ...report.planning, verified_zoning: true, classification: "Espaço Central" } };
    expect(said(zoned)).toContain("Espaço Central");
  });

  it("says the translation label and the demo label", () => {
    const translation = { available: true, kept_original: 0, note: "Tradução automática." };
    expect(said({ ...report, translation })).toContain("Tradução automática.");
    expect(said({ ...report, demo: true })).toContain("Demonstration data");
  });

  it("works with no assessment", () => {
    expect(said({ ...report, assessment: null })).toContain("No permit assessment yet");
  });

  it("speaks in the reader's language", () => {
    expect(buildVoiceScript(report, translator("pt"))[1]).toContain("Não é prova legal");
  });

  it("drops evidence references and splits long sentences", () => {
    expect(speakable("Confirm this [E1, E2]. Then that [K3].")).toEqual(["Confirm this.", "Then that."]);
    expect(speakable("word ".repeat(100)).every((s) => s.length <= 180)).toBe(true);
    expect(speakable("   ")).toEqual([]);
  });
});

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
});
