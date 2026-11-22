import test from "node:test";
import assert from "node:assert/strict";
import {
  STEPS, HELPERS, DEFAULTS, PITCH_AMOUNTS, BEAT_STYLES, GUIDE_KEY, normalizeSettings, readSettings, writeSettings,
  afterTake, stepSummaries, isChords, speedText, pitchAmountName, nextStep, previousStep, planSentence, layerSentence, pastTense, takeReport,
  VIEWS, VIEW_GROUPS, viewById, nextView, previousView, playsText, beforeText, viewSummaries, suggestNext, MOVES, PLACES, CONTROL_PLACES,
  MORE_VIEWS, songLines, VIEW_PARTS, PART_VIEWS, studioPart, guidedPlace,
} from "../guide.js";
import { GENRES } from "../genre.js";

const memory = (init = {}) => {
  const data = { ...init };
  return { getItem: k => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, data };
};

test("the three steps are Sing, Your song and Share, each with a Next label except the last", () => {
  assert.deepEqual(STEPS.map(s => s.label), ["Sing", "Your song", "Share"]);
  assert.deepEqual(STEPS.map(s => s.id), ["sing", "song", "share"]);
  assert.deepEqual(STEPS.map(s => s.next), ["Next: your song", "Next: finish and share", null]);
  assert.equal(nextStep("sing"), "song");
  assert.equal(nextStep("share"), null);
  assert.equal(previousStep("song"), "sing");
  assert.equal(previousStep("sing"), null);
  assert.equal(nextStep("nope"), null);
});

test("UX.5: a step kept from before Your song (notes or song) opens Your song", () => {
  assert.equal(normalizeSettings({ step: "notes" }).step, "song");
  assert.equal(normalizeSettings({ step: "song" }).step, "song");
  assert.equal(normalizeSettings({ step: "share" }).step, "share");
  assert.equal(normalizeSettings({ step: "view" }).step, "sing");
});

test("UX.5, UX.7: the twelve change views, grouped, in the order Prev and Next walk them", () => {
  assert.deepEqual(VIEWS.map(v => v.id), ["voice", "notes", "timing", "words", "chords", "voice2", "beat", "sound", "sections", "takes",
    "practise", "ask"]);
  assert.deepEqual(VIEWS.map(v => v.name), ["Voice", "Notes", "Timing", "Words", "Chords", "Second voice", "Beat", "Sound", "Sections",
    "Takes", "Practise", "Ask Tandem"]);
  assert.deepEqual(VIEW_GROUPS.map(g => g.id), ["fix", "add", "more", "ask"]);
  const groups = VIEWS.map(v => v.group);
  assert.deepEqual(groups, ["fix", "fix", "fix", "fix", "add", "add", "add", "add", "more", "more", "more", "ask"]);
  assert.ok(VIEWS.every(v => ["voice", "both", "song"].includes(v.plays)));
  assert.deepEqual(VIEWS.filter(v => v.roll).map(v => v.id), ["notes", "timing", "words", "sections", "practise"]);
  assert.equal(VIEWS[0].plays, "voice");
  assert.ok(Object.isFrozen(VIEWS) && VIEWS.every(Object.isFrozen));
  assert.equal(viewById("chords").name, "Chords");
  assert.equal(viewById("nope"), null);
  assert.equal(previousView("voice"), null);
  assert.equal(nextView("voice"), "notes");
  assert.equal(nextView("sound"), "sections");
  assert.equal(nextView("practise"), "ask");
  assert.equal(nextView("ask"), null);
  assert.equal(previousView("chords"), "words");
  assert.equal(nextView("nope"), null);
  // Walking Next from the first view visits every view once, and Prev walks back.
  const walk = [VIEWS[0].id];
  while (nextView(walk.at(-1))) walk.push(nextView(walk.at(-1)));
  assert.deepEqual(walk, VIEWS.map(v => v.id));
  const back = [walk.at(-1)];
  while (previousView(back.at(-1))) back.push(previousView(back.at(-1)));
  assert.deepEqual(back, [...walk].reverse());
});

