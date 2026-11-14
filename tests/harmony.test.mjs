import test from "node:test";
import assert from "node:assert/strict";
import { detectKey, chordsForKey, generateHarmony, keyLabel, CHORD_RANGE, BASS_LOW, STYLES, MODES, harmonyLines, parallelPerfects, HARMONY_LINES, MAX_HARMONY_NOTES } from "../harmony.js";

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
  // Voice leading: each chord takes the inversion nearest the previous one (G under C moves to
  // B-D-G below, not up to G-B-D), so no voice jumps more than a fifth.
  assert.deepEqual([0, 2, 4, 6].map(t => h.notes.filter(n => n.t === t).map(n => n.m)), [[52, 55, 60], [53, 57, 60], [50, 55, 59], [52, 55, 60]]);
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

test("a melody note sounding on the downbeat counts double", () => {
  // F for one beat on the downbeat, then B for a beat and a half. Counted once each, G (B, against
  // F) would win; with the downbeat doubled, F (F, against B) wins.
  const notes = [{ m: 65, t: 0, d: 0.5 }, { m: 71, t: 0.5, d: 0.75 }];
  assert.deepEqual(generateHarmony({ bpm: 120, notes }, { key: { tonic: 0, mode: "major" } }).chords.map(c => c.name), ["F"]);
});

test("a melody too long for a 1024-note harmony part is refused", () => {
  // 342 bars of chords would be 1026 notes, over what projects and /api/chat accept.
  const long = Array.from({ length: 342 }, (_, b) => ({ m: 60, t: b * 2, d: 1.9 }));
  long.push({ m: 64, t: 0.5, d: 0.2 }, { m: 67, t: 1, d: 0.2 });
  assert.throws(() => generateHarmony({ bpm: 120, notes: long }), /too long/);
  assert.equal(generateHarmony({ bpm: 120, notes: long }, { style: "bass" }).notes.length, 684);
});

// HARM.2: generated harmony lines for the harmony voice.
const C_MAJOR = { tonic: 0, mode: "major" }, A_MINOR = { tonic: 9, mode: "minor" };
const inKey = (m, key) => (key.mode === "major" ? [0, 2, 4, 5, 7, 9, 11] : [0, 2, 3, 5, 7, 8, 10]).map(x => (x + key.tonic) % 12).includes(pc(m));
const TUNE = [60, 62, 64, 65, 67, 65, 64, 62, 60, 67, 69, 67, 64, 62, 60, 59].map((m, i) => ({ m, t: i * 0.5, d: 0.45 }));

test("harmonyLines offers the default line first, then distinct alternatives, every note in the key", () => {
  for (const [key, tune] of [[C_MAJOR, TUNE], [A_MINOR, [57, 59, 60, 62, 64, 62, 60, 59, 57, 64, 65, 64, 60, 59, 57, 55].map((m, i) => ({ m, t: i * 0.5, d: 0.45 }))]]) {
    const lines = harmonyLines({ bpm: 120, notes: tune }, { key });
    assert.deepEqual(lines.map(l => l.id), HARMONY_LINES.map(l => l.id));
    assert.equal(lines[0].id, "thirds");
    const shapes = lines.map(l => JSON.stringify(l.notes));
    assert.equal(new Set(shapes).size, lines.length, "each alternative is distinct");
    for (const l of lines) {
      assert.ok(l.notes.length > 0 && l.notes.length <= MAX_HARMONY_NOTES, l.id);
      assert.ok(l.label, l.id);
      for (const n of l.notes) {
        assert.ok(inKey(n.m, key), l.id + " note " + n.m + " is in " + key.mode);
        assert.ok(n.d > 0 && n.t >= 0);
      }
    }
  }
});

test("the default line is a third above in key, a sixth where the third is not in the chord, with no parallel fifths or octaves", () => {
  // C major chords for the whole tune: C over C gives E (a third), G over C gives E above it (a
  // sixth, since B is not in the chord), D over C gives F (no chord tone either way: the third).
  const chords = [48, 52, 55].map(m => ({ m, t: 0, d: 8 }));
  const [line] = harmonyLines({ bpm: 120, notes: TUNE }, { key: C_MAJOR, chords });
  assert.deepEqual(line.notes.map(n => n.t), TUNE.map(n => n.t), "it moves with the melody");
  assert.deepEqual(line.notes.map(n => n.d), TUNE.map(n => n.d));
  const byStart = new Map(line.notes.map(n => [n.t, n.m]));
  assert.equal(byStart.get(0), 64, "C: a third above");
  assert.equal(byStart.get(1), 67, "E: a third above, G is in the chord");
  assert.equal(byStart.get(2), 76, "G: a sixth above, E, since B is not in the chord");
  assert.equal(byStart.get(0.5), 65, "D: neither F nor B is in the chord, so the third");
  for (const n of line.notes) assert.ok(n.m > TUNE.find(x => x.t === n.t).m, "above the melody");
  assert.equal(parallelPerfects(TUNE, line.notes), 0);
});

