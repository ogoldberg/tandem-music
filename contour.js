// Pitch-contour editor model (VOX.3). Pure and DOM-free so Node tests import it directly.
//
// The sung pitch line comes from Basic Pitch's contour output: per model frame, 264 salience
// bins, 3 per semitone, around A0 (MIDI 21; see CONTOUR_BIN_OFFSET). Times use the bundle's own frame-to-time
// mapping. previewCorrection mirrors world_tuning._target_notes on the server, so the editor can
// draw what /api/tune will do to each note before any audio is sent.

// Contour bin b is MIDI 21 + (b - CONTOUR_BIN_OFFSET) / 3. Measured on steady sine tones (A3..C5)
// through the vendored model in Chromium: with offset 0 every note read exactly one bin
// (33 cents) sharp; with offset 1 they read within 1 cent.
export const CONTOUR_BASE_MIDI = 21;
export const CONTOUR_BIN_OFFSET = 1;
export const BINS_PER_SEMITONE = 3;
export const CONTOUR_BINS = 88 * BINS_PER_SEMITONE;
export const VOICED_SALIENCE = 0.3;
export const MIN_MIDI = 36, MAX_MIDI = 96;
export const MIN_TARGET_SECONDS = 0.1;
// Keep in sync with world_tuning.MAX_NOTE_SHIFT_SEMITONES / MAX_RESIDUAL_SEMITONES.
export const MAX_NOTE_SHIFT = 12, MAX_RESIDUAL = 2.5;

// Basic Pitch 1.0.1 frame timing (its modelFrameToTime): 256-sample hop at 22,050 Hz, with a
// correction for the overlap between its 2 s analysis windows (172 frames each).
const SR = 22050, HOP = 256, WINDOW_FRAMES = Math.floor(SR / HOP) * 2;
const WINDOW_CORRECTION = HOP / SR * (WINDOW_FRAMES - (SR * 2 - HOP) / HOP) + 0.0018;
export const frameTime = r => r * HOP / SR - WINDOW_CORRECTION * Math.floor(r / WINDOW_FRAMES);

export const KEY_NAMES = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];
export const SCALES = Object.freeze({
  chromatic: { label: "Chromatic (any note)", steps: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] },
  major: { label: "Major", steps: [0, 2, 4, 5, 7, 9, 11] },
  minor: { label: "Natural minor", steps: [0, 2, 3, 5, 7, 8, 10] },
  "major-pentatonic": { label: "Major pentatonic", steps: [0, 2, 4, 7, 9] },
  "minor-pentatonic": { label: "Minor pentatonic", steps: [0, 3, 5, 7, 10] },
});

export function noteName(midi) {
  const names = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
  return names[((midi % 12) + 12) % 12] + (Math.floor(midi / 12) - 1);
}

// The sung pitch line: {t, m} Float32Arrays, m in fractional MIDI or NaN when unvoiced. A frame is
// voiced when its strongest bin passes VOICED_SALIENCE; its pitch is the salience-weighted mean
// of the bins around that peak, for sub-semitone precision. Frames past `duration` are dropped.
export function pitchContour(contours, { duration = Infinity, threshold = VOICED_SALIENCE } = {}) {
  const t = [], m = [];
  for (let r = 0; r < contours.length; r++) {
    const time = frameTime(r);
    if (time > duration) break;
    const bins = contours[r];
    let peak = 0;
    for (let b = 1; b < bins.length; b++) if (bins[b] > bins[peak]) peak = b;
    let midi = NaN;
    if (bins[peak] >= threshold) {
      let w = 0, sum = 0;
      for (let b = Math.max(0, peak - 2); b <= Math.min(bins.length - 1, peak + 2); b++) { w += bins[b]; sum += bins[b] * b; }
      midi = CONTOUR_BASE_MIDI + (sum / w - CONTOUR_BIN_OFFSET) / BINS_PER_SEMITONE;
    }
    t.push(time); m.push(midi);
  }
  return { t: Float64Array.from(t), m: Float32Array.from(m) };
}

// Robust centre of a set of pitches (world_tuning.note_centre): mean of values within a semitone
// of the median, which is unbiased for vibrato yet ignores octave errors and glides.
export function centreOf(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), mid = sorted.length >> 1;
  const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const near = values.filter(v => Math.abs(v - med) < 1);
  return near.length ? near.reduce((a, b) => a + b, 0) / near.length : med;
}

