import test from "node:test";
import assert from "node:assert/strict";
import { EXERCISES, exerciseNotes, exerciseStart, BEATS_PER_BAR, MAX_SECONDS } from "../exercises.js";
import { SCALES } from "../contour.js";
import { practiceSpan, scorePass } from "../practice.js";

const KEYS = [{ tonic: 0, mode: "major" }, { tonic: 9, mode: "minor" }, { tonic: 6, mode: "major" }, { tonic: 3, mode: "minor" }];
// The wide ones fit an octave above any tonic; the narrow one only fits some exercises in some keys, so the start
// note is pushed against the top of the range (the others are refused, checked below).
const RANGES = [{ low: 48, high: 71 }, { low: 55, high: 79 }, { low: 41, high: 66 }, { low: 60, high: 72 }];
const pcs = key => SCALES[key.mode].steps.map(s => (key.tonic + s) % 12);

test("every exercise stays in the range, in the key and on the tempo's beats", () => {
  for (const ex of EXERCISES) for (const key of KEYS) for (const range of RANGES) for (const bpm of [60, 92, 140]) {
    let r;
    try { r = exerciseNotes(ex.id, { key, range, bpm }); } catch (e) {
      assert.ok(range.high - range.low < 23, `${ex.id} refused in a wide range: ${e.message}`);
      assert.match(e.message, /needs \d+ semitones/);
      continue;
    }
    const beat = 60 / bpm, half = beat / 2;
    assert.ok(r.notes.length >= 5, ex.id);
    for (const n of r.notes) {
      assert.ok(n.m >= range.low && n.m <= range.high, `${ex.id} ${n.m} outside ${range.low}-${range.high}`);
      assert.ok(pcs(key).includes(((n.m % 12) + 12) % 12), `${ex.id} ${n.m} not in ${key.tonic} ${key.mode}`);
      const grid = ex.id === "siren" ? half : beat;
      assert.ok(Math.abs(n.t - Math.round(n.t / grid) * grid) <= 1e-3, `${ex.id} onset ${n.t} off the grid at ${bpm}`);
      assert.ok(Math.abs(n.d - Math.round(n.d / grid) * grid) <= 1e-3 && n.d >= grid - 1e-3, `${ex.id} length ${n.d}`);
    }
    for (let i = 1; i < r.notes.length; i++) assert.ok(r.notes[i].t >= r.notes[i - 1].t + r.notes[i - 1].d - 1e-3, "notes do not overlap");
    assert.equal(r.low, Math.min(...r.notes.map(n => n.m)));
    assert.equal(r.high, Math.max(...r.notes.map(n => n.m)));
    assert.equal(r.from, 0);
    assert.ok(Math.abs(r.to - (r.notes.at(-1).t + r.notes.at(-1).d)) < 1e-3);
  }
});

test("the shapes: scale, arpeggio and five-note scale start and end on the tonic, siren covers the range", () => {
  const key = { tonic: 0, mode: "major" }, range = { low: 50, high: 74 };
  assert.deepEqual(exerciseNotes("scale", { key, range, bpm: 120 }).notes.map(n => n.m), [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60]);
  assert.deepEqual(exerciseNotes("arpeggio", { key, range, bpm: 120 }).notes.map(n => n.m), [60, 64, 67, 72, 67, 64, 60]);
  assert.deepEqual(exerciseNotes("five", { key, range, bpm: 120 }).notes.map(n => n.m), [60, 62, 64, 65, 67, 65, 64, 62, 60]);
  const minor = exerciseNotes("arpeggio", { key: { tonic: 9, mode: "minor" }, range, bpm: 120 }).notes.map(n => n.m);
  assert.deepEqual(minor, [57, 60, 64, 69, 64, 60, 57]);
  const iv = exerciseNotes("intervals", { key, range, bpm: 120 }).notes.map(n => n.m);
  assert.deepEqual(iv.slice(0, 6), [60, 62, 60, 60, 64, 60]);
  assert.equal(iv.length, 21);
  const siren = exerciseNotes("siren", { key, range: { low: 59, high: 65 }, bpm: 120 }).notes.map(n => n.m);
  assert.deepEqual(siren, [59, 60, 62, 64, 65, 64, 62, 60, 59]);
});

