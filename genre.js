// GENRE.1: an optional genre for the song that sets better starting choices. Pure and DOM-free, so the
// studio and the Node tests import it directly. A project without a genre (null, the default) works
// exactly as before: every function here gives today's choice for null.
//
// What a genre chooses (each one can still be changed afterwards):
// - the chords and bass line Generate makes: which chords of the key it leans to (`prior`, added to
//   harmony.js's fit score), how a chord is voiced (`voicing`), how often it is struck (`rhythm`) and the
//   bass line's pattern (`bass`);
// - how a beatbox is read into a groove: Transcribe (a beat) lines the drum hits up to the genre's grid
//   and swing (`beat`), as its own edit, so Undo gives the hits as they were played;
// - the quantize grid, strength and swing the studio's controls start on (`beat`);
// - the tempo range Detect tempo searches (`tempo`), so a song is not read at double or half speed;
// - the melody and harmony instruments (`instruments`), set when the genre is chosen;
// - the starter beat offered (`groove`, a beats.js groove);
// - the band's style text, filled in when the band's box is empty (`band`);
// - context for the AI chat: the project's `genre` goes with it, and tandem_backend.py GENRES gives the
//   model a line about the genre (same ids in the same order, which a Node test checks).

import { TEMPO_RANGE } from "./groove.js";
import { INSTRUMENTS } from "./voices.js";
import { GROOVES } from "./beats.js";

export const VOICINGS = Object.freeze(["triad", "seventh", "power", "open"]);
export const RHYTHMS = Object.freeze({ bar: 1, half: 2, beats: 4 });
export const BASS_PATTERNS = Object.freeze(["rootfifth", "roots", "walk", "octaves", "held"]);

// The prior is keyed by a chord's scale degree in semitones above the tonic (harmony.js DEGREES):
// in major 0 I, 2 ii, 4 iii, 5 IV, 7 V, 9 vi; in minor 0 i, 3 III, 5 iv, 7 V, 8 VI, 10 VII.
// HARM.4: `moves` adds to harmony.js MOVES, the score of a chord change at a bar line, keyed "from>to" by
// Roman numeral; `stay` scales the cost of holding a chord into another bar and `split` that of a change in
// the middle of a bar (1 is Tandem's own).
export const ROMANS = Object.freeze(["I", "ii", "iii", "IV", "V", "vi", "i", "III", "iv", "VI", "VII"]);
export const GENRES = Object.freeze([
  {
    id: "pop", name: "Pop", about: "I, V, vi and IV, struck twice a bar; a straight beat",
    harmony: { prior: { 0: 0.3, 5: 0.25, 7: 0.25, 9: 0.25, 8: 0.2, 10: 0.2 }, voicing: "triad", rhythm: "half", bass: "rootfifth",
      moves: { "I>V": 0.5, "V>vi": 0.7, "vi>IV": 0.6, "IV>I": 0.3, "i>VI": 0.5, "VI>III": 0.5, "III>VII": 0.5, "VII>i": 0.3 }, stay: 1, split: 1 },
    beat: { division: 4, strength: 0.75, swing: 0 }, tempo: [80, 140],
    instruments: { melody: "piano", harmony: "piano" }, groove: "straight",
    band: "bright pop band with piano, bass and drums",
  },
  {
    id: "rock", name: "Rock", about: "Power chords on every beat over the root; a straight beat",
    harmony: { prior: { 0: 0.3, 5: 0.25, 7: 0.25, 10: 0.25, 8: 0.15 }, voicing: "power", rhythm: "beats", bass: "roots",
      moves: { "IV>I": 0.6, "V>IV": 1, "I>IV": 0.3, "i>VII": 0.6, "VII>VI": 0.5, "VI>VII": 0.4, "VII>i": 0.5 }, stay: 1, split: 1.3 },
    beat: { division: 4, strength: 1, swing: 0 }, tempo: [90, 170],
    instruments: { melody: "guitar", harmony: "guitar" }, groove: "straight",
    band: "driving rock band with electric guitars, bass and drums",
  },
  {
    id: "folk", name: "Folk", about: "I, IV and V in open voicings; a gentle straight beat",
    harmony: { prior: { 0: 0.35, 2: -0.4, 4: -0.5, 5: 0.25, 7: 0.25, 9: -0.4, 3: -0.3, 8: -0.3, 10: -0.3 }, voicing: "open", rhythm: "half", bass: "rootfifth",
      moves: { "I>IV": 0.3, "IV>I": 0.4, "V>I": 0.3, "I>V": 0.3, "i>iv": 0.3, "iv>i": 0.3, "V>i": 0.3 }, stay: 0.7, split: 1.2 },
    beat: { division: 2, strength: 0.75, swing: 0 }, tempo: [70, 130],
    instruments: { melody: "flute", harmony: "guitar" }, groove: "straight",
    band: "warm acoustic folk band with guitar, upright bass and light percussion",
  },
  {
    id: "jazz", name: "Jazz", about: "Seventh chords leaning to ii-V-I, a walking bass; a swung shuffle",
    harmony: { prior: { 2: 0.3, 7: 0.3, 0: 0.2, 5: 0.15 }, voicing: "seventh", rhythm: "half", bass: "walk",
      moves: { "ii>V": 1, "vi>ii": 0.7, "I>vi": 0.5, "iii>vi": 0.5, "IV>ii": 0.4, "I>ii": 0.3, "ii>I": -0.4, "VI>iv": 0.4, "iv>V": 0.5, "III>VI": 0.4 }, stay: 1.5, split: 0.5 },
    beat: { division: 2, strength: 0.75, swing: 1 }, tempo: [90, 200],
    instruments: { melody: "piano", harmony: "organ" }, groove: "shuffle",
    band: "small jazz combo with piano, upright bass and brushed drums",
  },
  {
    id: "hiphop", name: "Hip-hop", about: "Held seventh chords and a held bass; a half-time beat on a lightly swung grid",
    harmony: { prior: { 0: 0.3, 9: 0.2, 5: 0.2, 3: 0.2, 8: 0.2 }, voicing: "seventh", rhythm: "bar", bass: "held",
      moves: { "I>vi": 0.5, "vi>IV": 0.6, "IV>I": 0.4, "i>VI": 0.6, "VI>VII": 0.5, "VII>i": 0.5, "i>iv": 0.3 }, stay: 0.4, split: 1.5 },
    beat: { division: 4, strength: 1, swing: 0.25 }, tempo: [70, 110],
    instruments: { melody: "marimba", harmony: "piano" }, groove: "halftime",
    band: "laid-back hip-hop beat with dusty drums, deep bass and mellow keys",
  },
  {
    id: "electronic", name: "Electronic", about: "Chords on every beat, an octave bass; four on the floor, tight sixteenths",
    harmony: { prior: { 0: 0.3, 9: 0.25, 5: 0.2, 8: 0.2, 3: 0.15 }, voicing: "open", rhythm: "beats", bass: "octaves",
      moves: { "vi>IV": 0.7, "IV>I": 0.5, "I>V": 0.5, "V>vi": 0.7, "i>VI": 0.6, "VI>III": 0.5, "III>VII": 0.5, "VII>i": 0.5 }, stay: 0.8, split: 1.2 },
    beat: { division: 4, strength: 1, swing: 0 }, tempo: [110, 140],
    instruments: { melody: "chip", harmony: "strings" }, groove: "four",
    band: "electronic dance track with synth pads, pulsing bass and four-on-the-floor drums",
  },
].map(g => Object.freeze({
  ...g,
  harmony: Object.freeze({ ...g.harmony, prior: Object.freeze({ ...g.harmony.prior }), moves: Object.freeze({ ...g.harmony.moves }) }),
  beat: Object.freeze({ ...g.beat }), tempo: Object.freeze([...g.tempo]), instruments: Object.freeze({ ...g.instruments }),
})));

