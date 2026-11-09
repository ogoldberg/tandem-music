import test from "node:test";
import assert from "node:assert/strict";
import { planChunks, notesForChunk, stitchChunks, chooseSeams, encodeWav16, decodeWav16, tuneInChunks, CHUNK_SECONDS, OVERLAP_SECONDS, SEAM_SECONDS, SEAM_MARGIN_SECONDS } from "../tuning.js";

const sine = (n, sr, hz = 220, amp = 0.5) => Float32Array.from({ length: n }, (_, i) => amp * Math.sin(2 * Math.PI * hz * i / sr));
const maxJump = x => { let m = 0; for (let i = 1; i < x.length; i++) m = Math.max(m, Math.abs(x[i] - x[i - 1])); return m; };

test("planChunks covers the recording with fixed overlaps and chunks within the per-request cap", () => {
  const sr = 48000;
  for (const seconds of [3, 16, 16.5, 31, 95, 300]) {
    const total = Math.round(seconds * sr), plan = planChunks(total, sr);
    assert.equal(plan[0].start, 0);
    assert.equal(plan.at(-1).end, total);
    for (const c of plan) {
      assert.ok(c.end - c.start <= CHUNK_SECONDS * sr, `${seconds}s: chunk longer than ${CHUNK_SECONDS}s`);
      assert.ok(c.end - c.start > OVERLAP_SECONDS * sr || plan.length === 1);
      // 16-bit mono at this rate stays under Vercel's 4.5 MB request body limit.
      assert.ok(44 + (c.end - c.start) * 2 < 4.5e6);
    }
    for (let k = 1; k < plan.length; k++) assert.equal(plan[k - 1].end - plan[k].start, OVERLAP_SECONDS * sr, "overlap");
  }
  assert.equal(planChunks(10 * sr, sr).length, 1);
  assert.equal(planChunks(95 * sr, sr).length, 7);
});

test("notesForChunk offsets note targets to the chunk start and clips them to its edges", () => {
  const notes = [{ m: 60, t: 2, d: 1 }, { m: 62, t: 14.5, d: 2 }, { m: 64, t: 20, d: 1 }, { m: 65, t: 31.98, d: 0.5 }];
  // Chunk 2 of a 48 kHz plan spans 15 s to 31 s.
  assert.deepEqual(notesForChunk(notes, 15, 31), [{ m: 62, t: 0, d: 1.5 }, { m: 64, t: 5, d: 1 }]);
  assert.deepEqual(notesForChunk(notes, 0, 16), [{ m: 60, t: 2, d: 1 }, { m: 62, t: 14.5, d: 1.5 }]);
  // A sliver under 50 ms at a chunk edge is dropped instead of being rejected by the server.
  assert.deepEqual(notesForChunk(notes, 30, 32), []);
  assert.deepEqual(notesForChunk([], 0, 16), []);
  assert.throws(() => notesForChunk(Array.from({ length: 129 }, (_, i) => ({ m: 60, t: i * 0.1, d: 0.06 })), 0, 16), /Too many note targets/);
});

test("stitching unmodified chunks reproduces the recording exactly", () => {
  const sr = 22050, x = sine(Math.round(40.3 * sr), sr), plan = planChunks(x.length, sr);
  assert.ok(plan.length > 2);
  const y = stitchChunks(plan.map(c => x.slice(c.start, c.end)), plan, x.length);
  let err = 0;
  for (let i = 0; i < x.length; i++) err = Math.max(err, Math.abs(x[i] - y[i]));
  assert.ok(err < 1e-6, `max error ${err}`);
});

test("crossfades hide level differences between chunks: no clicks and no gaps at boundaries", () => {
  // A DC offset makes every boundary a step when butt-joined, whatever the sine's phase there.
  const sr = 22050, x = sine(Math.round(40 * sr), sr, 220, 0.4).map(v => v + 0.3), plan = planChunks(x.length, sr);
  // Each chunk comes back at a different level, as the server's per-chunk RMS matching can do.
  const gains = plan.map((_, k) => (k % 2 ? 0.8 : 1.2));
  const outputs = plan.map((c, k) => x.slice(c.start, c.end).map(v => v * gains[k]));
  const stitched = stitchChunks(outputs, plan, x.length);
  const naive = new Float32Array(x.length);
  plan.forEach((c, k) => naive.set(outputs[k].subarray(0, (plan[k + 1]?.start ?? c.end) - c.start), c.start));
  const smooth = maxJump(x) * Math.max(...gains) * 1.05;
  assert.ok(maxJump(stitched) <= smooth, `stitched jump ${maxJump(stitched)} > ${smooth}`);
  assert.ok(maxJump(naive) > smooth, "the test signal must click when butt-joined, or it proves nothing");
  // No gaps: the envelope never drops near zero across a boundary.
  for (let k = 1; k < plan.length; k++) {
    const seg = stitched.subarray(plan[k].start, plan[k - 1].end), period = Math.round(sr / 220);
    let minPeak = Infinity;
    for (let i = 0; i + period <= seg.length; i += period) {
      let p = 0; for (let j = i; j < i + period; j++) p = Math.max(p, Math.abs(seg[j]));
      minPeak = Math.min(minPeak, p);
    }
    assert.ok(minPeak > 0.5, `boundary ${k}: level dropped to ${minPeak}`);
  }
});

