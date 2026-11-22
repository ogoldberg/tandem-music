// TEMPO.1: tap the speed (pure; imported by index.html, capture.html and the Node tests). Its own module because the
// tandem-v60/v61 workers' cached groove.js has a fixed set of exports (tests/groove.test.mjs FIX.5).
import { TEMPO_RANGE } from "./groove.js";

// Taps are seconds on one clock. TAP_MIN taps make a tempo; a tap more than TAP_RESET after
// the one before starts a new run. The beats between taps are counted against the median gap, so a missed tap counts
// two beats and a tap closer than half a beat to the one before (a bounce) is dropped; the tempo is the least-squares
// slope of the taps' times over their beats, from the last TAP_WINDOW taps, rounded, and null outside TEMPO_RANGE.
export const TAP_MIN = 4;
export const TAP_RESET = 2;
export const TAP_WINDOW = 12;

export function tapTempo(times) {
  if (!Array.isArray(times) || times.some(t => !Number.isFinite(t))) throw new Error("Taps are times in seconds.");
  const taps = times.slice(-TAP_WINDOW);
  if (taps.length < TAP_MIN) return null;
  const gaps = [];
  for (let i = 1; i < taps.length; i++) gaps.push(taps[i] - taps[i - 1]);
  if (gaps.some(g => g < 0)) throw new Error("Taps are in time order.");
  const sorted = gaps.filter(g => g > 0).sort((a, b) => a - b);
  if (sorted.length < TAP_MIN - 1) return null;
  const median = sorted[Math.floor(sorted.length / 2)];
  const points = [{ beat: 0, t: taps[0] }];
  for (let i = 1; i < taps.length; i++) {
    const g = taps[i] - points[points.length - 1].t, beats = Math.round(g / median);
    if (beats < 1) continue;
    points.push({ beat: points[points.length - 1].beat + beats, t: taps[i] });
  }
  if (points.length < TAP_MIN) return null;
  const n = points.length, mb = points.reduce((s, p) => s + p.beat, 0) / n, mt = points.reduce((s, p) => s + p.t, 0) / n;
  let num = 0, den = 0;
  for (const p of points) { num += (p.beat - mb) * (p.t - mt); den += (p.beat - mb) ** 2; }
  const bpm = Math.round(60 / (num / den));
  return bpm >= TEMPO_RANGE[0] && bpm <= TEMPO_RANGE[1] ? bpm : null;
}

// One run of taps: tap(t) adds a tap (seconds) and gives how many the run holds and its tempo (null below TAP_MIN taps).
export function createTapper() {
  let taps = [];
  return {
    tap(t) {
      if (!Number.isFinite(t)) throw new Error("A tap is a time in seconds.");
      if (taps.length && (t - taps[taps.length - 1] > TAP_RESET || t < taps[taps.length - 1])) taps = [];
      taps.push(t);
      return { count: taps.length, bpm: tapTempo(taps) };
    },
    clear() { taps = []; },
    get count() { return taps.length; },
  };
}

// What the tap button says after a tap.
export function tapText({ count, bpm }) {
  if (count < TAP_MIN) return "Tap " + (TAP_MIN - count) + " more time" + (TAP_MIN - count === 1 ? "" : "s");
  if (bpm === null) return "Tap steadily, between " + TEMPO_RANGE[0] + " and " + TEMPO_RANGE[1] + " beats a minute";
  return bpm + " beats a minute: stop tapping to keep it";
}