export const GENRE_IDS = Object.freeze(GENRES.map(g => g.id));

// The genre with this id, or null for no genre (null, undefined or ""). Any other value is an error.
export function genreById(id) {
  if (id == null || id === "") return null;
  const g = GENRES.find(x => x.id === id);
  if (!g) throw Error(`There is no genre called ${id}.`);
  return g;
}

// The project field: a genre id, or null. Throws on anything else, like the other clean* functions.
export function cleanGenre(value) {
  return genreById(value)?.id ?? null;
}

// The harmony choices generateHarmony uses; null (no genre) means today's.
export const harmonyStyle = id => genreById(id)?.harmony ?? null;

// The tempo range Detect tempo searches.
export const tempoRange = id => genreById(id)?.tempo ?? TEMPO_RANGE;

// The quantize grid (divisions a beat), strength 0..1 and swing 0..1 the controls start on, or null to leave them.
export const beatFor = id => genreById(id)?.beat ?? null;

// The project fields choosing the genre changes in one edit: the genre and its instruments.
// Choosing no genre only clears the field; the instruments stay as they are.
export function genreChanges(id) {
  const g = genreById(id);
  if (!g) return { genre: null };
  return { genre: g.id, instrument: g.instruments.melody, harmony_instrument: g.instruments.harmony };
}

// Checks the table against the other modules' lists (also run by the Node tests).
export function checkGenres() {
  const grooves = GROOVES.map(g => g.id);
  for (const g of GENRES) {
    if (!INSTRUMENTS.includes(g.instruments.melody) || !INSTRUMENTS.includes(g.instruments.harmony)) throw Error(`${g.id}: unknown instrument`);
    if (!grooves.includes(g.groove)) throw Error(`${g.id}: unknown groove`);
    if (!VOICINGS.includes(g.harmony.voicing) || !(g.harmony.rhythm in RHYTHMS) || !BASS_PATTERNS.includes(g.harmony.bass)) throw Error(`${g.id}: unknown harmony style`);
    if (!Object.keys(g.harmony.moves).every(k => k.split(">").length === 2 && k.split(">").every(r => ROMANS.includes(r))) || !(g.harmony.stay > 0) || !(g.harmony.split > 0)) throw Error(`${g.id}: unknown chord moves`);
    // The studio's quantize controls: the grid menu (1/4, 1/8, 1/16), the strength menu, the swing slider in 5% steps.
    if (![1, 2, 4].includes(g.beat.division) || ![1, 0.75, 0.5].includes(g.beat.strength) || Math.round(g.beat.swing * 20) !== g.beat.swing * 20) throw Error(`${g.id}: quantize settings the studio cannot show`);
    const [lo, hi] = g.tempo;
    if (!(lo >= 45 && hi <= 220 && lo < hi)) throw Error(`${g.id}: tempo range outside 45..220`);
  }
  return true;
}
