import test from "node:test";
import assert from "node:assert/strict";
import { detectPhrases, movePhrase, transposePhrase, copyPhraseToEnd, phraseOf, MAX_MELODY_NOTES, PHRASE_GAP_BEATS, BEATS_PER_BAR } from "../phrases.js";

// 120 bpm: one beat is 0.5 s, one bar 2 s.
const BPM = 120;
const n = (m, t, d = 0.4) => ({ m, t, d });
// Two phrases: three notes, then a one-beat rest, then two notes; listed out of time order.
const TWO = [n(67, 2.0), n(60, 0), n(62, 0.5), n(64, 1.0), n(65, 2.5)];

test("constants", () => {
  assert.equal(PHRASE_GAP_BEATS, 1);
  assert.equal(BEATS_PER_BAR, 4);
  assert.equal(MAX_MELODY_NOTES, 1024);
});

test("detectPhrases splits at rests of a beat or more", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  assert.equal(ps.length, 2);
  assert.deepEqual(ps[0], { start: 0, end: 1.4, low: 60, high: 64, indices: [1, 2, 3] });
  assert.deepEqual(ps[1], { start: 2, end: 2.9, low: 65, high: 67, indices: [0, 4] });
});

test("a rest just under a beat does not split; exactly a beat does", () => {
  // 1.4 -> 1.89 is 0.49 s, under the 0.5 s beat.
  assert.equal(detectPhrases([n(60, 0), n(62, 0.5), n(64, 1.0), n(65, 1.89)], { bpm: BPM }).length, 1);
  // A rounded 0.4995 s rest counts as a full beat (millisecond tolerance).
  assert.equal(detectPhrases([n(60, 0), n(65, 0.8995)], { bpm: BPM }).length, 2);
});

test("the gap scales with the tempo", () => {
  const notes = [n(60, 0), n(62, 1.2)]; // 0.8 s rest
  assert.equal(detectPhrases(notes, { bpm: 60 }).length, 1, "at 60 bpm a beat is 1 s");
  assert.equal(detectPhrases(notes, { bpm: 120 }).length, 2);
  assert.equal(detectPhrases(notes, { bpm: 60, gapBeats: 0.5 }).length, 2);
});

test("a long note bridges later notes that start before it ends", () => {
  const ps = detectPhrases([n(60, 0, 3), n(62, 1), n(64, 3.2)], { bpm: BPM });
  assert.equal(ps.length, 1);
  assert.equal(ps[0].end, 3.6);
});

test("invalid notes are skipped; empty melody has no phrases; tempo is required", () => {
  assert.deepEqual(detectPhrases([], { bpm: BPM }), []);
  assert.deepEqual(detectPhrases([n(60, 0, 0), { m: 61, t: NaN, d: 1 }, n(62, -1)], { bpm: BPM }), []);
  assert.deepEqual(detectPhrases([n(60, 0, 0), n(62, 1)], { bpm: BPM })[0].indices, [1]);
  assert.throws(() => detectPhrases(TWO, {}), /tempo/);
  assert.throws(() => detectPhrases(TWO, { bpm: 0 }), /tempo/);
});

test("phraseOf finds the phrase holding a note", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  assert.equal(phraseOf(ps, 0), 1);
  assert.equal(phraseOf(ps, 3), 0);
  assert.equal(phraseOf(ps, 9), -1);
});

test("movePhrase shifts only the phrase, by beats at the project tempo", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  const { notes, indices } = movePhrase(TWO, ps[1], { bpm: BPM, beats: 2 });
  assert.deepEqual(indices, [0, 4]);
  assert.deepEqual(notes.map(x => x.t), [3.0, 0, 0.5, 1.0, 3.5]);
  assert.deepEqual(notes.map(x => x.m), TWO.map(x => x.m));
  assert.equal(TWO[0].t, 2.0, "input is not mutated");
  const back = movePhrase(TWO, ps[1], { bpm: BPM, beats: -1 });
  assert.deepEqual(back.notes.map(x => x.t), [1.5, 0, 0.5, 1.0, 2.0]);
});

test("movePhrase refuses to move before 0 s or past 600 s", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  assert.throws(() => movePhrase(TWO, ps[0], { bpm: BPM, beats: -1 }), /before the start/);
  assert.deepEqual(movePhrase(TWO, ps[1], { bpm: BPM, beats: -4 }).notes[0].t, 0, "exactly to 0 is allowed");
  const late = [n(60, 599.8)];
  assert.throws(() => movePhrase(late, detectPhrases(late, { bpm: BPM })[0], { bpm: BPM, beats: 1 }), /600 seconds/);
  assert.throws(() => movePhrase(TWO, ps[0], { bpm: BPM, beats: 0 }), /how far/);
});

