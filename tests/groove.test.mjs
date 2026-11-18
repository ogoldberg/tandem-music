import test from "node:test";
import assert from "node:assert/strict";
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

for (const bpm of [60, 70, 75, 79]) {
  test(`limit: slow quarters with an eighth every second beat read double at ${bpm} bpm`, () => {
    const b = 60 / bpm, times = [];
    for (let i = 0; i < 16; i++) { times.push(0.3 + i * b); if (i % 2) times.push(0.3 + i * b + b / 2); }
    assert.equal(estimateTempo(times), 2 * bpm);
  });
}

test("the same slow pattern reads correctly from 80 bpm", () => {
  for (const bpm of [80, 90]) {
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
  const notes = [0.04, 0.63, 1.17, 1.85].map((t, i) => ({ m: 60 + i, t, d: 0.4 }));
  const drums = grooveHits("straight", { bpm: 100, bars: 2 });
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
  assert.deepEqual(h.chords.map(c => c.t), [1.37, 3.77]);
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
