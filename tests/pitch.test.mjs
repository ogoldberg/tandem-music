import { test } from "node:test";
import assert from "node:assert/strict";
import { yin, createPitchTracker, PITCH_WORKLET, hzToMidi, centsOff, pitchTarget, guideReading, drawPitchStrip, TRACK_RATE, WINDOW, HOP } from "../pitch.js";
import { scalePitchClasses } from "../contour.js";

const midiHz = m => 440 * 2 ** ((m - 69) / 12);
const cents = (hz, ref) => 1200 * Math.log2(hz / ref);

// A deterministic random source, so the noise is the same on every run.
function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; }; }

function tone(hz, seconds, rate, { harmonics = [1], amp = 0.3 } = {}) {
  const x = new Float32Array(Math.round(seconds * rate));
  for (let i = 0; i < x.length; i++) {
    let v = 0;
    harmonics.forEach((a, k) => { v += a * Math.sin(2 * Math.PI * hz * (k + 1) * i / rate); });
    x[i] = amp * v;
  }
  return x;
}

// Every reading of `x` through a tracker fed in 128-frame blocks, as the worklet feeds it.
function track(x, rate, t0 = 0) {
  const tr = createPitchTracker(rate), out = [];
  for (let i = 0; i < x.length; i += 128) out.push(...tr.push(x.subarray(i, i + 128), t0 + i / rate));
  return out;
}

const median = a => { const s = [...a].sort((p, q) => p - q); return s[Math.floor(s.length / 2)]; };

test("YIN finds steady tones across the singing range within 10 cents, with no octave errors", () => {
  for (const rate of [44100, 48000]) {
    for (const hz of [82.4, 110, 196, 261.6, 440, 659.3, 880]) {
      // A voice-like tone: the second harmonic stronger than the first, where a tracker most easily jumps an octave.
      const readings = track(tone(hz, 0.6, rate, { harmonics: [0.5, 1, 0.6, 0.4, 0.2] }), rate).filter(r => r.hz);
      assert.ok(readings.length >= 20, `${hz} Hz at ${rate}: ${readings.length} readings`);
      for (const r of readings) assert.ok(Math.abs(cents(r.hz, hz)) <= 10, `${hz} Hz at ${rate} read as ${r.hz.toFixed(2)} Hz`);
    }
  }
});

test("silence and noise give no pitch", () => {
  const rate = 48000;
  assert.equal(yin(new Float32Array(WINDOW), TRACK_RATE), null);
  assert.ok(track(new Float32Array(rate), rate).every(r => r.hz === null));
  // A quiet room: very low noise is below the level gate.
  const r1 = rng(1), hiss = Float32Array.from({ length: rate }, () => (r1() - 0.5) * 0.01);
  assert.ok(track(hiss, rate).every(r => r.hz === null));
  // Loud white noise has no period.
  const r2 = rng(2), noise = Float32Array.from({ length: rate }, () => (r2() - 0.5) * 0.8);
  const voiced = track(noise, rate).filter(r => r.hz !== null);
  assert.equal(voiced.length, 0, `noise read as ${voiced.map(r => r.hz.toFixed(0)).join(", ")}`);
});

// A synthetic sung phrase: C4 E4 G4 F4, each sung a known number of cents off, with 5.5 Hz vibrato of 30 cents, a
// glottal-like harmonic series, a short slide between notes and breath noise. No recorded voice is in the repository.
const PHRASE = [[60, 20], [64, -15], [67, 8], [65, -30]];
function sungPhrase(rate) {
  const noteSeconds = 0.7, x = new Float32Array(Math.round(PHRASE.length * noteSeconds * rate)), r = rng(7);
  let phase = 0;
  for (let i = 0; i < x.length; i++) {
    const t = i / rate, k = Math.min(PHRASE.length - 1, Math.floor(t / noteSeconds)), into = t - k * noteSeconds;
    const [m, off] = PHRASE[k], prev = PHRASE[Math.max(0, k - 1)];
    // The first 60 ms of each note slides from the last one.
    const from = k ? prev[0] + prev[1] / 100 : m + off / 100, to = m + off / 100, glide = Math.min(1, into / 0.06);
    const pitch = from + (to - from) * glide + 0.3 * Math.sin(2 * Math.PI * 5.5 * t);
    phase += 2 * Math.PI * midiHz(pitch) / rate;
    let v = 0;
    for (let h = 1; h <= 12; h++) v += Math.sin(h * phase) / h * (h === 2 || h === 3 ? 1.6 : 1);
    x[i] = 0.12 * v + (r() - 0.5) * 0.02;
  }
  return { x, noteSeconds };
}

test("on a sung phrase each note's pitch is read within 10 cents of how it was sung, and the cents off its note are right", () => {
  for (const rate of [44100, 48000]) {
    const { x, noteSeconds } = sungPhrase(rate), readings = track(x, rate);
    PHRASE.forEach(([m, off], k) => {
      // The steady part of the note: past the slide and the window reaching back into the last note.
      const steady = readings.filter(r => r.hz && r.t > k * noteSeconds + 0.12 && r.t < (k + 1) * noteSeconds - 0.04);
      assert.ok(steady.length >= 25, `note ${k} at ${rate}: ${steady.length} readings`);
      const sung = median(steady.map(r => hzToMidi(r.hz)));
      assert.ok(Math.abs((sung - (m + off / 100)) * 100) <= 10, `note ${k} at ${rate}: ${(sung * 100 - m * 100).toFixed(1)} cents off ${m}, sung ${off}`);
      // No reading of the note is an octave (or a fifth) away.
      for (const r of steady) assert.ok(Math.abs(hzToMidi(r.hz) - m) < 1.5, `note ${k} read at MIDI ${hzToMidi(r.hz).toFixed(2)}`);
      // The guide measures it against the note in C major and reads the cents off it.
      const reading = guideReading(midiHz(sung), { pcs: scalePitchClasses(0, "major") });
      assert.equal(reading.target, m);
      assert.ok(Math.abs(reading.cents - off) <= 10);
    });
  }
});

