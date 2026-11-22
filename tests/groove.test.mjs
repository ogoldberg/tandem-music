import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { estimateTempo, quantizeProject, swungOffbeat, GRID_DIVISIONS, TEMPO_RANGE } from "../groove.js";

const close = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

// Deterministic pseudo-random jitter so tests are reproducible.
function jitter(seed) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) % 2147483648;
    return s / 2147483648 - 0.5;
  };
}

test("grid divisions are quarters, eighths and sixteenths", () => {
  assert.deepEqual(GRID_DIVISIONS, { "1/4": 1, "1/8": 2, "1/16": 4 });
});

test("swungOffbeat goes from straight to triplet", () => {
  assert.equal(swungOffbeat(0), 0.5);
  assert.ok(close(swungOffbeat(1), 2 / 3));
  assert.ok(close(swungOffbeat(0.5), 0.5 + 1 / 12));
  assert.equal(swungOffbeat(-1), 0.5, "clamped below");
  assert.ok(close(swungOffbeat(5), 2 / 3), "clamped above");
});

test("estimateTempo returns null with too few onsets", () => {
  assert.equal(estimateTempo([]), null);
  assert.equal(estimateTempo([0, 0.5, 1]), null);
});

for (const bpm of [72, 90, 100, 120, 140, 165]) {
  test(`estimateTempo recovers ${bpm} bpm from jittered eighth-note onsets`, () => {
    const r = jitter(bpm), beat = 60 / bpm, times = [];
    // A realistic mix: quarters with some eighths, offset from zero, +-12 ms jitter.
    for (let i = 0; i < 32; i++) if (i % 2 === 0 || i % 3 === 0) times.push(0.37 + i * beat / 2 + r() * 0.024);
    const est = estimateTempo(times);
    assert.ok(est !== null);
    assert.ok(Math.abs(est - bpm) <= 2, `estimated ${est} for ${bpm}`);
  });
}

for (const bpm of [70, 85, 100]) {
  test(`estimateTempo does not double sloppy quarter notes at ${bpm} bpm`, () => {
    // A finer grid always sits closer to jittered onsets; the chance correction stops that winning.
    const r = jitter(bpm), beat = 60 / bpm, times = [];
    for (let i = 0; i < 16; i++) times.push(0.2 + i * beat + r() * 0.05);
    const est = estimateTempo(times);
    assert.ok(Math.abs(est - bpm) <= 2, `estimated ${est} for ${bpm}`);
  });
}

for (const bpm of [120, 140, 165]) {
  for (const j of [0, 0.03]) {
    test(`estimateTempo does not halve on-beat onsets at ${bpm} bpm (jitter ${j * 1000} ms)`, () => {
      // Review of #28: with only quarter notes, the half-tempo eighth grid fits as well; the beat grid must decide.
      const r = jitter(bpm + 1), beat = 60 / bpm, times = [];
      for (let i = 0; i < 16; i++) times.push(0.5 + i * beat + r() * j);
      const est = estimateTempo(times);
      assert.ok(Math.abs(est - bpm) <= 2, `estimated ${est} for ${bpm}`);
    });
  }
}

test("estimateTempo finds the example project's 133 bpm pulse", () => {
  const notes = [60, 64, 67, 69, 67, 64, 62, 60].map((m, i) => i * 0.45);
  const drums = Array.from({ length: 16 }, (_, i) => i * 0.225);
  const est = estimateTempo([...notes, ...drums]);
  assert.ok(Math.abs(est - 133.3) <= 1.5, `estimated ${est}`);
});

test("estimateTempo stays inside the tempo range", () => {
  // Very fast onsets (every 0.1 s) must not produce a tempo above the range.
  const est = estimateTempo(Array.from({ length: 40 }, (_, i) => i * 0.1));
  assert.ok(est >= TEMPO_RANGE[0] && est <= TEMPO_RANGE[1], `estimated ${est}`);
});

