// SONG.1: song sections. A section is a named stretch of the song, {name, from, to} in seconds, kept in the
// project's optional `sections` list in time order, never overlapping (gaps between them are allowed).
// Repeat, Move and Delete edit every note part at once (SECTION_PARTS: melody, chords, harmony voice,
// drums); the recordings (takes, layers, band, voice as instrument, sung harmony) stay where they are.
// A note or hit belongs to the section its start is in; a note keeps its length, except that Delete cuts a
// note held into the deleted section at the section's start, so it does not sound over what follows.
// A project with no sections has no `sections` field, so an older project opens, saves and exports as before.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectSection mirrors cleanSections.

export const MAX_SECTIONS = 32;
export const MAX_SECTION_NAME = 40;
export const MAX_TIME = 600;
// The same shortest stretch the Timeline marks to loop (playhead.js loopRegion).
export const MIN_SECTION_SECONDS = 0.25;
// Each part's note cap, as in the project schema (ProjectNote/ProjectHit lists in tandem_backend.py).
export const MAX_EVENTS = 1024;
export const SECTION_NAMES = Object.freeze(["Intro", "Verse", "Pre-chorus", "Chorus", "Bridge", "Solo", "Outro"]);
export const SECTION_PARTS = Object.freeze(["notes", "harmony", "voice2", "drums"]);
const PART_NAMES = { notes: "melody", harmony: "chords", voice2: "harmony voice", drums: "drums" };
// Times within a millisecond count as equal, so rounded times do not fall on the wrong side of a boundary.
const EPS = 1e-3;
const round3 = x => Math.round(x * 1000) / 1000;
const isObject = x => !!x && typeof x === "object" && !Array.isArray(x);
const isTime = x => typeof x === "number" && Number.isFinite(x);

function cleanName(name) {
  const clean = typeof name === "string" ? name.trim() : "";
  if (!clean || clean.length > MAX_SECTION_NAME) throw Error("Give the section a name of up to " + MAX_SECTION_NAME + " characters.");
  return clean;
}

// The section list with every value checked. Throws on anything else, like the other project checks, so a
// bad file is refused rather than half read. A missing list is no sections.
export function cleanSections(sections) {
  if (sections == null) return [];
  if (!Array.isArray(sections) || sections.length > MAX_SECTIONS) throw Error("Invalid sections");
  let end = 0;
  return sections.map(s => {
    if (!isObject(s)) throw Error("Invalid section");
    for (const k of Object.keys(s)) if (!["name", "from", "to"].includes(k)) throw Error("Invalid section");
    if (typeof s.name !== "string") throw Error("Invalid section name");
    const name = cleanName(s.name);
    if (!isTime(s.from) || !isTime(s.to) || s.from < 0 || s.to > MAX_TIME || s.to <= s.from) throw Error("Invalid section times");
    if (s.from < end - EPS) throw Error("Sections must be in order and not overlap");
    end = s.to;
    return { name, from: s.from, to: s.to };
  });
}

// A time at the nearest beat of the project tempo, so a section marked by dragging on the Timeline
// starts and ends on the beat.
export function snapToBeat(t, bpm) {
  const b = Number(bpm);
  if (!Number.isFinite(b) || b <= 0) throw Error("Set a tempo before marking sections.");
  const beat = 60 / b;
  return round3(Math.max(0, Math.round(t / beat) * beat));
}

// The index of the section that holds time t, or -1.
export function sectionAt(sections, t) {
  return cleanSections(sections).findIndex(s => t >= s.from - EPS && t < s.to - EPS);
}

// The list with a new section {name, from, to} in its place in time order. Refused when it overlaps one.
export function markSection(sections, { name, from, to }) {
  const list = cleanSections(sections);
  const clean = cleanName(name);
  if (!isTime(from) || !isTime(to)) throw Error("Choose where the section starts and ends.");
  const f = round3(Math.max(0, Math.min(from, to))), e = round3(Math.min(MAX_TIME, Math.max(from, to)));
  if (e - f < MIN_SECTION_SECONDS - EPS) throw Error("That section is too short: mark at least a quarter of a second.");
  const hit = list.find(s => f < s.to - EPS && e > s.from + EPS);
  if (hit) throw Error(`That section overlaps ${hit.name}; unmark it first or mark a stretch outside it.`);
  if (list.length >= MAX_SECTIONS) throw Error(`A song can have at most ${MAX_SECTIONS} sections.`);
  return cleanSections([...list, { name: clean, from: f, to: e }].sort((a, b) => a.from - b.from));
}

function checkIndex(list, i) {
  if (!Number.isInteger(i) || i < 0 || i >= list.length) throw Error("Choose a section first.");
}

