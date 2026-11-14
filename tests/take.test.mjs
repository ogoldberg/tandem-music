import { test } from "node:test";
import assert from "node:assert/strict";
import { countIn, clickTimes, createTakeCollector, CAPTURE_WORKLET } from "../take.js";

test("the count-in is one 4/4 bar at the tempo, ending at the take's zero", () => {
  assert.deepEqual(countIn(100, 10), { lead: 2.4, zero: 12.4, beat: 0.6, beats: 4 });
  assert.deepEqual(countIn(120, 0), { lead: 2, zero: 2, beat: 0.5, beats: 4 });
  assert.deepEqual(countIn(120, 3, { on: false }), { lead: 0, zero: 3, beat: 0.5, beats: 0 });
  for (const bpm of [0, -5, NaN, Infinity, "90"]) assert.throws(() => countIn(bpm, 0), /tempo/);
});

test("the count-in clicks fall on its beats, the first accented, and the click goes on after zero only when asked", () => {
  const c = countIn(100, 10);
  assert.deepEqual(clickTimes(c, { from: 0, to: 13.5, click: false }), [
    { t: 10, accent: true }, { t: 10.6, accent: false }, { t: 11.2, accent: false }, { t: 11.8, accent: false },
  ]);
  const withClick = clickTimes(c, { from: 0, to: 13.7, click: true });
  assert.deepEqual(withClick.slice(4).map(x => [Math.round(x.t * 1000) / 1000, x.accent]), [[12.4, true], [13, false], [13.6, false]]);
  // A window picks the clicks due in it, so a ticker can ask again without scheduling one twice.
  assert.deepEqual(clickTimes(c, { from: 10.6, to: 11.8, click: false }).map(x => x.t), [10.6, 11.2]);
  // No count-in and no click: nothing sounds.
  assert.deepEqual(clickTimes(countIn(100, 10, { on: false }), { from: 0, to: 20, click: false }), []);
  // No count-in, click on: the click starts at the take's zero, accented on each bar.
  assert.deepEqual(clickTimes(countIn(120, 1, { on: false }), { from: 0, to: 3.1, click: true }).map(x => [x.t, x.accent]),
    [[1, true], [1.5, false], [2, false], [2.5, false], [3, true]]);
});

const block = (n, start, ch = 1) => Array.from({ length: ch }, (_, c) => Float32Array.from({ length: n }, (_, i) => (start + i) * (c + 1)));

test("the collector keeps only the frames from the take's zero to the stop, sample-accurately across blocks", () => {
  const rate = 10, take = createTakeCollector({ zero: 1.25, rate });
  // Frames are numbered by their index from time 0, so frame k is at k / rate seconds.
  take.add(0, block(8, 0));     // 0.0 .. 0.7 s: all before zero
  take.add(0.8, block(8, 8));   // 0.8 .. 1.5 s: frames 13, 14, 15 are at or after 1.25 s (frame 12.5 rounds up)
  take.add(1.6, block(8, 16));  // 1.6 .. 2.3 s
  const { channels, frames } = take.finish(2.05);
  assert.equal(frames, 8);
  assert.deepEqual(Array.from(channels[0]), [13, 14, 15, 16, 17, 18, 19, 20]);
});

test("a stop during the count-in keeps nothing; blocks out of order or stereo keep their places", () => {
  const take = createTakeCollector({ zero: 5, rate: 10 });
  take.add(0, block(10, 0));
  assert.equal(take.finish(4).frames, 0);
  const st = createTakeCollector({ zero: 0, rate: 4 });
  st.add(1, block(4, 4, 2));
  st.add(0, block(4, 0, 2));
  const out = st.finish(2);
  assert.equal(out.frames, 8);
  assert.deepEqual(Array.from(out.channels[0]), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(Array.from(out.channels[1]), [0, 2, 4, 6, 8, 10, 12, 14]);
  assert.throws(() => createTakeCollector({ zero: 0, rate: 0 }), /rate/);
});

test("the capture worklet's source registers a processor that posts the context time of each batch", () => {
  assert.match(CAPTURE_WORKLET, /registerProcessor\('tandem-capture'/);
  assert.match(CAPTURE_WORKLET, /currentTime/);
  // It runs as written in an AudioWorkletGlobalScope: a quick check that it parses as script.
  assert.doesNotThrow(() => new Function("registerProcessor", "AudioWorkletProcessor", "currentTime", "sampleRate", CAPTURE_WORKLET));
});