test("quantizeProject snaps starts to the beat grid of the onsets", () => {
  const project = {
    bpm: 120,
    notes: [{ m: 60, t: 1.0, d: 0.4 }, { m: 62, t: 1.27, d: 0.2 }, { m: 64, t: 1.98, d: 0.5 }],
    drums: [{ k: "kick", t: 1.02 }, { k: "hat", t: 1.51 }],
  };
  const out = quantizeProject(project, { division: 2, swing: 0, strength: 1 });
  // Anchor 1.0, eighth = 0.25 s.
  assert.deepEqual(out.notes.map(n => n.t), [1.0, 1.25, 2.0]);
  assert.deepEqual(out.notes.map(n => n.d), [0.4, 0.2, 0.5], "durations are kept");
  assert.deepEqual(out.drums.map(h => h.t), [1.0, 1.5]);
  assert.deepEqual(out.notes.map(n => n.m), [60, 62, 64]);
});

test("the grid follows the beat, not a zero-based grid", () => {
  // Events sit on an eighth grid offset by 0.37 s; a grid anchored at 0 would pull them 0.12 s early.
  const project = { bpm: 120, notes: [], drums: [0.37, 0.62, 0.88, 1.11, 1.37].map(t => ({ k: "hat", t })) };
  const out = quantizeProject(project, { division: 2, swing: 0, strength: 1 });
  out.drums.forEach((h, i) => assert.ok(close(h.t, 0.37 + i * 0.25, 1e-6), `${h.t}`));
});

test("a pickup note before the downbeat does not flip the swing", () => {
  // Review of #28: 120 bpm, downbeats at 1.0 .. 3.0 with offbeats at 1.25, 1.75, 2.25 and a pickup at 0.75.
  // The downbeats outnumber the offbeats, which is how the grid tells them apart.
  const t = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0];
  const project = { bpm: 120, notes: [], drums: t.map((x, i) => ({ k: i % 2 ? "kick" : "hat", t: x })) };
  const out = quantizeProject(project, { division: 2, swing: 1, strength: 1 });
  const want = [0.5 + 1 / 3, 1.0, 1 + 1 / 3, 1.5, 1.5 + 1 / 3, 2.0, 2 + 1 / 3, 2.5, 3.0];
  out.drums.forEach((h, i) => assert.ok(close(h.t, want[i], 1e-6), `${i}: ${h.t} vs ${want[i]}`));
});

test("quantized times never go below zero", () => {
  // The beat sits at 0.3 + n * 0.5, so the note at 0.03 is nearest the grid point at -0.2: it is clamped to 0.
  const project = { bpm: 120, notes: [{ m: 60, t: 0.03, d: 0.2 }], drums: [0.3, 0.8, 1.3, 1.8].map(t => ({ k: "kick", t })) };
  const out = quantizeProject(project, { division: 1, swing: 0, strength: 1 });
  assert.equal(out.notes[0].t, 0);
  assert.deepEqual(out.drums.map(h => h.t), [0.3, 0.8, 1.3, 1.8]);
});

test("quantizeProject leaves the input untouched", () => {
  const project = { bpm: 120, notes: [{ m: 60, t: 0.1, d: 0.3 }], drums: [{ k: "kick", t: 0.33 }] };
  const copy = JSON.parse(JSON.stringify(project));
  quantizeProject(project, { division: 4, swing: 0, strength: 1 });
  assert.deepEqual(project, copy);
});

test("swing moves offbeat eighths later and leaves downbeats alone", () => {
  const project = { bpm: 120, notes: [], drums: [0, 0.25, 0.5, 0.75, 1.0].map(t => ({ k: "hat", t })) };
  const out = quantizeProject(project, { division: 2, swing: 1, strength: 1 });
  // Beat 0.5 s; full swing puts the offbeat at 2/3 of the beat.
  const want = [0, 1 / 3, 0.5, 0.5 + 1 / 3, 1.0];
  out.drums.forEach((h, i) => assert.ok(close(h.t, want[i], 1e-6), `${h.t} vs ${want[i]}`));
});

test("with sixteenths, swing applies to each pair of sixteenths", () => {
  const project = { bpm: 120, notes: [], drums: [0, 0.125, 0.25, 0.375].map(t => ({ k: "hat", t })) };
  const out = quantizeProject(project, { division: 4, swing: 1, strength: 1 });
  const want = [0, 0.25 * 2 / 3, 0.25, 0.25 + 0.25 * 2 / 3];
  out.drums.forEach((h, i) => assert.ok(close(h.t, want[i], 1e-6), `${h.t} vs ${want[i]}`));
});

