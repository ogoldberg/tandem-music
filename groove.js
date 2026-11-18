// Groove tools for the Arrange panel (ARR.1): tempo detection and quantize with swing.
// Pure functions over the tandem-project shape ({bpm, notes:[{m,t,d}], drums:[{k,t}]}),
// imported by index.html and by the Node tests.

// Grid name -> subdivisions per beat.
export const GRID_DIVISIONS = Object.freeze({ "1/4": 1, "1/8": 2, "1/16": 4 });
// Tempo detection searches the project's whole range (FIX.4).
export const TEMPO_RANGE = Object.freeze([45, 220]);

const MIN_ONSETS = 4;
const ONSET_MERGE_SECONDS = 0.01;
// How far an onset may sit from a grid line and still count, as a Gaussian's sigma. FIX.4: 40 ms, wide
// enough for a singer's timing (about 30 ms either way), which a 20 ms window read as off the grid.
const FIT_SIGMA_SECONDS = 0.04;
// The window a beat phase (beatOrigin) and an anchor on it are found with: tighter, as a played grid.
const PHASE_SIGMA_SECONDS = 0.02;
const TEMPO_STEP_BPM = 0.25;
const ANCHORS = 4;
const round6 = x => Math.round(x * 1e6) / 1e6;
// 4/4, as beats.js and harmony.js.
const BEATS_PER_BAR = 4;

// Position of the swung offbeat within a pair of grid steps, as a fraction of the pair:
// 0 swing = 0.5 (straight), 1 = 2/3 (triplet feel).
export function swungOffbeat(swing) {
  const s = Math.max(0, Math.min(1, Number(swing) || 0));
  return 0.5 + s / 6;
}

function onsetTimes(times) {
  const sorted = times.filter(Number.isFinite).slice().sort((a, b) => a - b);
  const out = [];
  for (const t of sorted) if (!out.length || t - out[out.length - 1] > ONSET_MERGE_SECONDS) out.push(t);
  return out;
}

// How well onsets fit a grid with the given spacing, above what random onsets would score.
// The grid is anchored at each of the first few onsets and the best anchor counts.
function gridFit(onsets, spacing) {
  const chance = (FIT_SIGMA_SECONDS * Math.sqrt(2 * Math.PI)) / spacing;
  let best = -Infinity;
  for (let a = 0; a < Math.min(ANCHORS, onsets.length); a++) {
    const anchor = onsets[a];
    let score = 0;
    for (const t of onsets) {
      const x = (t - anchor) / spacing;
      const d = Math.abs(x - Math.round(x)) * spacing;
      score += Math.exp(-(d * d) / (2 * FIT_SIGMA_SECONDS * FIT_SIGMA_SECONDS));
    }
    best = Math.max(best, score - onsets.length * chance);
  }
  return best;
}

// A tempo is scored on both its beat grid and its eighth-note grid, weighted alike (FIX.4: the beat grid
// counted half before; with the 40 ms width that tied quarter notes with half their tempo). The chance term
// stops a finer grid (double tempo) from winning on sloppy timing; the beat term stops half tempo from
// winning when every onset is on the beat (its eighth grid would fit just as well).
function tempoFit(onsets, bpm) {
  return gridFit(onsets, 60 / bpm) + gridFit(onsets, 30 / bpm);
}

// FIX.4: a tempo whose fit is at least this share of the best fit is a near tie.
export const TEMPO_TIE = 0.9;
// After a take timed by a count-in, a click or the song, only this far either side of the project tempo is searched.
export const TIMED_WINDOW = 0.06;
// The time between notes, in beats, that a sung melody mostly moves in (eighths to quarters): of tempos an
// octave apart that fit about as well, the one whose median gap between onsets lies here is the melody's.
const MELODY_GAP_BEATS = Object.freeze([0.45, 1.1]);
const OCTAVE_PEAK = 0.03;

function medianGapBeats(onsets, bpm) {
  const gaps = [];
  for (let i = 1; i < onsets.length; i++) gaps.push((onsets[i] - onsets[i - 1]) * bpm / 60);
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)];
}

function checkRange(range, what) {
  const [lo, hi] = range;
  if (!(Number.isFinite(lo) && Number.isFinite(hi) && lo >= 45 && hi <= 220 && lo < hi)) throw new Error(`${what} lies inside 45..220 bpm.`);
}

