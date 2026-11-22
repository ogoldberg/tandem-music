// Harmony for the Arrange panel (ARR.1c): detect the melody's key and generate an editable chord
// or bass accompaniment from it. Pure and DOM-free so Node tests import it directly.
// Works on the tandem-project shape ({bpm, notes:[{m,t,d}]}) and returns plain {m,t,d} notes, the
// same shape as the melody, so the studio stores them as the project's optional `harmony` part.

import { KEY_NAMES } from "./contour.js";
import { keyPitchClasses, nextInScale } from "./noteedit.js";
import { barOrigin, BEATS_PER_BAR, barSeconds } from "./bars.js";

export const MODES = Object.freeze(["major", "minor"]);
export const STYLES = Object.freeze(["chords", "bass"]);
// GROW.1: bars.js owns the bar.
export { BEATS_PER_BAR };
// Chords are voiced in this range (C3..G4); bass notes start in C2..B2 (MIDI 36 is the lowest the
// studio's note rolls and the AI accept).
export const CHORD_RANGE = Object.freeze([48, 67]);
export const BASS_LOW = 36;
// GROW.2: the studio's harmony cap, sections.js MAX_EVENTS (the chat carries fewer: actions.js CHAT_LIMITS).
export const MAX_HARMONY_NOTES = 4096;
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

// SONG.3: the key's tonic triad for an ending, voiced like the generated chords: near `previous` (the chord before
// it), at or below `ceiling` (the melody's lowest note over it, HARM.4).
export function tonicChord(key, { previous = null, ceiling = CHORD_RANGE[1] } = {}) {
  const notes = voice(chordsForKey(key)[0], previous, ceiling);
  if (!notes.length) throw new Error("The tune ends too low for a chord under it.");
  return notes;
}

// How well each chord fits the melody inside [start, end): overlap in beats counts +1 for a chord
// tone, -0.5 for another note of the key and -1 for a note outside it. A note sounding on the
// downbeat counts double.
function fit(chord, notes, start, end, beat, scalePcs, prior = PRIOR, downbeat = true) {
  let score = 0;
  for (const n of notes) {
    const overlap = Math.min(end, n.t + n.d) - Math.max(start, n.t);
    if (overlap <= 0) continue;
    const w = (overlap / beat) * (downbeat && n.t <= start + 1e-6 && n.t + n.d > start ? 2 : 1);
    const p = pc(n.m);
    score += chord.pcs.includes(p) ? w : scalePcs.includes(p) ? -0.5 * w : -w;
  }
  return score + (prior[chord.degree] || 0);
}

// HARM.4: no chord note sounds above the melody's lowest note in its bar (`ceiling`), so the chords sit
// under a low hummed tune instead of on top of it. Chord notes go no lower than FLOOR (the lowest note the
// studio's rolls and the AI accept). A chord is voiced in its usual place when that fits under the ceiling,
// else lower; when even its lowest voicing does not fit, the notes above the ceiling are left out.
const FLOOR = 36;
const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;

// Close position on each chord tone from FLOOR up to the top of CHORD_RANGE.
function closePositions(pcs) {
  const out = [];
  for (let bass = FLOOR; bass <= CHORD_RANGE[1]; bass++) {
    if (!pcs.includes(pc(bass))) continue;
    const notes = [bass];
    while (notes.length < pcs.length) {
      let m = notes[notes.length - 1] + 1;
      while (!pcs.includes(pc(m)) || notes.some(x => pc(x) === pc(m))) m++;
      notes.push(m);
    }
    out.push(notes);
  }
  return out;
}

// The candidate under the ceiling with the least cost, taken from the usual band when one there fits.
function pick(candidates, inBand, ceiling, cost) {
  const fits = candidates.filter(v => v[v.length - 1] <= ceiling);
  const pool = fits.some(inBand) ? fits.filter(inBand) : fits;
  if (!pool.length) {
    // Nothing fits whole: the lowest voicing without the notes above the ceiling (none when the melody
    // goes below every chord tone).
    return (candidates[0] || []).filter(m => m <= ceiling);
  }
  let best = null, bestCost = Infinity;
  for (const v of pool) {
    const c = cost(v);
    if (c < bestCost - 1e-9) { best = v; bestCost = c; }
  }
  return best;
}

