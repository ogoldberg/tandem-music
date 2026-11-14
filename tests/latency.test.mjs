import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CALIBRATION, MAX_LATENCY, LATENCY_KEY, calibrationClick, clickPlan, detectLatency, estimateLatency, deviceKey,
  readLatency, saveLatency, takeLatency, latencyText,
} from "../latency.js";
import { countIn, createTakeCollector, takeStart } from "../take.js";

// A seeded noise source, so every run is the same.
function noise(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 31 - 1; };
}

// The calibration as a microphone would hear it: each click played at its time comes back `delay` later through a
// small speaker (no bass, softened highs), quieter, with a room's echo after it and steady background noise.
function loopback(rate, delay, { level = 0.08, hiss = 0.003, seed = 7, drop = [] } = {}) {
  const times = clickPlan(), n = Math.round((times.at(-1) + CALIBRATION.window + 0.1) * rate), out = new Float32Array(n);
  const click = calibrationClick(rate), rnd = noise(seed);
  times.forEach((t, k) => {
    if (drop.includes(k)) return;
    const at = Math.round((t + delay) * rate);
    for (let i = 0; i < click.length && at + i < n; i++) out[at + i] += level * click[i];
    // The room: a decaying echo starting 4 ms later.
    for (let i = 0; i < rate * 0.08 && at + i < n; i++) {
      const j = at + Math.round(rate * 0.004) + i;
      if (j < n) out[j] += level * 0.25 * rnd() * Math.exp(-i / (rate * 0.02));
    }
  });
  // The speaker: a one-pole high-pass at about 300 Hz and low-pass at about 6 kHz.
  let hp = 0, lp = 0, prev = 0;
  const a = Math.exp(-2 * Math.PI * 300 / rate), b = Math.exp(-2 * Math.PI * 6000 / rate);
  for (let i = 0; i < n; i++) { hp = a * (hp + out[i] - prev); prev = out[i]; lp = (1 - b) * hp + b * lp; out[i] = lp + hiss * rnd(); }
  return { samples: out, times };
}

test("the calibration finds the round trip of a synthetic loopback within 5 ms, from wired to slow Bluetooth", () => {
  for (const rate of [44100, 48000]) {
    for (const delay of [0.006, 0.0213, 0.0874, 0.25, 0.4127, 0.65]) {
      const { samples, times } = loopback(rate, delay);
      const r = detectLatency(samples, rate, times);
      assert.ok(Math.abs(r.seconds - delay) < 0.005, `${rate} Hz, ${delay} s: found ${r.seconds}`);
      assert.equal(r.of, 6);
      assert.ok(r.heard >= 4);
    }
  }
});

test("a click lost in the room is left out, and the rest still give the round trip", () => {
  const { samples, times } = loopback(48000, 0.123, { drop: [1, 4] });
  const r = detectLatency(samples, 48000, times);
  assert.ok(Math.abs(r.seconds - 0.123) < 0.005);
  assert.equal(r.heard, 4);
});

test("no clicks heard, or clicks that disagree, is an error rather than a guess", () => {
  const rate = 48000, rnd = noise(3), silence = Float32Array.from({ length: rate * 5 }, () => 0.002 * rnd());
  assert.throws(() => detectLatency(silence, rate, clickPlan()), /did not hear the clicks/);
  assert.throws(() => detectLatency(new Float32Array(0), rate, clickPlan()), /empty/);
  // Each click at a different delay: a stray sound, not the round trip.
  const { samples, times } = loopback(rate, 0.1, { drop: [0, 1, 2, 3, 4, 5] });
  times.forEach((t, k) => { const at = Math.round((t + 0.05 + k * 0.07) * rate); samples[at] = 0.5; samples[at + 1] = -0.5; });
  assert.throws(() => detectLatency(samples, rate, times), /different delays/);
});

