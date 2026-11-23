// A song sheet (SHEET.1): a page to hand someone who plays, with the song's name, key and speed, its
// sections, and the words line by line with each chord's symbol above the syllable sung when the
// chord starts. The words are laid on the melody exactly as the roll and Export MusicXML lay them
// (lyrics.js assignLyrics), the chords are the ones the chord strip reads from the chords part
// (harmony.js readChords), and a line belongs to the section (sections.js) its first chord or
// syllable falls in. Chords with no words under them (an intro, a break between lines, an ending)
// are a line of chords of their own, at most CHORD_LINE_BARS bars long.
// DOM-free so Node tests import it directly; the studio draws the model and the browser prints it.

import { assignLyrics, onsets, lyricLines, cleanLyrics } from "./lyrics.js";
import { readChords, keyLabel } from "./harmony.js";
import { cleanSections, sectionAt } from "./sections.js";
import { barSeconds } from "./bars.js";

// A line of chords alone holds at most this many bars.
export const CHORD_LINE_BARS = 4;

const finite = x => typeof x === "number" && Number.isFinite(x);

// The song as a sheet:
//   {title, key (its name, or null), bpm, blocks: [{section (name or null), lines}]}
// each line {kind: "words" | "chords", stanza (after a blank line in the words), segments}, each
// segment {text, chords: [names], joined (the word goes on into the next segment)}. A segment of a
// words line is one syllable, or a lead with no text holding chords struck just before the line's
// first word; a segment of a chords line is one chord. A section with nothing in it is a block with
// no lines, so the sheet still says where it comes. Throws when there are neither words nor chords.
export function songSheet(project, { key = null, title = "" } = {}) {
  const bpm = Number(project?.bpm);
  if (!finite(bpm) || bpm <= 0) throw Error("Set a tempo before making the song sheet.");
  const notes = Array.isArray(project.notes) ? project.notes : [];
  const text = typeof project.lyrics === "string" ? cleanLyrics(project.lyrics) : "";
  const chords = readChords(Array.isArray(project.harmony) ? project.harmony : [], { bpm, key });
  const lines = lyricLines(text);
  if (!lines.length && !chords.length) throw Error("Nothing for a song sheet yet: write the words or add chords first.");
  const sections = cleanSections(project.sections);
  // Half a sixteenth: a chord struck this close before a syllable is struck on it.
  const near = 60 / bpm / 8, bar = barSeconds(bpm);

  // Every syllable typed, by line, with the time of its note when it has one (assignLyrics' order).
  const syllables = [];
  lines.forEach((l, line) => l.tokens.forEach(tok => { if (!tok.hold) syllables.push({ ...tok, line, t: null, end: null }); }));
  const { byOnset } = assignLyrics(notes, text, bpm);
  let next = 0, last = null;
  for (const o of onsets(notes, bpm)) {
    const entry = byOnset.get(o.at);
    if (!entry) continue;
    const end = Math.max(...o.notes.map(i => notes[i].t + notes[i].d));
    if (entry.held) { if (last) last.end = Math.max(last.end, end); continue; }
    last = syllables[next++];
    last.t = notes[o.note].t;
    last.end = end;
  }
  const placed = syllables.filter(s => s.t != null);

  // Each chord on the syllable sounding when it starts, else between lines. A chord the same as the one
  // just before it, with no silence between, is not written again.
  const on = new Map(), gaps = new Map();  // gaps: index of the next placed syllable (or placed.length) -> chords
  let prev = null, p = 0;
  for (const c of chords) {
    const again = prev && prev.name === c.name && Math.abs(prev.t + prev.d - c.t) < 1e-3;
    prev = c;
    if (again) continue;
    while (p < placed.length && placed[p].t <= c.t + near) p++;
    const s = placed[p - 1], after = placed[p];
    if (s && ((after && after.line === s.line) || c.t < s.end - near)) {
      if (!on.has(s)) on.set(s, []);
      on.get(s).push(c);
    } else {
      if (!gaps.has(p)) gaps.set(p, []);
      gaps.get(p).push(c);
    }
  }

  // The lines in time order: chord lines from the gaps, then each words line with its lead chords.
  const out = [];
  const chordLines = list => {
    let run = [];
    const flush = () => { if (run.length) out.push({ kind: "chords", stanza: false, t: run[0].t, segments: run.map(c => ({ text: "", chords: [c.name], joined: false })) }); run = []; };
    for (const c of list) {
      if (run.length && (c.t - run[0].t >= CHORD_LINE_BARS * bar - 1e-3 || sectionAt(sections, c.t) !== sectionAt(sections, run[0].t))) flush();
      run.push(c);
    }
    flush();
  };
  const byLine = lines.map(() => []);
  for (const s of syllables) byLine[s.line].push(s);
  // Which words line the placed syllable at index i starts, if it is a line's first placed syllable.
  const starts = new Map();
  placed.forEach((s, i) => { if (!starts.has(s.line)) starts.set(s.line, i); });
  lines.forEach((l, line) => {
    const first = starts.get(line);
    let lead = [];
    if (first != null && gaps.has(first)) {
      const list = gaps.get(first), t0 = placed[first].t;
      // Chords within a bar before the first word lead into the line; earlier ones are a line of their own.
      lead = list.filter(c => t0 - c.t < bar - 1e-3);
      chordLines(list.filter(c => !lead.includes(c)));
    }
    const segments = byLine[line].map(s => ({ text: s.text, chords: (on.get(s) || []).map(c => c.name), joined: s.syllabic === "begin" || s.syllabic === "middle" }));
    if (lead.length) segments.unshift({ text: "", chords: lead.map(c => c.name), joined: false });
    const t = lead.length ? lead[0].t : first != null ? placed[first].t : null;
    out.push({ kind: "words", stanza: l.stanza, t, segments });
  });
  if (gaps.has(placed.length)) chordLines(gaps.get(placed.length));
  // Chord lines were pushed before the words line they precede; chords after the last word come last,
  // except when nothing has a time yet (words with no notes) and the chords come first.
  if (!placed.length) out.sort((a, b) => (a.t == null) - (b.t == null));

  // Blocks: consecutive lines in the same section (a line with no time stays in the block before it),
  // with a block for each section that has no line, in its place.
  const blocks = [];
  for (const line of out) {
    const at = line.t == null ? null : sectionAt(sections, line.t), b = blocks[blocks.length - 1];
    if (b && (at == null || at === b.at)) b.lines.push(line);
    else blocks.push({ at: at ?? -1, t: line.t, lines: [line] });
  }
  const shown = new Set(blocks.map(b => b.at));
  sections.forEach((s, i) => {
    if (shown.has(i)) return;
    const k = blocks.findIndex(b => b.t != null && b.t >= s.from);
    blocks.splice(k < 0 ? blocks.length : k, 0, { at: i, t: s.from, lines: [] });
  });
  return {
    title: String(title || "").trim() || "Untitled song",
    key: key ? keyLabel(key) : null,
    bpm: Math.round(bpm),
    blocks: blocks.map(b => ({ section: b.at >= 0 ? sections[b.at].name : null, lines: b.lines.map(({ t, ...l }) => l) })),
  };
}

// The sheet as plain text, chords on a line above the words lined up with their syllables: for a
// message, and so tests can read a sheet at a glance.
export function sheetText(sheet) {
  const out = [sheet.title, [sheet.key, `${sheet.bpm} bpm`].filter(Boolean).join(", ")];
  for (const b of sheet.blocks) {
    out.push("");
    if (b.section) out.push(`[${b.section}]`);
    for (const l of b.lines) {
      if (l.stanza && out[out.length - 1] !== "") out.push("");
      if (l.kind === "chords") { out.push(l.segments.map(s => s.chords.join(" ")).join("  ")); continue; }
      let top = "", words = "";
      l.segments.forEach((s, i) => {
        const chord = s.chords.join(" "), gap = s.joined || i === l.segments.length - 1 || !s.text ? "" : " ";
        const width = Math.max(s.text.length + gap.length, chord ? chord.length + 1 : 0);
        top += chord.padEnd(width);
        words += (s.text + (s.joined && chord.length + 1 > s.text.length ? "-" : gap)).padEnd(width);
      });
      if (top.trim()) out.push(top.trimEnd());
      out.push(words.trimEnd());
    }
  }
  return out.join("\n") + "\n";
}