// Voice a triad (or a seventh chord) in close position as near the previous voicing as it can (smallest
// total movement); the first chord nearest the middle of CHORD_RANGE, or a little under the ceiling when
// that is lower. The usual band is CHORD_RANGE.
function voice(chord, previous, ceiling = CHORD_RANGE[1]) {
  const [lo, hi] = CHORD_RANGE, top = Math.min(hi, ceiling), target = Math.min((lo + hi) / 2, top - 4);
  const cost = previous && previous.length
    ? v => v.reduce((s, m, i) => s + Math.abs(m - (previous[i] ?? previous[previous.length - 1])), 0)
    : v => Math.abs((v[0] + v[v.length - 1]) / 2 - target);
  return pick(closePositions(chord.pcs), v => v[0] >= lo, top, cost);
}

// GENRE.1 voicings (genre.js VOICINGS). "triad" is voice() above. "seventh" adds the key's seventh above
// the root (a scale tone 10 or 11 semitones up: maj7, m7 or 7) in close position. "power" is the root, the
// fifth and the octave, the root in E2..F3; "open" the root, the fifth and the third an octave up (a tenth),
// the root in F2..E3. Each is placed nearest the previous chord (the first nearest the middle), lower when
// the melody is (HARM.4).
const RHYTHM_STRIKES = { bar: 1, half: 2, beats: 4 };
const POWER_ROOTS = [40, 53], OPEN_ROOTS = [41, 52];
function seventhOf(chord, scalePcs) {
  const s = [10, 11].map(x => (chord.root + x) % 12).find(p => scalePcs.includes(p));
  return s === undefined ? chord : { ...chord, pcs: [...chord.pcs, s] };
}
function spread(chord, previous, [lo, hi], shape, ceiling) {
  const candidates = [];
  for (let r = FLOOR; r <= hi; r++) if (pc(r) === chord.root) candidates.push(shape(r));
  const cost = previous && previous.length ? v => Math.abs(mean(v) - mean(previous)) : v => Math.abs(v[0] - (lo + hi) / 2);
  return pick(candidates, v => v[0] >= lo, ceiling, cost);
}
function voiceFor(chord, previous, voicing, scalePcs, ceiling = CHORD_RANGE[1]) {
  if (voicing === "seventh") return voice(seventhOf(chord, scalePcs), previous, ceiling);
  if (voicing === "power") return spread(chord, previous, POWER_ROOTS, r => [r, r + 7, r + 12], ceiling);
  if (voicing === "open") return spread(chord, previous, OPEN_ROOTS, r => [r, r + 7, r + (chord.quality === "major" ? 16 : 15)], ceiling);
  return voice(chord, previous, ceiling);
}

// HARM.4: chords that go somewhere. The chords are chosen for the whole song at once (Viterbi over half
// bars) instead of bar by bar: besides how well a chord fits the melody (fit), a chord change at a bar line
// scores the move (MOVES: V to I, ii to V and IV to V go somewhere; V back to IV or ii does not), holding a
// chord into a second, third or fourth bar costs STAY more each time, a change in the middle of a bar must
// fit HALF_CHANGE beats better to be worth it (the downbeat doubling of fit is the bar's, not beat 3's), the
// first half bar leans to the tonic by START and the last one by ENDING, when their notes allow. A genre (genre.js) adds its own moves and scales the stay and half-bar costs.
const MOVES = Object.freeze({
  "V>I": 1, "ii>V": 0.8, "IV>V": 0.6, "I>IV": 0.5, "vi>IV": 0.5, "vi>ii": 0.5, "I>V": 0.4, "I>vi": 0.4, "IV>I": 0.4,
  "iii>vi": 0.4, "V>vi": 0.3, "IV>ii": 0.3, "I>ii": 0.3, "V>IV": -0.4, "V>ii": -0.5, "ii>I": -0.2, "iii>IV": 0.2,
  "V>i": 1, "iv>V": 0.6, "VI>V": 0.5, "i>iv": 0.5, "VII>III": 0.5, "i>V": 0.4, "i>VI": 0.4, "VI>iv": 0.4, "iv>i": 0.3,
  "III>iv": 0.3, "i>VII": 0.3, "VII>i": 0.3, "III>VI": 0.3, "V>iv": -0.4, "V>III": -0.4,
});
const STAY = Object.freeze([0.2, 0.6, 1.2]);
const HALF_CHANGE = 2;
const START = 1, ENDING = 2.5;
const TONIC = new Set(["I", "i"]);

