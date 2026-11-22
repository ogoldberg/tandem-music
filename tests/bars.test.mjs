// GROW.1: bars.js owns the bar grid. A pinned grid wins over the guess and does not move when notes are added or moved;
// without one the guess is FIX.3's, unchanged (tests/groove.test.mjs and e2e/test_bar_grid.py); every module's bar
// length comes from bars.js; a project without the new fields saves byte for byte as before.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as bars from "../bars.js";
import { BEATS_PER_BAR, barSeconds, beatSeconds, barOrigin, barGrid, cleanGrid, snapToBar, barsBetween, pickup, songBars, pinnedSpeeds, pinnedSpeedText, speedChange } from "../bars.js";
import * as groove from "../groove.js";
import * as beats from "../beats.js";
import * as harmony from "../harmony.js";
import * as phrases from "../phrases.js";
import * as exercises from "../exercises.js";
import * as take from "../take.js";
import { snapToBeat } from "../sections.js";
import { applyActions } from "../actions.js";
import { projectFromState, checkUses, KNOWN_USES, NEWER_TANDEM, usesOf } from "../versions.js";

const read = f => readFileSync(new URL("../" + f, import.meta.url), "utf8");
const BPM = 100; // a 0.6 s beat, a 2.4 s bar
// FIX.3's free-time tune: the beat the notes agree on falls at 1.37 s, with a half-beat pickup at 1.07 s before it.
const FREE = [{ m: 67, t: 1.07, d: 0.25 }, ...[60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 72].map((m, i) => ({ m, t: Math.round((1.37 + i * 0.6) * 1000) / 1000, d: 0.5 }))];

test("4/4 and the bar and beat lengths", () => {
  assert.equal(BEATS_PER_BAR, 4);
  assert.equal(barSeconds(100), 2.4);
  assert.equal(beatSeconds(120), 0.5);
  assert.throws(() => barSeconds(0), /Set a tempo first/);
  assert.throws(() => barSeconds(undefined, "Set a tempo before X."), /Set a tempo before X/);
});

test("every module's bar length comes from bars.js", () => {
  // The one declaration of the beats in a bar is bars.js's; the modules that export it re-export bars.js's.
  for (const f of ["groove.js", "beats.js", "harmony.js", "phrases.js", "exercises.js", "take.js", "sections.js", "actions.js", "index.html"]) {
    const src = read(f);
    assert.doesNotMatch(src, /(const|let|var)\s+BEATS_PER_BAR\s*=/, `${f} declares its own bar`);
    assert.doesNotMatch(src, /\bfunction\s+(barOrigin|beatOrigin)\b/, `${f} works out the bar grid itself`);
  }
  assert.match(read("bars.js"), /export const BEATS_PER_BAR = 4;/);
  for (const m of [beats, harmony, phrases, exercises, take]) assert.equal(m.BEATS_PER_BAR, bars.BEATS_PER_BAR);
  assert.equal(groove.barOrigin, bars.barOrigin);
  assert.equal(groove.ZERO_GRID_SHARE, bars.ZERO_GRID_SHARE);
  for (const f of ["groove.js", "beats.js", "harmony.js", "phrases.js", "exercises.js", "take.js", "sections.js", "actions.js"]) {
    assert.match(read(f), /from "\.\/bars\.js"/, `${f} does not use bars.js`);
  }
  // The lengths they give are bars.js's.
  assert.equal(beats.barSeconds(96), barSeconds(96));
  assert.equal(exercises.exerciseStart(5, 100), 9.6); // the first whole bar at least a bar after 5 s
  assert.equal(snapToBeat(0.95, 100), 1.2);
  assert.throws(() => snapToBeat(1, 0), /Set a tempo before marking sections/);
  assert.throws(() => phrases.copyPhraseToEnd([{ m: 60, t: 0, d: 1 }], { start: 0, end: 1, indices: [0] }, { bpm: 0 }), /Set a tempo before editing phrases/);
  assert.throws(() => beats.grooveHits("straight", { bpm: 0, bars: 1 }), /Set a tempo before adding a beat/);
});

test("a free-time origin and its pickup", () => {
  const p = { bpm: BPM, notes: FREE, drums: [] };
  assert.equal(barOrigin(p), 1.37);
  assert.deepEqual(barGrid(p), { origin: 1.37, bar: 2.4, beat: 0.6, pinned: false });
  // The first note is half a beat before the first downbeat: a pickup, and the song's first bar starts after it.
  assert.equal(pickup(p), 0.3);
  assert.deepEqual(songBars(p, FREE.at(-1).t + 0.5), { start: 1.37, bars: 3 });
  // On the grid from zero, a song that starts on its first beat has no pickup.
  const zero = { bpm: BPM, notes: [0, 0.6, 1.2, 1.8, 2.4].map(t => ({ m: 60, t, d: 0.5 })), drums: [] };
  assert.equal(barOrigin(zero), 0);
  assert.equal(pickup(zero), 0);
  assert.deepEqual(songBars(zero, 2.9), { start: 0, bars: 2 });
  // A first note more than a beat before the bar line is not a pickup: the song starts on the bar line before it.
  const late = { bpm: BPM, notes: [{ m: 60, t: 1.2, d: 0.5 }, { m: 62, t: 2.4, d: 0.5 }], drums: [], grid: { origin: 0 } };
  assert.equal(pickup(late), 0);
  assert.deepEqual(songBars(late, 2.9), { start: 0, bars: 2 });
  assert.deepEqual(songBars({ bpm: BPM, notes: [], drums: [] }, 0), { start: 0, bars: 1 });
});

