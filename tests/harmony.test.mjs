import test from "node:test";
import assert from "node:assert/strict";
import { detectKey, chordsForKey, generateHarmony, keyLabel, CHORD_RANGE, BASS_LOW, STYLES, MODES } from "../harmony.js";

const pc = m => ((m % 12) + 12) % 12;
// Quarter notes at 120 bpm (0.5 s each), one pitch list per 4/4 bar.
function melody(bars, beat = 0.5, start = 0) {
  const notes = [];
  bars.forEach((pitches, b) => pitches.forEach((m, i) => notes.push({ m, t: start + (b * 4 + i) * beat, d: beat * 0.9 })));
  return notes;
}

test("styles and modes", () => {
  assert.deepEqual([...STYLES], ["chords", "bass"]);
  assert.deepEqual([...MODES], ["major", "minor"]);
});

test("detectKey needs three notes with two pitch classes", () => {
  assert.equal(detectKey([]), null);
  assert.equal(detectKey([{ m: 60, t: 0, d: 1 }, { m: 64, t: 1, d: 1 }]), null);
  assert.equal(detectKey([{ m: 60, t: 0, d: 1 }, { m: 72, t: 1, d: 1 }, { m: 48, t: 2, d: 1 }]), null);
  assert.equal(detectKey([{ m: 60, t: 0, d: 0 }, { m: 64, t: 1, d: NaN }, { m: 67, t: 2, d: 1 }]), null, "invalid notes are ignored");
});

for (const [name, tonic, mode, steps] of [
  ["C major", 0, "major", [0, 2, 4, 5, 7, 9, 11, 12, 7, 4, 0]],
  ["G major", 7, "major", [0, 4, 7, 12, 11, 9, 7, 6, 7, 2, 0]],
  ["A minor", 9, "minor", [0, 3, 7, 12, 10, 8, 7, 5, 3, 2, 0]],
  ["E minor", 4, "minor", [0, 2, 3, 7, 3, 0, 11, 0, 7, 3, 0]],
]) {
  test(`detectKey finds ${name} from a scale-and-arpeggio melody`, () => {
    const notes = steps.map((s, i) => ({ m: 60 + tonic + s - (tonic > 6 ? 12 : 0), t: i * 0.5, d: i === 0 || i === steps.length - 1 ? 1.2 : 0.45 }));
    const key = detectKey(notes);
    assert.equal(key.tonic, tonic, keyLabel(key));
    assert.equal(key.mode, mode);
    assert.ok(key.confidence > 0.6 && key.confidence <= 1);
  });
}

test("detectKey does not mutate its input", () => {
  const notes = [{ m: 60, t: 0, d: 1 }, { m: 64, t: 1, d: 1 }, { m: 67, t: 2, d: 1 }];
  const copy = JSON.parse(JSON.stringify(notes));
  detectKey(notes);
  assert.deepEqual(notes, copy);
});

test("chordsForKey lists the diatonic triads", () => {
  assert.deepEqual(chordsForKey({ tonic: 0, mode: "major" }).map(c => c.name), ["C", "Dm", "Em", "F", "G", "Am"]);
  assert.deepEqual(chordsForKey({ tonic: 9, mode: "minor" }).map(c => c.name), ["Am", "C", "Dm", "E", "F", "G"]);
  assert.deepEqual(chordsForKey({ tonic: 7, mode: "major" }).find(c => c.roman === "V").pcs, [2, 6, 9]);
  assert.throws(() => chordsForKey({ tonic: 12, mode: "major" }), /Choose a key/);
  assert.throws(() => chordsForKey({ tonic: 0, mode: "dorian" }), /Choose a key/);
});

test("generateHarmony rejects bad input", () => {
  assert.throws(() => generateHarmony({ bpm: 120, notes: [] }), /melody/);
  assert.throws(() => generateHarmony({ bpm: 0, notes: melody([[60, 64, 67, 72]]) }), /tempo/);
  assert.throws(() => generateHarmony({ bpm: 120, notes: melody([[60, 64, 67, 72]]) }, { style: "pad" }), /style/);
  assert.throws(() => generateHarmony({ bpm: 120, notes: [{ m: 60, t: 0, d: 1 }, { m: 60, t: 1, d: 1 }] }), /choose a key/);
});

// I - IV - V - I outlined bar by bar in C major.
const CADENCE = melody([[60, 64, 67, 64], [65, 69, 72, 69], [67, 71, 74, 71], [72, 67, 64, 60]]);

