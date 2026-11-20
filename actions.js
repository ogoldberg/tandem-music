// AI.7: the studio side of the chat's actions. Each action is declared once in actions.json (its
// params, their limits and the parts it changes); tandem_backend.py builds the model's action list,
// the validation and melody lock from that file, and this module runs each validated action on the
// project. tests/actions.test.mjs checks HANDLERS has exactly the actions actions.json declares.
// The read side (songSummary) gives the model what the studio reads from the notes but the project
// does not store: the key and the chords part's chords. AI.6: generate_harmony, add_beat and set_genre
// run the studio's own generators; the model never writes the harmony's notes.
import { detectKey, readChords, generateHarmony } from "./harmony.js";
import { grooveHits } from "./beats.js";
import { barOrigin } from "./groove.js";
import { genreChanges, harmonyStyle } from "./genre.js";

const clampPitch = m => Math.max(36, Math.min(96, m));

// One function per action, (project, action, context) => void, changing the project in place. The studio calls
// applyActions inside one edit(), so a reply's actions are one undo step. A handler that cannot run throws before
// it changes anything (AI.6's generators work out the new part first and then assign it).
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
  // AI.6: the studio's own generators, as Generate, Starter beat and the Genre menu run them.
  generate_harmony(p, a, { key = null } = {}) {
    // key: the key menu's choice, or null for the melody's key, read after the reply's earlier actions.
    const h = generateHarmony(p, { style: a.style, key, feel: harmonyStyle(p.genre) });
    if (!p.harmony?.length && a.style === "bass" && (p.harmony_instrument ?? "piano") === "piano") p.harmony_instrument = "bass";
    p.harmony = h.notes;
  },
  add_beat(p, a) {
    const from = barOrigin({ bpm: p.bpm, notes: p.notes, drums: [], harmony: p.harmony, voice2: p.voice2 });
    p.drums = grooveHits(a.groove, { bpm: p.bpm, bars: a.bars, from });
  },
  set_genre(p, a) { Object.assign(p, genreChanges(a.genre === "none" ? null : a.genre)); },
});

// Runs the server's validated actions in order; an action this studio does not know is skipped, and one that
// cannot run on this song (chords without a melody) is skipped with its reason pushed to `problems`, leaving the
// project as the earlier actions left it. context.key is the key the studio's key menu chose (null: the melody's).
// Returns how many ran.
export function applyActions(project, actions, { key = null, problems = [] } = {}) {
  let ran = 0;
  for (const a of Array.isArray(actions) ? actions : []) {
    const run = a && Object.hasOwn(HANDLERS, a.type) ? HANDLERS[a.type] : null;
    if (!run) continue;
    try { run(project, a, { key }); ran++; } catch (e) { problems.push({ type: a.type, message: e.message }); }
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

// The server refuses a chat request body over this many bytes (request_guards.py CHAT_BODY_MAX_BYTES;
// tests/actions.test.mjs checks they match).
export const CHAT_BODY_MAX_BYTES = 262_144;

// The chat request's JSON text. The song summary is optional context: when the request with it would be
// over the server's limit, it goes without it (the prompt is then as before AI.7), rather than the request
// being refused. A partial chord list is not sent, since the model would read it as the whole song.
export function chatBody(body, { maxBytes = CHAT_BODY_MAX_BYTES } = {}) {
  const text = JSON.stringify(body);
  if (body.song === undefined || new TextEncoder().encode(text).length <= maxBytes) return text;
  const { song, ...rest } = body;
  return JSON.stringify(rest);
}
