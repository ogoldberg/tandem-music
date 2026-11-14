import test from "node:test";
import assert from "node:assert/strict";
import {
  STEPS, HELPERS, DEFAULTS, PITCH_AMOUNTS, BEAT_STYLES, GUIDE_KEY, normalizeSettings, readSettings, writeSettings,
  afterTake, stepSummaries, isChords, speedText, pitchAmountName, nextStep, previousStep,
} from "../guide.js";

const memory = (init = {}) => {
  const data = { ...init };
  return { getItem: k => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, data };
};

test("the four steps are Sing, Notes, Song and Share, each with a Next label except the last", () => {
  assert.deepEqual(STEPS.map(s => s.label), ["Sing", "Notes", "Song", "Share"]);
  assert.deepEqual(STEPS.map(s => s.id), ["sing", "notes", "song", "share"]);
  assert.ok(STEPS.slice(0, 3).every(s => s.next.startsWith("Next: ")));
  assert.equal(STEPS[3].next, null);
  assert.equal(nextStep("sing"), "notes");
  assert.equal(nextStep("share"), null);
  assert.equal(previousStep("notes"), "sing");
  assert.equal(previousStep("sing"), null);
  assert.equal(nextStep("nope"), null);
});

test("defaults: guided view, every helper on except lining up with the beat", () => {
  assert.equal(DEFAULTS.view, "guided");
  assert.equal(DEFAULTS.step, "sing");
  assert.deepEqual(DEFAULTS.helpers, { cleanup: true, notes: true, speed: true, fixpitch: true, lineup: false });
  assert.deepEqual(HELPERS.map(h => h.id), Object.keys(DEFAULTS.helpers));
  assert.equal(DEFAULTS.pitch, PITCH_AMOUNTS.natural);
  assert.equal(DEFAULTS.beat, "gently");
  assert.ok(Object.isFrozen(DEFAULTS) && Object.isFrozen(DEFAULTS.helpers));
});

test("normalizeSettings keeps valid values, replaces invalid ones with the defaults and never shares the defaults", () => {
  assert.deepEqual(normalizeSettings(null), structuredClone(DEFAULTS));
  assert.deepEqual(normalizeSettings("junk"), structuredClone(DEFAULTS));
  const s = normalizeSettings({
    view: "all", step: "song", helpers: { cleanup: false, lineup: true, extra: true, notes: "yes" },
    cleanup: "studio", pitch: 50, vibrato: false, beat: "swung", transcriber: "server", unknown: 1,
  });
  assert.deepEqual(s, {
    view: "all", step: "song", helpers: { cleanup: false, notes: true, speed: true, fixpitch: true, lineup: true },
    cleanup: "studio", pitch: 50, vibrato: false, beat: "swung", transcriber: "server",
  });
  const bad = normalizeSettings({ view: "x", step: "x", cleanup: "loud", pitch: 101, vibrato: 1, beat: "x", transcriber: "x" });
  assert.deepEqual(bad, structuredClone(DEFAULTS));
  assert.equal(normalizeSettings({ pitch: 42.6 }).pitch, 45, "rounded to the slider's 5% steps");
  assert.equal(normalizeSettings({ pitch: -5 }).pitch, DEFAULTS.pitch);
  const fresh = normalizeSettings({});
  fresh.helpers.cleanup = false;
  assert.equal(DEFAULTS.helpers.cleanup, true);
});

test("readSettings and writeSettings round trip through storage and survive unreadable or missing storage", () => {
  const store = memory();
  assert.deepEqual(readSettings(store), structuredClone(DEFAULTS));
  const s = normalizeSettings({ view: "all", helpers: { notes: false } });
  assert.equal(writeSettings(store, s), true);
  assert.deepEqual(readSettings(store), s);
  assert.deepEqual(JSON.parse(store.data[GUIDE_KEY]), s);
  assert.deepEqual(readSettings(memory({ [GUIDE_KEY]: "{not json" })), structuredClone(DEFAULTS));
  const throwing = { getItem() { throw Error("blocked"); }, setItem() { throw Error("blocked"); } };
  assert.deepEqual(readSettings(throwing), structuredClone(DEFAULTS));
  assert.equal(writeSettings(throwing, s), false);
  assert.deepEqual(readSettings(null), structuredClone(DEFAULTS));
  assert.equal(writeSettings(null, s), false);
});

test("afterTake: a hummed tune is cleaned up, turned into notes and its speed found", () => {
  const plan = afterTake("melody", DEFAULTS);
  assert.deepEqual(plan.map(a => a.action), ["polish", "transcribe", "tempo"]);
  assert.deepEqual(plan.map(a => a.label), ["Clean up the sound", "Turn your tune into notes", "Find the speed"]);
});