test("transposePhrase keeps the phrase shape and refuses to leave the MIDI range", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  const up = transposePhrase(TWO, ps[0], 12);
  assert.deepEqual(up.notes.map(x => x.m), [67, 72, 74, 76, 65]);
  assert.deepEqual(up.notes.map(x => x.t), TWO.map(x => x.t));
  assert.deepEqual(transposePhrase(TWO, ps[1], -1).notes.map(x => x.m), [66, 60, 62, 64, 64]);
  const high = [n(120, 0), n(126, 0.5)];
  const hp = detectPhrases(high, { bpm: BPM })[0];
  assert.deepEqual(transposePhrase(high, hp, 1).notes.map(x => x.m), [121, 127]);
  assert.throws(() => transposePhrase(high, hp, 2), /MIDI note range/);
  const low = [n(0, 0)];
  assert.throws(() => transposePhrase(low, detectPhrases(low, { bpm: BPM })[0], -1), /MIDI note range/);
  assert.throws(() => transposePhrase(TWO, ps[0], 0.5), /whole number/);
});

test("copyPhraseToEnd appends the copy whole bars later, after the last note", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  // Melody ends at 2.9 s; phrase 1 starts at 0, so the copy goes 2 bars (4 s) later.
  const c = copyPhraseToEnd(TWO, ps[0], { bpm: BPM });
  assert.equal(c.bars, 2);
  assert.deepEqual(c.indices, [5, 6, 7]);
  assert.deepEqual(c.notes.slice(5), [n(60, 4), n(62, 4.5), n(64, 5)]);
  assert.deepEqual(c.notes.slice(0, 5), TWO, "existing notes are kept in order");
  // The last phrase (starting at 2 s, ending 2.9 s) is copied one bar later.
  const c2 = copyPhraseToEnd(TWO, ps[1], { bpm: BPM });
  assert.equal(c2.bars, 1);
  assert.deepEqual(c2.notes.slice(5).map(x => x.t), [4, 4.5]);
  // A phrase that fills its bar exactly is repeated in the very next bar.
  const full = [n(60, 0, 0.5), n(62, 0.5, 0.5), n(64, 1, 0.5), n(65, 1.5, 0.5)];
  assert.equal(copyPhraseToEnd(full, detectPhrases(full, { bpm: BPM })[0], { bpm: BPM }).bars, 1);
});

test("copyPhraseToEnd keeps a pickup's position in the bar", () => {
  // A pickup a beat before bar 1 (t = 1.5 at 120 bpm), then the phrase continues.
  const notes = [n(59, 1.5), n(60, 2), n(62, 2.5)];
  const p = detectPhrases(notes, { bpm: BPM })[0];
  const c = copyPhraseToEnd(notes, p, { bpm: BPM });
  assert.deepEqual(c.notes.slice(3).map(x => x.t), [3.5, 4, 4.5]);
  assert.equal(c.notes[3].t % 2, 1.5, "the copy starts on the same beat of the bar");
});

test("copyPhraseToEnd respects the note cap and the 600 s limit", () => {
  const many = Array.from({ length: MAX_MELODY_NOTES - 1 }, (_, i) => n(60, i * 0.5, 0.4));
  const ps = detectPhrases(many, { bpm: 60 });
  assert.throws(() => copyPhraseToEnd(many, { ...ps[0], indices: [0, 1] }, { bpm: 60 }), /more than 1024 notes/);
  assert.equal(copyPhraseToEnd(many, { ...ps[0], indices: [0] }, { bpm: 60 }).notes.length, MAX_MELODY_NOTES);
  // The last phrase starts at 598.5 s, so its copy one bar later would start at 600.5 s.
  const late = [n(60, 0), n(62, 598.5)];
  assert.throws(() => copyPhraseToEnd(late, detectPhrases(late, { bpm: BPM })[1], { bpm: BPM }), /600 seconds/);
  const edge = [n(60, 0), n(62, 598)];
  assert.equal(copyPhraseToEnd(edge, detectPhrases(edge, { bpm: BPM })[1], { bpm: BPM }).notes[2].t, 600, "exactly 600 s is allowed");
});

test("a stale phrase is refused", () => {
  const ps = detectPhrases(TWO, { bpm: BPM });
  assert.throws(() => movePhrase(TWO.slice(0, 2), ps[0], { bpm: BPM, beats: 1 }), /choose it again/);
  assert.throws(() => transposePhrase(TWO, null, 1), /Choose a phrase/);
  assert.throws(() => copyPhraseToEnd(TWO, { indices: [] }, { bpm: BPM }), /Choose a phrase/);
});