test("encodeWav16 and decodeWav16 round-trip at the original rate", () => {
  const sr = 44100, x = sine(1000, sr);
  const { sampleRate, samples } = decodeWav16(encodeWav16(x, sr));
  assert.equal(sampleRate, sr);
  assert.equal(samples.length, x.length);
  for (let i = 0; i < x.length; i++) assert.ok(Math.abs(samples[i] - x[i]) < 1e-4);
  assert.throws(() => decodeWav16(new ArrayBuffer(8)), /not a WAV/);
});

test("tuneInChunks sends each chunk with offset notes, retries rate limits and stitches the result", async () => {
  const sr = 16000, x = sine(Math.round(95 * sr), sr), sent = [], waits = [];
  let limited = false;
  const send = async ({ wav, notes, strength }) => {
    if (sent.length === 3 && !limited) { limited = true; throw Object.assign(Error("HTTP 429"), { retryAfter: 7 }); }
    const { sampleRate, samples } = decodeWav16(wav);
    sent.push({ sampleRate, length: samples.length, notes, strength });
    return { wav: encodeWav16(samples, sampleRate), corrected: 10 };
  };
  const notes = [{ m: 60, t: 20, d: 2 }, { m: 67, t: 93, d: 1.5 }];
  const res = await tuneInChunks(x, sr, { strength: 0.85, notes, send, sleep: async ms => waits.push(ms) });
  assert.equal(res.chunks, 7);
  assert.equal(sent.length, 7);
  assert.deepEqual(waits, [7000]);
  assert.equal(res.corrected, 70);
  assert.ok(sent.every(s => s.sampleRate === sr && s.strength === 0.85 && s.length <= 16 * sr));
  assert.deepEqual(sent[1].notes, [{ m: 60, t: 5, d: 2 }]);
  assert.deepEqual(sent[6].notes, [{ m: 67, t: 3, d: 1.5 }]);
  assert.equal(res.samples.length, x.length);
  let err = 0;
  for (let i = 0; i < x.length; i++) err = Math.max(err, Math.abs(res.samples[i] - x[i]));
  assert.ok(err < 1e-3, `max error ${err}`);
});

test("tuneInChunks gives up after repeated rate limits and does not retry other errors", async () => {
  const sr = 16000, x = sine(20 * sr, sr);
  let calls = 0;
  await assert.rejects(tuneInChunks(x, sr, { strength: 1, send: async () => { calls++; throw Object.assign(Error("HTTP 429"), { retryAfter: 1 }); }, sleep: async () => {}, maxRetries: 2 }), /429/);
  assert.equal(calls, 3);
  calls = 0;
  await assert.rejects(tuneInChunks(x, sr, { strength: 1, send: async () => { calls++; throw Error("HTTP 400: bad"); }, sleep: async () => {} }), /400/);
  assert.equal(calls, 1);
});

test("chooseSeams puts each short seam at the quietest point inside the overlap, away from its edges", () => {
  const sr = 16000, x = sine(40 * sr, sr), plan = planChunks(x.length, sr);
  // A 60 ms breath inside the first overlap; nothing quiet in the others.
  const breath = plan[1].start + Math.round(0.6 * sr);
  x.fill(0, breath, breath + Math.round(0.06 * sr));
  const seams = chooseSeams(x, plan, sr);
  assert.equal(seams.length, plan.length - 1);
  for (let k = 1; k < plan.length; k++) {
    const { at, length } = seams[k - 1];
    assert.equal(length, Math.round(SEAM_SECONDS * sr));
    assert.ok(at >= plan[k].start + SEAM_MARGIN_SECONDS * sr && at + length <= plan[k - 1].end - SEAM_MARGIN_SECONDS * sr, `seam ${k} outside the overlap's middle`);
  }
  assert.ok(seams[0].at >= breath && seams[0].at + seams[0].length <= breath + Math.round(0.06 * sr), "first seam should sit in the breath");
});

test("stitching at seams reproduces the recording exactly and keeps out-of-phase chunks from dipping for long", () => {
  const sr = 16000, x = sine(40 * sr, sr), plan = planChunks(x.length, sr), seams = chooseSeams(x, plan, sr);
  const same = stitchChunks(plan.map(c => x.slice(c.start, c.end)), plan, x.length, seams);
  let err = 0;
  for (let i = 0; i < x.length; i++) err = Math.max(err, Math.abs(x[i] - same[i]));
  assert.ok(err < 1e-6, `max error ${err}`);
  // WORLD restarts each chunk at its own phase: model that as the same tone shifted in phase per chunk.
  const outputs = plan.map((c, k) => Float32Array.from({ length: c.end - c.start }, (_, i) => 0.5 * Math.sin(2 * Math.PI * 220 * (c.start + i) / sr + k * 2.5)));
  const rmsDipSeconds = y => {
    const win = Math.round(0.01 * sr); let low = 0;
    for (let i = 0; i + win <= y.length; i += win) { let e = 0; for (let j = i; j < i + win; j++) e += y[j] * y[j]; if (Math.sqrt(e / win) < 0.5 / Math.SQRT2 * 0.7) low++; }
    return low * 0.01;
  };
  const shortSeams = rmsDipSeconds(stitchChunks(outputs, plan, x.length, seams));
  const wholeOverlap = rmsDipSeconds(stitchChunks(outputs, plan, x.length));
  assert.ok(wholeOverlap > 1, `the whole-overlap crossfade should dip for a long time here, got ${wholeOverlap} s`);
  assert.ok(shortSeams <= (plan.length - 1) * (SEAM_SECONDS + 0.02), `short seams dipped for ${shortSeams} s in total`);
});
