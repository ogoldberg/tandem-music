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
// TRANS.2 options for the hummed melody: `lowest` (MIDI) ignores the bins below it, where room
// noise peaks when nothing is sung, and `subharmonics` takes the bin an octave, or an octave and
// a fifth, below the peak when that bin holds SUBHARMONIC_SHARE of the peak's salience (a soft low
// hum can read loudest at its 2nd or 3rd harmonic).
export const SUBHARMONIC_SHARE = 0.75;
const SUBHARMONIC_BINS = [12 * BINS_PER_SEMITONE, 19 * BINS_PER_SEMITONE];
export function pitchContour(contours, { duration = Infinity, threshold = VOICED_SALIENCE, lowest = null, subharmonics = false } = {}) {
  const t = [], m = [];
  const first = lowest == null ? 0 : Math.max(0, Math.round((lowest - 0.5 - CONTOUR_BASE_MIDI) * BINS_PER_SEMITONE + CONTOUR_BIN_OFFSET));
  for (let r = 0; r < contours.length; r++) {
    const time = frameTime(r);
    if (time > duration) break;
    const bins = contours[r];
    let peak = first;
    for (let b = first + 1; b < bins.length; b++) if (bins[b] > bins[peak]) peak = b;
    let midi = NaN;
    if (bins[peak] >= threshold) {
      if (subharmonics) {
        for (const below of SUBHARMONIC_BINS) {
          let best = -1;
          for (let b = Math.max(first, peak - below - 2); b <= peak - below + 2; b++) if (best < 0 || bins[b] > bins[best]) best = b;
          if (best >= 0 && bins[best] >= SUBHARMONIC_SHARE * bins[peak]) { peak = best; break; }
        }
      }
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

const median = values => {
  const s = [...values].sort((a, b) => a - b), k = s.length >> 1;
  return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2;
};

// TRANS.2: a hummed melody as notes, built from the sung pitch line rather than from Basic Pitch's
// note events, so a note lasts as long as its pitch is held, a new note starts where the pitch steps
// to another, and a slide joins the note it settles on. `line` is pitchContour's {t, m};
// `activation(frame, midi)` is the model's note activation (0..1) at that frame and pitch.
//  1. Voiced runs of at least `minRun` s, joined across dropouts shorter than `gap` s into stretches.
//     A stretch also ends at `gap` s or more of note activation under `minAct`: breath noise can read
//     at the sung pitch, and only the activation shows nothing is sung there.
//  2. Each stretch's pitch, median-smoothed over `smooth` frames each side (about one vibrato cycle).
//  3. A piece ends where the smoothed pitch stays `step` semitones from the piece's centre (the
//     median of its last `span` s) for `hold` s.
//  4. A piece whose note activation averages under `minAct` is not sung (fan noise in a breath) and
//     breaks the stretch. A piece shorter than `minNote` s, or one whose pitch keeps moving (`slide`
//     semitones or more between its first and last thirds, at `rate` semitones per second or faster),
//     is a slide: it joins the note after it, or the note before it at the end of a stretch.
//  5. Each remaining piece is a note at its rounded median pitch; touching notes of one pitch join.
export const SUNG_NOTE_OPTIONS = Object.freeze({
  gap: 0.15, minRun: 0.05, smooth: 7, step: 0.7, span: 0.5, hold: 0.05, minAct: 0.25, minNote: 0.1, slide: 0.35, rate: 3,
});
export function sungNotes(line, activation, options = {}) {
  const { gap, minRun, smooth, step, span, hold, minAct, minNote, slide, rate } = { ...SUNG_NOTE_OPTIONS, ...options };
  const { t } = line, n = t.length;
  if (n < 2) return [];
  const dt = (t[n - 1] - t[0]) / (n - 1);
  const m = Array.from(line.m, v => (Number.isFinite(v) && v >= MIN_MIDI - 0.5 && v <= MAX_MIDI + 0.5 ? v : NaN));
  const stretches = [];
  for (let i = 0; i < n;) {
    if (!Number.isFinite(m[i])) { i++; continue; }
    let j = i;
    while (j < n && Number.isFinite(m[j])) j++;
    if ((j - i) * dt >= minRun) {
      const last = stretches.at(-1);
      if (last && (i - last.at(-1)[1]) * dt < gap) last.push([i, j]); else stretches.push([[i, j]]);
    }
    i = j;
  }
  const notes = [], holdFrames = Math.max(1, Math.round(hold / dt)), spanFrames = Math.max(1, Math.round(span / dt));
  const breathFrames = Math.max(1, Math.round(gap / dt));
  const parts = [];
  for (const runs of stretches) {
    const all = runs.flatMap(([a, b]) => Array.from({ length: b - a }, (_, k) => a + k));
    const smoothed = all.map((_, k) => median(all.slice(Math.max(0, k - smooth), k + smooth + 1).map(i => m[i])));
    const acts = all.map((i, k) => activation(i, Math.round(smoothed[k])));
    // Noise in a breath can read at the sung pitch: `gap` s or more without note activation ends the stretch.
    let from = 0;
    for (let k = 0; k <= all.length; k++) {
      if (k < all.length && acts[k] < minAct) continue;
      let quiet = k;
      while (quiet > from && acts[quiet - 1] < minAct) quiet--;
      const breath = k - quiet >= breathFrames;
      if (breath || k === all.length) {
        const end = breath ? quiet : k;
        if (end > from) parts.push([all.slice(from, end), smoothed.slice(from, end), acts.slice(from, end)]);
        from = k;
      }
    }
  }
  for (const [idx, s, acts] of parts) {
    const pieces = [];
    let start = 0;
    for (let k = 1; k + holdFrames <= idx.length; k++) {
      const centre = median(s.slice(Math.max(start, k - spanFrames), k));
      let away = true;
      for (let q = k; away && q < k + holdFrames; q++) if (Math.abs(s[q] - centre) <= step) away = false;
      if (away) { pieces.push([start, k]); start = k; }
    }
    pieces.push([start, idx.length]);
    const from = k => t[idx[k]], to = k => t[idx[k - 1]] + dt;
    let slideFrom = null, prev = null;
    const extend = (note, end) => { note.d = round3(to(end) - note.t); };
    const settle = () => { if (slideFrom && prev && prev.end === slideFrom.a) { extend(prev.note, slideFrom.b); prev.end = slideFrom.b; } slideFrom = null; };
    for (const [a, b] of pieces) {
      const part = s.slice(a, b), third = Math.max(1, Math.floor(part.length / 3));
      let act = 0;
      for (let k = a; k < b; k++) act += acts[k];
      if (act / (b - a) < minAct) { settle(); prev = null; continue; }
      const change = Math.abs(median(part.slice(0, third)) - median(part.slice(-third)));
      const moving = change >= slide && change / Math.max(dt, (part.length - third) * dt) >= rate;
      if (to(b) - from(a) < minNote || moving) { slideFrom = slideFrom ? { a: slideFrom.a, b } : { a, b }; continue; }
      const pitch = clamp(Math.round(median(part)), MIN_MIDI, MAX_MIDI), begin = slideFrom ? slideFrom.a : a;
      slideFrom = null;
      if (prev && prev.note.m === pitch && prev.end === begin) { extend(prev.note, b); prev.end = b; continue; }
      const note = { m: pitch, t: round3(from(begin)), d: 0 };
      extend(note, b);
      notes.push(note); prev = { note, end: b };
    }
    settle();
  }
  return notes;
}