// The chord of each half bar: `fits[u][c]` is how well chord c fits half bar u, `empty[u]` that no melody
// sounds there (no change is made in it), `barLine[u]` that it starts a bar. Returns chord indexes.
function progression(chords, fits, empty, barLine, { moves = {}, stay = 1, split = 1 } = {}) {
  const C = chords.length, R = STAY.length + 1, U = fits.length;
  const move = (a, b) => (MOVES[chords[a].roman + ">" + chords[b].roman] || 0) + (moves[chords[a].roman + ">" + chords[b].roman] || 0);
  // score[c * R + r]: the best total ending in chord c held for r + 1 bars (capped).
  let score = new Float64Array(C * R).fill(-Infinity);
  const back = [];
  for (let c = 0; c < C; c++) score[c * R] = fits[0][c];
  for (let u = 1; u < U; u++) {
    const next = new Float64Array(C * R).fill(-Infinity), from = new Int32Array(C * R).fill(-1);
    const offer = (state, value, prev) => { if (value > next[state] + 1e-9) { next[state] = value; from[state] = prev; } };
    for (let a = 0; a < C; a++) for (let r = 0; r < R; r++) {
      const s = score[a * R + r];
      if (s === -Infinity) continue;
      // Holding the chord: free inside a bar and through a bar with no melody.
      if (!barLine[u] || empty[u]) offer(a * R + r, s + fits[u][a], a * R + r);
      else offer(a * R + Math.min(r + 1, R - 1), s + fits[u][a] - STAY[Math.min(r, STAY.length - 1)] * stay, a * R + r);
      if (empty[u]) continue;
      for (let b = 0; b < C; b++) {
        if (b === a) continue;
        offer(b * R, s + fits[u][b] + move(a, b) - (barLine[u] ? 0 : HALF_CHANGE * split), a * R + r);
      }
    }
    back.push(from);
    score = next;
  }
  let state = 0;
  for (let k = 1; k < C * R; k++) if (score[k] > score[state] + 1e-9) state = k;
  const out = new Array(U);
  for (let u = U - 1; u >= 0; u--) {
    out[u] = Math.floor(state / R);
    if (u > 0) state = back[u - 1][state];
  }
  return out;
}

// GENRE.1 bass patterns (genre.js BASS_PATTERNS) for one bar from t: [offset in beats, length in beats,
// semitones above the root]. "rootfifth" is today's (the root on 1, the fifth on 3). A walking line plays
// the root, third and fifth, then the note a semitone below the next bar's root (the fifth again when the
// chord stays), all inside the octave above the root.
function bassBar(pattern, chord, next) {
  const third = chord.quality === "major" ? 4 : 3;
  if (pattern === "roots") return [0, 1, 2, 3].map(b => [b, 1, 0]);
  if (pattern === "held") return [[0, 4, 0]];
  if (pattern === "octaves") return Array.from({ length: 8 }, (_, i) => [i / 2, 0.5, i % 2 ? 12 : 0]);
  if (pattern === "walk") {
    const up = (((next.root - chord.root) % 12) + 12) % 12;
    return [[0, 1, 0], [1, 1, third], [2, 1, 7], [3, 1, up === 0 ? 7 : up - 1]];
  }
  return [[0, 2, 0], [2, 2, 7]];
}