test("quarter grid ignores swing", () => {
  const project = { bpm: 120, notes: [], drums: [0, 0.48, 1.03].map(t => ({ k: "kick", t })) };
  const out = quantizeProject(project, { division: 1, swing: 1, strength: 1 });
  assert.deepEqual(out.drums.map(h => h.t), [0, 0.5, 1.0]);
});

test("strength moves events only part of the way", () => {
  const project = { bpm: 120, notes: [{ m: 60, t: 0, d: 0.2 }, { m: 62, t: 0.3, d: 0.2 }], drums: [] };
  const out = quantizeProject(project, { division: 2, swing: 0, strength: 0.5 });
  assert.ok(close(out.notes[1].t, 0.275, 1e-6), `${out.notes[1].t}`);
});

test("events that land on the same grid point are merged", () => {
  const project = {
    bpm: 120,
    notes: [{ m: 60, t: 0, d: 0.2 }, { m: 60, t: 0.49, d: 0.3 }, { m: 60, t: 0.52, d: 0.6 }, { m: 64, t: 0.51, d: 0.2 }],
    drums: [{ k: "kick", t: 0 }, { k: "snare", t: 0.49 }, { k: "snare", t: 0.51 }, { k: "hat", t: 0.5 }],
  };
  const out = quantizeProject(project, { division: 2, swing: 0, strength: 1 });
  assert.deepEqual(out.notes, [{ m: 60, t: 0, d: 0.2 }, { m: 60, t: 0.5, d: 0.6 }, { m: 64, t: 0.5, d: 0.2 }]);
  assert.deepEqual(out.drums, [{ k: "kick", t: 0 }, { k: "snare", t: 0.5 }, { k: "hat", t: 0.5 }]);
});

test("output is sorted by time", () => {
  const project = { bpm: 100, notes: [{ m: 67, t: 1.2, d: 0.2 }, { m: 60, t: 0.1, d: 0.2 }], drums: [{ k: "hat", t: 0.9 }, { k: "kick", t: 0.1 }] };
  const out = quantizeProject(project, { division: 2, swing: 0, strength: 1 });
  assert.deepEqual(out.notes.map(n => n.m), [60, 67]);
  assert.deepEqual(out.drums.map(h => h.k), ["kick", "hat"]);
});

test("an empty project quantizes to an empty project", () => {
  assert.deepEqual(quantizeProject({ bpm: 100, notes: [], drums: [] }, { division: 2, swing: 0, strength: 1 }), { notes: [], drums: [], harmony: [], voice2: [] });
});

test("quantizeProject rejects bad settings", () => {
  const p = { bpm: 100, notes: [{ m: 60, t: 0, d: 1 }], drums: [] };
  assert.throws(() => quantizeProject(p, { division: 3, swing: 0, strength: 1 }), /division/);
  assert.throws(() => quantizeProject({ ...p, bpm: 0 }, { division: 2, swing: 0, strength: 1 }), /tempo/);
  assert.throws(() => quantizeProject(p, { division: 2, swing: 0, strength: 0 }), /strength/);
});

// Known limits (issue #29). These pin current behaviour so a change to it is deliberate and the docs follow.
for (const run of [8, 9]) {
  test(`limit: off the grid from zero, a pickup into ${run} even eighths is taken as the beat`, () => {
    // 120 bpm, pickup at 0.85 then even eighths from 1.1 (off the zero grid by 0.1 s). With 8 eighths the
    // pickup's phase has more onsets (5 to 4) and wins outright; with 9 they tie (5 to 5) and the earliest
    // phase, the pickup's, wins. Either way the real downbeats become offbeats and swing moves them.
    const t = [0.85, ...Array.from({ length: run }, (_, i) => 1.1 + i * 0.25)];
    const project = { bpm: 120, notes: t.map(x => ({ m: 60, t: x, d: 0.1 })), drums: [] };
    const out = quantizeProject(project, { division: 2, swing: 1, strength: 1 });
    const want = t.map((x, i) => (i % 2 ? x - 0.25 + 1 / 3 : x));
    out.notes.forEach((n, i) => assert.ok(close(n.t, want[i], 1e-6), `${i}: ${n.t} vs ${want[i]}`));
  });
}

