// Export the melody, harmony and harmony voice (HARM.1) as MusicXML 4.0 for notation apps (EXP.2): MuseScore, Sibelius,
// Finale, Dorico. The notes are snapped to a sixteenth-note grid at the project tempo, in 4/4 from
// the start of the project (the same zero as the MIDI file and the stems), and every note or rest is
// split into notatable lengths, tied across barlines. Notes that start together are one chord; a note
// still sounding when the next one starts is cut there, so each part reads as one voice.
// DOM-free so Node tests import it directly.

import { keySignature, PROGRAMS } from "./daw.js";

// Divisions per quarter note: the grid is a sixteenth note, and a 4/4 measure is 16 of them.
export const DIVISIONS = 4;
export const MEASURE = 16;
// Notatable lengths in sixteenths, longest first, with the written type and dot, and the grid
// position (in sixteenths) a value may start on, so a quarter starts on a beat and a whole note on
// the barline.
const VALUES = [
  { length: 16, type: "whole", dot: false, align: 16 },
  { length: 12, type: "half", dot: true, align: 4 },
  { length: 8, type: "half", dot: false, align: 4 },
  { length: 6, type: "quarter", dot: true, align: 2 },
  { length: 4, type: "quarter", dot: false, align: 4 },
  { length: 3, type: "eighth", dot: true, align: 1 },
  { length: 2, type: "eighth", dot: false, align: 2 },
  { length: 1, type: "16th", dot: false, align: 1 },
];
// Rests are written undotted and on the beat: whole and half rests from the barline or the half bar.
const REST_VALUES = VALUES.filter(v => !v.dot).map(v => ({ ...v, align: v.length }));
const PARTS = [
  { key: "notes", name: "Melody", instrument: "instrument" },
  { key: "harmony", name: "Harmony", instrument: "harmony_instrument" },
  { key: "voice2", name: "Harmony voice", instrument: "voice2_instrument" },
];
const SHARPS = [["C", 0], ["C", 1], ["D", 0], ["D", 1], ["E", 0], ["F", 0], ["F", 1], ["G", 0], ["G", 1], ["A", 0], ["A", 1], ["B", 0]];
const FLATS = [["C", 0], ["D", -1], ["D", 0], ["E", -1], ["E", 0], ["F", 0], ["G", -1], ["G", 0], ["A", -1], ["A", 0], ["B", -1], ["B", 0]];
// The most, in sixteenths, a note is held on to reach the next onset or beat (see partMeasures).
const HOLD = 1;
// Below middle C on average, a part is written in the bass clef.
const BASS_CLEF_BELOW = 60;
// C0, the lowest pitch MusicXML can write (its octave runs from 0 to 9).
const LOWEST = 12;

const finite = x => typeof x === "number" && Number.isFinite(x);
const escape = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const round2 = x => Math.round(x * 100) / 100;

// MIDI pitch as a written {step, alter, octave}: black keys as sharps, or as flats when the key
// signature has flats (sf < 0). MIDI 60 is C4.
export function spell(m, sf = 0) {
  const [step, alter] = (sf < 0 ? FLATS : SHARPS)[((m % 12) + 12) % 12];
  return { step, alter, octave: Math.floor(m / 12) - 1 };
}

// The pieces a span of `length` sixteenths starting at `at` (within one measure) is written as.
function pieces(at, length, rest) {
  const out = [];
  while (length > 0) {
    const value = (rest ? REST_VALUES : VALUES).find(v => v.length <= length && at % v.align === 0);
    out.push({ at, value });
    at += value.length;
    length -= value.length;
  }
  return out;
}

// A part as measures of written events: {rest, pitches, at, length, value, tieStart, tieStop}, with
// `at` and `length` in sixteenths within the measure. Every measure adds up to MEASURE.
export function partMeasures(notes, bpm) {
  const grid = t => Math.max(0, Math.round((t * bpm) / 60 * DIVISIONS));
  const onsets = new Map();
  for (const n of notes) {
    if (!n || !finite(n.m) || !finite(n.t) || !finite(n.d) || n.d <= 0) continue;
    const start = grid(n.t), end = Math.max(start + 1, grid(n.t + n.d));
    const m = Math.min(127, Math.max(0, Math.round(n.m)));
    const at = onsets.get(start) || { start, end, pitches: new Set() };
    at.end = Math.max(at.end, end);
    at.pitches.add(m);
    onsets.set(start, at);
  }
  const chords = [...onsets.values()].sort((a, b) => a.start - b.start);
  // A note still sounding at the next onset is cut there. A sung note is usually released a little
  // early: one that ends within HOLD of the next onset, or of the next beat before a rest, is held
  // to it, so a quarter is not written as a dotted eighth and a sixteenth rest.
  chords.forEach((c, i) => {
    const next = chords[i + 1]?.start;
    if (next != null) c.end = Math.min(c.end, next);
    const beat = Math.ceil(c.end / DIVISIONS) * DIVISIONS;
    if (next != null && next - c.end <= HOLD) c.end = next;
    else if (beat - c.end <= HOLD && (next == null || beat <= next)) c.end = beat;
  });
  // The timeline as spans of sound or silence, from zero to the end of the last full measure.
  const total = Math.max(MEASURE, Math.ceil((chords.at(-1)?.end || 0) / MEASURE) * MEASURE);
  const spans = [];
  let cursor = 0;
  for (const c of chords) {
    if (c.start > cursor) spans.push({ start: cursor, end: c.start, pitches: null });
    spans.push({ start: c.start, end: c.end, pitches: [...c.pitches].sort((a, b) => a - b) });
    cursor = c.end;
  }
  if (cursor < total) spans.push({ start: cursor, end: total, pitches: null });
  const measures = Array.from({ length: total / MEASURE }, () => []);
  for (const span of spans) {
    const written = [];
    for (let bar = Math.floor(span.start / MEASURE); bar * MEASURE < span.end; bar++) {
      const from = Math.max(span.start, bar * MEASURE), to = Math.min(span.end, (bar + 1) * MEASURE);
      for (const p of pieces(from - bar * MEASURE, to - from, !span.pitches)) written.push({ bar, ...p });
    }
    written.forEach((w, i) => measures[w.bar].push({
      rest: !span.pitches, pitches: span.pitches || [], at: w.at, length: w.value.length, value: w.value,
      tieStart: !!span.pitches && i < written.length - 1, tieStop: !!span.pitches && i > 0,
    }));
  }
  // A measure that is all silence is one measure rest.
  return measures.map(bar => (bar.every(e => e.rest) ? [{ rest: true, pitches: [], at: 0, length: MEASURE, value: null, whole: true, tieStart: false, tieStop: false }] : bar));
}

