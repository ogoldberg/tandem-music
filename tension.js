// SILENT.1: how each melody note sits on the harmony, read from the notes alone so it can be seen with
// the sound off. Pure and DOM-free so Node tests import it directly.
// A note is a chord tone (its pitch class is a tone of the chord sounding under it, from harmony.js
// readChords), else a note of the key (noteedit.js keyPitchClasses), else outside the key. A phrase
// (phrases.js detectPhrases) whose last note sounds over the key's tonic chord ends on I (home), over
// the chord on the fifth degree on V (open). Nothing here says how a note feels: only what it is.

import { readChords, CHORD_QUALITIES } from "./harmony.js";
import { keyPitchClasses } from "./noteedit.js";
import { detectPhrases } from "./phrases.js";

export const NOTE_FITS = Object.freeze(["chord", "key", "outside"]);
export const FIT_LABELS = Object.freeze({ chord: "a chord tone", key: "in the key, not in the chord", outside: "outside the key" });
export const CADENCES = Object.freeze(["tonic", "dominant"]);

const pc = m => ((m % 12) + 12) % 12;
const TONES = Object.fromEntries(CHORD_QUALITIES.map(q => [q.id, q.tones]));
// The tonic chord's kinds for each mode: a seventh on the tonic still reads as I.
const TONIC_KINDS = { major: ["major", "maj7", "dom7"], minor: ["minor", "m7"] };
const EPS = 1e-6;
const valid = n => n && Number.isFinite(n.m) && Number.isFinite(n.t) && Number.isFinite(n.d) && n.d > 0;

// The chord under a note: the one sounding when it starts, else the one it overlaps longest, else null.
function chordUnder(chords, n) {
  const at = chords.find(c => n.t >= c.t - EPS && n.t < c.t + c.d - EPS);
  if (at) return at;
  let best = null, most = EPS;
  for (const c of chords) {
    const o = Math.min(n.t + n.d, c.t + c.d) - Math.max(n.t, c.t);
    if (o > most) { best = c; most = o; }
  }
  return best;
}

// notes: the melody; harmony: the chords part's notes (may be empty); key: {tonic, mode}, required.
// Returns {key, chords, notes:[{fit, chord}] one per melody note in its order (fit null for a note
// that is not a valid note), cadences:[{t, phrase, kind, chord, roman}] one per phrase that ends on
// I or V, counts:{chord, key, outside}}. chord is the name of the chord under the note, or null.
export function melodyFit(notes, harmony, { bpm, key } = {}) {
  const scale = keyPitchClasses(key);
  const chords = Array.isArray(harmony) && harmony.length ? readChords(harmony, { bpm, key }) : [];
  const list = Array.isArray(notes) ? notes : [];
  const counts = { chord: 0, key: 0, outside: 0 };
  const out = list.map(n => {
    if (!valid(n)) return { fit: null, chord: null };
    const c = chordUnder(chords, n), p = pc(n.m);
    const fit = c && TONES[c.quality].some(x => (c.root + x) % 12 === p) ? "chord" : scale.includes(p) ? "key" : "outside";
    counts[fit]++;
    return { fit, chord: c ? c.name : null };
  });
  const cadences = [];
  if (chords.length) {
    detectPhrases(list, { bpm }).forEach((ph, phrase) => {
      // The phrase's last note: the one that ends last, the later start on a tie.
      const last = ph.indices.reduce((a, i) => {
        const x = list[i], y = list[a];
        return x.t + x.d > y.t + y.d + EPS || (Math.abs(x.t + x.d - (y.t + y.d)) <= EPS && x.t > y.t) ? i : a;
      });
      const c = chordUnder(chords, list[last]);
      if (!c) return;
      let kind = null;
      if (c.root === key.tonic && TONIC_KINDS[key.mode].includes(c.quality)) kind = "tonic";
      else if (c.root === (key.tonic + 7) % 12 && ["major", "dom7"].includes(c.quality)) kind = "dominant";
      if (kind) cadences.push({ t: ph.end, phrase, note: last, kind, chord: c.name, roman: kind === "tonic" ? (key.mode === "minor" ? "i" : "I") : "V" });
    });
  }
  return { key, chords, notes: out, cadences, counts };
}

// One line for the studio: how many notes of each kind, and how the phrases end.
export function fitSummary(fit) {
  const { chord, key, outside } = fit.counts, n = chord + key + outside;
  if (!n) return "No melody notes yet.";
  const parts = [chord + " chord tone" + (chord === 1 ? "" : "s"), key + " in the key", outside + " outside the key"];
  let s = parts.join(", ") + ".";
  if (!fit.chords.length) s += " No chords under the melody yet: make chords to see chord tones and phrase endings.";
  else {
    const home = fit.cadences.filter(c => c.kind === "tonic").length, open = fit.cadences.length - home;
    s += " " + (home ? home + " phrase" + (home === 1 ? " ends" : "s end") + " home on " + (fit.key.mode === "minor" ? "i" : "I") : "No phrase ends home on " + (fit.key.mode === "minor" ? "i" : "I"));
    if (open) s += ", " + open + " open on V";
    s += ".";
  }
  return s;
}
