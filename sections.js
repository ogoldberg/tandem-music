// SONG.1: song sections. A section is a named stretch of the song, {name, from, to} in seconds, kept in the
// project's optional `sections` list in time order, never overlapping (gaps between them are allowed).
// Repeat, Move and Delete edit every note part at once (SECTION_PARTS: melody, chords, harmony voice,
// drums) and, GROW.3 (ADR-018), where every recording plays (placement.js): no recording is cut or rewritten,
// but its clips are repeated, moved and taken out with the notes, in the same edit.
// A note or hit belongs to the section its start is in; a note keeps its length, except that Delete cuts a
// note held into the deleted section at the section's start, so it does not sound over what follows.
// A project with no sections has no `sections` field, so an older project opens, saves and exports as before.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectSection mirrors cleanSections.

import { barGrid, beatSeconds, songBars } from "./bars.js";
import { tonicChord } from "./harmony.js";
import { cleanPlaced, clipsOf, deleteClips, moveClips, repeatClips, shiftClips, withClips } from "./placement.js";

export const MAX_SECTIONS = 32;
export const MAX_SECTION_NAME = 40;
export const MAX_TIME = 600;
// The same shortest stretch the Timeline marks to loop (playhead.js loopRegion).
export const MIN_SECTION_SECONDS = 0.25;
// GROW.2: each part's note cap in the studio, room for a whole song (phrases.js MAX_MELODY_NOTES and harmony.js
// MAX_HARMONY_NOTES are the same; a Node test checks). The chat carries fewer (actions.js CHAT_LIMITS).
export const MAX_EVENTS = 4096;
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
  const beat = beatSeconds(bpm, "Set a tempo before marking sections.");
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

// GROW.3: every recording channel's clips after `op(clips, key)`. `lengths` gives each recording the song has
// ({voice, band, timbre, voice2_sung, "layer-<id>"}: its length in seconds), so a channel with no entry (the
// whole recording from zero) can be placed; a channel back at the whole recording from zero has no entry again.
function rePlace(project, lengths, op) {
  const placed = cleanPlaced(project.placed);
  const keys = new Set([...Object.keys(placed || {}), ...Object.entries(lengths || {}).filter(([, s]) => s > 0).map(([k]) => k)]);
  let out = placed;
  for (const key of keys) {
    const seconds = lengths?.[key] || 0, clips = clipsOf(placed, key, seconds);
    out = withClips(out, key, op(clips, key), seconds);
  }
  return out;
}

// A copy of section i right after it, in every note part and every recording's clips, with everything after it
// moved later by the section's length. Returns {notes, harmony, voice2, drums, placed, sections, index}: index is
// the copy's; placed is null when every recording plays whole from zero.
export function repeatSection(project, i, { lengths = {} } = {}) {
  const list = cleanSections(project.sections);
  checkIndex(list, i);
  const s = list[i], len = round3(s.to - s.from);
  if (list.length >= MAX_SECTIONS) throw Error(`A song can have at most ${MAX_SECTIONS} sections.`);
  if (list[list.length - 1].to + len > MAX_TIME + EPS) throw Error(`The song would go past ${MAX_TIME} seconds.`);
  const parts = rework(project, t => (inside(t, s) ? [0, len] : t >= s.to - EPS ? len : 0));
  const placed = rePlace(project, lengths, (clips, key) => repeatClips(clips, s, key));
  const sections = [
    ...list.slice(0, i + 1), { name: s.name, from: s.to, to: round3(s.to + len) },
    ...list.slice(i + 1).map(x => ({ ...x, from: round3(x.from + len), to: round3(x.to + len) })),
  ];
  return { ...parts, placed, sections: cleanSections(sections), index: i + 1 };
}