test("whole-bar snapping and counting", () => {
  const g = { origin: 1.37, bar: 2.4 };
  assert.equal(snapToBar(1.37, g), 1.37);
  assert.equal(snapToBar(2.5, g), 1.37);
  assert.equal(snapToBar(2.6, g), 3.77);
  assert.equal(snapToBar(9, g), 8.57);
  // Never before the first bar line: the time before it is a lead-in.
  assert.equal(snapToBar(0, g), 1.37);
  assert.equal(barsBetween(1.37, 8.57, g), 3);
  assert.equal(barsBetween(1.37, 2.5, g), 0);
  assert.equal(barsBetween(1.37, 2.6, g), 1);
  assert.equal(barsBetween(5, 1, g), 0);
});

test("a pinned grid wins over the guess, and an added or moved note does not move the bar lines", () => {
  const pinned = { bpm: BPM, notes: FREE, drums: [], grid: { origin: 1.37 } };
  assert.deepEqual(barGrid(pinned), { origin: 1.37, bar: 2.4, beat: 0.6, pinned: true });
  // Without the pin these edits move the guessed grid; with it they do not.
  const edits = [
    FREE.map(n => ({ ...n, t: Math.round((n.t + 0.27) * 1000) / 1000 })),
    // A note added a beat before the first downbeat: the guess moves the bar lines a beat earlier.
    [{ m: 60, t: 0.77, d: 0.3 }, ...FREE],
    FREE.map(n => ({ ...n, t: Math.round((n.t + 0.13) * 1000) / 1000 })),
  ];
  for (const notes of edits) {
    assert.notEqual(barOrigin({ bpm: BPM, notes, drums: [] }), 1.37, "the edit should move the guessed grid");
    assert.equal(barOrigin({ ...pinned, notes }), 1.37);
  }
  // Even an empty song keeps it.
  assert.equal(barOrigin({ bpm: BPM, notes: [], drums: [], grid: { origin: 0.4 } }), 0.4);
  // Quantize, chords and the chat's starter beat follow the pin.
  const shifted = edits[0];
  const q = groove.quantizeProject({ bpm: BPM, notes: shifted, drums: [], grid: { origin: 1.37 } }, { division: 1 });
  for (const n of q.notes) {
    const x = (n.t - 1.37) / 0.6;
    assert.ok(Math.abs(x - Math.round(x)) < 1e-6, `${n.t} is off the pinned beat`);
  }
  const h = harmony.generateHarmony({ bpm: BPM, notes: shifted, drums: [], grid: { origin: 1.37 } }, { style: "chords", key: { tonic: 0, mode: "major" } });
  const chordStarts = [...new Set(h.notes.map(n => n.t))];
  for (const t of chordStarts) {
    const x = (t - 1.37) / 2.4;
    assert.ok(Math.abs(x - Math.round(x)) < 1e-6, `a chord at ${t} is off the pinned bars`);
  }
  const unpinned = harmony.generateHarmony({ bpm: BPM, notes: shifted, drums: [] }, { style: "chords", key: { tonic: 0, mode: "major" } });
  assert.notDeepEqual([...new Set(unpinned.notes.map(n => n.t))], chordStarts);
  const song = { bpm: BPM, notes: shifted, drums: [], harmony: [], voice2: [], grid: { origin: 1.37 } };
  assert.equal(applyActions(song, [{ type: "add_beat", groove: "straight", bars: 2 }]), 1);
  assert.equal(song.drums.find(d => d.k === "kick").t, 1.37);
});

test("cleanGrid takes an origin inside the first bar only", () => {
  assert.equal(cleanGrid(null, BPM), null);
  assert.equal(cleanGrid(undefined, BPM), null);
  assert.deepEqual(cleanGrid({ origin: 0 }, BPM), { origin: 0 });
  assert.deepEqual(cleanGrid({ origin: 1.3700000004 }, BPM), { origin: 1.37 });
  for (const bad of [{}, { origin: -0.1 }, { origin: 2.4 }, { origin: 3 }, { origin: "1" }, { origin: NaN }, { origin: 1, extra: 1 }, [], 1, "x"]) {
    assert.throws(() => cleanGrid(bad, BPM), /bar grid/, JSON.stringify(bad));
  }
  assert.throws(() => barOrigin({ bpm: BPM, notes: [], drums: [], grid: { origin: 5 } }), /within the first bar/);
});