function noteXml(e, sf) {
  if (e.rest) {
    if (e.whole) return `<note><rest measure="yes"/><duration>${MEASURE}</duration><voice>1</voice></note>`;
    return `<note><rest/><duration>${e.length}</duration><voice>1</voice><type>${e.value.type}</type>${e.value.dot ? "<dot/>" : ""}</note>`;
  }
  const ties = (e.tieStop ? ['<tie type="stop"/>'] : []).concat(e.tieStart ? ['<tie type="start"/>'] : []);
  const tied = (e.tieStop ? ['<tied type="stop"/>'] : []).concat(e.tieStart ? ['<tied type="start"/>'] : []);
  return e.pitches.map((m, i) => {
    const { step, alter, octave } = spell(m, sf);
    return "<note>" + (i ? "<chord/>" : "")
      + `<pitch><step>${step}</step>${alter ? `<alter>${alter}</alter>` : ""}<octave>${octave}</octave></pitch>`
      + `<duration>${e.length}</duration>${ties.join("")}<voice>1</voice><type>${e.value.type}</type>${e.value.dot ? "<dot/>" : ""}`
      + (tied.length ? `<notations>${tied.join("")}</notations>` : "") + "</note>";
  }).join("\n        ");
}

// The project's melody and harmony as a MusicXML 4.0 partwise score: one part per part with notes,
// named and with its General MIDI program, the key signature (and mode) when the key is known, 4/4
// and the tempo. Throws when neither part has a note: drums are not written as notation.
export function musicXml(project, { key = null, title = "Tandem" } = {}) {
  const bpm = finite(project.bpm) && project.bpm > 0 ? project.bpm : 100;
  const parts = PARTS.map(p => ({ ...p, notes: (Array.isArray(project[p.key]) ? project[p.key] : []).filter(n => n && finite(n.m) && finite(n.t) && finite(n.d) && n.d > 0) }))
    .filter(p => p.notes.length);
  if (!parts.length) throw Error("Nothing to write as notation yet: add melody or harmony notes first.");
  // MusicXML's lowest octave is 0, so MIDI 0-11 (below about 16 Hz) cannot be written. Refuse
  // rather than move or drop them silently.
  const low = parts.reduce((k, p) => k + p.notes.filter(n => Math.round(n.m) < LOWEST).length, 0);
  if (low) throw Error(`${low} ${low === 1 ? "note is" : "notes are"} below C0, lower than notation can write: raise or remove ${low === 1 ? "it" : "them"} first.`);
  const sf = key ? keySignature(key).sf : 0;
  const keyXml = `<key><fifths>${sf}</fifths>${key ? `<mode>${key.mode}</mode>` : ""}</key>`;
  const written = parts.map(p => partMeasures(p.notes, bpm));
  const bars = Math.max(...written.map(w => w.length));
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">',
    '<score-partwise version="4.0">',
    `  <work><work-title>${escape(title)}</work-title></work>`,
    "  <identification><encoding><software>Tandem</software></encoding></identification>",
    "  <part-list>",
  ];
  parts.forEach((p, i) => {
    const id = `P${i + 1}`, program = PROGRAMS[project[p.instrument]];
    lines.push(`    <score-part id="${id}"><part-name>${p.name}</part-name>`
      + (program == null ? "" : `<score-instrument id="${id}-I1"><instrument-name>${escape(project[p.instrument])}</instrument-name></score-instrument>`
        + `<midi-instrument id="${id}-I1"><midi-channel>${i + 1}</midi-channel><midi-program>${program + 1}</midi-program></midi-instrument>`)
      + "</score-part>");
  });
  lines.push("  </part-list>");
  parts.forEach((p, i) => {
    const measures = written[i];
    // Parts are padded with measure rests to the same number of measures.
    while (measures.length < bars) measures.push(partMeasures([], bpm)[0]);
    const mean = p.notes.reduce((s, n) => s + n.m, 0) / p.notes.length;
    const clef = mean < BASS_CLEF_BELOW ? "<clef><sign>F</sign><line>4</line></clef>" : "<clef><sign>G</sign><line>2</line></clef>";
    lines.push(`  <part id="P${i + 1}">`);
    measures.forEach((bar, n) => {
      lines.push(`    <measure number="${n + 1}">`);
      if (n === 0) {
        lines.push(`      <attributes><divisions>${DIVISIONS}</divisions>${keyXml}<time><beats>4</beats><beat-type>4</beat-type></time>${clef}</attributes>`);
        if (i === 0) lines.push(`      <direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>${round2(bpm)}</per-minute></metronome></direction-type><sound tempo="${round2(bpm)}"/></direction>`);
      }
      for (const e of bar) lines.push("      " + noteXml(e, sf));
      lines.push("    </measure>");
    });
    lines.push("  </part>");
  });
  lines.push("</score-partwise>", "");
  return lines.join("\n");
}
