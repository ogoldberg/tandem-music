// Starter beats (BEAT.1): a few built-in grooves written as ordinary drum hits ({k, t}, the project's
// drum part) at the project tempo, so they play, edit, quantize and export like beatboxed drums.
// Pure, DOM-free: index.html, capture.html (REC.3: the beat it records over), bundle.js and the Node tests import it.

import { BEATS_PER_BAR, barSeconds as bars } from "./bars.js";

// GROW.1: bars.js owns the bar.
export { BEATS_PER_BAR };
export const BAR_CHOICES = Object.freeze([4, 8, 16, 32]);
// GROW.2: how many bars a beat may have, room for a whole song: 256 bars is 4:39 at the fastest 220 bpm and
// past the project's 10 minutes below about 103 bpm, where hits after 600 s are left out (MAX_TIME).
export const MAX_BARS = 256;
export const MAX_TIME = 600;
// The most hits the drums hold, the same as every part (sections.js MAX_EVENTS; tests/longsong.test.mjs checks).
export const MAX_HITS = 4096;

// Each groove is one bar of 4/4: the beat (0 up to 4) each drum is hit on.
const eighths = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5];
export const GROOVES = Object.freeze([
  {
    id: "straight", name: "Straight", about: "Rock and pop: kick on 1 and 3, snare on 2 and 4, hi-hat in eighths",
    bar: { kick: [0, 2], snare: [1, 3], hat: eighths },
  },
  {
    id: "halftime", name: "Half-time", about: "Slow and heavy: the snare only on 3, hi-hat in eighths",
    bar: { kick: [0, 2.5], snare: [2], hat: eighths },
  },
  {
    id: "shuffle", name: "Shuffle", about: "Swung: the hi-hat on the first and last of each beat's triplet",
    bar: { kick: [0, 2], snare: [1, 3], hat: [0, 2 / 3, 1, 5 / 3, 2, 8 / 3, 3, 11 / 3] },
  },
  {
    id: "four", name: "Four on the floor", about: "Dance: a kick on every beat, snare on 2 and 4, hi-hat between the beats",
    bar: { kick: [0, 1, 2, 3], snare: [1, 3], hat: [0.5, 1.5, 2.5, 3.5] },
  },
].map(g => Object.freeze({ ...g, bar: Object.freeze(g.bar) })));

const ORDER = { kick: 0, snare: 1, hat: 2 };
const round6 = x => Math.round(x * 1e6) / 1e6;

export function grooveById(id) {
  const g = GROOVES.find(x => x.id === id);
  if (!g) throw Error(`There is no starter beat called ${id}.`);
  return g;
}

export function barSeconds(bpm) {
  return bars(bpm, "Set a tempo before adding a beat.");
}

// Enough whole bars to cover `seconds` of song, at least `min`.
export function barsToCover(seconds, bpm, min = 4) {
  const n = Math.ceil(Math.max(0, Number(seconds) || 0) / barSeconds(bpm) - 1e-9);
  return Math.min(MAX_BARS, Math.max(min, n));
}

// The groove's hits for `bars` bars at `bpm`, from `from` seconds, in time order (kick, snare, hi-hat
// when they fall together).
export function grooveHits(id, { bpm, bars, from = 0 }) {
  const g = grooveById(id), bar = barSeconds(bpm), beat = bar / BEATS_PER_BAR;
  if (!(Number.isInteger(bars) && bars >= 1 && bars <= MAX_BARS)) throw Error(`A beat is 1 to ${MAX_BARS} bars long.`);
  const hits = [];
  for (let b = 0; b < bars; b++) {
    for (const [k, beats] of Object.entries(g.bar)) for (const x of beats) {
      const t = round6(from + b * bar + x * beat);
      if (t <= MAX_TIME) hits.push({ k, t });
    }
  }
  return hits.sort((a, c) => a.t - c.t || ORDER[a.k] - ORDER[c.k]);
}

// The drum part after adding a beat: the beat alone (replace), or the beat with the drums already
// there (keep), where a beat hit on the same drum within 20 ms of one already there is left out.
export function withBeat(drums, hits, { keep = false } = {}) {
  let out = hits.map(h => ({ ...h }));
  if (keep) {
    const old = (drums || []).map(h => ({ ...h }));
    const fresh = out.filter(h => !old.some(o => o.k === h.k && Math.abs(o.t - h.t) < 0.02));
    out = [...old, ...fresh].sort((a, c) => a.t - c.t || ORDER[a.k] - ORDER[c.k]);
  }
  // GROW.2: the drums hold at most as many hits as any part (sections.js MAX_EVENTS).
  if (out.length > MAX_HITS) throw new Error(`The drums would have more than ${MAX_HITS} hits.`);
  return out;
}

// The groove's hits due in [from, to) when its first bar starts at `zero` and it repeats until stopped (the capture
// page's beat, REC.3), each at its time (`zero` plus its place in the song). A ticker asks for the next window each time.
export function grooveWindow(id, { bpm, zero, from, to }) {
  const g = grooveById(id), bar = barSeconds(bpm), beat = bar / BEATS_PER_BAR, out = [];
  for (let b = Math.max(0, Math.floor((from - zero) / bar)); zero + b * bar < to; b++) {
    for (const [k, beats] of Object.entries(g.bar)) {
      for (const x of beats) { const s = round6(b * bar + x * beat), t = round6(zero + s); if (t >= from && t < to) out.push({ k, t, s }); }
    }
  }
  return out.sort((a, c) => a.t - c.t || ORDER[a.k] - ORDER[c.k]);
}

