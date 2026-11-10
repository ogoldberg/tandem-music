// Phrase-aware melody editing for the Arrange panel (ARR.1d): split the melody into phrases at
// rests, then move, transpose or copy one whole phrase. Pure and DOM-free so Node tests import it
// directly. Works on the tandem-project shape ({bpm, notes:[{m,t,d}]}) and returns new note arrays;
// the studio applies them through edit() so every phrase edit is undoable.

export const BEATS_PER_BAR = 4;
// A rest of at least this many beats (at the project tempo) ends a phrase.
export const PHRASE_GAP_BEATS = 1;
// Same bounds as the project schema (ProjectNote in tandem_backend.py) and the melody cap.
export const MIN_PITCH = 0;
export const MAX_PITCH = 127;
export const MAX_TIME = 600;
export const MAX_MELODY_NOTES = 1024;
// Times within a millisecond count as equal, so rounded note times do not split or merge phrases.
const EPS = 1e-3;
const round3 = x => Math.round(x * 1000) / 1000;

function beatSeconds(bpm) {
  const b = Number(bpm);
  if (!Number.isFinite(b) || b <= 0) throw new Error("Set a tempo before editing phrases.");
  return 60 / b;
}

const validNote = n => n && Number.isFinite(n.m) && Number.isFinite(n.t) && Number.isFinite(n.d) && n.t >= 0 && n.d > 0;

// Phrases in time order. Each is {start, end, low, high, indices}: `indices` are positions in
// `notes` (so an edit keeps the array order), sorted by note start. A note that starts before the
// latest end so far, or after a rest shorter than `gapBeats`, joins the current phrase.
export function detectPhrases(notes, { bpm, gapBeats = PHRASE_GAP_BEATS } = {}) {
  const gap = beatSeconds(bpm) * gapBeats;
  const order = (notes || [])
    .map((n, i) => i)
    .filter(i => validNote(notes[i]))
    .sort((a, b) => notes[a].t - notes[b].t || a - b);
  const phrases = [];
  let cur = null;
  for (const i of order) {
    const n = notes[i];
    if (!cur || n.t - cur.end >= gap - EPS) {
      cur = { start: n.t, end: n.t + n.d, low: n.m, high: n.m, indices: [] };
      phrases.push(cur);
    }
    cur.indices.push(i);
    cur.end = Math.max(cur.end, n.t + n.d);
    cur.low = Math.min(cur.low, n.m);
    cur.high = Math.max(cur.high, n.m);
  }
  for (const p of phrases) { p.start = round3(p.start); p.end = round3(p.end); }
  return phrases;
}

function checkPhrase(notes, phrase) {
  if (!phrase || !Array.isArray(phrase.indices) || !phrase.indices.length) throw new Error("Choose a phrase first.");
  for (const i of phrase.indices) if (!Number.isInteger(i) || !validNote(notes[i])) throw new Error("That phrase no longer matches the melody; choose it again.");
}

// Shift the phrase by `beats` (may be fractional or negative). Refused when a note would start
// before 0 s or after the 600 s project limit. Returns {notes, indices}.
export function movePhrase(notes, phrase, { bpm, beats }) {
  checkPhrase(notes, phrase);
  if (!Number.isFinite(beats) || beats === 0) throw new Error("Choose how far to move the phrase.");
  const shift = beats * beatSeconds(bpm);
  const moved = phrase.indices.map(i => round3(notes[i].t + shift));
  if (Math.min(...moved) < -EPS) throw new Error("The phrase cannot move before the start of the song.");
  if (Math.max(...moved) > MAX_TIME) throw new Error(`A phrase cannot move past ${MAX_TIME} seconds.`);
  const out = notes.map(n => ({ ...n }));
  phrase.indices.forEach((i, k) => { out[i].t = Math.max(0, moved[k]); });
  return { notes: out, indices: [...phrase.indices] };
}

// Transpose every note of the phrase by `semitones`. Refused (not clamped, so the phrase keeps its
// shape) when a note would leave MIDI 0..127. Returns {notes, indices}.
export function transposePhrase(notes, phrase, semitones) {
  checkPhrase(notes, phrase);
  if (!Number.isInteger(semitones) || semitones === 0) throw new Error("Choose a whole number of semitones.");
  const pitches = phrase.indices.map(i => notes[i].m + semitones);
  if (Math.min(...pitches) < MIN_PITCH || Math.max(...pitches) > MAX_PITCH) throw new Error("That would take the phrase outside the MIDI note range.");
  const out = notes.map(n => ({ ...n }));
  phrase.indices.forEach((i, k) => { out[i].m = pitches[k]; });
  return { notes: out, indices: [...phrase.indices] };
}

// Append a copy of the phrase after the end of the melody, a whole number of 4/4 bars after the
// original, so the copy keeps the original's position in the bar (a pickup stays a pickup).
// Returns {notes, indices, bars}: `indices` are the copied notes, appended at the end of the array.
export function copyPhraseToEnd(notes, phrase, { bpm }) {
  checkPhrase(notes, phrase);
  const bar = beatSeconds(bpm) * BEATS_PER_BAR;
  const lastEnd = Math.max(...notes.filter(validNote).map(n => n.t + n.d));
  const bars = Math.max(1, Math.ceil((lastEnd - phrase.start - EPS) / bar));
  const shift = bars * bar;
  if (notes.length + phrase.indices.length > MAX_MELODY_NOTES) throw new Error(`The melody would have more than ${MAX_MELODY_NOTES} notes.`);
  const copies = phrase.indices.map(i => ({ ...notes[i], t: round3(notes[i].t + shift) }));
  if (Math.max(...copies.map(n => n.t)) > MAX_TIME) throw new Error(`The copy would start past ${MAX_TIME} seconds.`);
  const out = [...notes.map(n => ({ ...n })), ...copies];
  return { notes: out, indices: copies.map((_, k) => notes.length + k), bars };
}

// The phrase (index into `phrases`) that contains note index `i`, or -1.
export function phraseOf(phrases, i) {
  return phrases.findIndex(p => p.indices.includes(i));
}
