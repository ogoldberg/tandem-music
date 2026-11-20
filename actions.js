// AI.7: the studio side of the chat's actions. Each action is declared once in actions.json (its
// params, their limits and the parts it changes); tandem_backend.py builds the model's action list,
// the validation and melody lock from that file, and this module runs each validated action on the
// project. tests/actions.test.mjs checks HANDLERS has exactly the actions actions.json declares.
// The read side (songSummary) gives the model what the studio reads from the notes but the project
// does not store: the key and the chords part's chords.
import { detectKey, readChords } from "./harmony.js";

const clampPitch = m => Math.max(36, Math.min(96, m));

// One function per action, (project, action) => void, changing the project in place. The studio calls
// applyActions inside one edit(), so a reply's actions are one undo step.
export const HANDLERS = Object.freeze({
  set_tempo(p, a) { p.bpm = a.bpm; },
  set_instrument(p, a) { p.instrument = a.instrument; },
  transpose(p, a) { p.notes = p.notes.map(n => ({ ...n, m: clampPitch(n.m + a.semitones) })); },
  add_note(p, a) { p.notes.push({ m: a.pitch, t: a.start, d: a.duration }); },
  add_hit(p, a) { p.drums.push({ k: a.drum, t: a.start }); },
  remove_track(p, a) {
    if (a.track === "melody") p.notes = [];
    if (a.track === "rhythm") p.drums = [];
  },
  replace_notes(p, a) { p.notes = a.notes; },
  replace_drums(p, a) { p.drums = a.drums; },
});

// Runs the server's validated actions in order; an action this studio does not know is skipped.
// Returns how many ran.
export function applyActions(project, actions) {
  let ran = 0;
  for (const a of Array.isArray(actions) ? actions : []) {
    const run = a && Object.hasOwn(HANDLERS, a.type) ? HANDLERS[a.type] : null;
    if (run) { run(project, a); ran++; }
  }
  return ran;
}

export const MAX_SUMMARY_CHORDS = 256;
const round3 = x => Math.round(x * 1000) / 1000;

// The chat request's `song` field (SongSummary in tandem_backend.py): the key the studio shows (the
// harmony key menu's choice, else the melody's detected key, else none) and the chords part's chords
// as readChords names them in that key, in time order. Pure: key is passed in, or detected here.
export function songSummary(project, { key } = {}) {
  const k = key === undefined ? detectKey(project?.notes) : key;
  // readChords refuses a project without a usable tempo; the chat refuses that project too, so it is not hidden.
  const chords = readChords(project?.harmony, { bpm: project?.bpm, key: k ?? null });
  return {
    key: k ? { tonic: k.tonic, mode: k.mode } : null,
    chords: chords.slice(0, MAX_SUMMARY_CHORDS).map(c => ({ t: round3(c.t), d: round3(c.d), root: c.root, quality: c.quality })),
  };
}