// Generate an accompaniment for the melody in 4/4 bars at the project tempo.
// The bars are groove.js barOrigin's (FIX.3), the grid the starter beat and quantize use: from zero
// when the melody and drums sit on it, else from the first downbeat the onsets agree on; the first
// bar is the one the first melody note falls in, so a pickup does not move the bar lines, and a pickup
// (a first note in the second half of its bar) is left unaccompanied. The chords are chosen for the whole
// song at once (HARM.4, progression): each bar takes a chord of the key, or two for its halves where the
// second fits much better, so the chords move like a progression and end on the tonic when the last notes
// allow; a bar with no melody keeps the previous chord. style "chords" holds a voiced triad, under the
// melody's lowest note in the bar; "bass" plays the root on beat 1 and the fifth on beat 3 (the root alone
// for a half-bar chord). key defaults to detectKey(notes).
// feel (GENRE.1, genre.js harmonyStyle) is a genre's {prior, voicing, rhythm, bass, moves, stay, split};
// null keeps Tandem's own.
// Returns {key, chords:[{t,d,name,roman}], notes:[{m,t,d}]}; the input is unchanged.
export function generateHarmony(project, { style = "chords", key = null, feel = null } = {}) {
  if (!STYLES.includes(style)) throw new Error(`Unknown accompaniment style: ${style}`);
  const bpm = Number(project?.bpm);
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error("Set a tempo before generating harmony.");
  const melody = validNotes(project?.notes).sort((a, b) => a.t - b.t);
  if (!melody.length) throw new Error("Add or transcribe a melody before generating harmony.");
  const useKey = key ?? detectKey(melody);
  if (!useKey) throw new Error("The melody needs at least three notes with two different pitches to find its key; choose a key instead.");
  const chords = chordsForKey(useKey);
  const scalePcs = SCALE_STEPS[useKey.mode].map(x => (useKey.tonic + x) % 12);
  const bar = barSeconds(bpm), beat = bar / BEATS_PER_BAR, half = bar / 2;
  const grid = barOrigin({ bpm, notes: melody, drums: project?.drums || [], grid: project?.grid ?? null });
  const end = Math.max(...melody.map(n => n.t + n.d));
  const first = grid + Math.floor((melody[0].t - grid) / bar + 1e-6) * bar;
  // A pickup (a first note in the second half of its bar) is left unaccompanied, and no chord starts before zero;
  // but a melody that ends before the next bar line is accompanied in its own bar, when that bar starts at zero or later.
  let origin = first;
  if (melody[0].t - first >= bar / 2 - 1e-6 || first < -1e-6) origin += bar;
  if (origin >= end - 1e-6) {
    if (first < -1e-6) throw new Error("The melody ends before the song's first bar line: sing a little longer, or quantize it first.");
    origin = first;
  }
  const bars = Math.max(1, Math.ceil((end - origin) / bar - 1e-6));

  // Two half bars a bar; the prior is shared between them, as it was a bar's.
  const prior = feel ? feel.prior : PRIOR, fits = [], empty = [], barLine = [];
  const sounds = (start, stop) => melody.some(n => n.t < stop && n.t + n.d > start);
  for (let b = 0; b < bars; b++) {
    const start = origin + b * bar, silentBar = !sounds(start, start + bar);
    for (let h = 0; h < 2; h++) {
      const s = start + h * half;
      fits.push(chords.map(c => fit(c, melody, s, s + half, beat, scalePcs, {}, h === 0) + (prior[c.degree] || 0) / 2));
      empty.push(silentBar || (h === 1 && !sounds(s, s + half)));
      barLine.push(h === 0);
    }
  }
  // The song starts at home when its first notes allow, and its last half bar with melody leans to the tonic.
  const lastSung = empty.lastIndexOf(false), tonic = chords.findIndex(c => TONIC.has(c.roman));
  // "Allow": the tonic fits those notes better than not (a last B, the leading tone, is not pulled to I).
  const allows = u => fits[u][tonic] - (prior[chords[tonic].degree] || 0) / 2 > 0;
  const starts = allows(0), ends = lastSung >= 0 && allows(lastSung);
  if (starts) fits[0][tonic] += START;
  if (ends) fits[lastSung][tonic] += ENDING;
  const path = progression(chords, fits, empty, barLine, feel || {});

  // One chord a bar, or one a half bar where the halves differ.
  const spans = [];
  for (let b = 0; b < bars; b++) {
    const [a, z] = [path[2 * b], path[2 * b + 1]], at = origin + b * bar;
    if (a === z) spans.push({ c: chords[a], t: at, d: bar, bar: b });
    else spans.push({ c: chords[a], t: at, d: half, bar: b }, { c: chords[z], t: at + half, d: half, bar: b });
  }
  // The melody's lowest note in each bar; a bar with no melody keeps the last one.
  const ceilings = [];
  for (let b = 0; b < bars; b++) {
    const start = origin + b * bar, under = melody.filter(n => n.t < start + bar - 1e-6 && n.t + n.d > start + 1e-6);
    ceilings.push(under.length ? Math.min(...under.map(n => n.m)) : (ceilings[b - 1] ?? Math.min(...melody.map(n => n.m))));
  }

  const notes = [], chordList = [];
  let previous = null;
  spans.forEach((s, i) => {
    const { c, t: at, d } = s;
    chordList.push({ t: round3(at), d: round3(d), name: c.name, roman: c.roman });
    if (style === "chords") {
      const voiced = feel ? voiceFor(c, previous, feel.voicing, scalePcs, ceilings[s.bar]) : voice(c, previous, ceilings[s.bar]);
      if (voiced.length) previous = voiced;
      const strikes = Math.max(1, Math.round((feel ? RHYTHM_STRIKES[feel.rhythm] || 1 : 1) * d / bar)), each = d / strikes;
      for (let k = 0; k < strikes; k++) for (const m of voiced) notes.push({ m, t: round3(at + k * each), d: round3(each * RELEASE) });
    } else {
      const root = BASS_LOW + ((c.root - BASS_LOW) % 12 + 12) % 12, next = (spans[i + 1] || spans[0]).c;
      const from = (at - (origin + s.bar * bar)) / beat, to = from + d / beat;
      for (const [off, len, up] of bassSpan(feel ? feel.bass : "rootfifth", c, next, from, to)) notes.push({ m: root + up, t: round3(at + (off - from) * beat), d: round3(len * beat * RELEASE) });
    }
  });
  if (notes.length > MAX_HARMONY_NOTES) {
    throw new Error(`The melody is too long for a harmony part: ${bars} bars would need ${notes.length} notes, over the ${MAX_HARMONY_NOTES}-note limit.`);
  }
  return { key: { tonic: useKey.tonic, mode: useKey.mode }, chords: chordList, notes };
}