test("the tonic is placed in the middle of a wide range, and the last note is held two beats", () => {
  const r = exerciseNotes("arpeggio", { key: { tonic: 0, mode: "major" }, range: { low: 36, high: 84 }, bpm: 60 });
  assert.equal(r.low, 48); // C3-C4 and C4-C5 are as near the middle (C4); the lower wins
  assert.equal(r.notes.at(-1).d, 2);
  assert.equal(r.notes[0].d, 1);
});

test("an exercise that does not fit, or a missing key or range, is refused with a message", () => {
  const key = { tonic: 0, mode: "major" };
  assert.throws(() => exerciseNotes("scale", { key, range: { low: 60, high: 70 }, bpm: 100 }), /needs 12 semitones .*range is C4 to A♯4/);
  assert.doesNotThrow(() => exerciseNotes("five", { key, range: { low: 60, high: 70 }, bpm: 100 }));
  assert.throws(() => exerciseNotes("five", { key, range: { low: 61, high: 70 }, bpm: 100 }), /needs 7 semitones/);
  assert.throws(() => exerciseNotes("siren", { key, range: { low: 61, high: 61 }, bpm: 100 }), /at least two notes/);
  assert.throws(() => exerciseNotes("scale", { key, range: null, bpm: 100 }), /range is not known yet/);
  assert.throws(() => exerciseNotes("scale", { key: null, range: { low: 48, high: 72 }, bpm: 100 }), /Choose a key/);
  assert.throws(() => exerciseNotes("nope", { key, range: { low: 48, high: 72 }, bpm: 100 }), /Unknown exercise/);
});

test("an exercise starts a bar after the end of the song, on a bar line, and is a stretch Practise accepts", () => {
  const bar = BEATS_PER_BAR * 60 / 120;
  assert.equal(exerciseStart(0, 120), 0);
  assert.equal(exerciseStart(4, 120), 4 + bar);
  assert.equal(exerciseStart(4.1, 120), 6 + bar);
  const key = { tonic: 7, mode: "major" }, range = { low: 50, high: 74 };
  for (const ex of EXERCISES) for (const bpm of [45, 100, 220]) {
    const start = exerciseStart(9.3, bpm), r = exerciseNotes(ex.id, { key, range, bpm, start });
    assert.equal(r.from, start);
    assert.ok(r.notes[0].t === start);
    const span = practiceSpan(r.notes, { loop: { start: r.from, end: r.to } });
    assert.deepEqual([span.from, span.to], [r.from, r.to], ex.id + " at " + bpm);
  }
});

test("an exercise that would end after 600 s is refused, one that ends by then is not", () => {
  const key = { tonic: 0, mode: "major" }, range = { low: 50, high: 74 }, bpm = 120;
  assert.equal(MAX_SECONDS, 600);
  const len = exerciseNotes("scale", { key, range, bpm }).to; // 16 beats at 120: 8 s
  assert.doesNotThrow(() => exerciseNotes("scale", { key, range, bpm, start: MAX_SECONDS - len }));
  assert.throws(() => exerciseNotes("scale", { key, range, bpm, start: exerciseStart(595, bpm) }), /would end at 606\.0 s, after the 600 s/);
});

test("an exercise sung exactly scores every note in tune", () => {
  const r = exerciseNotes("arpeggio", { key: { tonic: 2, mode: "major" }, range: { low: 50, high: 70 }, bpm: 100, start: 4 });
  const readings = [];
  for (let t = r.from; t < r.to; t += 0.016) {
    const n = r.notes.find(x => t >= x.t && t < x.t + x.d);
    readings.push({ t, m: n ? n.m : null });
  }
  const scores = scorePass(readings, r.notes, { from: r.from, to: r.to });
  assert.equal(scores.length, r.notes.length);
  for (const s of scores) assert.ok(s.sung && Math.abs(s.cents) <= 1 && s.pitch === "in", JSON.stringify(s));
});