test("UX.5: what a view's Play plays, said plainly with and without a take", () => {
  assert.equal(playsText("voice", true), "Plays your voice");
  assert.equal(playsText("voice", false), "Record yourself first to hear your voice");
  assert.equal(playsText("both", true), "Plays your voice with the notes");
  assert.equal(playsText("both", false), "Plays the song");
  assert.equal(playsText("song", true), "Plays the song");
  assert.equal(playsText("song", false), "Plays the song");
});

test("UX.5: viewSummaries says each kind's state in plain words", () => {
  const empty = viewSummaries({ notes: [], drums: [], harmony: [], voice2: [], bpm: 100 });
  assert.deepEqual(empty, {
    voice: "Nothing recorded yet", notes: "No notes yet", timing: "100 beats a minute", words: "No words yet",
    chords: "Not added", voice2: "Not added", beat: "Not added", sound: "No genre", sections: "No sections yet",
    takes: "Nothing recorded yet", practise: "Needs a tune first", ask: "Your melody is protected",
  });
  assert.deepEqual(Object.keys(empty), VIEWS.map(v => v.id), "one line per view, in VIEWS order");
  const chords = [{ m: 48, t: 0, d: 1 }, { m: 52, t: 0, d: 1 }, { m: 55, t: 0, d: 1 }];
  const full = viewSummaries({
    notes: [{ m: 60, t: 0, d: 0.5 }], drums: [{ k: "kick", t: 0 }, { k: "hat", t: 0.5 }], harmony: chords,
    voice2: [{ m: 64, t: 0, d: 0.5 }, { m: 65, t: 0.5, d: 0.5 }], voice2_sung: { id: "a", seconds: 2, muted: false, line: "x" },
    bpm: 92.4, lyrics: "Twin-kle twin-kle _ lit-tle star", genre: "jazz", melody_locked: false,
    sections: [{ name: "Verse", from: 0, to: 2 }, { name: "Chorus", from: 2, to: 4 }],
    takes: { list: [{ id: "a", name: "Take 1", seconds: 2 }, { id: "b", name: "Take 2", seconds: 2 }], comp: [] },
    layers: [{ id: "l", name: "Layer 1", seconds: 2 }],
  }, { recorded: true, polished: true, tuned: true, sounds: { melody: "Flute" } });
  assert.equal(full.sections, "2 sections");
  assert.equal(full.takes, "2 takes, 1 layer");
  assert.equal(full.practise, "Sing along, note by note");
  assert.equal(full.voice, "Cleaned up, pitch fixed");
  assert.equal(full.notes, "1 note");
  assert.equal(full.timing, "92 beats a minute");
  assert.equal(full.words, "4 words", "the hold mark _ is not a word");
  assert.equal(full.chords, "Chords added");
  assert.equal(full.voice2, "2 notes, sung in your voice");
  assert.equal(full.beat, "2 hits");
  assert.equal(full.sound, GENRES.find(g => g.id === "jazz").name + ", melody on Flute");
  assert.equal(full.ask, "Tandem may change your melody");
  const some = viewSummaries({ notes: [], drums: [], harmony: [{ m: 40, t: 0, d: 1 }, { m: 43, t: 1, d: 1 }], voice2: [],
    voice2_sung: { muted: true }, bpm: 120 }, { recorded: true });
  assert.equal(some.voice, "Not cleaned up, pitch as sung");
  assert.equal(some.chords, "A line added");
  assert.equal(some.takes, "1 take", "one recording and no takes list is one take");
  assert.equal(viewSummaries(null).notes, "No notes yet");
});