test("the click starts at full level and is gone in under 10 ms", () => {
  const c = calibrationClick(48000);
  assert.equal(c.length, 384);
  assert.ok(Math.max(...c.slice(0, 5).map(Math.abs)) > 0.5);
  assert.ok(Math.max(...c.slice(-20).map(Math.abs)) < 0.01);
  assert.deepEqual(clickPlan(), [0.3, 1.05, 1.8, 2.55, 3.3, 4.05]);
});

test("the estimate adds the output's, the context's and the microphone's latency, ignoring what the browser does not say", () => {
  assert.equal(estimateLatency({ outputLatency: 0.04, baseLatency: 0.0107, inputLatency: 0.012 }), 0.0627);
  assert.equal(estimateLatency({ outputLatency: undefined, baseLatency: NaN, inputLatency: -1 }), 0);
  assert.equal(estimateLatency({}), 0);
  assert.equal(estimateLatency({ outputLatency: 5 }), MAX_LATENCY);
});

function memoryStorage() {
  const m = new Map();
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m };
}

test("a measurement is kept per microphone and output; until then the take uses the estimate", () => {
  const s = memoryStorage(), speaker = deviceKey({ input: "mic1", output: "" }), bt = deviceKey({ input: "mic1", output: "Pixel Buds" });
  assert.equal(speaker, "mic1|default");
  assert.equal(deviceKey(), "default|default");
  assert.equal(readLatency(s, speaker), null);
  assert.deepEqual(takeLatency(s, speaker, { outputLatency: 0.02 }), { seconds: 0.02, measured: false });
  saveLatency(s, bt, 0.21234, 5);
  assert.deepEqual(JSON.parse(s.m.get(LATENCY_KEY)), { "mic1|Pixel Buds": { seconds: 0.2123, at: 5 } });
  assert.deepEqual(takeLatency(s, bt, { outputLatency: 0.02 }), { seconds: 0.2123, measured: true });
  assert.deepEqual(takeLatency(s, speaker, { outputLatency: 0.02 }), { seconds: 0.02, measured: false });
  assert.throws(() => saveLatency(s, bt, 2), /0 to 1/);
  assert.throws(() => saveLatency(s, bt, -0.1), /0 to 1/);
  // Unreadable or out-of-range storage reads as not measured.
  s.setItem(LATENCY_KEY, "{oops");
  assert.equal(readLatency(s, bt), null);
  s.setItem(LATENCY_KEY, JSON.stringify({ [bt]: { seconds: 7 } }));
  assert.equal(readLatency(s, bt), null);
  assert.equal(readLatency(null, bt), null);
  assert.match(latencyText({ seconds: 0.2123, measured: true }), /212 ms earlier .*measured/);
  assert.match(latencyText({ seconds: 0.02, measured: false }), /20 ms earlier .*estimated/);
});

test("a take recorded over the song is moved by the round trip: a note sung on a beat lands on that beat", () => {
  const rate = 1000, latency = 0.137, c = countIn(120, 0.5);
  assert.equal(takeStart(c.zero, latency), 2.637);
  assert.equal(takeStart(c.zero), c.zero);
  assert.throws(() => takeStart(1, -0.01), /round trip/);
  assert.throws(() => takeStart(1, NaN), /round trip/);
  // The beats of the song are heard at zero + 0.5 k; the voice singing on each arrives at the capture `latency` later.
  const frames = Math.round(8 * rate), input = new Float32Array(frames);
  const beats = [0, 0.5, 1, 1.5, 2];
  for (const s of beats) input[Math.round((c.zero + s + latency) * rate)] = 1;
  const shifted = createTakeCollector({ zero: takeStart(c.zero, latency), rate }), plain = createTakeCollector({ zero: c.zero, rate });
  for (let at = 0; at < frames; at += 128) { shifted.add(at / rate, [input.slice(at, at + 128)]); plain.add(at / rate, [input.slice(at, at + 128)]); }
  const where = take => [...take.finish(7).channels[0].keys()].filter(i => take.finish(7).channels[0][i] === 1).map(i => i / rate);
  assert.deepEqual(where(shifted), beats);
  assert.deepEqual(where(plain), beats.map(s => Math.round((s + latency) * 1000) / 1000));
});