// The tempo range of a project (the backend's ChatProject accepts 45 to 220 bpm).
export const MIN_BPM = 45, MAX_BPM = 220;

// The beat an idea was recorded over ({id, bpm}), or null when there was none or it is not one this version knows.
export function cleanBeat(beat) {
  if (!beat || typeof beat !== "object" || !GROOVES.some(g => g.id === beat.id)) return null;
  const bpm = Number(beat.bpm);
  return Number.isFinite(bpm) && bpm >= MIN_BPM && bpm <= MAX_BPM ? { id: beat.id, bpm } : null;
}

// BEAT.2: drum fills. A fill is half a bar of kick, snare and hi-hat (the beat, 0 up to 2, each drum is hit on in
// that half bar) that replaces the last half bar of the beat before a section starts or ends, or every four bars
// from the bar grid's origin when there are no sections, wherever the drums play on both sides of that line.
export const FILL_BARS = 4;
const sixteenths = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75];
export const FILLS = Object.freeze([
  { id: "build", name: "Build", about: "Pop: the snare picks up into the next bar over two kicks", half: { kick: [0, 1], snare: [0.5, 1, 1.5, 1.75], hat: [0] } },
  { id: "roll", name: "Snare roll", about: "Rock: a kick, then the snare on every sixteenth", half: { kick: [0], snare: sixteenths } },
  { id: "light", name: "Light", about: "Folk: a few soft snare notes and the hi-hat", half: { kick: [0], snare: [1, 1.5, 1.75], hat: [0.5] } },
  { id: "triplet", name: "Triplet", about: "Jazz: the snare in triplets after a kick", half: { kick: [0], snare: [1 / 3, 2 / 3, 1, 4 / 3, 5 / 3], hat: [0] } },
  { id: "break", name: "Break", about: "Hip-hop: a syncopated kick and snare, the hi-hat at the end", half: { kick: [0, 0.75], snare: [0.5, 1.25, 1.5], hat: [1.75] } },
  { id: "riser", name: "Riser", about: "Electronic: kicks on the eighths under a snare that speeds up", half: { kick: [0, 0.5, 1, 1.5], snare: [1, 1.25, 1.5, 1.75] } },
].map(f => Object.freeze({ ...f, half: Object.freeze(f.half) })));

export function fillById(id) {
  const f = FILLS.find(x => x.id === id);
  if (!f) throw Error(`There is no drum fill called ${id}.`);
  return f;
}

// The lines a fill leads into, in time order: each section's start and end (else every FILL_BARS bars from
// `origin`), each at least half a bar into the song, a line within half a bar of the one before left out.
export function fillLines({ bpm, origin = 0, sections = [], end }) {
  const bar = barSeconds(bpm), half = bar / 2, lines = [];
  if (sections.length) for (const s of sections) lines.push(s.from, s.to);
  else for (let t = origin + FILL_BARS * bar; t <= end + 1e-9; t += FILL_BARS * bar) lines.push(t);
  const out = [];
  for (const t of [...new Set(lines.map(round6))].sort((a, c) => a - c)) {
    if (t - half < -1e-9 || t > MAX_TIME) continue;
    if (out.length && t - out[out.length - 1] < half - 1e-9) continue;
    out.push(t);
  }
  return out;
}

// The drum part with the fill before each line where the drums play in the half bar before it and in the half
// bar after it (a fill leads from the beat into more of it, never out of silence or into it); `lines` says
// where they went. Fills replace whatever was in their half bar, so adding them again gives the same drums.
export function withFills(drums, id, { bpm, origin = 0, sections = [] }) {
  const f = fillById(id), bar = barSeconds(bpm), half = bar / 2, beat = bar / BEATS_PER_BAR;
  const old = (drums || []).map(h => ({ ...h }));
  if (!old.length) throw Error("Add a beat first: a fill replaces the end of a bar of drums.");
  const end = Math.max(...old.map(h => h.t));
  const lines = fillLines({ bpm, origin, sections, end }).filter(t =>
    old.some(h => h.t >= t - half - 1e-9 && h.t < t - 1e-9) && old.some(h => h.t >= t - 1e-9 && h.t < t + half - 1e-9));
  let out = old.filter(h => !lines.some(t => h.t >= t - half - 1e-9 && h.t < t - 1e-9));
  for (const t of lines) for (const [k, beats] of Object.entries(f.half)) for (const x of beats) {
    const at = round6(t - half + x * beat);
    if (at >= 0 && at <= MAX_TIME) out.push({ k, t: at });
  }
  out.sort((a, c) => a.t - c.t || ORDER[a.k] - ORDER[c.k]);
  if (out.length > MAX_HITS) throw new Error(`The drums would have more than ${MAX_HITS} hits.`);
  return { drums: out, lines };
}
