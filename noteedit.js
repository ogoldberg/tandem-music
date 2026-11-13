// EDIT.3: pure note-editing operations for the melody and harmony rolls. Every function takes the
// part's notes ({m,t,d}) and the selected indices and returns a new notes array (the input is never
// changed), or throws an Error whose message the studio shows when the edit cannot be made.
// Selections are arrays of indices in ascending order; edits keep every note at its index, so the
// selection stays on the same notes after a move, resize or shift.

export const MIN_PITCH = 0, MAX_PITCH = 127;
// The shortest note a resize leaves, in seconds.
export const MIN_DURATION = 0.05;
// Times are kept to the millisecond.
const ms = x => Math.round(x * 1000) / 1000;

// MIDI pitch classes of a key's scale: major or natural minor from a tonic 0..11.
const STEPS = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10] };
export function keyPitchClasses(key) {
  if (!key || !Number.isInteger(key.tonic) || key.tonic < 0 || key.tonic > 11 || !STEPS[key.mode]) throw Error("Choose a key first.");
  return STEPS[key.mode].map(s => (s + key.tonic) % 12).sort((a, b) => a - b);
}

function checked(notes, indices) {
  const sel = [...new Set(indices)].sort((a, b) => a - b);
  for (const i of sel) if (!Number.isInteger(i) || i < 0 || i >= notes.length) throw Error("The selection is out of date.");
  if (!sel.length) throw Error("Select a note first.");
  return sel;
}

// Indices of the notes that overlap the time range [t0, t1] and whose pitch is within [m0, m1].
export function notesInBox(notes, { t0, t1, m0, m1 }) {
  const [a, b] = t0 <= t1 ? [t0, t1] : [t1, t0], [lo, hi] = m0 <= m1 ? [m0, m1] : [m1, m0];
  const out = [];
  notes.forEach((n, i) => { if (n.t <= b && n.t + n.d >= a && n.m >= lo && n.m <= hi) out.push(i); });
  return out;
}

export const allIndices = notes => notes.map((_, i) => i);

// Add or remove one index (shift-click).
export function toggleIndex(indices, i) {
  const s = new Set(indices);
  s.has(i) ? s.delete(i) : s.add(i);
  return [...s].sort((a, b) => a - b);
}

// The nearest grid time to `t` for a division of the beat (4 = sixteenths) at `bpm`.
export function snapTime(t, bpm, division = 4) {
  const step = 60 / bpm / division;
  return ms(Math.max(0, Math.round(t / step) * step));
}

// Move the selected notes by dt seconds and dm semitones. The move is cut short so no note starts
// before zero or leaves the MIDI range, which keeps the notes' spacing.
export function moveNotes(notes, indices, { dt = 0, dm = 0 } = {}) {
  const sel = checked(notes, indices), chosen = sel.map(i => notes[i]);
  const earliest = Math.min(...chosen.map(n => n.t)), lo = Math.min(...chosen.map(n => n.m)), hi = Math.max(...chosen.map(n => n.m));
  const t = Math.max(dt, -earliest), m = Math.round(Math.min(Math.max(dm, MIN_PITCH - lo), MAX_PITCH - hi));
  const set = new Set(sel);
  return notes.map((n, i) => (set.has(i) ? { ...n, m: n.m + m, t: ms(n.t + t) } : n));
}

// Drag one edge of note i to time `at`: the start edge keeps the note's end, the end edge keeps its
// start. The note stays at least MIN_DURATION long and does not start before zero.
export function resizeNote(notes, i, edge, at) {
  checked(notes, [i]);
  const n = notes[i], end = n.t + n.d;
  let out;
  if (edge === "start") {
    const t = Math.min(Math.max(0, at), end - MIN_DURATION);
    out = { ...n, t: ms(t), d: ms(end - t) };
  } else if (edge === "end") {
    out = { ...n, d: ms(Math.max(MIN_DURATION, at - n.t)) };
  } else throw Error("Unknown edge: " + edge);
  return notes.map((x, k) => (k === i ? out : x));
}

// Lengthen or shorten every selected note by dd seconds, never below MIN_DURATION.
export function lengthenNotes(notes, indices, dd) {
  const set = new Set(checked(notes, indices));
  return notes.map((n, i) => (set.has(i) ? { ...n, d: ms(Math.max(MIN_DURATION, n.d + dd)) } : n));
}

// A new note at the end of the part's array; its index is notes.length.
export function drawNote(notes, { m, t, d }) {
  if (!Number.isInteger(m) || m < MIN_PITCH || m > MAX_PITCH) throw Error("That pitch is outside the MIDI range.");
  if (!(t >= 0) || !(d > 0)) throw Error("A note needs a start and a length.");
  return [...notes, { m, t: ms(t), d: ms(Math.max(MIN_DURATION, d)) }];
}

export function deleteNotes(notes, indices) {
  const set = new Set(checked(notes, indices));
  return notes.filter((_, i) => !set.has(i));
}

// Move the selection up (dir 1) or down (dir -1) an octave; refused if a note would leave the MIDI range.
export function shiftOctave(notes, indices, dir) {
  const sel = checked(notes, indices), s = dir > 0 ? 12 : -12;
  if (sel.some(i => notes[i].m + s < MIN_PITCH || notes[i].m + s > MAX_PITCH)) throw Error("An octave " + (s > 0 ? "up" : "down") + " would go outside the MIDI range.");
  const set = new Set(sel);
  return notes.map((n, i) => (set.has(i) ? { ...n, m: n.m + s } : n));
}

// The next pitch of the scale above (dir > 0) or below (dir < 0) `m`, or null outside the MIDI range.
export function nextInScale(m, pcs, dir) {
  for (let p = m + (dir > 0 ? 1 : -1); p >= MIN_PITCH && p <= MAX_PITCH; p += dir > 0 ? 1 : -1) if (pcs.includes(p % 12)) return p;
  return null;
}

// Move each selected note one step of the key up or down: a note in the scale goes to the next scale
// note, and a note outside it to the nearest scale note in that direction, so every shifted note
// ends up in the key. Refused if a note would leave the MIDI range.
export function stepInKey(notes, indices, key, dir) {
  const sel = checked(notes, indices), pcs = keyPitchClasses(key), set = new Set(sel), to = new Map();
  for (const i of sel) {
    const p = nextInScale(notes[i].m, pcs, dir);
    if (p === null) throw Error("A step " + (dir > 0 ? "up" : "down") + " would go outside the MIDI range.");
    to.set(i, p);
  }
  return notes.map((n, i) => (set.has(i) ? { ...n, m: to.get(i) } : n));
}