test("with the grid pinned the speed can only be doubled or halved", () => {
  const p = { bpm: 100, grid: { origin: 1.37 } };
  assert.equal(pinnedSpeeds({ bpm: 100 }), null);
  assert.equal(pinnedSpeedText({ bpm: 100 }), "");
  assert.deepEqual(pinnedSpeeds(p), [50, 200]);
  assert.equal(pinnedSpeedText(p), "The song's bars are pinned, so its speed can only be doubled or halved: 50 or 200 beats a minute.");
  assert.deepEqual(pinnedSpeeds({ bpm: 120, grid: { origin: 0 } }), [60]);
  assert.deepEqual(pinnedSpeeds({ bpm: 200, grid: { origin: 0 } }), [100]);
  // Not pinned: any speed, and no grid key is added.
  assert.deepEqual(speedChange({ bpm: 100 }, 93), { bpm: 93 });
  assert.throws(() => speedChange(p, 93), /only be doubled or halved: 50 or 200/);
  assert.deepEqual(speedChange(p, 50), { bpm: 50, grid: { origin: 1.37 } });
  // Doubled, a bar is 1.2 s long, so the origin comes inside it, on the same bar lines.
  assert.deepEqual(speedChange(p, 200), { bpm: 200, grid: { origin: 0.17 } });
  assert.deepEqual(speedChange(p, 100), { bpm: 100, grid: { origin: 1.37 } });
  // The chat's set_tempo is refused with the reason while pinned, and changes nothing.
  const song = { bpm: 100, notes: [], drums: [], grid: { origin: 1.37 } }, problems = [];
  assert.equal(applyActions(song, [{ type: "set_tempo", bpm: 120 }], { problems }), 0);
  assert.equal(song.bpm, 100);
  assert.match(problems[0].message, /only be doubled or halved/);
  assert.equal(applyActions(song, [{ type: "set_tempo", bpm: 200 }]), 1);
  assert.deepEqual([song.bpm, song.grid], [200, { origin: 0.17 }]);
  const free = { bpm: 100, notes: [], drums: [] };
  applyActions(free, [{ type: "set_tempo", bpm: 120 }]);
  assert.deepEqual(free, { bpm: 120, notes: [], drums: [] });
});

test("a project without the new fields saves byte for byte as before, and one with a grid says it uses it", () => {
  // The fixture was written by the versions.js of the commit before GROW.1.
  const fixture = readFileSync(new URL("./fixtures/grid-none.json", import.meta.url), "utf8");
  const base = { band: null, timbre: null, voice2_sung: null, takes: null, grid: null };
  const empty = projectFromState({ bpm: 100, instrument: "piano", melody_locked: true, notes: [], drums: [], harmony: [], harmony_instrument: "piano", voice2: [], voice2_instrument: "piano", mix: {}, layers: [], sections: [], lyrics: "", genre: null, ...base });
  const state = { bpm: 96, instrument: "flute", melody_locked: true,
    notes: [{ m: 67, t: 1.07, d: 0.25 }, { m: 60, t: 1.37, d: 0.5 }, { m: 64, t: 1.97, d: 0.5 }],
    drums: [{ k: "kick", t: 1.37 }, { k: "snare", t: 1.97 }],
    harmony: [{ m: 48, t: 1.37, d: 2.4 }], harmony_instrument: "piano",
    voice2: [{ m: 64, t: 1.37, d: 0.5 }], voice2_instrument: "strings",
    layers: [{ id: "l1", name: "Layer 1", seconds: 4, into: null }],
    sections: [{ name: "Verse", from: 1.37, to: 3.77 }],
    lyrics: "la la la", genre: "folk", mix: { drums: { level: -3 } }, ...base };
  assert.equal(JSON.stringify({ empty, song: projectFromState(state) }, null, 1) + "\n", fixture);
  const pinned = projectFromState({ ...state, grid: { origin: 1.37 } });
  assert.deepEqual(pinned.grid, { origin: 1.37 });
  assert.deepEqual(pinned.uses, ["grid"]);
  assert.deepEqual(usesOf(state), []);
});

test("a file whose uses names a feature this Tandem does not know is refused", () => {
  assert.deepEqual(KNOWN_USES, ["grid"]);
  assert.deepEqual(checkUses(undefined), []);
  assert.deepEqual(checkUses(["grid"]), ["grid"]);
  for (const newer of [["placed"], ["grid", "comp-src"]]) assert.throws(() => checkUses(newer), e => e.message === NEWER_TANDEM);
  assert.equal(NEWER_TANDEM, "This song was made with a newer Tandem. Update, then open it again.");
  for (const bad of ["grid", [1], {}]) assert.throws(() => checkUses(bad), /uses must be a list/);
  // The backend knows the same names.
  const backend = read("tandem_backend.py").match(/^KNOWN_USES=\(([^)]*)\)/m);
  assert.ok(backend, "tandem_backend.py has no KNOWN_USES");
  assert.deepEqual([...backend[1].matchAll(/"([^"]+)"/g)].map(m => m[1]), [...KNOWN_USES]);
});
