// VOX.4: the on-device WORLD tuning port. Its agreement with the server on the VOX.1 benchmark is
// checked by tests/test_vocal_benchmark.py; these are the unit checks of the port itself.
import test from "node:test";
import assert from "node:assert/strict";
import { quantizeF0, targetNotes, noteCentre, worldTune, bindWorld, FRAME_PERIOD_MS } from "../worldtune.js";
import { tuneInChunks } from "../tuning.js";
import createWorld from "../vendor/world-d625e76-1/world.mjs";

const hz = m => 440 * 2 ** ((m - 69) / 12);
const midi = f => 69 + 12 * Math.log2(f / 440);
const world = bindWorld(await createWorld());

test("quantizeF0 snaps voiced frames like numpy, halves to the even note, at most 2 semitones", () => {
  const f0 = [0, hz(60.4), hz(69.5), hz(70.5), hz(64.6), 1200];
  const { f0: out, changed } = quantizeF0(f0, { strength: 1 });
  assert.equal(out[0], 0);
  assert.ok(Math.abs(midi(out[1]) - 60) < 1e-9);
  assert.ok(Math.abs(midi(out[2]) - 70) < 1e-9, "69.5 rounds to the even 70");
  assert.ok(Math.abs(midi(out[3]) - 70) < 1e-9, "70.5 rounds to the even 70");
  assert.ok(Math.abs(midi(out[4]) - 65) < 1e-9);
  assert.equal(out[5], 1200, "above 1100 Hz is not voiced");
  assert.equal(changed, 4);
  const inScale = quantizeF0([hz(61.2)], { strength: 1, scale: [0, 2, 4, 5, 7, 9, 11] }).f0;
  assert.ok(Math.abs(midi(inScale[0]) - 62) < 1e-9, "C#+20 goes to D in C major");
  assert.deepEqual(Array.from(quantizeF0(f0, { strength: 0 }).f0), f0);
  assert.throws(() => quantizeF0(f0, { scale: [12] }), /pitch classes/);
  assert.throws(() => quantizeF0(f0, { strength: 1.5 }), /Strength/);
});

test("targetNotes moves each note's centre onto its target and keeps vibrato by its share", () => {
  const times = Array.from({ length: 100 }, (_, i) => i / 100);
  const sung = times.map(t => 60.4 + 0.25 * Math.sin(2 * Math.PI * 5 * t));
  const f0 = sung.map(hz), notes = [{ m: 62, t: 0, d: 1 }];
  const flat = targetNotes(f0, times, notes, 1, 0).f0.map(midi);
  assert.ok(flat.every(m => Math.abs(m - 62) < 1e-9), "vibrato 0 flattens onto the target");
  const kept = targetNotes(f0, times, notes, 1, 1).f0.map(midi);
  const centre = noteCentre(kept);
  assert.ok(Math.abs(centre - 62) < 1e-9);
  kept.forEach((m, i) => assert.ok(Math.abs(m - centre - (sung[i] - noteCentre(sung))) < 1e-9));
  assert.equal(targetNotes(f0, times, [{ m: 30, t: 0, d: 1 }], 1).changed, 0, "targets below MIDI 36 are skipped");
});

function tone(m, seconds, rate) {
  const x = new Float32Array(Math.round(seconds * rate));
  let phase = 0;
  for (let i = 0; i < x.length; i++) {
    phase += 2 * Math.PI * hz(m) / rate;
    for (let k = 1; k <= 6; k++) x[i] += 0.3 * 0.7 ** k / k * Math.sin(k * phase);
  }
  return x;
}

function measuredMidi(x, rate) {
  const { f0 } = world.analyze(Float64Array.from(x), rate);
  const voiced = Array.from(f0).filter(f => f > 0).slice(10, -10).map(midi).sort((a, b) => a - b);
  return voiced[voiced.length >> 1];
}

test("worldTune on the WebAssembly build corrects a sharp tone and keeps its length and level", () => {
  const rate = 22050, x = tone(57.4, 1.2, rate);
  assert.ok(Math.abs(measuredMidi(x, rate) - 57.4) < 0.05);
  const { samples, corrected } = worldTune(world, x, rate, { strength: 1 });
  assert.equal(samples.length, x.length);
  assert.ok(corrected > 50);
  assert.ok(Math.abs(measuredMidi(samples, rate) - 57) < 0.05);
  const rms = a => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / a.length);
  assert.ok(Math.abs(20 * Math.log10(rms(samples) / rms(x))) < 1);
  const toTarget = worldTune(world, x, rate, { strength: 1, notes: [{ m: 59, t: 0, d: 1.2 }] });
  assert.ok(Math.abs(measuredMidi(toTarget.samples, rate) - 59) < 0.05);
  assert.deepEqual(worldTune(world, x, rate, { strength: 0 }).samples, x);
  assert.throws(() => worldTune(world, x, 8000, { strength: 1 }), /16 kHz/);
  assert.equal(FRAME_PERIOD_MS, 10);
});

test("tuneInChunks tunes each section with the device engine, never encoding a WAV", async () => {
  const rate = 16000, x = tone(64.3, 3.5, rate), calls = [];
  const result = await tuneInChunks(x, rate, {
    strength: 1, notes: null, chunkSeconds: 2, send: () => assert.fail("no server request"),
    tune: async ({ samples, sampleRate, notes, strength }) => {
      calls.push(samples.length);
      return worldTune(world, samples, sampleRate, { strength, notes });
    },
  });
  assert.equal(calls.length, 3);
  assert.equal(result.samples.length, x.length);
  assert.ok(Math.abs(measuredMidi(result.samples, rate) - 64) < 0.05);
  await assert.rejects(tuneInChunks(x, rate, { strength: 1, chunkSeconds: 2, tune: async () => ({ samples: new Float32Array(3), corrected: 0 }) }), /came back with 3 samples/);
});
