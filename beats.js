// Starter beats (BEAT.1): a few built-in grooves written as ordinary drum hits ({k, t}, the project's
// drum part) at the project tempo, so they play, edit, quantize and export like beatboxed drums.
// Pure, DOM-free: index.html, capture.html (REC.3: the beat it records over), bundle.js and the Node tests import it.

export const BEATS_PER_BAR = 4;
export const BAR_CHOICES = Object.freeze([4, 8, 16, 32]);
// How many bars a beat may have: at the slowest tempo (45 bpm) 64 bars is about six minutes.
export const MAX_BARS = 64;

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
  if (!(Number(bpm) > 0)) throw Error("Set a tempo before adding a beat.");
  return (BEATS_PER_BAR * 60) / Number(bpm);
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
    for (const [k, beats] of Object.entries(g.bar)) for (const x of beats) hits.push({ k, t: round6(from + b * bar + x * beat) });
  }
  return hits.sort((a, c) => a.t - c.t || ORDER[a.k] - ORDER[c.k]);
}

// The drum part after adding a beat: the beat alone (replace), or the beat with the drums already
// there (keep), where a beat hit on the same drum within 20 ms of one already there is left out.
export function withBeat(drums, hits, { keep = false } = {}) {
  if (!keep) return hits.map(h => ({ ...h }));
  const old = (drums || []).map(h => ({ ...h }));
  const fresh = hits.filter(h => !old.some(o => o.k === h.k && Math.abs(o.t - h.t) < 0.02)).map(h => ({ ...h }));
  return [...old, ...fresh].sort((a, c) => a.t - c.t || ORDER[a.k] - ORDER[c.k]);
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
