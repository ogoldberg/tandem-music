// Harmony for the Arrange panel (ARR.1c): detect the melody's key and generate an editable chord
// or bass accompaniment from it. Pure and DOM-free so Node tests import it directly.
// Works on the tandem-project shape ({bpm, notes:[{m,t,d}]}) and returns plain {m,t,d} notes, the
// same shape as the melody, so the studio stores them as the project's optional `harmony` part.

import { KEY_NAMES } from "./contour.js";
import { keyPitchClasses, nextInScale } from "./noteedit.js";

export const MODES = Object.freeze(["major", "minor"]);
export const STYLES = Object.freeze(["chords", "bass"]);
export const BEATS_PER_BAR = 4;
// Chords are voiced in this range (C3..G4); bass notes start in C2..B2 (MIDI 36 is the lowest the
// studio's note rolls and the AI accept).
export const CHORD_RANGE = Object.freeze([48, 67]);
export const BASS_LOW = 36;
// Projects and /api/chat accept at most this many harmony notes (ChatProject.harmony).
export const MAX_HARMONY_NOTES = 1024;
// Each generated note ends a little before the next one starts, so repeated pitches re-strike.
const RELEASE = 0.94;
const MIN_KEY_NOTES = 3;
const round3 = x => Math.round(x * 1000) / 1000;
const pc = m => ((m % 12) + 12) % 12;

// Krumhansl-Kessler key profiles (probe-tone ratings), index 0 = tonic.
const PROFILES = {
  major: [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
  minor: [6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
};

// Diatonic chords offered per mode: scale degree root (semitones above the tonic), triad quality
// and Roman numeral. Diminished triads are left out; minor keys use the major V (harmonic minor).
const DEGREES = {
  major: [
    { root: 0, quality: "major", roman: "I" },
    { root: 2, quality: "minor", roman: "ii" },
    { root: 4, quality: "minor", roman: "iii" },
    { root: 5, quality: "major", roman: "IV" },
    { root: 7, quality: "major", roman: "V" },
    { root: 9, quality: "minor", roman: "vi" },
  ],
  minor: [
    { root: 0, quality: "minor", roman: "i" },
    { root: 3, quality: "major", roman: "III" },
    { root: 5, quality: "minor", roman: "iv" },
    { root: 7, quality: "major", roman: "V" },
    { root: 8, quality: "major", roman: "VI" },
    { root: 10, quality: "major", roman: "VII" },
  ],
};
const SCALE_STEPS = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10] };
// A small preference for the tonic and the dominant/subdominant, in beats of matching melody.
const PRIOR = { 0: 0.3, 5: 0.15, 7: 0.2 };
const triad = quality => (quality === "major" ? [0, 4, 7] : [0, 3, 7]);

export function keyLabel(key) {
  return KEY_NAMES[key.tonic] + " " + key.mode;
}

function validNotes(notes) {
  return (Array.isArray(notes) ? notes : []).filter(n => n && Number.isFinite(n.m) && Number.isFinite(n.t) && Number.isFinite(n.d) && n.d > 0);
}

function pearson(a, b) {
  const n = a.length, ma = a.reduce((s, x) => s + x, 0) / n, mb = b.reduce((s, x) => s + x, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) { num += (a[i] - ma) * (b[i] - mb); da += (a[i] - ma) ** 2; db += (b[i] - mb) ** 2; }
  return da && db ? num / Math.sqrt(da * db) : 0;
}

// Estimate the key of a melody from its duration-weighted pitch classes (Krumhansl-Schmuckler).
// Returns {tonic 0..11, mode, confidence} or null when there are fewer than three notes or a
// single repeated pitch class (any key would fit). confidence is the profile correlation, -1..1.
export function detectKey(notes) {
  const clean = validNotes(notes);
  if (clean.length < MIN_KEY_NOTES) return null;
  const hist = new Array(12).fill(0);
  for (const n of clean) hist[pc(n.m)] += n.d;
  if (hist.filter(x => x > 0).length < 2) return null;
  let best = null;
  for (const mode of MODES) {
    for (let tonic = 0; tonic < 12; tonic++) {
      const rotated = hist.map((_, i) => hist[(i + tonic) % 12]);
      const r = pearson(rotated, PROFILES[mode]);
      if (!best || r > best.confidence + 1e-12) best = { tonic, mode, confidence: r };
    }
  }
  best.confidence = Math.round(best.confidence * 1000) / 1000;
  return best;
}

