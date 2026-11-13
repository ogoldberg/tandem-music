// VOX.4: pitch correction on the device. A line-for-line port of world_tuning.py (the server's
// /api/tune) that runs the same WORLD vocoder, compiled to WebAssembly by tools/world-wasm/build.sh
// from the WORLD commit pyworld 0.3.6 is built from, with pyworld's default options. Only the
// analysis and synthesis run in WebAssembly; the F0 correction is here, so it can be read next to
// the Python. Pure functions: the compiled module is passed in, so Node tests load it from disk and
// the page loads it from /vendor/ in a worker (tuneworker.js).
import { MAX_NOTE_SHIFT, MAX_RESIDUAL } from "./contour.js";

export const FRAME_PERIOD_MS = 10;
export const WORLD_URL = "/vendor/world-d625e76-1/world.mjs";

// numpy's round: halves go to the even neighbour.
function roundHalfEven(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

const isVoiced = f => Number.isFinite(f) && f > 65 && f < 1100;
const midiOf = f => 69 + 12 * Math.log2(f / 440);
const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

function checkScale(scale) {
  if (scale == null) return;
  if (!scale.length || scale.some(n => !Number.isInteger(n) || n < 0 || n > 11)) throw Error("Scale must contain MIDI pitch classes 0..11");
}

// world_tuning.quantize_f0: move voiced F0 toward the closest allowed MIDI pitch, at most 2 semitones.
export function quantizeF0(f0, { strength = 0.85, scale = null } = {}) {
  if (!(strength >= 0 && strength <= 1)) throw Error("Strength must be between 0 and 1");
  checkScale(scale);
  const out = Float64Array.from(f0);
  if (strength === 0 || !out.some(isVoiced)) return { f0: out, changed: 0 };
  const allowed = scale == null ? null : [];
  if (allowed) for (let n = 24; n < 109; n++) if (scale.includes(n % 12)) allowed.push(n);
  let changed = 0;
  for (let i = 0; i < out.length; i++) {
    if (!isVoiced(f0[i])) continue;
    const midi = midiOf(f0[i]);
    let target;
    if (!allowed) target = roundHalfEven(midi);
    else {
      target = allowed[0];
      for (const n of allowed) if (Math.abs(midi - n) < Math.abs(midi - target)) target = n;
    }
    const correction = clip((target - midi) * strength, -2, 2);
    out[i] = f0[i] * 2 ** (correction / 12);
    if (Math.abs(correction) > 0.02) changed++;
  }
  return { f0: out, changed };
}

function median(values) {
  const s = Float64Array.from(values).sort(), h = s.length >> 1;
  return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
}

// world_tuning.note_centre: the mean of the frames within a semitone of the median.
export function noteCentre(midi) {
  const med = median(midi), near = midi.filter(m => Math.abs(m - med) < 1);
  return near.length ? near.reduce((a, b) => a + b, 0) / near.length : med;
}

// world_tuning._target_notes: each note moves by the offset between its target and its sung
// centre; each frame's deviation from that centre is scaled by (1 - vibrato).
export function targetNotes(f0, times, notes, strength, vibrato = 0) {
  if (!(vibrato >= 0 && vibrato <= 1)) throw Error("Vibrato must be between 0 and 1");
  const out = Float64Array.from(f0);
  let changed = 0;
  for (const n of notes) {
    const start = Number(n.t), end = start + Number(n.d), midi = Math.trunc(Number(n.m));
    if (midi < 36 || midi > 96 || start < 0 || !(end > start)) continue;
    const frames = [];
    for (let i = 0; i < f0.length; i++) if (times[i] >= start && times[i] < end && isVoiced(f0[i])) frames.push(i);
    if (!frames.length) continue;
    const sung = frames.map(i => midiOf(f0[i])), centre = noteCentre(sung);
    const shift = clip(midi - centre, -MAX_NOTE_SHIFT, MAX_NOTE_SHIFT);
    frames.forEach((i, k) => {
      const residual = clip((1 - vibrato) * (centre - sung[k]), -MAX_RESIDUAL, MAX_RESIDUAL);
      const correction = strength * (shift + residual);
      out[i] = f0[i] * 2 ** (correction / 12);
      if (Math.abs(correction) * 100 > 3) changed++;
    });
  }
  return { f0: out, changed };
}

// The compiled WORLD module (tools/world-wasm/tandem_world.cpp) behind two calls that copy in and
// out of its heap: analyze (DIO + StoneMask) and resynthesize (CheapTrick + D4C on the sung F0,
// then Synthesis with the corrected F0).
export function bindWorld(M) {
  const put = arr => { const p = M._malloc(arr.length * 8); M.HEAPF64.set(arr, p / 8); return p; };
  const take = (p, n) => Float64Array.from(M.HEAPF64.subarray(p / 8, p / 8 + n));
  return {
    analyze(x, fs) {
      const frames = M._tw_frames(fs, x.length, FRAME_PERIOD_MS);
      const px = put(x), pt = M._malloc(frames * 8), pf = M._malloc(frames * 8);
      try {
        M._tw_f0(px, x.length, fs, FRAME_PERIOD_MS, pt, pf);
        return { times: take(pt, frames), f0: take(pf, frames) };
      } finally { M._free(px); M._free(pt); M._free(pf); }
    },
    resynthesize(x, fs, times, f0, corrected) {
      const n = f0.length, yLength = Math.trunc(n * FRAME_PERIOD_MS * fs / 1000);
      const px = put(x), pt = put(times), pf = put(f0), pc = put(corrected), py = M._malloc(Math.max(1, yLength) * 8);
      try {
        if (M._tw_resynth(px, x.length, fs, FRAME_PERIOD_MS, pt, pf, pc, n, py, yLength) !== 0) throw Error("WORLD could not allocate memory for this section");
        return take(py, yLength);
      } finally { for (const p of [px, pt, pf, pc, py]) M._free(p); }
    },
  };
}

// world_tuning.world_tune: a length-preserving WORLD re-synthesis with the corrected F0, at the
// input's loudness. Returns { samples: Float32Array, corrected: frames changed }.
export function worldTune(world, samples, sampleRate, { strength = 0.85, notes = null, scale = null, vibrato = 0 } = {}) {
  if (!(strength >= 0 && strength <= 1)) throw Error("Invalid correction strength");
  if (!(vibrato >= 0 && vibrato <= 1)) throw Error("Vibrato must be between 0 and 1");
  if (sampleRate < 16000) throw Error("WORLD requires audio sampled at least 16 kHz");
  if (!samples.length) throw Error("Empty recording");
  const x = Float64Array.from(samples), unchanged = () => ({ samples: Float32Array.from(samples), corrected: 0 });
  if (strength === 0) return unchanged();
  const { times, f0 } = world.analyze(x, sampleRate);
  const { f0: corrected, changed } = notes?.length ? targetNotes(f0, times, notes, strength, vibrato) : quantizeF0(f0, { strength, scale });
  if (changed === 0) return unchanged();
  const synth = world.resynthesize(x, sampleRate, times, f0, corrected);
  const y = new Float64Array(x.length);
  y.set(synth.subarray(0, x.length));
  let before = 0, after = 0;
  for (let i = 0; i < x.length; i++) {
    if (!Number.isFinite(y[i])) throw Error("WORLD generated non-finite audio");
    before += x[i] * x[i]; after += y[i] * y[i];
  }
  before = Math.sqrt(before / x.length + 1e-12); after = Math.sqrt(after / x.length + 1e-12);
  const gain = after > 1e-8 ? Math.min(4, before / after) : 1, out = new Float32Array(x.length);
  for (let i = 0; i < x.length; i++) out[i] = clip(y[i] * gain, -0.98, 0.98);
  return { samples: out, corrected: changed };
}