test("UX.8: songLines lists only the parts the song has, each with its view and state", () => {
  assert.deepEqual(songLines({ notes: [], drums: [], harmony: [], voice2: [], bpm: 100 }), [], "an empty song has no lines");
  const chords = [{ m: 48, t: 0, d: 1 }, { m: 52, t: 0, d: 1 }];
  const full = songLines({
    notes: [{ m: 60, t: 0, d: 0.5 }, { m: 62, t: 0.5, d: 0.5 }], drums: [{ k: "kick", t: 0 }], harmony: chords,
    voice2: [{ m: 64, t: 0, d: 0.5 }], bpm: 100, lyrics: "la la", sections: [{ name: "Verse", from: 0, to: 1 }],
  }, { recorded: true, tuned: true });
  assert.deepEqual(full, [
    { view: "voice", name: "Voice", text: "Not cleaned up, pitch fixed" },
    { view: "notes", name: "Notes", text: "2 notes" },
    { view: "words", name: "Words", text: "2 words" },
    { view: "chords", name: "Chords", text: "Chords added" },
    { view: "voice2", name: "Second voice", text: "1 note" },
    { view: "beat", name: "Beat", text: "1 hit" },
  ]);
  const beatOnly = songLines({ notes: [], drums: [{ k: "hat", t: 0 }], harmony: [], voice2: [], lyrics: " _ - " });
  assert.deepEqual(beatOnly.map(l => l.view), ["beat"], "no take, no notes, and marks without letters are no words");
  assert.deepEqual(songLines(null), []);
});

test("UX.5: suggestNext offers chords for a tune without them, then a beat, then Share", () => {
  const n = [{ m: 60, t: 0, d: 0.5 }], h = [{ m: 48, t: 0, d: 1 }], d = [{ k: "kick", t: 0 }];
  assert.equal(suggestNext({ notes: n, harmony: [], drums: [] }), "chords");
  assert.equal(suggestNext({ notes: n, harmony: [], drums: d }), "chords");
  assert.equal(suggestNext({ notes: n, harmony: h, drums: [] }), "beat");
  assert.equal(suggestNext({ notes: [], harmony: [], drums: [] }), "beat", "no tune: chords cannot be made yet");
  assert.equal(suggestNext({ notes: n, harmony: h, drums: d }), "share");
  assert.equal(suggestNext({ notes: [], harmony: [], drums: d }), "share");
  assert.equal(suggestNext(null), "beat");
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
  assert.deepEqual(empty, { sing: "Nothing recorded yet", notes: "No notes yet", song: "Melody only", share: "No versions saved", yoursong: "Nothing yet" });
  const full = stepSummaries({ duration: 81.4, notes: 14, drums: 9, harmony: chords, versions: 2, tuned: true, polished: true });
  assert.deepEqual(full, {
    sing: "Recorded 1:21, cleaned up", notes: "14 notes, pitch fixed", song: "Chords and drums added", share: "2 versions saved",
    yoursong: "14 notes, chords and drums",
  });
  const one = stepSummaries({ duration: 7, notes: 1, drums: 0, harmony: bass, versions: 1 });
  assert.deepEqual(one, { sing: "Recorded 0:07", notes: "1 note", song: "A harmony line added", share: "1 version saved", yoursong: "1 note and a harmony line" });
  assert.equal(stepSummaries({ duration: 0, notes: 0, drums: 3, harmony: [], versions: 0 }).song, "Drums added");
  assert.equal(stepSummaries({ duration: 0, notes: 0, drums: 3, versions: null }).share, "Versions not available");
  assert.equal(stepSummaries({ duration: 0, notes: 4, drums: 0, harmony: [], voice2: 4, versions: 0 }).song, "A second voice added");
  assert.equal(stepSummaries({ duration: 0, notes: 4, drums: 2, harmony: chords, voice2: 4, versions: 0 }).song, "Chords, a second voice and drums added");
  // UX.5: the guided rail's Your song.
  assert.equal(stepSummaries({ notes: 0, drums: 3 }).yoursong, "Drums");
  assert.equal(stepSummaries({ notes: 4, voice2: 4 }).yoursong, "4 notes and a second voice");
});