export function chordsForKey(key) {
  if (!key || !Number.isInteger(key.tonic) || key.tonic < 0 || key.tonic > 11 || !MODES.includes(key.mode)) {
    throw new Error("Choose a key: a tonic 0..11 and major or minor.");
  }
  return DEGREES[key.mode].map(d => {
    const root = (key.tonic + d.root) % 12;
    return { ...d, degree: d.root, root, pcs: triad(d.quality).map(x => (root + x) % 12), name: KEY_NAMES[root] + (d.quality === "minor" ? "m" : "") };
  });
}

// How well each chord fits the melody inside [start, end): overlap in beats counts +1 for a chord
// tone, -0.5 for another note of the key and -1 for a note outside it. A note sounding on the
// downbeat counts double.
function fit(chord, notes, start, end, beat, scalePcs) {
  let score = 0;
  for (const n of notes) {
    const overlap = Math.min(end, n.t + n.d) - Math.max(start, n.t);
    if (overlap <= 0) continue;
    const w = (overlap / beat) * (n.t <= start + 1e-6 && n.t + n.d > start ? 2 : 1);
    const p = pc(n.m);
    score += chord.pcs.includes(p) ? w : scalePcs.includes(p) ? -0.5 * w : -w;
  }
  return score + (PRIOR[chord.degree] || 0);
}

// Voice a triad inside CHORD_RANGE as close as possible to the previous voicing (smallest total
// movement); the first chord is placed nearest the middle of the range.
function voice(chord, previous) {
  const [lo, hi] = CHORD_RANGE, target = previous ? null : (lo + hi) / 2;
  let best = null, bestCost = Infinity;
  for (let bass = lo; bass <= hi; bass++) {
    if (!chord.pcs.includes(pc(bass))) continue;
    // Close position starting on this chord tone.
    const notes = [bass];
    while (notes.length < 3) {
      let m = notes[notes.length - 1] + 1;
      while (!chord.pcs.includes(pc(m)) || notes.some(x => pc(x) === pc(m))) m++;
      notes.push(m);
    }
    if (notes[2] > hi) continue;
    const cost = previous
      ? notes.reduce((s, m, i) => s + Math.abs(m - previous[i]), 0)
      : Math.abs((notes[0] + notes[2]) / 2 - target);
    if (cost < bestCost - 1e-9) { best = notes; bestCost = cost; }
  }
  return best;
}

// Generate an accompaniment for the melody, one chord per 4/4 bar at the project tempo.
// Bars start at the melody's first note, so a melody that starts on a downbeat lines up; a pickup
// shifts the bar lines. Each bar takes the chord of the key that best fits the melody notes it
// overlaps (see fit); a bar with no melody keeps the previous chord. style "chords" holds a
// voiced triad for the bar; "bass" plays the root on beat 1 and the fifth on beat 3. key defaults to detectKey(notes).
// Returns {key, chords:[{t,d,name,roman}], notes:[{m,t,d}]}; the input is unchanged.
export function generateHarmony(project, { style = "chords", key = null } = {}) {
  if (!STYLES.includes(style)) throw new Error(`Unknown accompaniment style: ${style}`);
  const bpm = Number(project?.bpm);
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error("Set a tempo before generating harmony.");
  const melody = validNotes(project?.notes).sort((a, b) => a.t - b.t);
  if (!melody.length) throw new Error("Add or transcribe a melody before generating harmony.");
  const useKey = key ?? detectKey(melody);
  if (!useKey) throw new Error("The melody needs at least three notes with two different pitches to find its key; choose a key instead.");
  const chords = chordsForKey(useKey);
  const scalePcs = SCALE_STEPS[useKey.mode].map(x => (useKey.tonic + x) % 12);
  const beat = 60 / bpm, bar = beat * BEATS_PER_BAR;
  const origin = melody[0].t;
  const end = Math.max(...melody.map(n => n.t + n.d));
  const bars = Math.max(1, Math.ceil((end - origin) / bar - 1e-6));

  const picked = [];
  for (let b = 0; b < bars; b++) {
    const start = origin + b * bar, stop = start + bar;
    const sounding = melody.some(n => n.t < stop && n.t + n.d > start);
    if (!sounding && picked.length) { picked.push(picked[picked.length - 1]); continue; }
    let best = null, bestScore = -Infinity;
    for (const c of chords) {
      const s = fit(c, melody, start, stop, beat, scalePcs);
      if (s > bestScore + 1e-9) { best = c; bestScore = s; }
    }
    picked.push(best);
  }

  const notes = [], chordList = [];
  let previous = null;
  picked.forEach((c, b) => {
    const t = round3(origin + b * bar);
    chordList.push({ t, d: round3(bar), name: c.name, roman: c.roman });
    if (style === "chords") {
      const voiced = voice(c, previous);
      previous = voiced;
      for (const m of voiced) notes.push({ m, t, d: round3(bar * RELEASE) });
    } else {
      const root = BASS_LOW + ((c.root - BASS_LOW) % 12 + 12) % 12;
      const half = bar / 2;
      notes.push({ m: root, t, d: round3(half * RELEASE) });
      notes.push({ m: root + 7, t: round3(origin + b * bar + half), d: round3(half * RELEASE) });
    }
  });
  if (notes.length > MAX_HARMONY_NOTES) {
    throw new Error(`The melody is too long for a harmony part: ${bars} bars would need ${notes.length} notes, over the ${MAX_HARMONY_NOTES}-note limit.`);
  }
  return { key: { tonic: useKey.tonic, mode: useKey.mode }, chords: chordList, notes };
}