// The list without section i; the notes in it stay where they are.
export function unmarkSection(sections, i) {
  const list = cleanSections(sections);
  checkIndex(list, i);
  return list.filter((_, k) => k !== i);
}

// Every note part of the project, each event moved by `shift(t)` (null drops it; an array of shifts
// copies it once per shift), with the limits checked. `trim(n)` may give a note a new length.
function rework(project, shift, trim = null) {
  const out = {};
  for (const part of SECTION_PARTS) {
    const events = Array.isArray(project[part]) ? project[part] : [];
    const moved = [], copies = [];
    for (const ev of events) {
      const s = shift(ev.t);
      if (s == null) continue;
      const [first, ...more] = Array.isArray(s) ? s : [s];
      const keep = { ...ev, t: round3(ev.t + first) };
      if (trim && "d" in ev) keep.d = trim(ev, keep);
      moved.push(keep);
      for (const m of more) copies.push({ ...ev, t: round3(ev.t + m) });
    }
    const all = [...moved, ...copies];
    if (all.length > MAX_EVENTS) throw Error(`The ${PART_NAMES[part]} would have more than ${MAX_EVENTS} notes.`);
    if (all.some(ev => ev.t > MAX_TIME + EPS)) throw Error(`The ${PART_NAMES[part]} would go past ${MAX_TIME} seconds.`);
    out[part] = all;
  }
  return out;
}

const inside = (t, s) => t >= s.from - EPS && t < s.to - EPS;

// A copy of section i right after it, in every note part, with everything after it moved later by the
// section's length. Returns {notes, harmony, voice2, drums, sections, index}: index is the copy's.
export function repeatSection(project, i) {
  const list = cleanSections(project.sections);
  checkIndex(list, i);
  const s = list[i], len = round3(s.to - s.from);
  if (list.length >= MAX_SECTIONS) throw Error(`A song can have at most ${MAX_SECTIONS} sections.`);
  if (list[list.length - 1].to + len > MAX_TIME + EPS) throw Error(`The song would go past ${MAX_TIME} seconds.`);
  const parts = rework(project, t => (inside(t, s) ? [0, len] : t >= s.to - EPS ? len : 0));
  const sections = [
    ...list.slice(0, i + 1), { name: s.name, from: s.to, to: round3(s.to + len) },
    ...list.slice(i + 1).map(x => ({ ...x, from: round3(x.from + len), to: round3(x.to + len) })),
  ];
  return { ...parts, sections: cleanSections(sections), index: i + 1 };
}

// Section i and its notes taken out of every note part, with everything after it moved earlier by its
// length. A note held into it from before is cut at its start. Returns {notes, harmony, voice2, drums, sections}.
export function deleteSection(project, i) {
  const list = cleanSections(project.sections);
  checkIndex(list, i);
  const s = list[i], len = round3(s.to - s.from);
  const parts = rework(project, t => (inside(t, s) ? null : t >= s.to - EPS ? -len : 0),
    (ev, kept) => (ev.t < s.from - EPS && ev.t + ev.d > s.from + EPS ? round3(s.from - ev.t) : kept.d));
  const sections = [...list.slice(0, i), ...list.slice(i + 1).map(x => ({ ...x, from: round3(x.from - len), to: round3(x.to - len) }))];
  return { ...parts, sections: cleanSections(sections) };
}

// Section i swapped with the one before it (dir -1) or after it (dir 1), in every note part. The stretch
// between the two keeps its length and stays between them, so nothing outside the pair moves.
// Returns {notes, harmony, voice2, drums, sections, index}: index is the moved section's new place.
export function moveSection(project, i, dir) {
  const list = cleanSections(project.sections);
  checkIndex(list, i);
  if (dir !== -1 && dir !== 1) throw Error("Choose whether to move the section earlier or later.");
  if (dir === -1 && i === 0) throw Error(`${list[i].name} is already the first section.`);
  if (dir === 1 && i === list.length - 1) throw Error(`${list[i].name} is already the last section.`);
  const a = dir === 1 ? i : i - 1, b = a + 1, A = list[a], B = list[b];
  const lenA = A.to - A.from, lenB = B.to - B.from, gap = { from: A.to, to: B.from };
  const shiftB = A.from - B.from, shiftGap = A.from + lenB - A.to, shiftA = lenB + (B.from - A.to);
  const parts = rework(project, t => (inside(t, A) ? shiftA : inside(t, B) ? shiftB : gap.to - gap.from > EPS && inside(t, gap) ? shiftGap : 0));
  const sections = list.map((x, k) => {
    if (k === a) return { ...B, from: round3(A.from), to: round3(A.from + lenB) };
    if (k === b) return { ...A, from: round3(B.to - lenA), to: round3(B.to) };
    return x;
  });
  return { ...parts, sections: cleanSections(sections), index: dir === 1 ? b : a };
}
