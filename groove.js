// Groove tools for the Arrange panel (ARR.1): tempo detection and quantize with swing.
// Pure functions over the tandem-project shape ({bpm, notes:[{m,t,d}], drums:[{k,t}]}),
// imported by index.html and by the Node tests.

// Grid name -> subdivisions per beat.
export const GRID_DIVISIONS = Object.freeze({ "1/4": 1, "1/8": 2, "1/16": 4 });
// Tempo detection searches this range; the project itself allows 45..220.
export const TEMPO_RANGE = Object.freeze([60, 180]);

const MIN_ONSETS = 4;
const ONSET_MERGE_SECONDS = 0.01;
const FIT_SIGMA_SECONDS = 0.02;
const TEMPO_STEP_BPM = 0.25;
const ANCHORS = 4;
const round6 = x => Math.round(x * 1e6) / 1e6;

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

// A tempo is scored on both its beat grid and its eighth-note grid. The chance term stops a
// finer grid (double tempo) from winning on sloppy timing; the beat term stops half tempo
// from winning when every onset is on the beat (its eighth grid would fit just as well).
function tempoFit(onsets, bpm) {
  return 0.5 * gridFit(onsets, 60 / bpm) + gridFit(onsets, 30 / bpm);
}

// Estimate the tempo (integer bpm) from onset times in seconds, or null when there are
// too few distinct onsets to say.
export function estimateTempo(times) {
  const onsets = onsetTimes(times);
  if (onsets.length < MIN_ONSETS) return null;
  let bestBpm = null, bestScore = -Infinity;
  for (let bpm = TEMPO_RANGE[0]; bpm <= TEMPO_RANGE[1] + 1e-9; bpm += TEMPO_STEP_BPM) {
    const score = tempoFit(onsets, bpm);
    if (score > bestScore + 1e-9) { bestScore = score; bestBpm = bpm; }
  }
  return Math.round(bestBpm);
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
      score += Math.exp(-(d * d) / (2 * FIT_SIGMA_SECONDS * FIT_SIGMA_SECONDS));
    }
    if (score > bestScore + 1e-9) { bestScore = score; bestPhase = candidate; }
  }
  // Anchor on the earliest onset in that phase, so the first downbeat stays where it was played.
  const onPhase = t => {
    const x = (t - bestPhase) / beat;
    return Math.abs(x - Math.round(x)) * beat <= 2 * FIT_SIGMA_SECONDS;
  };
  const anchor = sorted.find(onPhase);
  return anchor - Math.ceil((anchor - sorted[0]) / beat - 1e-9) * beat;
}

// Snap note and drum start times to a (possibly swung) grid at the project tempo.
// The grid follows the beat the onsets agree on (see beatOrigin), so leading silence is kept.
// A pickup stays a pickup only when more onsets fall on the downbeats than on the offbeats;
// on a tie (a pickup into even eighths) the pickup's phase is taken as the beat.
// Durations are kept. Events that land on the same grid point merge (same pitch: the
// longer note wins; same drum: one hit). Returns new {notes, drums}; the input is unchanged.
export function quantizeProject(project, { division, swing = 0, strength = 1 }) {
  if (!Object.values(GRID_DIVISIONS).includes(division)) throw new Error(`Unsupported grid division: ${division}`);
  const bpm = Number(project.bpm);
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error("Set a tempo before quantizing.");
  if (!(strength > 0 && strength <= 1)) throw new Error("Quantize strength must be above 0 and at most 1.");
  const notes = project.notes || [], drums = project.drums || [];
  const all = [...notes, ...drums].map(e => e.t);
  if (!all.length) return { notes: [], drums: [] };
  const beat = 60 / bpm;
  const origin = beatOrigin(all, beat);
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
  return {
    notes: merged(notes.map(n => ({ ...n, t: snap(n.t) })), n => `${n.m}@${n.t}`, (a, b) => (b.d > a.d ? b : a)),
    drums: merged(drums.map(h => ({ ...h, t: snap(h.t) })), h => `${h.k}@${h.t}`, a => a),
  };
}