// HARM.2: harmony lines for the harmony voice (ADR-014). The first is the default; Try another steps
// through the rest. Each is a plain note list the studio keeps in `voice2` as one edit.
export const HARMONY_LINES = Object.freeze([
  Object.freeze({ id: "thirds", label: "Thirds above" }),
  Object.freeze({ id: "sixth_below", label: "A sixth below" }),
  Object.freeze({ id: "octave", label: "The tune an octave lower" }),
  Object.freeze({ id: "counter", label: "A counter-melody" }),
  Object.freeze({ id: "stack", label: "Two voices: thirds above and below" }),
]);

// `steps` steps of the key away from m (up when > 0), or null outside the MIDI range. A note
// outside the key takes the nearest key note in that direction as its first step.
function stepsInKey(m, pcs, steps) {
  let p = m;
  for (let k = 0; k < Math.abs(steps) && p !== null; k++) p = nextInScale(p, pcs, Math.sign(steps));
  return p;
}

// Pitch classes of the chord notes sounding at time t.
function chordAt(chords, t) {
  const at = t + 1e-6;
  return new Set(chords.filter(n => n.t <= at && n.t + n.d > at).map(n => pc(n.m)));
}

// How many times the line moves into a fifth or an octave (or unison) with the melody from the same
// perfect interval, both voices moving the same way. Each line note is paired with the melody note
// that starts with it.
export function parallelPerfects(melody, line) {
  const mel = validNotes(melody), pairs = [];
  for (const n of validNotes(line).sort((a, b) => a.t - b.t)) {
    const m = mel.find(x => Math.abs(x.t - n.t) < 1e-3);
    if (m) pairs.push([m.m, n.m]);
  }
  let count = 0;
  for (let i = 1; i < pairs.length; i++) {
    const [a0, b0] = pairs[i - 1], [a1, b1] = pairs[i], iv0 = pc(b0 - a0), iv1 = pc(b1 - a1);
    if ((iv0 === 0 || iv0 === 7) && iv0 === iv1 && a1 !== a0 && Math.sign(a1 - a0) === Math.sign(b1 - b0)) count++;
  }
  return count;
}

// The default: a third above each melody note in the key, or a sixth above when the third is not a
// tone of the chord sounding then and the sixth is. When both or neither are, the one nearer the
// previous harmony note wins, with a small preference for the third. Thirds and sixths are never
// fifths or octaves, so the line has no parallel fifths or octaves with the melody.
function thirdsAbove(melody, pcs, chords) {
  const out = [];
  let prev = null;
  for (const n of melody) {
    const chord = chordAt(chords, n.t);
    let best = null, bestCost = Infinity;
    for (const [steps, bias] of [[2, 0], [5, 0.5]]) {
      const m = stepsInKey(n.m, pcs, steps);
      if (m === null) continue;
      const cost = (chord.size && !chord.has(pc(m)) ? 10 : 0) + bias + (prev === null ? 0 : Math.abs(m - prev) * 0.1);
      if (cost < bestCost - 1e-9) { best = m; bestCost = cost; }
    }
    if (best === null) continue;
    out.push({ m: best, t: n.t, d: n.d });
    prev = best;
  }
  return out;
}

