// GROW.1: the one place bars are worked out. 4/4 is the only time (3/4 was left out on 2026-11-18), so a bar is four
// beats; every module that needs a bar's length or where bars start takes it from here: groove.js (quantize),
// beats.js (starter beats), harmony.js (a chord a bar), phrases.js (copy a phrase a whole number of bars on),
// exercises.js (a warm-up a bar after the song), take.js (the count-in's accents) and sections.js (beats).
// Pure, DOM-free: index.html and the Node tests import it.
//
// The bar grid is a time in [0, one bar) where a bar starts, every bar line being that time plus whole bars. A project
// may pin it in the optional field `grid` {origin} (seconds); a project without it has its grid guessed from the
// onsets every time it is asked for (barOrigin, FIX.3), which an edit that adds or moves notes can change.

export const BEATS_PER_BAR = 4;

const round6 = x => Math.round(x * 1e6) / 1e6;
const EPS = 1e-6;

function tempo(bpm, message) {
  const b = Number(bpm);
  if (!Number.isFinite(b) || b <= 0) throw Error(message);
  return b;
}

// One beat and one bar at `bpm`, in seconds. `message` is the error for a missing tempo, in the words of the caller.
export function beatSeconds(bpm, message = "Set a tempo first.") {
  return 60 / tempo(bpm, message);
}
export function barSeconds(bpm, message = "Set a tempo first.") {
  return (BEATS_PER_BAR * 60) / tempo(bpm, message);
}

// The optional project field `grid`: null when absent, else {origin} with origin at least 0 and under one bar at `bpm`.
// Throws with a message for anything else (an unknown key, a negative origin, one a bar or more).
export function cleanGrid(grid, bpm) {
  if (grid == null) return null;
  if (typeof grid !== "object" || Array.isArray(grid)) throw Error("Invalid bar grid");
  for (const k of Object.keys(grid)) if (k !== "origin") throw Error("Invalid bar grid");
  const origin = grid.origin;
  if (typeof origin !== "number" || !Number.isFinite(origin) || origin < 0) throw Error("The bar grid must start at 0 seconds or later");
  if (origin >= barSeconds(bpm) - EPS) throw Error("The bar grid must start within the first bar");
  return { origin: round6(origin) };
}

// How far an onset may sit from a beat and still count, as a Gaussian's sigma: a played grid (beatOrigin and an anchor
// on it), and the zero grid, which a singer lands 30 ms or so either side of.
const PHASE_SIGMA_SECONDS = 0.02;
export const ZERO_GRID_SHARE = 0.8;
const ZERO_FIT_SIGMA_SECONDS = 0.05;

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