// A bar's bass pattern for the beats [from, to) of it (the whole bar, or the half a half-bar chord has):
// the pattern's notes starting there, cut at `to`, and the root at `from` when none starts there.
function bassSpan(pattern, chord, next, from, to) {
  const events = bassBar(pattern, chord, next).filter(([off]) => off >= from - 1e-9 && off < to - 1e-9).map(([off, len, up]) => [off, Math.min(len, to - off), up]);
  if (!events.length || events[0][0] > from + 1e-9) events.unshift([from, (events[0]?.[0] ?? to) - from, 0]);
  return events;
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
      const leap = prev === null ? 0 : Math.abs(m - prev);
      const cost = (chord.size && !chord.has(pc(m)) ? 10 : 0) + bias + leap * 0.1 + (leap > LEAP ? LEAP_COST + leap : 0);
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
      let cost = prev === null ? Math.abs(m - (lo + hi) / 2) : m === prev ? 3.5 : Math.abs(m - prev) + (Math.abs(m - prev) > LEAP ? LEAP_COST : 0);
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
// HARM.4: a harmony line moving more than a fourth from one note to the next costs more than a note
// outside the chord, so a line follows a stepwise tune by step instead of leaping a seventh and back.
const LEAP = 5, LEAP_COST = 15;

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
    // The whole line an octave down, or up when the tune is too low for that, so it never jumps between the two.
    octave: () => { const kept = melody.filter(n => pcs.includes(pc(n.m))), by = kept.length && Math.min(...kept.map(n => n.m)) - 12 >= MIN_LINE ? -12 : 12; return kept.map(n => ({ m: n.m + by, t: n.t, d: n.d })); },
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

// CHORD.1: chord symbols for the harmony part, read from its notes (the project keeps no chord
// list, so a symbol is always what the notes say), and a chord changed by rewriting its notes.
// `rank` breaks near-ties in favour of the plainer chord.
export const CHORD_QUALITIES = Object.freeze([
  { id: "major", suffix: "", label: "Major", tones: [0, 4, 7], rank: 0 },
  { id: "minor", suffix: "m", label: "Minor", tones: [0, 3, 7], rank: 0 },
  { id: "dom7", suffix: "7", label: "Seventh", tones: [0, 4, 7, 10], rank: 0.01 },
  { id: "maj7", suffix: "maj7", label: "Major seventh", tones: [0, 4, 7, 11], rank: 0.01 },
  { id: "m7", suffix: "m7", label: "Minor seventh", tones: [0, 3, 7, 10], rank: 0.01 },
  { id: "sus2", suffix: "sus2", label: "Suspended second", tones: [0, 2, 7], rank: 0.02 },
  { id: "sus4", suffix: "sus4", label: "Suspended fourth", tones: [0, 5, 7], rank: 0.02 },
  { id: "dim", suffix: "dim", label: "Diminished", tones: [0, 3, 6], rank: 0.02 },
  { id: "aug", suffix: "aug", label: "Augmented", tones: [0, 4, 8], rank: 0.03 },
  { id: "m7b5", suffix: "m7♭5", label: "Half-diminished", tones: [0, 3, 6, 10], rank: 0.02 },
  { id: "dim7", suffix: "dim7", label: "Diminished seventh", tones: [0, 3, 6, 9], rank: 0.03 },
].map(q => Object.freeze({ ...q, tones: Object.freeze(q.tones) })));
const QUALITY = Object.fromEntries(CHORD_QUALITIES.map(q => [q.id, q]));
// Notes starting this close together are struck together.
const TOGETHER = 0.03;

function checkChord(chord) {
  if (!chord || !Number.isInteger(chord.root) || chord.root < 0 || chord.root > 11 || !QUALITY[chord.quality]) {
    throw new Error("Choose a chord: a root 0..11 and one of the chord kinds.");
  }
  return QUALITY[chord.quality];
}

export function chordName(chord) {
  return KEY_NAMES[chord.root] + checkChord(chord).suffix;
}

// The chord the notes sound inside [start, end), each pitch class weighted by how long it sounds
// there. A chord's tones count for it and other notes against it, a tone of the chord that is not
// played costs a quarter (a tenth for the perfect fifth, which chords often leave out), the lowest note as the root and a chord of the key (chordsForKey) each
// add a little. So a full chord is named exactly, and a root and fifth (a bass line) is the key's
// own chord on that root. Returns {root, quality, name} or null when nothing sounds.
function nameSpan(notes, start, end, key) {
  const w = new Array(12).fill(0);
  let total = 0, low = Infinity;
  for (const n of notes) {
    const o = Math.min(end, n.t + n.d) - Math.max(start, n.t);
    if (o <= 1e-6) continue;
    w[pc(n.m)] += o; total += o; low = Math.min(low, n.m);
  }
  if (!total) return null;
  const inKey = key ? chordsForKey(key) : [];
  let best = null, bestScore = -Infinity;
  for (let root = 0; root < 12; root++) {
    for (const q of CHORD_QUALITIES) {
      const pcs = q.tones.map(x => (root + x) % 12);
      let covered = 0, missing = 0;
      q.tones.forEach((x, i) => { covered += w[pcs[i]]; if (!w[pcs[i]]) missing += x === 7 && q.tones.length === 4 ? 0.4 : 1; });
      let score = (2 * covered - total) / total - 0.25 * missing - q.rank;
      if (pc(low) === root) score += 0.1;
      if (inKey.some(c => c.root === root && c.quality === q.id)) score += 0.05;
      if (score > bestScore + 1e-9) { best = { root, quality: q.id }; bestScore = score; }
    }
  }
  return { ...best, name: chordName(best) };
}

export function nameChord(notes, { key = null } = {}) {
  const clean = validNotes(notes);
  if (!clean.length) return null;
  return nameSpan(clean, Math.min(...clean.map(n => n.t)), Math.max(...clean.map(n => n.t + n.d)), key);
}

// The harmony part's chords in time order: one a 4/4 bar at the tempo, the bars starting at the
// first harmony note (as generateHarmony lays them), and a new one inside a bar where two or more
// pitch classes are struck together and name a different chord. A bar where nothing sounds has
// none. Each is {t, d, root, quality, name, indices}, indices being the notes that start in it.
export function readChords(harmony, { bpm, key = null } = {}) {
  bpm = Number(bpm);
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error("Set a tempo before reading the chords.");
  const notes = validNotes(harmony);
  if (!notes.length) return [];
  const bar = barSeconds(bpm);
  const origin = Math.min(...notes.map(n => n.t)), end = Math.max(...notes.map(n => n.t + n.d));
  const bars = Math.max(1, Math.ceil((end - origin) / bar - 1e-6));
  // GROW.2: each bar looks only at the notes near it (in the part's own order, so each chord is named exactly as
  // before), which keeps a song of thousands of notes quick to read on every redraw.
  const near = Array.from({ length: bars }, () => []);
  for (const n of notes) {
    const first = Math.max(0, Math.floor((n.t - origin) / bar) - 1), last = Math.min(bars - 1, Math.floor((n.t + n.d - origin) / bar) + 1);
    for (let b = first; b <= last; b++) near[b].push(n);
  }
  const out = [];
  for (let b = 0; b < bars; b++) {
    const start = origin + b * bar, stop = start + bar, here = near[b];
    const onsets = [...new Set(here.map(n => n.t))].sort((a, b) => a - b);
    // Where a chord is struck inside the bar (a time within TOGETHER of the bar line is the bar line).
    const cuts = [start];
    for (const t of onsets) {
      if (t < start + TOGETHER || t >= stop - TOGETHER || t - cuts[cuts.length - 1] < TOGETHER) continue;
      const struck = new Set(here.filter(n => Math.abs(n.t - t) < TOGETHER).map(n => pc(n.m)));
      if (struck.size >= 2) cuts.push(t);
    }
    cuts.push(stop);
    let last = null;
    for (let i = 0; i + 1 < cuts.length; i++) {
      const c = nameSpan(here, cuts[i], cuts[i + 1], key);
      if (!c) { last = null; continue; }
      if (last && last.name === c.name) { last.d = round3(cuts[i + 1] - last.t); continue; }
      last = { t: round3(cuts[i]), d: round3(cuts[i + 1] - cuts[i]), ...c };
      out.push(last);
    }
  }
  // Each note that starts in a chord is one of its indices. The chords are in time order, so a binary search finds
  // the last one starting by the note, and the ones before it are checked while they still hold it.
  const eps = 1e-6, list = Array.isArray(harmony) ? harmony : [], valid = new Set(notes);
  for (const c of out) c.indices = [];
  list.forEach((n, i) => {
    if (!valid.has(n)) return;
    let lo = 0, hi = out.length - 1, at = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (out[mid].t - eps <= n.t) { at = mid; lo = mid + 1; } else hi = mid - 1; }
    for (let j = at; j >= 0 && n.t < out[j].t + out[j].d - eps; j--) out[j].indices.push(i);
  });
  return out;
}