// Section i and its notes taken out of every note part and every recording's clips, with everything after it
// moved earlier by its length. A note held into it from before is cut at its start.
// Returns {notes, harmony, voice2, drums, placed, sections}.
export function deleteSection(project, i, { lengths = {} } = {}) {
  const list = cleanSections(project.sections);
  checkIndex(list, i);
  const s = list[i], len = round3(s.to - s.from);
  const parts = rework(project, t => (inside(t, s) ? null : t >= s.to - EPS ? -len : 0),
    (ev, kept) => (ev.t < s.from - EPS && ev.t + ev.d > s.from + EPS ? round3(s.from - ev.t) : kept.d));
  const placed = rePlace(project, lengths, (clips, key) => deleteClips(clips, s, key));
  const sections = [...list.slice(0, i), ...list.slice(i + 1).map(x => ({ ...x, from: round3(x.from - len), to: round3(x.to - len) }))];
  return { ...parts, placed, sections: cleanSections(sections) };
}

// Section i swapped with the one before it (dir -1) or after it (dir 1), in every note part and every recording's
// clips. The stretch between the two keeps its length and stays between them, so nothing outside the pair moves.
// Returns {notes, harmony, voice2, drums, placed, sections, index}: index is the moved section's new place.
export function moveSection(project, i, dir, { lengths = {} } = {}) {
  const list = cleanSections(project.sections);
  checkIndex(list, i);
  if (dir !== -1 && dir !== 1) throw Error("Choose whether to move the section earlier or later.");
  if (dir === -1 && i === 0) throw Error(`${list[i].name} is already the first section.`);
  if (dir === 1 && i === list.length - 1) throw Error(`${list[i].name} is already the last section.`);
  const a = dir === 1 ? i : i - 1, b = a + 1, A = list[a], B = list[b];
  const lenA = A.to - A.from, lenB = B.to - B.from, gap = { from: A.to, to: B.from };
  const shiftB = A.from - B.from, shiftGap = A.from + lenB - A.to, shiftA = lenB + (B.from - A.to);
  const parts = rework(project, t => (inside(t, A) ? shiftA : inside(t, B) ? shiftB : gap.to - gap.from > EPS && inside(t, gap) ? shiftGap : 0));
  const placed = rePlace(project, lengths, (clips, key) => moveClips(clips, A, B, key));
  const sections = list.map((x, k) => {
    if (k === a) return { ...B, from: round3(A.from), to: round3(A.from + lenB) };
    if (k === b) return { ...A, from: round3(B.to - lenA), to: round3(B.to) };
    return x;
  });
  return { ...parts, placed, sections: cleanSections(sections), index: dir === 1 ? b : a };
}

// SONG.3: an intro and an ending, each one edit that marks an Intro or Outro section.
export const INTRO_BARS = Object.freeze([1, 2]);
const checkLimits = (part, events) => {
  if (events.length > MAX_EVENTS) throw Error(`The ${PART_NAMES[part]} would have more than ${MAX_EVENTS} notes.`);
  if (events.some(ev => ev.t > MAX_TIME + EPS)) throw Error(`The ${PART_NAMES[part]} would go past ${MAX_TIME} seconds.`);
};

// One or two bars before the song's first bar (bars.js songBars: the bar after a pickup), playing the first bars of
// the chords and the drums the song has; the melody and the harmony voice are not copied. Everything, the sections
// and where every recording plays (GROW.3) included, moves later by the intro, whole bars, so the bar grid stays.
// A chord held past the intro is cut at its end. Refused with no chords or drums in those bars, or when a section is
// named Intro already. Returns {notes, harmony, voice2, drums, placed, sections, index}: index is the Intro's.
export function addIntro(project, { bars = 2, lengths = {} } = {}) {
  if (!INTRO_BARS.includes(bars)) throw Error("Choose an intro of one or two bars.");
  const list = cleanSections(project.sections);
  if (list.some(s => s.name === "Intro")) throw Error("The song has an intro already: delete that section to make another.");
  if (list.length >= MAX_SECTIONS) throw Error(`A song can have at most ${MAX_SECTIONS} sections.`);
  const { bar } = barGrid(project), { start } = songBars(project, 0), by = bars * bar, to = start + by;
  const out = {};
  let copied = 0;
  for (const part of SECTION_PARTS) {
    const events = Array.isArray(project[part]) ? project[part] : [];
    const copies = part === "harmony" || part === "drums"
      ? events.filter(ev => ev.t >= start - EPS && ev.t < to - EPS).map(ev => ("d" in ev ? { ...ev, d: round3(Math.min(ev.d, to - ev.t)) } : { ...ev }))
      : [];
    copied += copies.length;
    out[part] = [...copies, ...events.map(ev => ({ ...ev, t: round3(ev.t + by) }))];
    checkLimits(part, out[part]);
  }
  if (!copied) throw Error("Add chords or a beat first: the intro plays the first bars of them before the tune.");
  const placed = rePlace(project, lengths, (clips, key) => shiftClips(clips, by, key));
  const moved = list.map(x => ({ ...x, from: round3(x.from + by), to: round3(x.to + by) }));
  const end = Math.min(to, moved.length ? moved[0].from : to);
  const intro = end - start >= MIN_SECTION_SECONDS - EPS ? [{ name: "Intro", from: round3(start), to: round3(end) }] : [];
  return { ...out, placed, sections: cleanSections([...intro, ...moved]), index: intro.length ? 0 : -1 };
}