// First index whose time is >= x (contour times are ascending).
function lowerBound(times, x) {
  let lo = 0, hi = times.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] < x) lo = mid + 1; else hi = mid; }
  return lo;
}

function voicedIndexes(contour, note) {
  const out = [], end = note.t + note.d;
  for (let i = lowerBound(contour.t, note.t); i < contour.t.length && contour.t[i] < end; i++) {
    if (Number.isFinite(contour.m[i])) out.push(i);
  }
  return out;
}

// The sung centre of one note (fractional MIDI), or null without voiced contour frames in it.
export function noteCentre(contour, note) {
  if (!contour) return null;
  return centreOf(voicedIndexes(contour, note).map(i => contour.m[i]));
}

export function scalePitchClasses(tonic, scale) {
  if (!(Number.isInteger(tonic) && tonic >= 0 && tonic <= 11)) throw Error("The key must be a pitch class 0..11");
  const s = SCALES[scale];
  if (!s) throw Error(`Unknown scale: ${scale}`);
  return s.steps.map(x => (x + tonic) % 12).sort((a, b) => a - b);
}

const allowedPitches = pcs => {
  const out = [];
  for (let p = MIN_MIDI; p <= MAX_MIDI; p++) if (pcs.includes(p % 12)) out.push(p);
  return out;
};

// Nearest in-scale MIDI pitch to `midi` within 36..96. A tie between the scale notes either side
// goes to the one nearer `prefer` (the sung pitch), else the lower one.
export function snapToScale(midi, pcs, prefer = null) {
  let best = null;
  for (const p of allowedPitches(pcs)) {
    if (best === null) { best = p; continue; }
    const dp = Math.abs(p - midi), db = Math.abs(best - midi);
    if (dp < db || (dp === db && prefer != null && Math.abs(p - prefer) < Math.abs(best - prefer))) best = p;
  }
  return best;
}

// The next in-scale pitch above (dir > 0) or below (dir < 0) `midi`, clamped to 36..96.
export function stepInScale(midi, pcs, dir) {
  const allowed = allowedPitches(pcs);
  if (dir > 0) return allowed.find(p => p > midi) ?? allowed.at(-1);
  return allowed.findLast(p => p < midi) ?? allowed[0];
}