test("planSentence: the Sing step says in one sentence what happens when the take stops", () => {
  assert.equal(planSentence(afterTake("melody", DEFAULTS)),
    "When you stop, Tandem will clean up the sound, turn your tune into notes and find the speed, then let you hear it.");
  assert.equal(planSentence([{ action: "polish", label: "Clean up the sound" }]), "When you stop, Tandem will clean up the sound, then let you hear it.");
  assert.match(planSentence([]), /^When you stop, Tandem lets you hear your take\. Every helper/);
});

test("pastTense: every helper the plan can hold has a past form", () => {
  const all = { ...DEFAULTS, helpers: Object.fromEntries(Object.keys(DEFAULTS.helpers).map(k => [k, true])) };
  const labels = new Set(["melody", "rhythm", "vocal"].flatMap(m => afterTake(m, all).map(a => a.label)));
  for (const label of labels) assert.notEqual(pastTense(label), label, label);
  assert.equal(pastTense("Write down the notes you sang"), "Wrote down the notes you sang");
});

test("takeReport: one plain line per helper, done, skipped, failed or not run", () => {
  const plan = afterTake("vocal", { ...DEFAULTS, helpers: { ...DEFAULTS.helpers, lineup: true } });
  const report = takeReport(plan, { polish: "done", fixpitch: "failed", transcribe: "done", tempo: "skipped" },
    { fixpitch: "The server is busy.", transcribe: "13 notes.", tempo: "Too short to find the speed: sing a little longer, or carry on." });
  assert.deepEqual(report.map(r => r.state), ["done", "failed", "done", "skipped", "notrun"]);
  assert.deepEqual(report.map(r => r.text), [
    "Cleaned up the sound",
    "Could not fix the pitch of your singing: The server is busy.",
    "Wrote down the notes you sang. 13 notes.",
    "Skipped: find the speed. Too short to find the speed: sing a little longer, or carry on.",
    "Not done: line the notes up with the beat",
  ]);
  assert.deepEqual(takeReport([]), []);
});

test("UX.6: Before names what it plays: the take as sung in Voice, the song as the view opened elsewhere", () => {
  assert.equal(beforeText("voice"), "Before: your take as you sang it. Choose After to hear it as it is now.");
  assert.equal(beforeText("timing"), "Before: the song as it was when you opened Timing. Choose After to change it.");
  assert.equal(beforeText("voice2"), "Before: the song as it was when you opened Second voice. Choose After to change it.");
  assert.equal(beforeText("nope"), "");
});

