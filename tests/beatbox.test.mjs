// SEC.6: beatbox.js reads a beat take on the device exactly as /api/analyze?mode=rhythm does on the server.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { readBeats, findPeaks, percentile, rfftMagnitudes, uploadSamples } from "../beatbox.js";

const fixture = JSON.parse(await readFile(new URL("./fixtures/beatbox.json", import.meta.url), "utf8"));

function readWav(buf) {
  const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  let o = 12, rate = 0, data = null;
  while (o < buf.length) {
    const id = buf.toString("ascii", o, o + 4), size = v.getUint32(o + 4, true);
    if (id === "fmt ") rate = v.getUint32(o + 12, true);
    if (id === "data") data = new Float32Array(size / 2).map((_, i) => v.getInt16(o + 8 + i * 2, true) / 32768);
    o += 8 + size;
  }
  return { rate, data };
}

test("the device reads the fixture beat as the server does, hit for hit", async () => {
  const { rate, data } = readWav(await readFile(new URL("./fixtures/beatbox.wav", import.meta.url)));
  assert.equal(rate, fixture.sample_rate);
  assert.equal(fixture.drums.length, 16);
  assert.deepEqual(readBeats(data, rate), fixture.drums);
});

test("findPeaks keeps the peaks scipy.signal.find_peaks keeps", () => {
  for (const c of fixture.peak_cases)
    assert.deepEqual(findPeaks(c.x, { height: c.height, distance: c.distance, prominence: c.prominence }), c.peaks);
});

test("percentile is numpy's linear percentile", () => {
  for (const c of fixture.peak_cases) assert.ok(Math.abs(percentile(c.x, 85) - c.percentile85) < 1e-12);
});

test("rfftMagnitudes matches a plain DFT for any length", () => {
  for (const n of [64, 65, 100, 1433]) {
    const x = Float64Array.from({ length: n }, (_, i) => Math.sin(i * 0.37) + ((i * 7919) % 13) / 13 - 0.5);
    const got = rfftMagnitudes(x);
    assert.equal(got.length, Math.floor(n / 2) + 1);
    for (const k of [0, 1, Math.floor(n / 4), Math.floor(n / 2)]) {
      let re = 0, im = 0;
      for (let i = 0; i < n; i++) { re += x[i] * Math.cos(-2 * Math.PI * k * i / n); im += x[i] * Math.sin(-2 * Math.PI * k * i / n); }
      assert.ok(Math.abs(got[k] - Math.hypot(re, im)) < 1e-8, `n=${n} k=${k}`);
    }
  }
});

test("uploadSamples averages the channels and rounds them as the studio's upload does", () => {
  const out = uploadSamples([Float32Array.of(0.5, -1, 0.25), Float32Array.of(0.5, -1, -0.25)]);
  assert.deepEqual(Array.from(out), [Math.round(0.5 * 32767) / 32768, -32767 / 32768, 0]);
});

test("silence and an empty take read as no hits", () => {
  assert.deepEqual(readBeats(new Float32Array(22050), 22050), []);
  assert.deepEqual(readBeats(new Float32Array(0), 22050), []);
});
