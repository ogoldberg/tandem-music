// SILENT.1: each melody note against the chord under it, and how the phrases end.
import test from "node:test";
import assert from "node:assert/strict";
import { melodyFit, fitSummary, NOTE_FITS } from "../tension.js";

// 120 bpm: a beat is 0.5 s, a bar 2 s. Chords a bar each, read by harmony.js readChords.
const BPM = 120;
const C_MAJOR = { tonic: 0, mode: "major" };
const chord = (t, ms) => ms.map(m => ({ m, t, d: 2 }));
const C = t => chord(t, [48, 52, 55]);
const G = t => chord(t, [50, 55, 59]);
const F = t => chord(t, [53, 57, 60]);
const line = (start, ms, d = 0.5) => ms.map((m, i) => ({ m, t: start + i * d, d }));
const fits = r => r.notes.map(n => n.fit);

test("a melody of chord tones: every note is a chord tone, named by the chord under it", () => {
  const notes = [...line(0, [60, 64, 67, 72]), ...line(2, [62, 67, 71, 74])];
  const r = melodyFit(notes, [...C(0), ...G(2)], { bpm: BPM, key: C_MAJOR });
  assert.deepEqual(fits(r), Array(8).fill("chord"));
  assert.deepEqual(r.notes.map(n => n.chord), [..."CCCC"].concat([..."GGGG"]));
  assert.deepEqual(r.counts, { chord: 8, key: 0, outside: 0 });
});

test("passing tones are in the key but not in the chord", () => {
  // C D E F G over C: D and F are passing tones.
  const r = melodyFit(line(0, [60, 62, 64, 65], 0.4).concat([{ m: 67, t: 1.6, d: 0.4 }]), C(0), { bpm: BPM, key: C_MAJOR });
  assert.deepEqual(fits(r), ["chord", "key", "chord", "key", "chord"]);
  assert.deepEqual(r.counts, { chord: 3, key: 2, outside: 0 });
});

test("notes outside the key are marked outside, even with no chord under them", () => {
  // C# and F# are not in C major; the last note sounds after the chords end.
  const notes = [{ m: 61, t: 0, d: 0.5 }, { m: 64, t: 0.5, d: 0.5 }, { m: 66, t: 1, d: 0.5 }, { m: 66, t: 3, d: 0.5 }, { m: 65, t: 3.5, d: 0.5 }];
  const r = melodyFit(notes, C(0), { bpm: BPM, key: C_MAJOR });
  assert.deepEqual(fits(r), ["outside", "chord", "outside", "outside", "key"]);
  assert.deepEqual(r.notes.map(n => n.chord), ["C", "C", "C", null, null]);
});

test("a note that starts before the first chord takes the chord it overlaps longest", () => {
  const r = melodyFit([{ m: 67, t: 0, d: 2 }], G(1), { bpm: BPM, key: C_MAJOR });
  assert.deepEqual(r.notes, [{ fit: "chord", chord: "G" }]);
});

test("phrase endings: one ending over V is open, one over I is home, one over IV is not marked", () => {
  // Three phrases split by a rest of a beat or more: ends over G (bar 2), C (bar 4) and F (bar 3).
  const p1 = line(0, [64, 62, 60, 62, 64, 62, 67]); // last note 67 at 3.0 to 3.5, over G
  const p2 = line(6, [64, 62, 60]); // ends 7.5, over C
  const p3 = [{ m: 65, t: 4.5, d: 0.5 }]; // alone between them, over F
  const notes = [...p1, ...p3, ...p2];
  const r = melodyFit(notes, [...C(0), ...G(2), ...F(4), ...C(6)], { bpm: BPM, key: C_MAJOR });
  assert.deepEqual(r.cadences.map(c => [c.kind, c.roman, c.chord, c.t]), [["dominant", "V", "G", 3.5], ["tonic", "I", "C", 7.5]]);
  // Each mark names its phrase and the note it falls on.
  assert.deepEqual(r.cadences.map(c => [c.phrase, c.note]), [[0, 6], [2, notes.length - 1]]);
});

test("no chords part: chord tones and phrase endings cannot be read, the key still can", () => {
  const r = melodyFit(line(0, [60, 61, 62]), [], { bpm: BPM, key: C_MAJOR });
  assert.deepEqual(fits(r), ["key", "outside", "key"]);
  assert.deepEqual(r.cadences, []);
  assert.match(fitSummary(r), /No chords under the melody yet/);
});

test("in a minor key the leading tone is a chord tone over the major V and outside the key on its own", () => {
  const A_MINOR = { tonic: 9, mode: "minor" };
  const Am = chord(0, [45, 48, 52]), E = chord(2, [52, 56, 59]);
  const notes = [...line(0.5, [69, 72, 76]), ...line(2, [68, 71]), { m: 68, t: 6, d: 0.5 }];
  const r = melodyFit(notes, [...Am, ...E], { bpm: BPM, key: A_MINOR });
  assert.deepEqual(fits(r), ["chord", "chord", "chord", "chord", "chord", "outside"]);
  // The first phrase ends over E (V); the last note, alone after the chords, has no chord.
  assert.deepEqual(r.cadences.map(c => [c.kind, c.roman]), [["dominant", "V"]]);
  // And a phrase ending over A minor ends home on i.
  const home = melodyFit(line(0, [76, 72, 69]), Am, { bpm: BPM, key: A_MINOR });
  assert.deepEqual(home.cadences.map(c => [c.kind, c.roman]), [["tonic", "i"]]);
  assert.match(fitSummary(home), /1 phrase ends home on i\./);
});

test("an edit changes the classes: moving a chord tone a semitone takes it outside the key", () => {
  const notes = line(0, [60, 64, 67]);
  assert.equal(melodyFit(notes, C(0), { bpm: BPM, key: C_MAJOR }).notes[1].fit, "chord");
  const moved = notes.map((n, i) => (i === 1 ? { ...n, m: 63 } : n));
  assert.equal(melodyFit(moved, C(0), { bpm: BPM, key: C_MAJOR }).notes[1].fit, "outside");
});

test("the summary counts each kind and the phrase endings", () => {
  const r = melodyFit([...line(0, [60, 62, 64]), ...line(1.5, [62, 61, 67])], [...C(0), ...G(2)], { bpm: BPM, key: C_MAJOR });
  assert.equal(fitSummary(r), "3 chord tones, 2 in the key, 1 outside the key. No phrase ends home on I, 1 open on V.");
  assert.equal(fitSummary(melodyFit([], [], { bpm: BPM, key: C_MAJOR })), "No melody notes yet.");
});

test("a key is required, and the input is not changed", () => {
  assert.throws(() => melodyFit(line(0, [60]), [], { bpm: BPM, key: null }), /key/);
  const notes = line(0, [60, 64]), harmony = C(0), before = JSON.stringify([notes, harmony]);
  melodyFit(notes, harmony, { bpm: BPM, key: C_MAJOR });
  assert.equal(JSON.stringify([notes, harmony]), before);
  assert.deepEqual(NOTE_FITS, ["chord", "key", "outside"]);
});