// FIX.3: the bar grid chords, the starter beat and quantize share. A pinned `grid` is returned as it is. Otherwise it is
// guessed: zero (the song's own bar 1, where a take recorded after the count-in or over the song starts, and where a
// starter beat starts) when the onsets of the melody and drums sit on the beat grid from zero about as well as on any
// other; otherwise the beat the onsets agree on (beatOrigin), with a bar starting at the earliest onset on that beat,
// so a free-time recording keeps its first downbeat where it was sung. With no melody or drums, the chords part and
// the harmony voice give it. An empty project is 0.
export function barOrigin(project) {
  const bpm = tempo(project?.bpm, "Set a tempo first.");
  const beat = 60 / bpm, bar = beat * BEATS_PER_BAR;
  if (project.grid != null) return cleanGrid(project.grid, bpm).origin;
  const onsets = list => list.map(e => Number(e.t)).filter(Number.isFinite);
  let times = onsets([...(project.notes || []), ...(project.drums || [])]);
  if (!times.length) times = onsets([...(project.harmony || []), ...(project.voice2 || [])]);
  if (!times.length) return 0;
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

// The project's bar grid: {origin, bar, beat} in seconds, and `pinned` when it comes from the project's `grid`.
export function barGrid(project) {
  const bar = barSeconds(project?.bpm);
  return { origin: barOrigin(project), bar: round6(bar), beat: round6(bar / BEATS_PER_BAR), pinned: project?.grid != null };
}

// The bar line nearest `t` on `grid` ({origin, bar}); never before the first bar line (origin), since the time before
// it is a lead-in, not a bar.
export function snapToBar(t, { origin, bar }) {
  const k = Math.max(0, Math.round((Number(t) - origin) / bar));
  return round6(origin + k * bar);
}

// How many whole bars from `from` to `to` on a grid with bars `bar` long, to the nearest bar; at least 0.
export function barsBetween(from, to, { bar }) {
  return Math.max(0, Math.round((Number(to) - Number(from)) / bar + EPS));
}

// The onsets the song's shape is read from: every note part and the drums.
function firstOnset(project) {
  const ts = [...(project.notes || []), ...(project.drums || []), ...(project.harmony || []), ...(project.voice2 || [])]
    .map(e => Number(e.t)).filter(Number.isFinite);
  return ts.length ? Math.min(...ts) : null;
}

// A pickup: when the song's first onset is less than a beat before a bar line, how long before it, in seconds; else 0.
// A tune with a pickup starts at it, so the song's first bar is the one after the pickup.
export function pickup(project) {
  const t = firstOnset(project);
  if (t === null) return 0;
  const { origin, bar, beat } = barGrid(project);
  const next = origin + Math.ceil((t - origin) / bar - EPS) * bar, gap = next - t;
  return gap > EPS && gap < beat - EPS ? round6(gap) : 0;
}

// The song as whole bars up to `end` seconds: {start, bars}. `start` is the bar line the song's first bar begins on
// (the one after a pickup, else the one at or before the first onset, never before the first bar line), and `bars`
// how many whole bars from there reach `end`, at least 1. An empty song starts at the first bar line.
export function songBars(project, end) {
  const { origin, bar } = barGrid(project);
  const t = firstOnset(project);
  let start = origin;
  if (t !== null) {
    const lift = pickup(project);
    start = lift ? t + lift : origin + Math.floor((t - origin) / bar + EPS) * bar;
    start = Math.max(origin, start);
  }
  const bars = Math.max(1, Math.ceil((Number(end) - start) / bar - EPS));
  return { start: round6(start), bars };
}

// GROW.1: once the grid is pinned the speed can only be doubled or halved, so bar lines stay bar lines (a bar at the
// new speed is half or twice as long and starts on the same lines). The speeds the song can go to, inside the studio's
// range: every speed when the grid is not pinned (null).
export const TEMPO_LIMITS = Object.freeze([45, 220]);
export function pinnedSpeeds(project) {
  if (project?.grid == null) return null;
  const bpm = Number(project.bpm);
  return [bpm / 2, bpm * 2].filter(b => b >= TEMPO_LIMITS[0] && b <= TEMPO_LIMITS[1]).map(round6);
}
export function pinnedSpeedText(project) {
  const speeds = pinnedSpeeds(project);
  if (!speeds) return "";
  // One of the two is always inside 45 to 220, which is narrower than a doubling either way.
  return "The song's bars are pinned, so its speed can only be doubled or halved: " + speeds.join(" or ") + " beats a minute.";
}

// The project's fields after a change of speed to `bpm`: {bpm} when the grid is not pinned, else {bpm, grid} with the
// origin brought inside the new bar (a doubled speed halves the bar). Throws pinnedSpeedText's reason for any other
// speed while it is pinned.
export function speedChange(project, bpm) {
  const to = Number(bpm);
  if (project?.grid == null || to === Number(project.bpm)) return project?.grid == null ? { bpm: to } : { bpm: to, grid: { ...project.grid } };
  if (!pinnedSpeeds(project).some(b => Math.abs(b - to) < EPS)) throw Error(pinnedSpeedText(project));
  const bar = barSeconds(to), origin = cleanGrid(project.grid, project.bpm).origin;
  return { bpm: to, grid: { origin: round6(((origin % bar) + bar) % bar) } };
}