// The bar the last melody note starts in, to the bar line at or after its end (at least one bar), becomes the ending:
// the chords there are one tonic chord of `key` held to that bar line, voiced near the chord before it and under the
// melody (harmony.js tonicChord), and the drums, when the song has some, stop on a kick and a snare together on its
// first beat. A chord held into it stops where it starts. The melody, the harmony voice and the recordings are left as
// they are. A section running into the ending stops at its start and one inside it gives way to the Outro. Adding it
// again changes nothing. Returns {notes, harmony, voice2, drums, placed, sections, index}: index is the Outro's.
export function addEnding(project, { key } = {}) {
  const tune = (Array.isArray(project.notes) ? project.notes : []).filter(n => isTime(n.t) && isTime(n.d));
  if (!tune.length) throw Error("Add ending needs a tune: sing or write the melody first.");
  const last = tune.reduce((a, n) => (n.t > a.t + EPS || (Math.abs(n.t - a.t) <= EPS && n.t + n.d > a.t + a.d) ? n : a));
  const { origin, bar } = barGrid(project);
  const from = round3(Math.max(0, origin + Math.floor((last.t - origin) / bar + 1e-6) * bar));
  const to = round3(Math.max(from + bar, origin + Math.ceil((last.t + last.d - origin) / bar - 1e-6) * bar));
  if (to > MAX_TIME + EPS) throw Error(`The song would go past ${MAX_TIME} seconds.`);
  const list = cleanSections(project.sections);
  const kept = [];
  for (const x of list) {
    if (x.to <= from + EPS) kept.push(x);
    else if (x.from < from - EPS && from - x.from >= MIN_SECTION_SECONDS - EPS) kept.push({ ...x, to: from });
  }
  if (kept.length >= MAX_SECTIONS) throw Error(`A song can have at most ${MAX_SECTIONS} sections.`);
  const before = (Array.isArray(project.harmony) ? project.harmony : []).filter(n => n.t < from - EPS)
    .map(n => (n.t + n.d > from + EPS ? { ...n, d: round3(from - n.t) } : { ...n }));
  const lastStart = before.reduce((t, n) => Math.max(t, n.t), -Infinity);
  const previous = before.filter(n => Math.abs(n.t - lastStart) < 0.03).map(n => n.m).sort((a, b) => a - b);
  const over = tune.filter(n => n.t < to - EPS && n.t + n.d > from + EPS).map(n => n.m);
  const chord = tonicChord(key, { previous: previous.length ? previous : null, ceiling: Math.min(...over) });
  const harmony = [...before, ...chord.map(m => ({ m, t: from, d: round3(to - from) }))];
  const beat = Array.isArray(project.drums) ? project.drums : [];
  const drums = beat.length ? [...beat.filter(h => h.t < from - EPS).map(h => ({ ...h })), { k: "kick", t: from }, { k: "snare", t: from }] : [];
  checkLimits("harmony", harmony);
  checkLimits("drums", drums);
  const sections = cleanSections([...kept, { name: "Outro", from, to }]);
  return {
    notes: (project.notes || []).map(n => ({ ...n })),
    harmony, voice2: (project.voice2 || []).map(n => ({ ...n })), drums,
    placed: cleanPlaced(project.placed), sections, index: sections.length - 1,
  };
}