for (const run of [8, 9]) {
  test(`FIX.3: on the grid from zero, a pickup into ${run} even eighths keeps the downbeats`, () => {
    // As above but sung to the count-in: the zero grid fits as well as any, so the beat is zero's.
    const t = [0.75, ...Array.from({ length: run }, (_, i) => 1.0 + i * 0.25)];
    const project = { bpm: 120, notes: t.map(x => ({ m: 60, t: x, d: 0.1 })), drums: [] };
    const out = quantizeProject(project, { division: 2, swing: 1, strength: 1 });
    const want = t.map(x => (Math.abs(x * 2 - Math.round(x * 2)) < 1e-9 ? x : x - 0.25 + 1 / 3));
    out.notes.forEach((n, i) => assert.ok(close(n.t, want[i], 1e-6), `${i}: ${n.t} vs ${want[i]}`));
  });
}

for (const bpm of [55, 60, 65]) {
  test(`limit: slow quarters with an eighth every second beat read double at ${bpm} bpm`, () => {
    const b = 60 / bpm, times = [];
    for (let i = 0; i < 16; i++) { times.push(0.3 + i * b); if (i % 2) times.push(0.3 + i * b + b / 2); }
    assert.equal(estimateTempo(times), 2 * bpm);
  });
}

test("the same slow pattern reads correctly from 70 bpm", () => {
  for (const bpm of [70, 75, 79, 80, 90]) {
    const b = 60 / bpm, times = [];
    for (let i = 0; i < 16; i++) { times.push(0.3 + i * b); if (i % 2) times.push(0.3 + i * b + b / 2); }
    assert.equal(estimateTempo(times), bpm);
  }
});

// FIX.3: one bar grid for chords, the starter beat and quantize.
import { barOrigin } from "../groove.js";
import { grooveHits } from "../beats.js";
import { generateHarmony } from "../harmony.js";

// 100 bpm (beat 0.6 s, bar 2.4 s); a tune sung after the count-in with a pickup on beat 4 (1.8 s),
// each onset up to 25 ms off the beat as a singer is.
const PICKUP_TUNE = [[67, 1.8], [72, 2.41], [71, 3.02], [72, 3.58], [74, 4.21], [76, 4.8], [74, 5.42], [72, 6.03], [71, 7.2], [72, 7.8]]
  .map(([m, t]) => ({ m, t, d: 0.5 }));

test("barOrigin: zero for a take sung on the grid from zero, a pickup and all", () => {
  assert.equal(barOrigin({ bpm: 100, notes: PICKUP_TUNE, drums: [] }), 0);
  assert.equal(barOrigin({ bpm: 100, notes: [], drums: [] }), 0);
});

test("barOrigin: a free-time recording keeps its first downbeat, as a time within the first bar", () => {
  // On the beat from 3.37 s, off the zero grid by 0.37 s.
  const notes = [0, 1, 2, 3, 4, 5].map(i => ({ m: 60 + i, t: 3.37 + i * 0.6, d: 0.5 }));
  assert.ok(close(barOrigin({ bpm: 100, notes, drums: [] }), 3.37 - 2.4, 1e-6));
});

test("barOrigin: a starter beat from zero holds the grid at zero under a sloppy take", () => {
  // Alone these notes agree on a beat 0.11 s after zero; under a starter beat from zero the grid stays at zero.
  const notes = [0.11, 0.71, 1.31, 1.91].map((t, i) => ({ m: 60 + i, t, d: 0.4 }));
  const drums = grooveHits("straight", { bpm: 100, bars: 2 });
  assert.ok(close(barOrigin({ bpm: 100, notes, drums: [] }), 0.11, 1e-6));
  assert.equal(barOrigin({ bpm: 100, notes, drums }), 0);
});

test("chords start on the starter beat's bars under a tune with a pickup, which is left unaccompanied", () => {
  const h = generateHarmony({ bpm: 100, notes: PICKUP_TUNE }, { key: { tonic: 0, mode: "major" } });
  const kicks = grooveHits("straight", { bpm: 100, bars: 4 }).filter(x => x.k === "kick").map(x => x.t);
  assert.deepEqual(h.chords.map(c => c.t), [2.4, 4.8, 7.2]);
  for (const c of h.chords) assert.ok(kicks.some(k => close(k, c.t, 1e-6)), `chord at ${c.t} is on a kick`);
});

