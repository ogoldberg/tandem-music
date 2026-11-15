// Lyrics on the melody notes (LYR.1). The words are typed as text, kept in the optional project
// field `lyrics`, and laid on the melody one syllable a note, in time order:
//   - words are split by spaces or new lines; a hyphen splits a word into syllables ("slow-ly", or
//     "slow- ly" as notation apps type it), so "beau-ti-ful" is three syllables on three notes;
//   - "_" holds the syllable before it over one more note (a melisma: "it _" is one word on two
//     notes); at the very start, or after another hold of nothing, it leaves a note without a word.
// Notes that start on the same sixteenth (the MusicXML grid, notation.js) are one chord and take one
// syllable, so the roll and the score always agree on which note carries which word. The words do
// not move with the notes: edit the notes and the syllables flow onto them again in order.
// DOM-free so Node tests import it directly.

export const MAX_LYRICS = 4000;
// Sixteenths per quarter note: the grid notation.js writes on (its DIVISIONS).
export const GRID = 4;

// The sixteenth a time falls on at the tempo; notation.js snaps notes with the same function.
export const sixteenth = (t, bpm) => Math.max(0, Math.round((t * bpm) / 60 * GRID));

// The lyrics as kept in the project: a string, new lines as "\n", at most MAX_LYRICS characters.
// Text that is only spaces is no lyrics. Throws on anything else, like the other clean* functions.
export function cleanLyrics(text) {
  if (text == null) return "";
  if (typeof text !== "string") throw Error("The lyrics must be text.");
  const out = text.replace(/\r\n?/g, "\n");
  if (out.length > MAX_LYRICS) throw Error(`The lyrics are too long: at most ${MAX_LYRICS} characters.`);
  return out.trim() ? out : "";
}

// The lyrics as tokens in order: {text, syllabic} for a syllable (syllabic is MusicXML's single,
// begin, middle or end) or {hold: true} for "_".
export function syllables(text) {
  const out = [];
  // "slow- ly" and "slow -ly" are typed for "slow-ly"; join them first.
  const words = cleanLyrics(text).replace(/\s*-+\s*/g, "-").split(/\s+/).filter(Boolean);
  for (const word of words) {
    // Underscores around a word are holds: "it_" is "it _", "_it" is "_ it".
    const lead = word.match(/^_*/)[0].length, trail = word.match(/_*$/)[0].length;
    for (let i = 0; i < lead; i++) out.push({ hold: true });
    if (lead === word.length) continue;
    const pieces = word.slice(lead, word.length - trail).split("-").filter(p => p && !/^_+$/.test(p));
    pieces.forEach((p, i) => out.push({
      text: p,
      syllabic: pieces.length === 1 ? "single" : i === 0 ? "begin" : i === pieces.length - 1 ? "end" : "middle",
    }));
    for (let i = 0; i < trail; i++) out.push({ hold: true });
  }
  return out;
}

const playable = n => n && Number.isFinite(n.m) && Number.isFinite(n.t) && Number.isFinite(n.d) && n.d > 0;

// The melody's onsets in time order: {at (sixteenth), note (index of its highest note), notes}.
export function onsets(notes, bpm) {
  const byAt = new Map();
  (Array.isArray(notes) ? notes : []).forEach((n, i) => {
    if (!playable(n)) return;
    const at = sixteenth(n.t, bpm), o = byAt.get(at);
    if (!o) byAt.set(at, { at, note: i, notes: [i] });
    else {
      o.notes.push(i);
      if (n.m > notes[o.note].m) o.note = i;
    }
  });
  return [...byAt.values()].sort((a, b) => a.at - b.at);
}

// The syllables laid on the melody. Returns
//   byOnset: Map sixteenth -> {text, syllabic, extend} for an onset that starts a syllable, or
//            {held: true, last} for one the syllable before is held over (last: the hold ends there);
//   byNote:  per note index, the same entry on the onset's highest note, else null;
//   words:   how many onsets have a syllable; left: syllables with no note left for them;
//   bare:    onsets after the last syllable with no word.
export function assignLyrics(notes, text, bpm) {
  const tokens = syllables(text), list = onsets(notes, bpm);
  const byOnset = new Map(), byNote = Array.from({ length: Array.isArray(notes) ? notes.length : 0 }, () => null);
  // syllable: the last syllable laid; held: the last onset it is held over, if any.
  let k = 0, syllable = null, held = null, words = 0;
  for (; k < tokens.length && k < list.length; k++) {
    const token = tokens[k], o = list[k];
    let entry = null;
    if (token.hold) {
      // A hold with no syllable before it leaves this note without a word.
      if (syllable) {
        syllable.extend = true;
        if (held) held.last = false;
        entry = held = { held: true, last: true };
      }
    } else {
      entry = syllable = { text: token.text, syllabic: token.syllabic, extend: false };
      held = null;
      words++;
    }
    if (entry) {
      byOnset.set(o.at, entry);
      byNote[o.note] = entry;
    }
  }
  return { byOnset, byNote, words, left: tokens.slice(k).filter(t => !t.hold).length, bare: list.length - k };
}

// The syllable as the roll shows it: a hyphen after a syllable the word goes on from.
export const shown = e => (e && !e.held ? e.text + (e.syllabic === "begin" || e.syllabic === "middle" ? "-" : "") : "");

// A line for the person: how the words sit on the notes.
export function lyricsSummary(notes, text, bpm) {
  if (!cleanLyrics(text)) return "";
  const { words, left, bare } = assignLyrics(notes, text, bpm);
  const parts = [`${words} ${words === 1 ? "syllable" : "syllables"} on the notes`];
  if (left) parts.push(`${left} more ${left === 1 ? "has" : "have"} no note yet`);
  if (bare) parts.push(`${bare} ${bare === 1 ? "note has" : "notes have"} no word`);
  return parts.join("; ") + ".";
}