test("afterTake: a beat is not cleaned up (the vocal clean-up would gate drum hits) and becomes drum hits", () => {
  const plan = afterTake("rhythm", { ...DEFAULTS, helpers: { ...DEFAULTS.helpers, lineup: true } });
  assert.deepEqual(plan.map(a => a.action), ["transcribe", "tempo", "quantize"]);
  assert.equal(plan[0].label, "Turn your beat into drum hits");
  assert.equal(plan[2].label, "Line the notes up with the beat");
});

test("afterTake: singing with words is cleaned up, pitch fixed, then written down as notes", () => {
  const plan = afterTake("vocal", DEFAULTS);
  assert.deepEqual(plan.map(a => a.action), ["polish", "fixpitch", "transcribe", "tempo"]);
  assert.equal(plan[1].label, "Fix the pitch of your singing");
});

test("afterTake: finding the speed and lining up need the notes, and helpers turned off are left out", () => {
  const off = h => ({ ...DEFAULTS, helpers: { ...DEFAULTS.helpers, ...h } });
  assert.deepEqual(afterTake("melody", off({ notes: false, lineup: true })).map(a => a.action), ["polish"]);
  assert.deepEqual(afterTake("vocal", off({ cleanup: false, fixpitch: false })).map(a => a.action), ["transcribe", "tempo"]);
  assert.deepEqual(afterTake("melody", off({ speed: false, lineup: true })).map(a => a.action), ["polish", "transcribe", "quantize"]);
  assert.deepEqual(afterTake("melody", off({ cleanup: false, notes: false, speed: false, fixpitch: false })), []);
  assert.deepEqual(afterTake("nope", DEFAULTS), []);
});

test("the pitch and beat presets", () => {
  assert.deepEqual(PITCH_AMOUNTS, { light: 50, natural: 85, perfect: 100 });
  assert.equal(pitchAmountName(85), "Natural");
  assert.equal(pitchAmountName(100), "Perfect");
  assert.equal(pitchAmountName(70), "70%");
  assert.deepEqual(BEAT_STYLES.gently, { label: "Gently", division: 4, strength: 0.75, swing: 0 });
  assert.deepEqual(BEAT_STYLES.tightly, { label: "Tightly", division: 4, strength: 1, swing: 0 });
  assert.equal(BEAT_STYLES.swung.division, 2);
  assert.ok(BEAT_STYLES.swung.swing > 0);
});

test("speedText says the tempo in plain words", () => {
  assert.equal(speedText(96), "96 beats a minute");
  assert.equal(speedText(120.4), "120 beats a minute");
});

test("isChords: two notes starting together make chords", () => {
  assert.equal(isChords([{ m: 48, t: 0.5, d: 1 }, { m: 52, t: 0.5004, d: 1 }]), true);
  assert.equal(isChords([{ m: 48, t: 0, d: 1 }, { m: 52, t: 1, d: 1 }]), false);
  assert.equal(isChords([]), false);
});

test("stepSummaries describe what each step holds", () => {
  const chords = [{ m: 48, t: 0, d: 2 }, { m: 52, t: 0, d: 2 }, { m: 55, t: 0, d: 2 }], bass = [{ m: 36, t: 0, d: 1 }, { m: 43, t: 1, d: 1 }];
  const empty = stepSummaries({ duration: 0, notes: 0, drums: 0, harmony: [], versions: 0 });
  assert.deepEqual(empty, { sing: "Nothing recorded yet", notes: "No notes yet", song: "Melody only", share: "No versions saved" });
  const full = stepSummaries({ duration: 81.4, notes: 14, drums: 9, harmony: chords, versions: 2, tuned: true, polished: true });
  assert.deepEqual(full, {
    sing: "Recorded 1:21, cleaned up", notes: "14 notes, pitch fixed", song: "Chords and drums added", share: "2 versions saved",
  });
  const one = stepSummaries({ duration: 7, notes: 1, drums: 0, harmony: bass, versions: 1 });
  assert.deepEqual(one, { sing: "Recorded 0:07", notes: "1 note", song: "A harmony line added", share: "1 version saved" });
  assert.equal(stepSummaries({ duration: 0, notes: 0, drums: 3, harmony: [], versions: 0 }).song, "Drums added");
  assert.equal(stepSummaries({ duration: 0, notes: 0, drums: 3, versions: null }).share, "Versions not available");
  assert.equal(stepSummaries({ duration: 0, notes: 4, drums: 0, harmony: [], voice2: 4, versions: 0 }).song, "A second voice added");
  assert.equal(stepSummaries({ duration: 0, notes: 4, drums: 2, harmony: chords, voice2: 4, versions: 0 }).song, "Chords, a second voice and drums added");
});