// Estimate the tempo (integer bpm) from onset times in seconds, or null when there are too few distinct
// onsets to say. FIX.4:
// - timed (a take sung to a count-in, a click or the song at current): only current +-6% is searched, and
//   current is kept unless a tempo there fits clearly better.
// - otherwise the whole 45..220 is searched; current is kept when it fits about as well as the best (a near
//   tie, TEMPO_TIE); else the answer is folded by octaves: of the best tempo and its doubles and halves that
//   fit about as well (never a 3:2 neighbour), the one the melody mostly moves in eighths to quarters at wins,
//   then one inside prefer (GENRE.1: a genre's likely tempos, a soft preference), then the best fit.
export function estimateTempo(times, { prefer = null, current = null, timed = false } = {}) {
  if (prefer !== null) checkRange(prefer, "A preferred tempo range");
  const now = current === null ? null : Number(current);
  if (now !== null && !(Number.isFinite(now) && now >= 45 && now <= 220)) throw new Error("The current tempo lies inside 45..220 bpm.");
  if (timed && now === null) throw new Error("A timed take needs the tempo it was sung to.");
  const onsets = onsetTimes(times);
  if (onsets.length < MIN_ONSETS) return null;
  const lo = timed ? Math.max(45, now * (1 - TIMED_WINDOW)) : TEMPO_RANGE[0];
  const hi = timed ? Math.min(220, now * (1 + TIMED_WINDOW)) : TEMPO_RANGE[1];
  const scored = [];
  for (let bpm = lo; bpm <= hi + 1e-9; bpm += TEMPO_STEP_BPM) scored.push({ bpm, score: tempoFit(onsets, bpm) });
  const best = scored.reduce((a, b) => (b.score > a.score + 1e-9 ? b : a));
  if (now !== null && tempoFit(onsets, now) >= TEMPO_TIE * best.score) return Math.round(now);
  if (timed) return Math.round(best.bpm);
  const candidates = [];
  for (const k of [-2, -1, 0, 1, 2]) {
    const target = best.bpm * 2 ** k;
    let peak = null;
    for (const s of scored) if (Math.abs(s.bpm / target - 1) <= OCTAVE_PEAK && (!peak || s.score > peak.score)) peak = s;
    if (peak && peak.score >= TEMPO_TIE * best.score) candidates.push(peak);
  }
  const melodic = c => { const g = medianGapBeats(onsets, c.bpm); return g >= MELODY_GAP_BEATS[0] && g <= MELODY_GAP_BEATS[1]; };
  const preferred = c => prefer !== null && c.bpm >= prefer[0] && c.bpm <= prefer[1];
  candidates.sort((a, b) => (melodic(b) - melodic(a)) || (preferred(b) - preferred(a)) || (b.score - a.score));
  return Math.round(candidates[0].bpm);
}

// Where the beat grid sits: the onset phase (within one beat) that the most onsets agree with,
// so a pickup note before the downbeat does not shift the grid. Ties go to the earliest onset.
// Returned as a time at or before the earliest onset.
function beatOrigin(times, beat) {
  const sorted = times.slice().sort((a, b) => a - b);
  let bestPhase = sorted[0], bestScore = -Infinity;
  for (const candidate of sorted) {
    let score = 0;
    for (const t of sorted) {
      const x = (t - candidate) / beat;
      const d = Math.abs(x - Math.round(x)) * beat;
      score += Math.exp(-(d * d) / (2 * PHASE_SIGMA_SECONDS * PHASE_SIGMA_SECONDS));
    }
    if (score > bestScore + 1e-9) { bestScore = score; bestPhase = candidate; }
  }
  // Anchor on the earliest onset in that phase, so the first downbeat stays where it was played.
  const onPhase = t => {
    const x = (t - bestPhase) / beat;
    return Math.abs(x - Math.round(x)) * beat <= 2 * PHASE_SIGMA_SECONDS;
  };
  const anchor = sorted.find(onPhase);
  return anchor - Math.ceil((anchor - sorted[0]) / beat - 1e-9) * beat;
}