// Move every target onto the scale. Returns new note objects and how many changed pitch.
export function snapNotesToScale(notes, pcs, contour = null) {
  let moved = 0;
  const out = notes.map(n => {
    const m = snapToScale(n.m, pcs, noteCentre(contour, n));
    if (m !== n.m) moved++;
    return { ...n, m };
  });
  return { notes: out, moved };
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

// Predicted pitch line after /api/tune with these targets (fractional MIDI, NaN when unvoiced):
// each note moves by its target minus its sung centre (at most an octave), each frame keeps
// `vibrato` of its deviation from that centre (residual capped at 2.5 semitones), and
// `strength` scales the whole correction. Frames outside every note are left as sung; a later
// note overrides an earlier one where they overlap, as on the server.
export function previewCorrection(contour, notes, { strength = 1, vibrato = 0 } = {}) {
  const out = Float32Array.from(contour.m);
  for (const note of notes || []) {
    const idx = voicedIndexes(contour, note);
    if (!idx.length) continue;
    const centre = centreOf(idx.map(i => contour.m[i]));
    const shift = clamp(note.m - centre, -MAX_NOTE_SHIFT, MAX_NOTE_SHIFT);
    for (const i of idx) {
      const residual = clamp((1 - vibrato) * (centre - contour.m[i]), -MAX_RESIDUAL, MAX_RESIDUAL);
      out[i] = contour.m[i] + strength * (shift + residual);
    }
  }
  return out;
}

// Rows to draw: all targets and all voiced sung pitches, with two semitones of margin, in 36..96.
export function contourRange(notes, contour) {
  let lo = Infinity, hi = -Infinity;
  for (const n of notes) { lo = Math.min(lo, n.m); hi = Math.max(hi, n.m); }
  if (contour) for (const v of contour.m) if (Number.isFinite(v)) { lo = Math.min(lo, Math.floor(v)); hi = Math.max(hi, Math.ceil(v)); }
  if (!Number.isFinite(lo)) { lo = 60; hi = 72; }
  return { lo: clamp(lo - 2, MIN_MIDI, MAX_MIDI), hi: clamp(hi + 2, MIN_MIDI, MAX_MIDI) };
}

const round3 = x => Math.round(x * 1000) / 1000;

// New {t, d} for note `i` when its start or end edge is dragged to `time` (seconds). The note
// keeps MIN_TARGET_SECONDS, stays inside 0..duration and does not grow into a neighbour it did
// not already overlap.
export function resizeNote(notes, i, edge, time, duration) {
  const n = notes[i], start = n.t, end = n.t + n.d;
  if (edge === "start") {
    let lo = 0;
    for (const o of notes) if (o !== n && o.t + o.d <= start + 1e-9) lo = Math.max(lo, o.t + o.d);
    const t = round3(clamp(time, lo, end - MIN_TARGET_SECONDS));
    return { t, d: round3(end - t) };
  }
  let hi = duration;
  for (const o of notes) if (o !== n && o.t >= end - 1e-9) hi = Math.min(hi, o.t);
  const e = clamp(time, start + MIN_TARGET_SECONDS, Math.max(start + MIN_TARGET_SECONDS, hi));
  return { t: start, d: round3(e - start) };
}

// Longest stretch (seconds) without a voiced contour frame between times a and b.
function longestSilence(contour, a, b) {
  let last = a, longest = 0;
  for (let i = lowerBound(contour.t, a); i < contour.t.length && contour.t[i] <= b; i++) {
    if (!Number.isFinite(contour.m[i])) continue;
    longest = Math.max(longest, contour.t[i] - last); last = contour.t[i];
  }
  return Math.max(longest, b - last);
}

// Basic Pitch splits a note sung with vibrato or drift into several short notes a semitone apart.
// Merge each run of neighbours whose sung centres stay within `within` semitones of the run's sung
// centre so far into one target at the run's rounded sung centre, so "keep vibrato" sees the whole
// note (and a hummed melody keeps its sustained notes, TRANS.1).
// Neighbours join when the gap between them is under `gap` seconds (the detector's millisecond
// overlaps and notes contained in the run count as touching) and the sung line stays voiced
// across the join (no dropout of `gap` seconds or more), so a breath always separates notes.
// Without contour data only same-pitch neighbours merge. Confidence becomes the duration-weighted mean.
export function mergeFragments(notes, contour, { gap = 0.08, within = 0.6 } = {}) {
  const sorted = [...notes].sort((a, b) => a.t - b.t || b.d - a.d), out = [];
  const centreOfNote = n => (contour ? noteCentre(contour, n) : null) ?? n.m;
  let run = null;
  const flush = () => {
    if (!run) return;
    if (run.parts.length === 1) { out.push(run.parts[0]); run = null; return; }
    const first = run.parts[0], span = { t: first.t, d: round3(run.end - first.t) };
    const centre = contour ? noteCentre(contour, span) : null;
    const longest = run.parts.reduce((a, b) => (b.d > a.d ? b : a));
    const merged = { m: centre == null ? longest.m : clamp(Math.round(centre), MIN_MIDI, MAX_MIDI), ...span };
    if (run.parts.some(p => p.c != null)) {
      const total = run.parts.reduce((s, p) => s + p.d, 0);
      merged.c = Math.round(run.parts.reduce((s, p) => s + (p.c ?? 0) * p.d, 0) / total * 100) / 100;
    }
    out.push(merged); run = null;
  };
  for (const n of sorted) {
    const c = centreOfNote(n);
    if (run) {
      const last = run.parts.at(-1), g = n.t - run.end, contained = n.t + n.d <= run.end + 1e-9;
      const touching = g < gap && (g > -0.05 || contained);
      // A piece is about half a vibrato cycle, so its centre swings with the vibrato: compare it with
      // the sung centre of the whole run so far rather than with every other piece.
      const samePitch = contour ? Math.abs(c - (noteCentre(contour, { t: run.parts[0].t, d: run.end - run.parts[0].t }) ?? run.c)) <= within : n.m === last.m;
      // Check both pieces whole: the detector sometimes carries a note's tail across a breath.
      const voiced = !contour || longestSilence(contour, last.t, n.t + n.d) < gap;
      if (touching && samePitch && voiced) {
        run.parts.push(n); run.end = Math.max(run.end, n.t + n.d);
        continue;
      }
      flush();
    }
    run = { parts: [n], c, end: n.t + n.d };
  }
  flush();
  return out;
}