test("generateHarmony picks I-IV-V-I under a melody that outlines it", () => {
  const h = generateHarmony({ bpm: 120, notes: CADENCE });
  assert.deepEqual(h.key, { tonic: 0, mode: "major" });
  assert.deepEqual(h.chords.map(c => c.name), ["C", "F", "G", "C"]);
  assert.deepEqual(h.chords.map(c => c.roman), ["I", "IV", "V", "I"]);
  assert.deepEqual(h.chords.map(c => c.t), [0, 2, 4, 6]);
  assert.ok(h.chords.every(c => c.d === 2));
});

test("chord style voices a triad per bar inside the chord range with smooth voice leading", () => {
  const h = generateHarmony({ bpm: 120, notes: CADENCE }, { style: "chords" });
  assert.equal(h.notes.length, 12);
  for (let b = 0; b < 4; b++) {
    const bar = h.notes.filter(n => n.t === b * 2);
    assert.equal(bar.length, 3);
    assert.deepEqual([...new Set(bar.map(n => pc(n.m)))].sort((a, b) => a - b), [...chordsForKey(h.key).find(c => c.name === h.chords[b].name).pcs].sort((a, b) => a - b));
    for (const n of bar) {
      assert.ok(n.m >= CHORD_RANGE[0] && n.m <= CHORD_RANGE[1], `note ${n.m} out of range`);
      assert.ok(n.d < 2 && n.d > 1.8, "held for most of the bar, released before the next");
    }
  }
  // Voice leading: no voice jumps more than a fifth between neighbouring chords.
  for (let b = 1; b < 4; b++) {
    const prev = h.notes.filter(n => n.t === (b - 1) * 2).map(n => n.m).sort((x, y) => x - y);
    const cur = h.notes.filter(n => n.t === b * 2).map(n => n.m).sort((x, y) => x - y);
    cur.forEach((m, i) => assert.ok(Math.abs(m - prev[i]) <= 7, `bar ${b} voice ${i}: ${prev[i]} -> ${m}`));
  }
});

test("bass style plays root on beat 1 and fifth on beat 3 in the bass register", () => {
  const h = generateHarmony({ bpm: 120, notes: CADENCE }, { style: "bass" });
  assert.equal(h.notes.length, 8);
  const roots = { C: 0, F: 5, G: 7 };
  h.chords.forEach((c, b) => {
    const [one, three] = h.notes.slice(b * 2, b * 2 + 2);
    assert.equal(one.t, b * 2);
    assert.equal(three.t, b * 2 + 1);
    assert.equal(pc(one.m), roots[c.name]);
    assert.equal(three.m, one.m + 7);
    assert.ok(one.m >= BASS_LOW && one.m < BASS_LOW + 12);
    assert.ok(one.d < 1 && one.d > 0.9);
  });
});

test("bars follow the tempo and start at the first melody note", () => {
  const notes = melody([[57, 60, 64, 60], [62, 65, 69, 65]], 60 / 90, 1.25);
  const h = generateHarmony({ bpm: 90, notes }, { key: { tonic: 9, mode: "minor" } });
  assert.deepEqual(h.key, { tonic: 9, mode: "minor" });
  assert.deepEqual(h.chords.map(c => c.t), [1.25, 1.25 + 160 / 60].map(x => Math.round(x * 1000) / 1000));
  assert.deepEqual(h.chords.map(c => c.name), ["Am", "Dm"]);
});

test("a chosen key overrides detection", () => {
  const h = generateHarmony({ bpm: 120, notes: CADENCE }, { key: { tonic: 9, mode: "minor" } });
  assert.deepEqual(h.key, { tonic: 9, mode: "minor" });
  assert.ok(h.chords.every(c => chordsForKey(h.key).some(k => k.name === c.name)));
});

test("a bar with no melody keeps the previous chord", () => {
  const notes = [...melody([[60, 64, 67, 64], [65, 69, 72, 69]]), { m: 67, t: 6, d: 0.45 }, { m: 62, t: 6.5, d: 0.45 }];
  const h = generateHarmony({ bpm: 120, notes });
  assert.deepEqual(h.chords.map(c => c.name).slice(0, 3), ["C", "F", "F"]);
  assert.equal(h.chords.length, 4);
});

test("generated notes are plain {m,t,d} with finite, non-negative times", () => {
  for (const style of STYLES) {
    const h = generateHarmony({ bpm: 100, notes: CADENCE }, { style });
    for (const n of h.notes) {
      assert.deepEqual(Object.keys(n).sort(), ["d", "m", "t"]);
      assert.ok(Number.isInteger(n.m) && n.m >= 36 && n.m <= 96);
      assert.ok(Number.isFinite(n.t) && n.t >= 0 && n.d > 0);
    }
  }
});

test("generateHarmony does not mutate the project", () => {
  const project = { bpm: 120, notes: CADENCE.map(n => ({ ...n })).reverse() };
  const copy = JSON.parse(JSON.stringify(project));
  generateHarmony(project);
  assert.deepEqual(project, copy);
});
