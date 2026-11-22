// PRACTICE.3: warm-ups and exercises in your range. Each exercise is ordinary melody notes ({m, t, d}, seconds) in the
// song's key, inside the range PRACTICE.2 measured, at the project tempo, so Practise (PRACTICE.1) scores it like any
// other stretch of the melody. Pure functions: the studio adds the notes to the melody as one edit.
import { SCALES, noteName } from "./contour.js";

import { BEATS_PER_BAR, barSeconds } from "./bars.js";

// GROW.1: bars.js owns the bar.
export { BEATS_PER_BAR };
// A project's notes end by 600 s (tandem_backend.py's note fields, sections.js MAX_TIME).
export const MAX_SECONDS = 600;
export const EXERCISES = Object.freeze([
  { id: "five", label: "Five-note scale", what: "up five notes of the scale and back, a beat each" },
  { id: "scale", label: "Scale", what: "up an octave of the scale and back, a beat each" },
  { id: "arpeggio", label: "Arpeggio", what: "the tonic chord up to the octave and back, a beat each" },
  { id: "intervals", label: "Intervals", what: "from the tonic to each note of the scale up to the octave and back, a bar each" },
  { id: "siren", label: "Siren", what: "every note of the scale in your range, up and back, an eighth each, joined like a glide" },
]);

// Scale degrees (0 = tonic, 7 = the octave) of the exercises built on one tonic.
const DEGREES = {
  five: [0, 1, 2, 3, 4, 3, 2, 1, 0],
  scale: [0, 1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2, 1, 0],
  arpeggio: [0, 2, 4, 7, 4, 2, 0],
};

const round3 = x => Math.round(x * 1000) / 1000;
const pc = m => ((m % 12) + 12) % 12;

function checkInputs({ key, range, bpm }) {
  if (!key || !Number.isInteger(key.tonic) || key.tonic < 0 || key.tonic > 11 || !["major", "minor"].includes(key.mode)) {
    throw Error("Choose a key in the harmony key menu for the exercise.");
  }
  if (!range || !Number.isInteger(range.low) || !Number.isInteger(range.high) || range.high < range.low) {
    throw Error("Your range is not known yet: hold a few notes while practising or recording first.");
  }
  if (!Number.isFinite(bpm) || bpm <= 0) throw Error("The exercise needs a tempo.");
}

// The MIDI note of scale degree `d` (0 = tonic, 7 = an octave up) above the tonic note `tonic`.
function degreeNote(tonic, steps, d) {
  return tonic + 12 * Math.floor(d / steps.length) + steps[d % steps.length];
}

// The tonic note for an exercise spanning `span` semitones above it inside the range: the one whose middle is nearest the
// middle of the range (the lower one on a tie), or null when none fits.
function placeTonic(key, range, span) {
  let best = null;
  const mid = (range.low + range.high) / 2;
  for (let m = range.low; m + span <= range.high; m++) {
    if (pc(m) !== key.tonic) continue;
    if (best === null || Math.abs(m + span / 2 - mid) < Math.abs(best + span / 2 - mid)) best = m;
  }
  return best;
}

// The scale notes of the key from the bottom of the range to the top.
function scaleInRange(key, range) {
  const pcs = SCALES[key.mode].steps.map(s => (key.tonic + s) % 12);
  const out = [];
  for (let m = range.low; m <= range.high; m++) if (pcs.includes(pc(m))) out.push(m);
  return out;
}

// Where an exercise starts: at 0 in an empty song, else on the first whole bar at least a bar after `after` seconds (the
// end of the song), so the exercise is heard on its own.
export function exerciseStart(after, bpm) {
  const bar = barSeconds(bpm);
  if (!(after > 0)) return 0;
  return round3((Math.ceil(after / bar - 1e-9) + 1) * bar);
}

// The exercise `id` as melody notes from `start` seconds: {notes, from, to, label, low, high}, `from`/`to` being the
// stretch to practise. Throws with a message for the person when the key or range is missing or the exercise does not
// fit in the range, or would end after MAX_SECONDS.
export function exerciseNotes(id, { key, range, bpm, start = 0 }) {
  const ex = EXERCISES.find(e => e.id === id);
  if (!ex) throw Error("Unknown exercise: " + id);
  checkInputs({ key, range, bpm });
  const beat = 60 / bpm, steps = SCALES[key.mode].steps;
  const seq = []; // [{m, beats, rest}] in order
  if (id === "siren") {
    const run = scaleInRange(key, range);
    if (run.length < 2) throw Error("A siren needs at least two notes of the key in your range (" + rangeName(range) + ").");
    for (const m of [...run, ...run.slice(0, -1).reverse()]) seq.push({ m, beats: 0.5 });
    seq.at(-1).beats = 2;
  } else {
    const degrees = id === "intervals" ? null : DEGREES[id];
    const top = id === "intervals" ? 7 : Math.max(...degrees);
    const span = degreeNote(0, steps, top);
    const tonic = placeTonic(key, range, span);
    if (tonic === null) {
      throw Error(ex.label + " needs " + span + " semitones up from the key's tonic, " + noteName(key.tonic + 60).replace(/-?\d+$/, "")
        + ", and your range is " + rangeName(range) + ". Try a shorter exercise, or another key.");
    }
    if (id === "intervals") {
      for (let d = 1; d <= 7; d++) {
        seq.push({ m: tonic, beats: 1 }, { m: degreeNote(tonic, steps, d), beats: 1 }, { m: tonic, beats: 1 }, { rest: true, beats: 1 });
      }
      seq.pop();
      seq.at(-1).beats = 2;
    } else {
      for (const d of degrees) seq.push({ m: degreeNote(tonic, steps, d), beats: 1 });
      seq.at(-1).beats = 2;
    }
  }
  const notes = [];
  let at = start; // the exercise never ends on a rest, so it ends with its last note
  for (const s of seq) {
    // Both ends rounded to the ms where they fall, so a note ends exactly where the next one starts.
    if (!s.rest) notes.push({ m: s.m, t: round3(at), d: round3(round3(at + s.beats * beat) - round3(at)) });
    at += s.beats * beat;
  }
  const ms = notes.map(n => n.m), last = notes.at(-1);
  if (last.t + last.d > MAX_SECONDS) {
    throw Error(ex.label + " would end at " + (last.t + last.d).toFixed(1) + " s, after the " + MAX_SECONDS
      + " s a song can last: there is no room for it after this song.");
  }
  return { notes, from: round3(start), to: round3(last.t + last.d), label: ex.label, low: Math.min(...ms), high: Math.max(...ms) };
}

export function rangeName(range) {
  return noteName(range.low) + (range.high > range.low ? " to " + noteName(range.high) : " only");
}
