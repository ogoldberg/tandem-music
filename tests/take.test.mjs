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

// Runs the worklet's source in a stand-in AudioWorkletGlobalScope whose clock the test sets, and returns the processor
// and what it posted.
function runWorklet(rate) {
  const scope = { currentTime: 0, sampleRate: rate, Processor: null };
  scope.AudioWorkletProcessor = class { constructor() { this.port = { posted: [], postMessage: m => this.port.posted.push(m) }; } };
  scope.registerProcessor = (name, cls) => { assert.equal(name, "tandem-capture"); scope.Processor = cls; };
  new Function("scope", `with (scope) { ${CAPTURE_WORKLET} }`)(scope);
  const node = new scope.Processor();
  const block = (frame, start) => { scope.currentTime = frame / rate; return node.process([[Float32Array.from({ length: 128 }, (_, i) => start + i)]]); };
  return { scope, node, block, posted: node.port.posted };
}

test("the capture worklet posts each batch with the context time of its first frame, and splits a batch at a gap", () => {
  const rate = 1000, w = runWorklet(rate);
  // 16 blocks of 128 frames from frame 256 (0.256 s): one full batch of 2048 frames.
  for (let b = 0; b < 16; b++) w.block(256 + b * 128, 256 + b * 128);
  // Then a gap: the next block's first frame is 640 frames later than the frames held.
  w.block(2304, 2304); w.block(3072, 3072); w.block(3200, 3200);
  w.node.port.onmessage({ data: "flush" });
  const batches = w.posted.filter(m => m !== "done");
  assert.equal(w.posted.at(-1), "done");
  assert.deepEqual(batches.map(b => [b.t, b.channels[0].length, b.channels[0][0]]),
    [[0.256, 2048, 256], [2.304, 128, 2304], [3.072, 256, 3072]]);
  // Every frame of a batch is the value of its own frame number, so each frame's time is the batch's time plus its index.
  for (const b of batches) b.channels[0].forEach((x, i) => assert.equal(x, Math.round(b.t * rate) + i));
  // The collector puts each frame at its time: a take from frame 2000 to 3300 holds the gap as silence.
  const col = createTakeCollector({ zero: 2, rate });
  for (const b of batches) col.add(b.t, b.channels);
  const out = col.finish(3.3);
  assert.equal(out.frames, 1300);
  assert.equal(out.channels[0][0], 2000);
  assert.equal(out.channels[0][304], 2304);
  assert.equal(out.channels[0][500], 0);
  assert.equal(out.channels[0][1072], 3072);
  // After the flush the processor stops.
  assert.equal(w.block(3328, 3328), false);
});
