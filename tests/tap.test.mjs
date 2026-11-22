// TEMPO.1: tap.js, the tempo from taps.
import test from "node:test";
import assert from "node:assert/strict";
import { tapTempo, createTapper, tapText, TAP_MIN, TAP_RESET } from "../tap.js";

// A small seeded generator, so the jitter is the same on every run.
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
const taps = (bpm, n, { jitter = 0, seed = 1, start = 3 } = {}) => {
  const r = rng(seed), beat = 60 / bpm;
  return Array.from({ length: n }, (_, i) => start + i * beat + (r() * 2 - 1) * jitter);
};

test("fewer than four taps give no tempo", () => {
  assert.equal(TAP_MIN, 4);
  assert.equal(tapTempo([]), null);
  assert.equal(tapTempo(taps(120, 3)), null);
  assert.equal(tapTempo(taps(120, 4)), 120);
});

test("eight taps each up to 25 ms off land within 2% of the tempo", () => {
  for (const bpm of [50, 72, 90, 100, 120, 145, 180, 210]) {
    for (let seed = 1; seed <= 40; seed++) {
      // A person taps within about 25 ms of the beat; at 210 bpm that is up to 9% of a beat.
      const got = tapTempo(taps(bpm, 8, { jitter: 0.025, seed }));
      assert.ok(Math.abs(got - bpm) <= 0.02 * bpm, `${bpm} bpm, seed ${seed}: got ${got}`);
    }
  }
});

test("more taps narrow it: twelve jittered taps at 133 read 133", () => {
  for (let seed = 1; seed <= 40; seed++) assert.equal(tapTempo(taps(133, 12, { jitter: 0.015, seed })), 133);
});

test("a missed tap counts two beats and a bounce is dropped", () => {
  const t = taps(96, 9, { jitter: 0.01, seed: 7 });
  const missed = t.filter((_, i) => i !== 4);
  assert.equal(tapTempo(missed), 96);
  const bounced = [...t.slice(0, 5), t[4] + 0.04, ...t.slice(5)];
  assert.equal(tapTempo(bounced), 96);
});

test("only the last twelve taps count, so a run that settles reads the settled speed", () => {
  const early = taps(80, 6, { start: 0 }), late = taps(120, 12, { start: early.at(-1) + 0.5 });
  assert.equal(tapTempo([...early, ...late]), 120);
});

test("a speed outside 45..220 is not a tempo", () => {
  assert.equal(tapTempo(taps(240, 8)), null);
  assert.equal(tapTempo([0, 1.5, 3, 4.5, 6]), null); // 40 bpm
  assert.throws(() => tapTempo([0, 1, NaN, 2]), /seconds/);
  assert.throws(() => tapTempo([0, 1, 0.5, 2]), /time order/);
});

test("the tapper starts a new run after a pause", () => {
  const tapper = createTapper();
  let r;
  for (const t of taps(110, 5, { start: 10 })) r = tapper.tap(t);
  assert.deepEqual(r, { count: 5, bpm: 110 });
  r = tapper.tap(10 + 4 * 60 / 110 + TAP_RESET + 0.1);
  assert.deepEqual(r, { count: 1, bpm: null });
  tapper.clear();
  assert.equal(tapper.count, 0);
});

test("the tap button says how many taps are left, then the speed", () => {
  assert.equal(tapText({ count: 1, bpm: null }), "Tap 3 more times");
  assert.equal(tapText({ count: 3, bpm: null }), "Tap 1 more time");
  assert.equal(tapText({ count: 5, bpm: 118 }), "118 beats a minute: stop tapping to keep it");
  assert.match(tapText({ count: 6, bpm: null }), /between 45 and 220/);
});