test("a pickup does not move the bar lines of a free-time tune", () => {
  // On the beat from 1.37 s (off the zero grid) with a half-beat pickup at 1.07 s: the bars start at 1.37 s.
  const notes = [1.07, 1.37, 1.97, 2.57, 3.17, 3.77, 4.37, 4.97, 5.57].map((t, i) => ({ m: [65, 67, 72, 71, 72, 74, 76, 74, 72][i], t, d: 0.25 }));
  const h = generateHarmony({ bpm: 100, notes }, { key: { tonic: 0, mode: "major" } });
  // HARM.4: a bar may change chord at its half; the bars themselves start at 1.37 s and 3.77 s.
  const barOf = t => Math.round((1.37 + Math.floor((t - 1.37) / 2.4 + 1e-6) * 2.4) * 1000) / 1000;
  assert.deepEqual([...new Set(h.chords.map(c => barOf(c.t)))], [1.37, 3.77]);
  assert.ok(h.chords.every(c => Math.abs(((c.t - 1.37) / 1.2) - Math.round((c.t - 1.37) / 1.2)) < 1e-3), "every chord starts on a bar or half bar");
});

test("quantize moves the chords and the harmony voice with the melody, on one grid", () => {
  const project = {
    bpm: 100,
    notes: [{ m: 60, t: 0.03, d: 0.5 }, { m: 64, t: 0.62, d: 0.5 }, { m: 67, t: 1.17, d: 0.5 }, { m: 72, t: 1.83, d: 0.5 }],
    drums: [],
    harmony: [{ m: 48, t: 0.02, d: 2.3 }, { m: 52, t: 0.02, d: 2.3 }, { m: 55, t: 0.02, d: 2.3 }],
    voice2: [{ m: 64, t: 0.04, d: 0.5 }, { m: 67, t: 0.61, d: 0.5 }],
  };
  const out = quantizeProject(project, { division: 4, swing: 0, strength: 1 });
  assert.deepEqual(out.notes.map(n => n.t), [0, 0.6, 1.2, 1.8]);
  assert.deepEqual(out.harmony.map(n => n.t), [0, 0, 0]);
  assert.deepEqual(out.harmony.map(n => n.m).sort(), [48, 52, 55]);
  assert.deepEqual(out.voice2.map(n => n.t), [0, 0.6]);
  assert.deepEqual(project.harmony[0].t, 0.02, "the input is unchanged");
});

test("no chord starts before zero: a bar that would begin before the song starts at the next bar line", () => {
  // On the beat from 2.0 s in free time, with a note at 0.5 s off that beat: its bar would start at -0.4 s.
  const notes = [0.5, 2.0, 2.6, 3.2, 3.8, 4.4, 5.0, 5.6, 6.2].map((t, i) => ({ m: [64, 60, 62, 64, 65, 67, 65, 64, 62][i], t, d: 0.4 }));
  assert.ok(close(barOrigin({ bpm: 100, notes, drums: [] }), 2.0, 1e-6));
  const h = generateHarmony({ bpm: 100, notes }, { key: { tonic: 0, mode: "major" } });
  assert.deepEqual(h.chords.map(c => c.t), [2.0, 4.4]);
  assert.ok(h.notes.every(n => n.t >= 0));
});

test("a melody all in the second half of its bar is accompanied in that bar, not by a chord after it ends", () => {
  const notes = [1.2, 1.5, 1.8].map((t, i) => ({ m: 60 + 2 * i, t, d: 0.2 }));
  const h = generateHarmony({ bpm: 100, notes }, { key: { tonic: 0, mode: "major" } });
  assert.deepEqual(h.chords.map(c => c.t), [0]);
});