// The pitch with pitch class p nearest m (the lower one on a tie), inside the MIDI range.
function nearestPc(m, p) {
  const down = m - (((m - p) % 12) + 12) % 12, up = down + 12;
  const best = m - down <= up - m ? down : up;
  return best < 0 ? best + 12 : best > 127 ? best - 12 : best;
}

// All the chord's tones once, in close position, as near the old voicing as possible.
function voiceNear(pcs, old) {
  const mean = xs => xs.reduce((s, x) => s + x, 0) / xs.length;
  const oldMean = mean(old), oldLow = Math.min(...old);
  let best = null, bestCost = Infinity;
  for (let low = Math.max(0, oldLow - 12); low <= Math.min(127, oldLow + 12); low++) {
    if (!pcs.includes(pc(low))) continue;
    const notes = [low];
    while (notes.length < pcs.length) {
      let m = notes[notes.length - 1] + 1;
      while (!pcs.includes(pc(m)) || notes.some(x => pc(x) === pc(m))) m++;
      notes.push(m);
    }
    if (notes[notes.length - 1] > 127) continue;
    const cost = Math.abs(mean(notes) - oldMean) + 0.5 * Math.abs(low - oldLow);
    if (cost < bestCost - 1e-9) { best = notes; bestCost = cost; }
  }
  return best;
}

