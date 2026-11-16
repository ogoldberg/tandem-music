// SILENT.2: a melody drawn as a line on the roll becomes notes in the key. The line is read the way
// a sung pitch line is (contour.js): each point snaps to the key's scale, a pitch held makes one note
// (sungNotes), a quick slide joins the note it settles on, and the notes land on the project's grid.
// Pure and DOM-free so Node tests import it directly.

import { sungNotes, snapToScale, MIN_MIDI, MAX_MIDI } from "./contour.js";
import { keyPitchClasses, snapTime } from "./noteedit.js";

// The drawn line is sampled every LINE_FRAME seconds of song time before it is read.
export const LINE_FRAME = 0.01;
// A line shorter than this in song time makes no note (sungNotes' shortest voiced run).
export const MIN_LINE_SECONDS = 0.05;

const round3 = x => Math.round(x * 1000) / 1000;

// The points of a stroke as a line in time: only finite points, each later than the one kept before
// it, so drawing back over the line does not fold it. points: [{t, m}] with m fractional MIDI.
export function linePoints(points) {
  const out = [];
  for (const p of points || []) {
    if (!p || !Number.isFinite(p.t) || !Number.isFinite(p.m) || p.t < 0) continue;
    if (out.length && p.t <= out.at(-1).t) continue;
    out.push({ t: p.t, m: p.m });
  }
  return out;
}

// The line sampled every `dt` s from its first point to its last, joining points with straight lines.
export function sampleLine(points, dt = LINE_FRAME) {
  const p = linePoints(points);
  if (p.length < 2) return { t: new Float64Array(0), m: new Float64Array(0) };
  const t0 = p[0].t, n = Math.floor((p.at(-1).t - t0) / dt + 1e-9) + 1;
  const t = new Float64Array(n), m = new Float64Array(n);
  let j = 0;
  for (let i = 0; i < n; i++) {
    const at = t0 + i * dt;
    while (j < p.length - 2 && p[j + 1].t < at) j++;
    const a = p[j], b = p[j + 1], f = Math.min(1, Math.max(0, (at - a.t) / (b.t - a.t)));
    t[i] = at;
    m[i] = a.m + (b.m - a.m) * f;
  }
  return { t, m };
}

// The notes a drawn line makes. points: [{t, m}] in song seconds and fractional MIDI; bpm and
// division (notes a beat: 1, 2 or 4) give the grid; key {tonic, mode} gives the scale.
// Returns [{m, t, d}] in time order, every pitch in the key, every start and end on the grid.
export function lineNotes(points, { bpm, division = 4, key } = {}) {
  if (!(Number.isFinite(bpm) && bpm > 0)) throw Error("The tempo must be a positive number.");
  if (![1, 2, 4].includes(division)) throw Error("The grid must be 1, 2 or 4 notes a beat.");
  const pcs = keyPitchClasses(key);
  const line = sampleLine(points);
  if (line.t.length < 2 || line.t.at(-1) - line.t[0] < MIN_LINE_SECONDS) throw Error("Draw a longer line: it is too short to make a note.");
  const snapped = { t: line.t, m: Float64Array.from(line.m, v => snapToScale(Math.min(MAX_MIDI, Math.max(MIN_MIDI, v)), pcs)) };
  const held = sungNotes(snapped, () => 1);
  const step = 60 / bpm / division, out = [];
  for (const n of held) {
    const m = snapToScale(n.m, pcs);
    const t = snapTime(n.t, bpm, division);
    let end = snapTime(n.t + n.d, bpm, division);
    if (end <= t) end = t + step;
    const prev = out.at(-1);
    if (prev && t < prev.end) {
      prev.end = t;
      if (prev.end <= prev.t + 1e-9) out.pop();
    }
    const last = out.at(-1);
    if (last && last.m === m && Math.abs(last.end - t) < 1e-9) { last.end = end; continue; }
    out.push({ m, t, end });
  }
  return out.map(n => ({ m: n.m, t: round3(n.t), d: round3(n.end - n.t) }));
}

// The melody with the drawn notes in place of the notes in their span (from the first drawn note's
// start to the last one's end): a note starting in the span goes, a note starting before it is cut
// at its start, the rest stay. Returns {notes, indices, replaced}: the new melody in time order, the
// indices of the drawn notes in it and how many notes were taken out or cut.
export function withLine(notes, drawn) {
  if (!drawn?.length) throw Error("The line made no notes.");
  const from = drawn[0].t, to = Math.max(...drawn.map(n => n.t + n.d));
  const kept = [];
  let replaced = 0;
  for (const n of notes || []) {
    if (n.t >= to - 1e-9 || n.t + n.d <= from + 1e-9) { kept.push({ ...n }); continue; }
    replaced++;
    if (n.t < from - 1e-9) kept.push({ ...n, d: round3(from - n.t) });
  }
  const all = [...kept.map(n => ({ n, drawn: false })), ...drawn.map(n => ({ n: { ...n }, drawn: true }))];
  all.sort((a, b) => a.n.t - b.n.t || a.n.m - b.n.m);
  const indices = [];
  all.forEach((x, i) => { if (x.drawn) indices.push(i); });
  return { notes: all.map(x => x.n), indices, replaced };
}