test("quantize lines up the chords and the harmony voice when they are the only parts", () => {
  const out = quantizeProject({ bpm: 100, notes: [], drums: [], harmony: [{ m: 48, t: 0.03, d: 2 }, { m: 52, t: 2.38, d: 2 }], voice2: [{ m: 64, t: 0.62, d: 0.5 }] },
    { division: 4, swing: 0, strength: 1 });
  assert.deepEqual(out.harmony.map(n => n.t), [0, 2.4]);
  assert.deepEqual(out.voice2.map(n => n.t), [0.6]);
  assert.equal(barOrigin({ bpm: 100, notes: [], drums: [], harmony: [{ m: 48, t: 1.37, d: 1 }, { m: 48, t: 3.77, d: 1 }] }), 1.37);
});

test("a melody that ends before the song's first bar line is not given a chord off the grid", () => {
  // A beat from 1.37 s at 100 bpm puts the bar line before the melody at -1.03 s; the melody ends at 0.97 s.
  const project = { bpm: 100, notes: [0.27, 0.57, 0.87].map((t, i) => ({ t, m: 60 + 2 * i, d: 0.1 })), drums: grooveHits("straight", { bpm: 100, bars: 4, from: 1.37 }) };
  assert.ok(close(barOrigin(project), 1.37, 1e-6));
  assert.throws(() => generateHarmony(project, { key: { tonic: 0, mode: "major" } }), /ends before the song's first bar line/);
});

// FIX.4: Find the speed on sung, syncopated tunes.
const CELLS = [[0, 1, 1.5, 2.5, 3], [0, 0.5, 1.5, 2, 3], [0, 1.5, 2, 3, 3.5], [0, 1, 2, 2.5, 3.5], [0.5, 1, 1.5, 2.5, 3], [0, 1.5, 3], [0, 0.5, 1, 2, 3], [0, 1.5, 2.5, 3]];
function seeded(seed) {
  let s = seed >>> 0 || 1;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
// An eight-bar tune of syncopated one-bar rhythms (offbeat starts, dotted quarters, ties over the beat)
// ending on a held note, from a random start, each onset off by a Gaussian of sd seconds as a singer is.
function syncopatedTune(bpm, seed, sd) {
  const r = seeded(seed * 7919 + bpm), beat = 60 / bpm, start = 0.2 + r() * 1.3, times = [];
  const gauss = () => { let u = 0; while (!u) u = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r()); };
  for (let bar = 0; bar < 8; bar++) {
    const cell = bar === 7 ? [0] : CELLS[Math.floor(r() * CELLS.length)];
    for (const x of cell) times.push(start + (bar * 4 + x) * beat + gauss() * sd);
  }
  return times;
}
const right = (est, bpm) => Math.abs(est - bpm) <= 2;

for (const genre of [null, "pop", "folk", "jazz", "rock", "hiphop", "electronic"]) {
  test(`FIX.4: syncopated sung tunes at 70, 84, 100 and 150 bpm read right in 36 of 40 trials (genre ${genre})`, async () => {
    const { tempoRange } = await import("../genre.js");
    for (const bpm of [70, 84, 100, 150]) {
      let ok = 0; const wrong = [];
      for (let seed = 1; seed <= 40; seed++) {
        const est = estimateTempo(syncopatedTune(bpm, seed, 0.03), { prefer: genre ? tempoRange(genre) : null, current: 100 });
        if (right(est, bpm)) ok++; else wrong.push(est);
      }
      assert.ok(ok >= 36, `${bpm} bpm: ${ok} of 40 (wrong: ${wrong.join(", ")})`);
    }
  });
}

test("FIX.4: 150 bpm under pop (80..140) is not pulled to a 3:2 or octave neighbour inside the range", async () => {
  const { tempoRange } = await import("../genre.js");
  const answers = Array.from({ length: 40 }, (_, i) => estimateTempo(syncopatedTune(150, i + 1, 0.03), { prefer: tempoRange("pop") }));
  assert.ok(answers.filter(e => right(e, 150)).length >= 36, answers.join(", "));
});

test("FIX.4: the current tempo is kept when it fits about as well, and dropped when it does not", () => {
  const tune = syncopatedTune(100, 3, 0.02);
  // Notes every 0.4 s fit 150 and 75 bpm about as well; alone 150 wins, a current 75 is kept.
  const eighths = Array.from({ length: 16 }, (_, i) => i * 0.4);
  assert.equal(estimateTempo(eighths), 150);
  assert.equal(estimateTempo(eighths, { current: 75 }), 75, "a near tie keeps the current tempo");
  assert.equal(estimateTempo(eighths, { current: 100 }), 150, "a 3:2 neighbour of the best is no tie");
  assert.ok(right(estimateTempo(tune, { current: 133 }), 100), "a 4:3 neighbour fits clearly worse");
  assert.ok(right(estimateTempo(tune, { current: 150 }), 100), "a 3:2 neighbour fits clearly worse");
});

test("FIX.4: a timed take searches only near the tempo it was sung to", () => {
  // Sung to a count-in at 100 bpm but rushed a little: kept at 100.
  for (let seed = 1; seed <= 20; seed++) assert.equal(estimateTempo(syncopatedTune(100, seed, 0.03), { current: 100, timed: true }), 100);
  // A tune at 70 sung over a 100 bpm click (ignored): the answer stays within 6% of 100, never 70 or 140.
  const est = estimateTempo(syncopatedTune(70, 1, 0.02), { current: 100, timed: true });
  assert.ok(est >= 94 && est <= 106, `estimated ${est}`);
  // Sung clearly faster than the click: the tempo near it that fits best.
  assert.equal(estimateTempo(syncopatedTune(104, 2, 0.01), { current: 100, timed: true }), 104);
  assert.throws(() => estimateTempo([0, 1, 2, 3], { timed: true }), /sung to/);
  assert.throws(() => estimateTempo([0, 1, 2, 3], { current: 300 }), /45\.\.220/);
});

test('FIX.5: a speed can be found only from four distinct onsets', () => {
  assert.equal(estimateTempo([]), null);
  assert.equal(estimateTempo([0.5, 1.1, 1.7]), null);
  assert.equal(estimateTempo([0.5, 0.505, 1.1, 1.7]), null);
  assert.notEqual(estimateTempo([0.5, 1.1, 1.7, 2.3]), null);
});

// The exports of the groove.js the tandem-v60 and tandem-v61 service workers cache. Those workers fetch network
// first, so until a client moves to the FIX.6 worker a page fetched just before the connection drops can meet
// that groove.js, and a module script fails to link on a missing export: the studio imports only these.
const V61_GROOVE_EXPORTS = ["barOrigin", "estimateTempo", "GRID_DIVISIONS", "quantizeProject", "swungOffbeat",
  "TEMPO_RANGE", "TEMPO_TIE", "TIMED_WINDOW", "ZERO_GRID_SHARE"];

test("FIX.5: every groove import of the studio links against the groove.js the v60 and v61 workers cache", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  // Whole declarations, over any number of lines; every mention of groove.js must be one of them, so a default,
  // namespace or dynamic import (whose names this cannot check) fails here too.
  const declarations = [...html.matchAll(/\bimport\s*\{([^}]*)\}\s*from\s*['"]\.\/groove\.js['"]/g)];
  const mentions = html.match(/['"]\.\/groove\.js['"]/g) ?? [];
  assert.ok(declarations.length > 0);
  assert.equal(declarations.length, mentions.length, "groove.js is loaded other than by a named import");
  for (const [, list] of declarations) {
    const names = list.split(",").map(n => n.trim().split(/\s+as\s+/)[0]).filter(Boolean);
    for (const name of names) assert.ok(V61_GROOVE_EXPORTS.includes(name), `${name} is not in the v61 groove.js`);
  }
});

// A module the studio and capture page import statically links against that groove.js too (TEMPO.1's tap.js).
test("FIX.5: tap.js imports only what the v60 and v61 workers' groove.js exports", () => {
  const src = readFileSync(new URL("../tap.js", import.meta.url), "utf8");
  const declarations = [...src.matchAll(/\bimport\s*\{([^}]*)\}\s*from\s*['"]\.\/groove\.js['"]/g)];
  const mentions = src.match(/['"]\.\/groove\.js['"]/g) ?? [];
  assert.ok(declarations.length > 0);
  assert.equal(declarations.length, mentions.length, "groove.js is loaded other than by a named import");
  for (const [, list] of declarations) {
    const names = list.split(",").map(n => n.trim().split(/\s+as\s+/)[0]).filter(Boolean);
    for (const name of names) assert.ok(V61_GROOVE_EXPORTS.includes(name), `${name} is not in the v61 groove.js`);
  }
});