// A counter-melody below the tune: a chord tone every two beats (fewer where the chord changes
// sooner), each the in-key chord tone nearest the last. A repeated note costs more than a small
// move and moving the same way as the melody costs a little, so the line moves, mostly against the
// tune; a fifth or octave with the melody reached from the same interval is avoided. Where no
// melody sounds there is a rest.
function counterMelody(melody, pcs, chords, bpm) {
  const low = Math.min(...melody.map(n => n.m)), lo = Math.max(MIN_LINE, low - 12), hi = low - 1;
  const half = (60 / bpm) * 2, onsets = [...new Set(chords.map(n => round3(n.t)))].sort((a, b) => a - b);
  const pieces = [];
  onsets.forEach((t, i) => {
    const end = Math.min(onsets[i + 1] ?? Infinity, Math.max(...chords.filter(n => round3(n.t) === t).map(n => n.t + n.d)));
    for (let s = t; s < end - 1e-6; s += half) pieces.push([s, Math.min(end, s + half)]);
  });
  const out = [];
  let prev = null, prevMel = null;
  for (const [t, end] of pieces) {
    const under = melody.filter(n => n.t < end - 1e-6 && n.t + n.d > t + 1e-6);
    if (!under.length) continue;
    const chord = [...chordAt(chords, t)], keyed = chord.filter(p => pcs.includes(p)), allowed = keyed.length ? keyed : pcs;
    const mel = under[0].m;
    let best = null, bestCost = Infinity;
    for (let m = lo; m <= hi; m++) {
      if (!allowed.includes(pc(m))) continue;
      let cost = prev === null ? Math.abs(m - (lo + hi) / 2) : m === prev ? 3.5 : Math.abs(m - prev);
      if (prev !== null && prevMel !== null && mel !== prevMel && Math.sign(mel - prevMel) === Math.sign(m - prev)) {
        cost += 1;
        const iv0 = pc(prevMel - prev), iv1 = pc(mel - m);
        if ((iv1 === 0 || iv1 === 7) && iv0 === iv1) cost += 100;
      }
      if (cost < bestCost - 1e-9) { best = m; bestCost = cost; }
    }
    if (best === null) continue;
    out.push({ m: best, t, d: round3((end - t) * RELEASE) });
    prev = best;
    prevMel = mel;
  }
  return out;
}
const MIN_LINE = 36;

// Every harmony line for the melody in `key`, against `chords` (the harmony part's notes; when there
// are none, the chords generateHarmony works out from the melody). Lines that come out the same as
// an earlier one, empty, or over the part's note limit are left out. Returns [{id, label, notes}].
export function harmonyLines(project, { key = null, chords = null } = {}) {
  const melody = validNotes(project?.notes).sort((a, b) => a.t - b.t || a.m - b.m);
  if (!melody.length) throw new Error("Add or transcribe a melody before creating a harmony line.");
  const pcs = keyPitchClasses(key);
  const context = validNotes(chords).length ? validNotes(chords) : generateHarmony({ bpm: project.bpm, notes: melody }, { style: "chords", key }).notes;
  const thirds = thirdsAbove(melody, pcs, context);
  const shifted = steps => melody.flatMap(n => { const m = stepsInKey(n.m, pcs, steps); return m === null ? [] : [{ m, t: n.t, d: n.d }]; });
  const build = {
    thirds: () => thirds,
    sixth_below: () => shifted(-5),
    octave: () => melody.filter(n => pcs.includes(pc(n.m))).map(n => ({ m: n.m - 12 >= MIN_LINE ? n.m - 12 : n.m + 12, t: n.t, d: n.d })),
    counter: () => counterMelody(melody, pcs, context, Number(project.bpm) || 100),
    stack: () => [...thirds, ...shifted(-2)].sort((a, b) => a.t - b.t || a.m - b.m),
  };
  const seen = new Set(), out = [];
  for (const { id, label } of HARMONY_LINES) {
    const held = new Set(), notes = [];
    for (const n of build[id]()) {
      const k = n.m + "@" + n.t;
      if (!held.has(k)) { held.add(k); notes.push({ m: n.m, t: round3(n.t), d: round3(n.d) }); }
    }
    const shape = JSON.stringify(notes);
    if (!notes.length || notes.length > MAX_HARMONY_NOTES || seen.has(shape)) continue;
    seen.add(shape);
    out.push({ id, label, notes });
  }
  return out;
}
