// PLAY.1: the timing of play from here and of a looped section, kept pure so Node can test it.
// Playing is a list of segments: { at, from, to } plays the song from `from` to `to` starting `at`
// seconds after Play. Without a loop that is one segment to the end of the song; with one it is the
// start point to the loop's end, then the loop again and again until Stop.

// The shortest loop: a drag shorter than this is a click, and a shorter loop would stutter.
export const MIN_LOOP = 0.25;
// A clipped note shorter than this is left out rather than played as a click.
const SLIVER = 0.001;

// A loop between two times in either order, kept inside the song; null when too short.
export function loopRegion(a, b, end) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const start = Math.max(0, Math.min(a, b)), stop = Math.min(Math.max(a, b), Number.isFinite(end) ? end : Infinity);
  return stop - start >= MIN_LOOP ? { start, end: stop } : null;
}

const looping = (from, loop) => !!loop && from < loop.end;

// The segments to play, one at a time from next(); null when there are no more.
export function createPlan({ from = 0, loop = null } = {}) {
  let at = 0, first = true;
  return {
    next() {
      if (first) {
        first = false;
        const seg = { at: 0, from, to: looping(from, loop) ? loop.end : Infinity };
        at = seg.to - seg.from;
        return seg;
      }
      if (!looping(from, loop)) return null;
      const seg = { at, from: loop.start, to: loop.end };
      at += loop.end - loop.start;
      return seg;
    },
  };
}

// The time in the song `elapsed` seconds after Play started at `from`, wrapping inside the loop;
// null before the song has started (a count-in).
export function songTime(elapsed, { from = 0, loop = null } = {}) {
  if (!(elapsed >= 0)) return null;
  const t = from + elapsed;
  if (!looping(from, loop) || t < loop.end) return t;
  const len = loop.end - loop.start;
  return loop.start + ((t - loop.end) % len);
}

// The part of each note inside [from, to), timed from `from`.
export function clipNotes(notes, from, to) {
  const out = [];
  for (const n of notes || []) {
    const start = Math.max(n.t, from), end = Math.min(n.t + n.d, to);
    if (end - start >= SLIVER) out.push({ ...n, t: start - from, d: end - start });
  }
  return out;
}

// The drum hits inside [from, to), timed from `from`.
export function clipHits(hits, from, to) {
  return (hits || []).filter(h => h.t >= from && h.t < to).map(h => ({ ...h, t: h.t - from }));
}

// The project with every part clipped to [from, to); the project itself is not changed.
export function clipProject(project, from, to) {
  return {
    ...project,
    notes: clipNotes(project.notes, from, to),
    harmony: clipNotes(project.harmony, from, to),
    voice2: clipNotes(project.voice2, from, to),
    drums: clipHits(project.drums, from, to),
  };
}

// The length the timeline and every roll show, so a time is at the same place in each: the end
// of the longest part (a drum hit drawn 0.3 s wide), the band, the voice as instrument and the sung
// harmony unless muted, and any `extra` notes shown (a harmony line being tried), at least 8 s.
export function timelineEnd(project, extra = []) {
  const notes = [...(project.notes || []), ...(project.harmony || []), ...(project.voice2 || []), ...extra];
  const ends = notes.map(n => (n.t || 0) + (n.d || 0.3))
    .concat((project.drums || []).map(h => (h.t || 0) + 0.3))
    .concat(["band", "timbre", "voice2_sung"].flatMap(k => project[k] && !project[k].muted && Number.isFinite(project[k].seconds) ? [project[k].seconds] : []));
  return Math.max(8, ...ends);
}