// Change one chord from readChords to {root, quality} and return the new harmony notes; the input
// is unchanged. Notes struck three or more together are revoiced as the new chord near where they
// were, with the same start and length; other notes (a bass line, a single line) each move to the
// new chord's tone in the same role (root to root, third to third, fifth to fifth; a note outside
// the old chord moves with the root) in the nearest octave, and when that line would still read as
// another chord, its last one or two notes that are not the root take the new chord's third or
// seventh, whichever makes it read as the chord asked for. A note held into the
// chord from before stops where it starts; a chord with no note of its own gets the new chord voiced
// near the one before it. key is the one readChords was given, so the line is read the same way.
export function changeChord(harmony, chord, to, { key = null } = {}) {
  const q = checkChord(to);
  if (!chord || !Number.isFinite(chord.t) || !Number.isFinite(chord.d) || chord.d <= 0 || !Array.isArray(chord.indices)) {
    throw new Error("Choose a chord of the harmony part to change.");
  }
  const oldQ = checkChord(chord), eps = 1e-6, start = chord.t, end = chord.t + chord.d;
  const notes = validNotes(harmony).map(n => ({ m: n.m, t: n.t, d: n.d }));
  const pcsNew = q.tones.map(x => (to.root + x) % 12);
  const inside = [], kept = [];
  for (const n of notes) {
    if (n.t >= start - eps && n.t < end - eps) inside.push(n);
    else {
      if (n.t < start - eps && n.t + n.d > start + eps) n.d = round3(start - n.t);
      kept.push(n);
    }
  }
  const made = [];
  if (!inside.length) {
    const before = kept.filter(n => n.t < start).sort((a, b) => b.t - a.t);
    const ref = before.length ? before.filter(n => Math.abs(n.t - before[0].t) < TOGETHER).map(n => n.m) : [60];
    for (const m of voiceNear(pcsNew, ref)) made.push({ m, t: round3(start), d: round3((end - start) * RELEASE) });
  } else {
    const groups = [];
    for (const n of [...inside].sort((a, b) => a.t - b.t || a.m - b.m)) {
      const g = groups[groups.length - 1];
      if (g && Math.abs(n.t - g[0].t) < TOGETHER) g.push(n); else groups.push([n]);
    }
    const line = [];
    for (const g of groups) {
      if (g.length >= 3) {
        const voiced = voiceNear(pcsNew, g.map(n => n.m));
        for (const m of voiced) made.push({ m, t: g[0].t, d: g[0].d });
        continue;
      }
      for (const n of g) {
        const role = oldQ.tones.findIndex(x => (chord.root + x) % 12 === pc(n.m));
        const p = role < 0 ? (pc(n.m) - chord.root + to.root + 12) % 12 : (to.root + q.tones[role < q.tones.length ? role : 0]) % 12;
        const m = nearestPc(n.m, p), note = { m, t: n.t, d: n.d };
        made.push(note); line.push({ note, root: role === 0 });
      }
    }
    // A bass line's root and fifth fit several chords: give it the tones that say which.
    const matches = () => { const r = nameSpan([...made, ...kept], start, end, key); return r && r.root === to.root && r.quality === to.quality; };
    // Try the third, then the seventh, on the last note that is not a root, then on the last two,
    // fewest changes first; keep the first that reads as the chord asked for.
    const free = line.filter(x => !x.root).slice(-2).reverse(), first = free.map(x => x.note.m);
    const markers = [q.tones[1], q.tones[3]].filter(x => x !== undefined).map(x => (to.root + x) % 12);
    const tries = [[]];
    for (const a of markers) tries.push([a]);
    if (free.length > 1) for (const a of markers) for (const b of markers) tries.push([a, b]);
    if (!matches()) {
      for (const pcs of tries.slice(1)) {
        free.forEach((x, k) => { x.note.m = k < pcs.length ? nearestPc(first[k], pcs[k]) : first[k]; });
        if (matches()) break;
      }
      if (!matches()) free.forEach((x, k) => { x.note.m = first[k]; });
    }
  }
  const out = [...kept, ...made].sort((a, b) => a.t - b.t || a.m - b.m);
  if (out.length > MAX_HARMONY_NOTES) throw new Error(`That chord would take the harmony part over the ${MAX_HARMONY_NOTES}-note limit.`);
  return out;
}