test("without a harmony part the chords are worked out from the melody", () => {
  const generated = generateHarmony({ bpm: 120, notes: TUNE }, { key: C_MAJOR }).notes;
  assert.deepEqual(harmonyLines({ bpm: 120, notes: TUNE }, { key: C_MAJOR }),
    harmonyLines({ bpm: 120, notes: TUNE }, { key: C_MAJOR, chords: generated }));
  assert.deepEqual(harmonyLines({ bpm: 120, notes: TUNE }, { key: C_MAJOR, chords: [] }),
    harmonyLines({ bpm: 120, notes: TUNE }, { key: C_MAJOR, chords: generated }));
});

test("parallelPerfects counts fifths and octaves held in similar motion", () => {
  const mel = [60, 62, 64].map((m, i) => ({ m, t: i, d: 1 }));
  assert.equal(parallelPerfects(mel, mel.map(n => ({ ...n, m: n.m + 7 }))), 2);
  assert.equal(parallelPerfects(mel, mel.map(n => ({ ...n, m: n.m - 12 }))), 2);
  assert.equal(parallelPerfects(mel, mel.map(n => ({ ...n, m: n.m + 4 }))), 0);
  assert.equal(parallelPerfects(mel, [{ m: 67, t: 0, d: 1 }, { m: 67, t: 1, d: 1 }, { m: 71, t: 2, d: 1 }]), 0, "a held note is oblique motion");
});

test("the alternatives: a sixth below, an octave below, a counter-melody and a two-voice stack", () => {
  const chords = [48, 52, 55].map(m => ({ m, t: 0, d: 4 })).concat([53, 57, 60].map(m => ({ m, t: 4, d: 4 })));
  const lines = Object.fromEntries(harmonyLines({ bpm: 120, notes: TUNE }, { key: C_MAJOR, chords }).map(l => [l.id, l.notes]));
  assert.deepEqual(lines.sixth_below.slice(0, 3).map(n => n.m), [52, 53, 55], "C D E a sixth below: E F G");
  assert.deepEqual(lines.octave.map(n => n.m), TUNE.map(n => n.m - 12));
  // The counter-melody moves every two beats (a second at 120 bpm), on a tone of the chord sounding
  // then, below the tune, by small steps, and does not sit on one note.
  assert.deepEqual(lines.counter.map(n => n.t), [0, 1, 2, 3, 4, 5, 6, 7]);
  lines.counter.forEach(n => assert.ok((n.t < 4 ? [0, 4, 7] : [5, 9, 0]).includes(pc(n.m)), "chord tone at " + n.t));
  assert.ok(lines.counter.every(n => n.m < Math.min(...TUNE.map(x => x.m))));
  lines.counter.slice(1).forEach((n, i) => assert.ok(Math.abs(n.m - lines.counter[i].m) <= 5, "a small move at " + n.t));
  assert.ok(new Set(lines.counter.map(n => n.m)).size > 2);
  // The stack is the default line plus a third below, two notes for each melody note.
  assert.equal(lines.stack.length, 2 * TUNE.length);
  assert.deepEqual(lines.stack.filter(n => n.t === 0).map(n => n.m).sort((a, b) => a - b), [57, 64]);
});

test("the counter-melody leaves the nearest chord tone for another when it would move in octaves or fifths with the tune", () => {
  // G A G over A minor, F, C: from A under the tune's A, the nearest C-chord tone is G, an octave
  // below the tune's G reached in the same direction; the line goes up to C instead.
  const tune = [67, 69, 67].map((m, t) => ({ m, t, d: 1 }));
  const chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55]].flatMap((c, t) => c.map(m => ({ m, t, d: 1 })));
  const counter = harmonyLines({ bpm: 120, notes: tune }, { key: C_MAJOR, chords }).find(l => l.id === "counter").notes;
  assert.deepEqual(counter.map(n => n.m), [60, 57, 60]);
  assert.equal(parallelPerfects(tune, counter), 0);
});

test("harmonyLines needs a melody and a key, and leaves the project unchanged", () => {
  assert.throws(() => harmonyLines({ bpm: 120, notes: [] }, { key: C_MAJOR }), /melody/);
  assert.throws(() => harmonyLines({ bpm: 120, notes: TUNE }, { key: null }), /key/);
  const project = { bpm: 120, notes: TUNE.map(n => ({ ...n })) }, copy = JSON.parse(JSON.stringify(project));
  harmonyLines(project, { key: C_MAJOR });
  assert.deepEqual(project, copy);
  // A note out of the key is left out of the octave double rather than doubled out of the key.
  const sharp = TUNE.map((n, i) => (i === 3 ? { ...n, m: 66 } : n));
  const oct = harmonyLines({ bpm: 120, notes: sharp }, { key: C_MAJOR }).find(l => l.id === "octave");
  assert.equal(oct.notes.length, TUNE.length - 1);
});
