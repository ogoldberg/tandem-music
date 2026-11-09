import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { polishSamples, butterBandpassSOS, POLISH_STYLES } from "../polish.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/polish_reference.json", import.meta.url), "utf8"));
const decode = b64 => {
  const bytes = Buffer.from(b64, "base64");
  return new Float32Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
};

test("polishSamples matches the original server polish (scipy reference) for each style and rate", () => {
  for (const c of fixture.cases) {
    const input = decode(c.input);
    for (const style of POLISH_STYLES) {
      const expected = decode(c.expected[style]);
      const out = polishSamples(input, c.sr, style);
      assert.equal(out.length, expected.length);
      let maxErr = 0;
      for (let i = 0; i < out.length; i++) maxErr = Math.max(maxErr, Math.abs(out[i] - expected[i]));
      assert.ok(maxErr < 1e-4, `${style} @ ${c.sr} Hz: max abs error ${maxErr}`);
    }
  }
});

test("butterBandpassSOS gives unity gain at band centre and blocks DC and Nyquist", () => {
  const sr = 48000, sos = butterBandpassSOS(3, 120, 6800, sr);
  assert.equal(sos.length, 3);
  const gainAt = f => {
    const w = 2 * Math.PI * f / sr;
    let re = 1, im = 0;
    for (const [b0, b1, b2, , a1, a2] of sos) {
      const nr = b0 + b1 * Math.cos(-w) + b2 * Math.cos(-2 * w), ni = b1 * Math.sin(-w) + b2 * Math.sin(-2 * w);
      const dr = 1 + a1 * Math.cos(-w) + a2 * Math.cos(-2 * w), di = a1 * Math.sin(-w) + a2 * Math.sin(-2 * w);
      const qr = (nr * dr + ni * di) / (dr * dr + di * di), qi = (ni * dr - nr * di) / (dr * dr + di * di);
      [re, im] = [re * qr - im * qi, re * qi + im * qr];
    }
    return Math.hypot(re, im);
  };
  assert.ok(Math.abs(gainAt(Math.sqrt(120 * 6800)) - 1) < 0.01);
  assert.ok(gainAt(1) < 1e-3);
  assert.ok(gainAt(sr / 2 - 1) < 1e-3);
});

test("polishSamples has no length cap: a 5-minute 48 kHz recording is processed", () => {
  const sr = 48000, n = sr * 300, x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = 0.3 * Math.sin(2 * Math.PI * 220 * i / sr);
  const out = polishSamples(x, sr, "studio");
  assert.equal(out.length, n);
  assert.ok(out.every(Number.isFinite));
});

test("polishSamples rejects an unknown style and bad input", () => {
  assert.throws(() => polishSamples(new Float32Array(10), 44100, "loud"), /style/);
  assert.throws(() => polishSamples([], 44100, "studio"), TypeError);
  assert.throws(() => polishSamples(new Float32Array(0), 44100, "studio"), /empty/);
  assert.throws(() => polishSamples(new Float32Array(10), 1000, "studio"), /sample rate/);
});

test("silence stays silent and output never exceeds full scale", () => {
  const silent = polishSamples(new Float32Array(4800), 16000, "studio");
  assert.ok(silent.every(v => Math.abs(v) < 1e-6));
  const loud = new Float32Array(16000).map((_, i) => (i % 2 ? 1 : -1));
  assert.ok(polishSamples(loud, 16000, "studio").every(v => Math.abs(v) <= 1));
});
