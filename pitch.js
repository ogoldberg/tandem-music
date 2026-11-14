// Live pitch guide (SING.1): the pitch of the microphone while recording, tracked on the device and drawn as a moving line
// with how many cents sharp or flat the voice is of its target note. It only shows: the recording, Transcribe and Tune are
// unchanged. The tracker (YIN on the input brought down to about 16 kHz) runs in an AudioWorklet; its source is built
// from `yin` and `createPitchTracker` below, so the Node tests run the very code the worklet runs.

import { snapToScale, noteName } from "./contour.js";

export const TRACK_RATE = 16000;   // the tracker's working sample rate (the input is averaged down to about this)
export const WINDOW = 1024;        // frames of that rate in each analysis window (64 ms at 16 kHz)
export const HOP = 256;            // frames between readings (16 ms at 16 kHz, about 60 readings a second)
export const IN_TUNE_CENTS = 10;   // within this many cents of the target the voice reads as in tune

// YIN (de Cheveigné and Kawahara 2002) on one window `x` at `rate`: {hz, clarity} for a voiced window, null for silence,
// noise or anything without a clear period. Self-contained: it is copied into the worklet's source as written.
function yin(x, rate, { threshold = 0.15, minHz = 65, maxHz = 1100, minRms = 0.01 } = {}) {
  const n = x.length, w = Math.floor(n / 2);
  let energy = 0;
  for (let i = 0; i < n; i++) energy += x[i] * x[i];
  if (Math.sqrt(energy / n) < minRms) return null;
  const maxLag = Math.min(w - 1, Math.floor(rate / minHz)), minLag = Math.max(2, Math.floor(rate / maxHz));
  const d = new Float32Array(maxLag + 2);
  for (let tau = 1; tau <= maxLag + 1; tau++) {
    let s = 0;
    for (let j = 0; j < w; j++) { const v = x[j] - x[j + tau]; s += v * v; }
    d[tau] = s;
  }
  // The cumulative mean normalized difference.
  const c = new Float32Array(maxLag + 2);
  c[0] = 1;
  let sum = 0;
  for (let tau = 1; tau <= maxLag + 1; tau++) { sum += d[tau]; c[tau] = sum > 0 ? d[tau] * tau / sum : 1; }
  let tau = -1;
  for (let t = minLag; t <= maxLag; t++) {
    if (c[t] < threshold) { while (t + 1 <= maxLag && c[t + 1] < c[t]) t++; tau = t; break; }
  }
  if (tau < 0) return null;
  // A parabola through the dip and its neighbours places the period between samples.
  const a = c[tau - 1], b = c[tau], e = c[tau + 1], den = a - 2 * b + e;
  const shift = den > 0 ? Math.max(-1, Math.min(1, (a - e) / (2 * den))) : 0;
  return { hz: rate / (tau + shift), clarity: Math.max(0, Math.min(1, 1 - b)) };
}

// A running tracker for input at `rate`: push(block, t) takes the next block of samples, whose first sample is at
// context time t, and returns the readings it completed, {t, hz, clarity} with hz null where nothing is sung. A
// reading's t is the middle of its window. Self-contained apart from `yin`, which the worklet's source holds too.
function createPitchTracker(rate, { target = 16000, size = 1024, hop = 256 } = {}) {
  const step = Math.max(1, Math.round(rate / target)), r = rate / step;
  const ring = new Float32Array(size), frame = new Float32Array(size);
  let at = 0, filled = 0, since = 0, acc = 0, accN = 0;
  return {
    rate: r,
    push(block, t) {
      const out = [];
      for (let i = 0; i < block.length; i++) {
        acc += block[i]; accN++;
        if (accN < step) continue;
        ring[at] = acc / step; at = (at + 1) % size; acc = 0; accN = 0;
        if (filled < size) filled++;
        since++;
        if (filled < size || since < hop) continue;
        since = 0;
        for (let k = 0; k < size; k++) frame[k] = ring[(at + k) % size];
        const p = yin(frame, r);
        out.push({ t: t + (i + 1) / rate - size / 2 / r, hz: p ? p.hz : null, clarity: p ? p.clarity : 0 });
      }
      return out;
    },
  };
}

export { yin, createPitchTracker };

