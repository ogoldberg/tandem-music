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
  assert.deepEqual(quantizeProject({ bpm: 100, notes: [], drums: [] }, { division: 2, swing: 0, strength: 1 }), { notes: [], drums: [] });
});

test("quantizeProject rejects bad settings", () => {
  const p = { bpm: 100, notes: [{ m: 60, t: 0, d: 1 }], drums: [] };
  assert.throws(() => quantizeProject(p, { division: 3, swing: 0, strength: 1 }), /division/);
  assert.throws(() => quantizeProject({ ...p, bpm: 0 }, { division: 2, swing: 0, strength: 1 }), /tempo/);
  assert.throws(() => quantizeProject(p, { division: 2, swing: 0, strength: 0 }), /strength/);
});
