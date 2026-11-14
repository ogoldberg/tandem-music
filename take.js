// Recording the voice with a count-in and a click (REC.2). The studio (index.html) records the microphone in the
// same AudioContext that plays the click, through the capture worklet below, so every captured frame has a context
// time: the take is exactly the frames from its zero (the end of the count-in) to the stop, and the click, which is
// played to the speakers only, is never in it. This module is the timing and the trimming, so Node tests import it.

import { COUNT_IN_BEATS } from "./midi.js";

// One 4/4 bar, the MIDI keyboard's count-in (EXP.4).
export { COUNT_IN_BEATS };
export const BEATS_PER_BAR = 4;

const round6 = x => Math.round(x * 1e6) / 1e6;

// When a take starts at `start` (a context time): the count-in's length, the take's zero and the beat, all in seconds.
// With the count-in off the take's zero is `start` itself.
export function countIn(bpm, start, { on = true } = {}) {
  if (typeof bpm !== "number" || !Number.isFinite(bpm) || bpm <= 0) throw Error("The count-in needs a tempo above zero");
  const beat = 60 / bpm, beats = on ? COUNT_IN_BEATS : 0, lead = round6(beats * beat);
  return { lead, zero: round6(start + lead), beat: round6(beat), beats };
}

// The clicks due in [from, to): the count-in's beats, the first of the bar accented, and with `click` the beats from
// the take's zero on, accented on the first beat of each bar. A ticker asks for the next window each time, so no click
// is scheduled twice.
export function clickTimes({ zero, beat, beats }, { from, to, click }) {
  const out = [];
  for (let n = -beats; ; n++) {
    if (n >= 0 && !click) break;
    const t = round6(zero + n * beat);
    if (t >= to) break;
    if (t >= from) out.push({ t, accent: ((n % BEATS_PER_BAR) + BEATS_PER_BAR) % BEATS_PER_BAR === 0 });
  }
  return out;
}

// Collects the capture worklet's batches ({t: context time of the first frame, channels}) and keeps the frames at or
// after `zero` and before the stop, in time order whatever order the batches came in.
export function createTakeCollector({ zero, rate }) {
  if (typeof rate !== "number" || !(rate > 0)) throw Error("The take needs a sample rate above zero");
  const batches = [];
  return {
    add(t, channels) { if (channels?.length && channels[0].length) batches.push({ t, channels }); },
    finish(end) {
      const first = Math.ceil(round6(zero * rate)), last = Math.ceil(round6(end * rate));
      const frames = Math.max(0, last - first), count = batches.reduce((n, b) => Math.max(n, b.channels.length), 0) || 1;
      const channels = Array.from({ length: count }, () => new Float32Array(frames));
      for (const b of batches) {
        const at = Math.round(b.t * rate) - first;
        for (let c = 0; c < count; c++) {
          const src = b.channels[Math.min(c, b.channels.length - 1)];
          const from = Math.max(0, -at), to = Math.min(src.length, frames - at);
          if (to > from) channels[c].set(src.subarray(from, to), at + from);
        }
      }
      return { channels, frames, rate };
    },
  };
}

// The capture processor, loaded from a Blob URL so it needs no file of its own. It copies its input in batches of
// BATCH frames and posts each with the context time of its first frame; "flush" posts what it holds and then "done".
export const CAPTURE_WORKLET = `
const BATCH = 2048;
class TandemCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.held = null; this.t = 0; this.n = 0; this.live = true;
    this.port.onmessage = e => { if (e.data === 'flush') { this.post(); this.port.postMessage('done'); this.live = false; } };
  }
  post() {
    if (this.held && this.n) this.port.postMessage({ t: this.t, channels: this.held.map(c => c.slice(0, this.n)) });
    this.held = null; this.n = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!this.live) return false;
    if (!input || !input.length) return true;
    const len = input[0].length;
    // A batch is one run of frames without a gap: if the input skipped (the context's time moved on more than the frames
    // held), the batch so far is posted and the next starts at the time it is now, so no frame lands early.
    if (this.held && (this.n + len > BATCH || Math.abs(currentTime - this.t - this.n / sampleRate) > 0.5 / sampleRate)) this.post();
    if (!this.held) { this.held = input.map(() => new Float32Array(Math.max(BATCH, len))); this.t = currentTime; this.n = 0; }
    for (let c = 0; c < this.held.length; c++) this.held[c].set(input[Math.min(c, input.length - 1)].subarray(0, len), this.n);
    this.n += len;
    return true;
  }
}
registerProcessor('tandem-capture', TandemCapture);
`;

// Records `source` (the microphone's node) in `ac` through the capture worklet: each batch goes to `onBatch(t, channels)`.
// `flush()` resolves once the worklet has posted what it holds (or after a second). The worklet is loaded once per context.
const loaded = new WeakMap();
export async function startCapture(ac, source, onBatch) {
  if (!loaded.has(ac)) {
    loaded.set(ac, (async () => {
      const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "text/javascript" }));
      try { await ac.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    })());
  }
  try { await loaded.get(ac); } catch (e) { loaded.delete(ac); throw e; }
  const node = new AudioWorkletNode(ac, "tandem-capture");
  let done = null;
  node.port.onmessage = e => { if (e.data === "done") done?.(); else onBatch(e.data.t, e.data.channels); };
  source.connect(node); node.connect(ac.destination);
  return {
    node,
    flush() {
      return new Promise(resolve => {
        let over = false;
        const finish = () => { if (over) return; over = true; try { source.disconnect(node); } catch {} node.disconnect(); resolve(); };
        done = finish; setTimeout(finish, 1000); node.port.postMessage("flush");
      });
    },
  };
}

// Where a take's first frame is in the context: the song's zero plus the round trip, since the voice singing along
// with what is heard at the song's time s reaches the capture at zero + s + latency.
export function takeStart(zero, latency = 0) {
  if (!(Number.isFinite(latency) && latency >= 0)) throw Error("The round trip must be zero or more seconds");
  return round6(zero + latency);
}