// The worklet: the input's channels summed (a dead channel adds nothing), tracked, and each batch of readings posted.
// Its output stays silent. 'stop' ends it.
export const PITCH_WORKLET = `${yin.toString()}
${createPitchTracker.toString()}
class TandemPitch extends AudioWorkletProcessor {
  constructor() {
    super();
    this.tracker = createPitchTracker(sampleRate, { target: ${TRACK_RATE}, size: ${WINDOW}, hop: ${HOP} });
    this.mix = new Float32Array(128); this.live = true;
    this.port.onmessage = e => { if (e.data === 'stop') this.live = false; };
  }
  process(inputs) {
    if (!this.live) return false;
    const input = inputs[0];
    if (!input || !input.length) return true;
    const len = input[0].length;
    if (this.mix.length !== len) this.mix = new Float32Array(len);
    this.mix.fill(0);
    for (const ch of input) for (let i = 0; i < len; i++) this.mix[i] += ch[i];
    const out = this.tracker.push(this.mix, currentTime);
    if (out.length) this.port.postMessage(out);
    return true;
  }
}
registerProcessor('tandem-pitch', TandemPitch);
`;

export const hzToMidi = hz => 69 + 12 * Math.log2(hz / 440);

export const centsOff = (midi, target) => Math.round((midi - target) * 100);

// The note a sung pitch `midi` is measured against at song time `t`: the melody note sounding then (the nearest in pitch
// when several are), else the nearest note of the scale `pcs` (pitch classes; all twelve when none is given).
export function pitchTarget(midi, { t = null, melody = [], pcs = null } = {}) {
  if (!Number.isFinite(midi)) return null;
  if (t != null) {
    let best = null;
    for (const n of melody) if (t >= n.t && t < n.t + n.d && (best === null || Math.abs(n.m - midi) < Math.abs(best - midi))) best = n.m;
    if (best !== null) return best;
  }
  const scale = pcs && pcs.length ? pcs : [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
  // snapToScale keeps to MIDI 36..96; a voice outside that is measured against the nearest semitone.
  return midi < 35.5 || midi > 96.5 ? Math.round(midi) : snapToScale(midi, scale, midi);
}

// A reading for the guide: the target note, the cents off it and the words shown.
export function guideReading(hz, options = {}) {
  if (!(hz > 0)) return null;
  const m = hzToMidi(hz), target = pitchTarget(m, options), cents = centsOff(m, target);
  const how = Math.abs(cents) <= IN_TUNE_CENTS ? "in tune" : `${Math.abs(cents)} cents ${cents > 0 ? "sharp" : "flat"}`;
  return { m, target, cents, text: `${noteName(target)}, ${how}` };
}

// Starts the guide on `source` (a node carrying the microphone) in `ac`; every batch of readings goes to `onReadings`.
// The node's output is silent; it is connected only so the context runs it. Resolves to {stop}.
export async function startPitchGuide(ac, source, onReadings) {
  const url = URL.createObjectURL(new Blob([PITCH_WORKLET], { type: "text/javascript" }));
  try { await ac.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
  const node = new AudioWorkletNode(ac, "tandem-pitch");
  node.port.onmessage = e => onReadings(e.data);
  source.connect(node); node.connect(ac.destination);
  return {
    stop() {
      node.port.onmessage = null; node.port.postMessage("stop");
      try { source.disconnect(node); } catch {}
      node.disconnect();
    },
  };
}

// The guide's strip: the last `span` seconds of readings as a line on rows a semitone apart around the latest pitch,
// the target's row marked. `cx` is a 2D canvas context of `width` x `height` CSS pixels.
export function drawPitchStrip(cx, { width, height, readings, now, span = 4, reading = null }) {
  cx.clearRect(0, 0, width, height);
  const centre = reading ? reading.target : (readings.findLast?.(r => r.m != null)?.m ?? 60);
  const rows = 7, unit = height / (rows * 2), y = m => height / 2 - (m - centre) * unit, x = t => width - (now - t) / span * width;
  cx.lineWidth = 1;
  for (let k = -rows; k <= rows; k++) {
    cx.strokeStyle = k === 0 && reading ? "rgba(245,178,74,.7)" : "rgba(255,255,255,.08)";
    cx.beginPath(); cx.moveTo(0, y(centre + k)); cx.lineTo(width, y(centre + k)); cx.stroke();
  }
  cx.strokeStyle = "#7fd3b4"; cx.lineWidth = 3; cx.lineJoin = "round";
  // Only the readings inside the strip are read, from the newest back, so a long take costs no more to draw.
  let first = readings.length;
  while (first > 0 && readings[first - 1].t >= now - span) first--;
  let open = false;
  cx.beginPath();
  for (let i = first; i < readings.length; i++) {
    const r = readings[i];
    if (r.m == null) { open = false; continue; }
    if (open) cx.lineTo(x(r.t), y(r.m)); else { cx.moveTo(x(r.t), y(r.m)); open = true; }
  }
  cx.stroke();
}