test("UX.7: every control of the studio page has a guided screen or fold, and every entry is a control", async () => {
  const { readFileSync } = await import("node:fs");
  const page = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const ids = [...page.matchAll(/<(button|input|select|textarea|details|form|a)\b[^>]*\bid="([^"]+)"/g)].map(m => m[2]).filter(id => !id.includes("'"));
  assert.ok(ids.length > 250 && new Set(ids).size === ids.length);
  const guided = ids.filter(id => page.indexOf('id="' + id + '"') < page.indexOf('<main id="allcontrols">'));
  const missing = ids.filter(id => !(id in CONTROL_PLACES));
  assert.deepEqual(missing, [], "a control with no place in the guided view");
  assert.deepEqual(Object.keys(CONTROL_PLACES).filter(id => !ids.includes(id)), [], "an entry for a control the page does not have");
  for (const [id, { place, via }] of Object.entries(CONTROL_PLACES)) {
    assert.ok(place in PLACES, id + ": " + place);
    if (via?.startsWith("#")) assert.ok(ids.includes(via.slice(1)), id + " is driven from " + via + ", which the page does not have");
    if (via) assert.ok(!guided.includes(id), id + ": a control of the guided view is shown there, not driven");
  }
  // Each place is an element of the page, and each slot a move fills is one.
  for (const sel of Object.values(PLACES)) {
    const id = sel.match(/^#([\w-]+)$/)?.[1];
    if (id) assert.ok(page.includes('id="' + id + '"'), sel);
  }
  for (const [sel, slot] of MOVES) {
    assert.ok(page.includes('id="' + slot + '"'), slot);
    const id = sel.match(/^#([\w-]+)$/)?.[1];
    if (id) assert.ok(page.includes('id="' + id + '"'), sel);
  }
  assert.equal(new Set(MOVES.map(m => m[0])).size, MOVES.length, "an element moves to one place");
  // Only the studio's own header, rail and side-panel link are left out of the guided view, and the file pickers.
  assert.deepEqual(Object.keys(CONTROL_PLACES).filter(id => CONTROL_PLACES[id].place === "studio").sort(), ["backtotracks", "shortcuts", "showguide"]);
  assert.deepEqual(MORE_VIEWS.map(id => PLACES["view:" + id + ":more"]), ["#gmore-voice", "#gmoretools", "#gmore-timing", "#gmore-chords",
    "#gmore-voice2", "#gmore-beat", "#gmore-sound"]);
});

test("UX.9: Show every control opens the part that holds the place, and Guided steps comes back to it or to the part's view", () => {
  // Every change view has a part, and every part the studio has comes back to a view that opens on that part.
  assert.deepEqual(Object.keys(VIEW_PARTS).sort(), VIEWS.map(v => v.id).sort());
  const parts = ["voice", "melody", "harmony", "voice2", "drums", "band", "timbre", "song"];
  assert.deepEqual(Object.keys(PART_VIEWS).sort(), [...parts].sort());
  for (const part of ["voice", "melody", "harmony", "voice2", "drums", "song"]) assert.equal(VIEW_PARTS[PART_VIEWS[part]], part, part);
  assert.equal(studioPart({ step: "sing" }), "voice");
  assert.equal(studioPart({ step: "sing", take: true }), "voice");
  assert.equal(studioPart({ step: "song" }), "melody");
  assert.equal(studioPart({ step: "share" }), "share");
  assert.equal(studioPart({ step: "song", view: "chords" }), "harmony");
  assert.equal(studioPart({ step: "song", view: "beat" }), "drums");
  assert.equal(studioPart({ step: "song", view: "takes" }), "voice");
  assert.equal(studioPart({ step: "song", view: "ask" }), "song");
  assert.equal(studioPart({ step: "song", view: "nope" }), "melody");
  assert.equal(studioPart(), "voice");
  // The part left as it was: back to the very place, Timing included (Notes shares its part).
  const timing = { step: "song", view: "timing" };
  assert.equal(guidedPlace("melody", timing), timing);
  assert.deepEqual(guidedPlace("voice", { step: "sing", take: true }), { step: "sing", take: true });
  assert.deepEqual(guidedPlace("melody", { step: "song" }), { step: "song" });
  // Another part chosen in the studio: its own view.
  assert.deepEqual(guidedPlace("drums", timing), { step: "song", view: "beat" });
  assert.deepEqual(guidedPlace("band", timing), { step: "song", view: "sound" });
  assert.deepEqual(guidedPlace("song", { step: "sing" }), { step: "song", view: "ask" });
  assert.deepEqual(guidedPlace("share", timing), { step: "share" });
  assert.deepEqual(guidedPlace("voice", { step: "share" }), { step: "song", view: "voice" });
});

test("FIX.11: the Sing step's line for a layer says what happens to it, and a beat is read into the drums", () => {
  assert.equal(layerSentence(true), "When you stop, Tandem keeps your beat as a layer over the song and reads it into the drums.");
  assert.equal(layerSentence(false), "When you stop, Tandem keeps the take as a layer over the song. The take the song uses stays as it is.");
  assert.doesNotMatch(layerSentence(false), /drums/);
});