test("readings come at least 20 times a second, each at the middle of its window", () => {
  for (const rate of [44100, 48000]) {
    const readings = track(tone(440, 2, rate), rate, 5);
    const perSecond = (readings.length - 1) / (readings.at(-1).t - readings[0].t);
    assert.ok(perSecond >= 20, `${perSecond.toFixed(1)} readings a second at ${rate}`);
    const step = Math.round(rate / TRACK_RATE), r = rate / step;
    // The first reading comes when the window is full; its time is the window's middle.
    assert.ok(Math.abs(readings[0].t - (5 + (WINDOW * step) / rate - WINDOW / 2 / r)) < 1 / rate * step + 1e-9);
    assert.ok(Math.abs(readings[1].t - readings[0].t - HOP / r) < 1e-9);
  }
});

test("the cents off a target, and the target: the melody note sounding, else the nearest note of the key", () => {
  assert.equal(centsOff(69.25, 69), 25);
  assert.equal(centsOff(68.6, 69), -40);
  const melody = [{ m: 64, t: 1, d: 0.5 }, { m: 67, t: 1.2, d: 0.5 }];
  // A note of the melody sounds: the voice is measured against it, even far off; of two, the nearer.
  assert.equal(pitchTarget(62.4, { t: 1.1, melody, pcs: scalePitchClasses(0, "major") }), 64);
  assert.equal(pitchTarget(66.2, { t: 1.3, melody }), 67);
  // Between melody notes, the key: F♯ (66) is not in C major, so 66.4 measures against G.
  assert.equal(pitchTarget(66.4, { t: 2, melody, pcs: scalePitchClasses(0, "major") }), 67);
  assert.equal(pitchTarget(66.4, { t: 2, melody }), 66);
  assert.equal(pitchTarget(NaN), null);
  // Outside MIDI 36..96 the nearest semitone.
  assert.equal(pitchTarget(30.2), 30);
  const sharp = guideReading(440 * 2 ** (25 / 1200));
  assert.deepEqual([sharp.target, sharp.cents, sharp.text], [69, 25, "A4, 25 cents sharp"]);
  assert.equal(guideReading(440 * 2 ** (-40 / 1200)).text, "A4, 40 cents flat");
  assert.equal(guideReading(440 * 2 ** (6 / 1200)).text, "A4, in tune");
  assert.equal(guideReading(0), null);
  assert.equal(guideReading(null), null);
});

test("the worklet's source runs the same tracker and posts its readings", () => {
  const scope = { currentTime: 0, sampleRate: 48000, Processor: null };
  scope.AudioWorkletProcessor = class { constructor() { this.port = { posted: [], postMessage: m => this.port.posted.push(m) }; } };
  scope.registerProcessor = (name, cls) => { assert.equal(name, "tandem-pitch"); scope.Processor = cls; };
  new Function("scope", `with (scope) { ${PITCH_WORKLET} }`)(scope);
  const node = new scope.Processor(), x = tone(330, 0.5, 48000);
  // A one-sided stereo input: the dead channel adds nothing.
  for (let i = 0; i < x.length; i += 128) {
    scope.currentTime = i / 48000;
    assert.equal(node.process([[x.subarray(i, i + 128), new Float32Array(128)]]), true);
  }
  const readings = node.port.posted.flat();
  assert.deepEqual(readings, track(x, 48000));
  assert.ok(readings.length > 10 && readings.every(r => Math.abs(cents(r.hz, 330)) <= 10));
  node.port.onmessage({ data: "stop" });
  assert.equal(node.process([[x.subarray(0, 128)]]), false);
});

test("the strip draws the last few seconds and reads only those readings, however long the take", () => {
  // Ten minutes of readings at 60 a second, a held A4 then a held C5 in the last two seconds.
  const all = Array.from({ length: 36000 }, (_, i) => ({ t: i / 60, m: i >= 36000 - 120 ? 72 : 69 }));
  let reads = 0;
  const readings = new Proxy(all, { get(a, k) { if (typeof k === "string" && /^\d+$/.test(k)) reads++; return a[k]; } });
  const calls = [], cx = new Proxy({}, { get: (o, k) => k in o ? o[k] : (...args) => calls.push([k, ...args]), set: (o, k, v) => (o[k] = v, true) });
  const now = all.at(-1).t;
  drawPitchStrip(cx, { width: 400, height: 100, readings, now, span: 4 });
  assert.ok(reads < 3 * 4 * 60, `${reads} of ${all.length} readings read`);
  // The line is every reading of the last 4 s, from the left edge to the right edge (after the 15 grid lines).
  const inWindow = all.filter(r => r.t >= now - 4).length, line = calls.slice(calls.findLastIndex(c => c[0] === "beginPath") + 1).filter(c => c[0] === "moveTo" || c[0] === "lineTo");
  assert.equal(line.length, inWindow);
  assert.ok(Math.abs(line[0][1]) < 1e-6 && Math.abs(line.at(-1)[1] - 400) < 1e-9);
  // The held C5 at the end is drawn above the A4 before it.
  assert.ok(line.at(-1)[2] < line[0][2]);
});