// FIX.3: the bar grid chords, the starter beat and quantize share. A time in [0, one bar) where a
// bar starts; every bar line is that time plus whole bars. Zero (the song's own bar 1, where a take
// recorded after the count-in or over the song starts, and where a starter beat starts) when the
// onsets of the melody and drums sit on the beat grid from zero about as well as on any other;
// otherwise the beat the onsets agree on (beatOrigin), with a bar starting at the earliest onset on
// that beat, so a free-time recording keeps its first downbeat where it was sung. An empty project is 0.
// The zero grid is compared with a wider window than beatOrigin's: a singer lands 30 ms or so either side of
// the click, which the 20 ms window would count as off the grid, while a free-time take is off it by far more.
export const ZERO_GRID_SHARE = 0.8;
const ZERO_FIT_SIGMA_SECONDS = 0.05;
export function barOrigin(project) {
  const bpm = Number(project?.bpm);
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error("Set a tempo first.");
  // With no melody or drums, the chords part and the harmony voice give the grid.
  const onsets = list => list.map(e => Number(e.t)).filter(Number.isFinite);
  let times = onsets([...(project.notes || []), ...(project.drums || [])]);
  if (!times.length) times = onsets([...(project.harmony || []), ...(project.voice2 || [])]);
  if (!times.length) return 0;
  const beat = 60 / bpm, bar = beat * BEATS_PER_BAR;
  const fitAt = phase => times.reduce((sum, t) => {
    const x = (t - phase) / beat, d = Math.abs(x - Math.round(x)) * beat;
    return sum + Math.exp(-(d * d) / (2 * ZERO_FIT_SIGMA_SECONDS * ZERO_FIT_SIGMA_SECONDS));
  }, 0);
  const origin = beatOrigin(times, beat);
  if (fitAt(0) >= ZERO_GRID_SHARE * fitAt(origin) - 1e-9) return 0;
  const sorted = times.slice().sort((a, b) => a - b);
  const anchor = sorted.find(t => { const x = (t - origin) / beat; return Math.abs(x - Math.round(x)) * beat <= 2 * PHASE_SIGMA_SECONDS; }) ?? origin;
  return round6(((anchor % bar) + bar) % bar);
}

// Snap note and drum start times to a (possibly swung) grid at the project tempo.
// The grid is barOrigin's: zero when the onsets sit on it, else the beat they agree on (beatOrigin), so
// leading silence is kept. The chords part and the harmony voice (FIX.3) move with the melody on the same grid.
// A pickup stays a pickup only when more onsets fall on the downbeats than on the offbeats;
// with a pickup into even eighths the pickup's phase has as many onsets or more and is taken as the beat.
// Durations are kept. Events that land on the same grid point merge (same pitch: the
// longer note wins; same drum: one hit). Returns new {notes, drums, harmony, voice2}; the input is unchanged.
export function quantizeProject(project, { division, swing = 0, strength = 1 }) {
  if (!Object.values(GRID_DIVISIONS).includes(division)) throw new Error(`Unsupported grid division: ${division}`);
  const bpm = Number(project.bpm);
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error("Set a tempo before quantizing.");
  if (!(strength > 0 && strength <= 1)) throw new Error("Quantize strength must be above 0 and at most 1.");
  const notes = project.notes || [], drums = project.drums || [];
  const harmony = project.harmony || [], voice2 = project.voice2 || [];
  if (!notes.length && !drums.length && !harmony.length && !voice2.length) return { notes: [], drums: [], harmony: harmony.map(n => ({ ...n })), voice2: voice2.map(n => ({ ...n })) };
  const beat = 60 / bpm;
  const origin = barOrigin(project);
  const step = beat / division;
  const pair = 2 * step, off = pair * swungOffbeat(swing);
  const nearest = x => {
    if (division === 1) return Math.round(x / step) * step;
    const p = Math.floor(x / pair);
    const candidates = [p * pair, p * pair + off, (p + 1) * pair];
    return candidates.reduce((a, b) => (Math.abs(b - x) < Math.abs(a - x) ? b : a));
  };
  const snap = t => {
    const x = t - origin, q = nearest(x);
    return Math.max(0, round6(origin + (strength === 1 ? q : x + strength * (q - x))));
  };
  const merged = (events, key, keep) => {
    const byKey = new Map();
    for (const e of events) {
      const k = key(e), prev = byKey.get(k);
      byKey.set(k, prev ? keep(prev, e) : e);
    }
    return [...byKey.values()].sort((a, b) => a.t - b.t);
  };
  const snapNotes = list => merged(list.map(n => ({ ...n, t: snap(n.t) })), n => `${n.m}@${n.t}`, (a, b) => (b.d > a.d ? b : a));
  return {
    notes: snapNotes(notes),
    harmony: snapNotes(harmony),
    voice2: snapNotes(voice2),
    drums: merged(drums.map(h => ({ ...h, t: snap(h.t) })), h => `${h.k}@${h.t}`, a => a),
  };
}
