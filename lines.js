// CHAT.1: instrument lines. Besides the fixed note parts (melody, chords, harmony voice, drums) a song can
// have up to MAX_LINES lines of notes, each a part of its own with a name and an instrument: "a guitar line"
// has a place that is not the melody. Kept in the project's optional `lines` list
// [{id, name, instrument, notes: [{m, t, d}]}], written only when there are lines, with `uses` naming
// "lines" (versions.js), so a Tandem that does not know them refuses the file instead of dropping them.
// A line's mixer channel is its key in the project's `mix` ("line-<id>", heard by default); in the MIDI
// file and MIDI out it has a channel of its own after the harmony voice's (lineChannel), and its stem is
// lineStemFile. No AI action edits a line.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectLine mirrors cleanLines.

import { INSTRUMENTS } from "./voices.js";

export const MAX_LINES = 8;
export const MAX_LINE_NAME = 40;
export const MAX_LINE_NOTES = 1024;
const MAX_SECONDS = 600;
const ID = /^[a-z0-9]{1,24}$/;
// A line's key: its mixer channel and its stem's part name.
export const LINE_KEY = /^line-([a-z0-9]{1,24})$/;
export const lineKey = id => {
  if (!ID.test(id)) throw Error("Invalid line id");
  return "line-" + id;
};
export const isLineKey = key => typeof key === "string" && LINE_KEY.test(key);
export const lineIdOf = key => (isLineKey(key) ? key.slice(5) : null);

// MIDI channels (0-based) for the lines, in list order: after the melody (0), the chords (1) and the harmony
// voice (2), skipping the drums' channel 9 (channel 10 in General MIDI), so no line ever plays as drums.
export const LINE_CHANNELS = Object.freeze([3, 4, 5, 6, 7, 8, 10, 11]);
// The velocity a line plays at in the MIDI file, DAWproject and MIDI out (the harmony voice's).
export const LINE_VELOCITY = 80;

const isObject = x => !!x && typeof x === "object" && !Array.isArray(x);

function cleanNote(n) {
  if (!isObject(n)) throw Error("Invalid line note");
  for (const k of Object.keys(n)) if (!["m", "t", "d"].includes(k)) throw Error("Invalid line note");
  const { m, t, d } = n;
  if (!Number.isInteger(m) || m < 0 || m > 127) throw Error("Invalid line note");
  if (typeof t !== "number" || !Number.isFinite(t) || t < 0 || t > MAX_SECONDS) throw Error("Invalid line note");
  if (typeof d !== "number" || !Number.isFinite(d) || d <= 0 || d > MAX_SECONDS) throw Error("Invalid line note");
  return { m, t, d };
}

// The line list with every value checked. Throws on anything else, like the other project checks, so a bad
// file is refused rather than half read. A missing list is no lines; the notes are kept in time order.
export function cleanLines(lines) {
  if (lines == null) return [];
  if (!Array.isArray(lines) || lines.length > MAX_LINES) throw Error("Invalid lines");
  const seen = new Set();
  return lines.map(l => {
    if (!isObject(l)) throw Error("Invalid line");
    for (const k of Object.keys(l)) if (!["id", "name", "instrument", "notes"].includes(k)) throw Error("Invalid line");
    if (typeof l.id !== "string" || !ID.test(l.id) || seen.has(l.id)) throw Error("Invalid line id");
    seen.add(l.id);
    const name = typeof l.name === "string" ? l.name.trim() : "";
    if (!name || name.length > MAX_LINE_NAME) throw Error("Invalid line name");
    if (!INSTRUMENTS.includes(l.instrument)) throw Error("Unsupported line instrument: " + l.instrument);
    if (!Array.isArray(l.notes) || l.notes.length > MAX_LINE_NOTES) throw Error("Invalid line notes");
    const notes = l.notes.map(cleanNote).sort((a, b) => a.t - b.t || a.m - b.m);
    return { id: l.id, name, instrument: l.instrument, notes };
  });
}

// A new line id: 12 lowercase letters and digits from `random` (crypto.getRandomValues by default).
export function newLineId(random = n => crypto.getRandomValues(new Uint8Array(n))) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  return [...random(12)].map(b => chars[b % chars.length]).join("");
}

// "Line 1", "Line 2", ...: the lowest number no line is named with.
export function nextLineName(lines) {
  const used = new Set(cleanLines(lines).map(l => l.name));
  let n = 1;
  while (used.has("Line " + n)) n++;
  return "Line " + n;
}

// The list with a new line at the end. Throws when the list is full.
export function addLine(lines, { id, instrument, name = null, notes = [] }) {
  const list = cleanLines(lines);
  if (list.length >= MAX_LINES) throw Error(`A song can have ${MAX_LINES} lines; remove one first.`);
  return cleanLines([...list, { id, name: name ?? nextLineName(list), instrument, notes }]);
}

// The lines and the mix without line `id` (its mixer channel goes with it).
export function removeLine(lines, mix, id) {
  const list = cleanLines(lines);
  if (!list.some(l => l.id === id)) throw Error("No such line");
  const out = { ...(isObject(mix) ? mix : {}) };
  delete out[lineKey(id)];
  return { lines: list.filter(l => l.id !== id), mix: out };
}

// The list with line `id` changed by `change` ({name?, instrument?, notes?}), checked again.
export function changeLine(lines, id, change) {
  const list = cleanLines(lines);
  if (!list.some(l => l.id === id)) throw Error("No such line");
  return cleanLines(list.map(l => (l.id === id ? { ...l, ...change } : l)));
}

// A line's MIDI channel (0-based) by its place in the list.
export function lineChannel(lines, id) {
  const i = (Array.isArray(lines) ? lines : []).findIndex(l => l?.id === id);
  if (i < 0 || i >= LINE_CHANNELS.length) throw Error("No such line");
  return LINE_CHANNELS[i];
}

// A line's stem and DAWproject track file: "line-1.wav" for the first line, by its place in the list, so
// the files sort in the order of the lanes.
export function lineStemFile(lines, id) {
  const i = (Array.isArray(lines) ? lines : []).findIndex(l => l?.id === id);
  if (i < 0) throw Error("No such line");
  return `line-${i + 1}.wav`;
}

// The project's lines as note tracks for the exports: {key, id, name, instrument, channel, notes}, in list
// order. A project without lines (or with an unreadable list, which the studio refuses on opening) has none.
export function lineTracks(project) {
  const lines = Array.isArray(project?.lines) ? project.lines : [];
  return lines.slice(0, LINE_CHANNELS.length).filter(l => l && ID.test(l.id) && Array.isArray(l.notes))
    .map((l, i) => ({ key: lineKey(l.id), id: l.id, name: l.name, instrument: l.instrument, channel: LINE_CHANNELS[i], notes: l.notes }));
}

// Every note of every line, for how long the song is and where its bars are.
export function lineNotes(project) {
  return lineTracks(project).flatMap(l => l.notes);
}

// The lines with each line's notes replaced by fn(notes, line) (quantize, section edits, clipping).
export function mapLineNotes(lines, fn) {
  return (Array.isArray(lines) ? lines : []).map(l => ({ ...l, notes: fn(l.notes || [], l) }));
}
