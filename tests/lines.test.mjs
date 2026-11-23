// CHAT.1a: instrument lines in the project, and in every place a note part goes.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  cleanLines, addLine, removeLine, changeLine, nextLineName, newLineId, lineKey, isLineKey, lineIdOf, lineChannel,
  lineStemFile, lineTracks, linesNotes, LINE_CHANNELS, LINE_VELOCITY, MAX_LINES, MAX_LINE_NAME, MAX_LINE_NOTES,
} from "../lines.js";
import { midiFile, arrangementSeconds, stemsZip, PROGRAMS, TICKS_PER_BEAT } from "../daw.js";
import { musicXml } from "../notation.js";
import { projectXml } from "../dawproject.js";
import { partChannels, songEvents, DRUM_CHANNEL } from "../midi.js";
import { cleanMix, mixParts, mixGains, channel } from "../mixer.js";
import { clipProject, timelineEnd } from "../playhead.js";
import { contentSeconds, STAGES } from "../evolution.js";
import { quantizeProject, GRID_DIVISIONS } from "../groove.js";
import { repeatSection, deleteSection, moveSection, addIntro, addEnding } from "../sections.js";
import { projectFromState, usesOf, checkUses, hasWork, KNOWN_USES } from "../versions.js";
import { unzipFiles } from "../bundle.js";
import { INSTRUMENTS } from "../voices.js";

const read = f => readFile(new URL("../" + f, import.meta.url), "utf8");
const guitar = (notes = [{ m: 64, t: 0.5, d: 0.25 }, { m: 67, t: 1, d: 0.5 }]) => ({ id: "g1", name: "Guitar", instrument: "guitar", notes });
const flute = (notes = [{ m: 79, t: 2, d: 1 }]) => ({ id: "f2", name: "Flute", instrument: "flute", notes });
const song = (extra = {}) => ({
  bpm: 120, instrument: "piano", notes: [{ m: 60, t: 0, d: 0.5 }], drums: [{ k: "kick", t: 0 }],
  harmony: [], harmony_instrument: "piano", voice2: [], voice2_instrument: "piano", lines: [guitar(), flute()], ...extra,
});

test("cleanLines keeps a valid list, trims names, sorts notes and refuses anything else", () => {
  assert.deepEqual(cleanLines(undefined), []);
  assert.deepEqual(cleanLines(null), []);
  const out = cleanLines([{ id: "abc", name: "  Lead  ", instrument: "guitar", notes: [{ m: 67, t: 1, d: 0.5 }, { m: 64, t: 0.5, d: 0.25 }, { m: 60, t: 0.5, d: 0.25 }] }]);
  assert.deepEqual(out, [{ id: "abc", name: "Lead", instrument: "guitar", notes: [{ m: 60, t: 0.5, d: 0.25 }, { m: 64, t: 0.5, d: 0.25 }, { m: 67, t: 1, d: 0.5 }] }]);
  const ok = { id: "a1", name: "x", instrument: "piano", notes: [] };
  const bad = [
    "lines", {}, [ok, { ...ok }], // duplicate id
    Array.from({ length: MAX_LINES + 1 }, (_, i) => ({ ...ok, id: "a" + i })),
    [{ ...ok, id: "A1" }], [{ ...ok, id: "" }], [{ ...ok, id: "a".repeat(25) }],
    [{ ...ok, name: "   " }], [{ ...ok, name: "n".repeat(MAX_LINE_NAME + 1) }], [{ ...ok, name: 3 }],
    [{ ...ok, instrument: "kazoo" }], [{ ...ok, instrument: undefined }],
    [{ ...ok, notes: null }], [{ ...ok, notes: Array.from({ length: MAX_LINE_NOTES + 1 }, (_, i) => ({ m: 60, t: i * 0.1, d: 0.1 })) }],
    [{ ...ok, notes: [{ m: 60.5, t: 0, d: 1 }] }], [{ ...ok, notes: [{ m: 128, t: 0, d: 1 }] }], [{ ...ok, notes: [{ m: -1, t: 0, d: 1 }] }],
    [{ ...ok, notes: [{ m: 60, t: -0.1, d: 1 }] }], [{ ...ok, notes: [{ m: 60, t: 601, d: 1 }] }],
    [{ ...ok, notes: [{ m: 60, t: 0, d: 0 }] }], [{ ...ok, notes: [{ m: 60, t: 0, d: 601 }] }], [{ ...ok, notes: [{ m: 60, t: NaN, d: 1 }] }],
    [{ ...ok, notes: [{ m: 60, t: 0, d: 1, v: 3 }] }], [{ ...ok, colour: "red" }], [null],
  ];
  for (const b of bad) assert.throws(() => cleanLines(b), undefined, JSON.stringify(b).slice(0, 80));
  // The limits themselves are allowed.
  assert.equal(cleanLines(Array.from({ length: MAX_LINES }, (_, i) => ({ ...ok, id: "a" + i }))).length, MAX_LINES);
  assert.equal(cleanLines([{ ...ok, name: "n".repeat(MAX_LINE_NAME), notes: Array.from({ length: MAX_LINE_NOTES }, (_, i) => ({ m: 0, t: i * 0.5, d: 600 })) }])[0].notes.length, MAX_LINE_NOTES);
  assert.deepEqual(cleanLines([{ ...ok, notes: [{ m: 127, t: 600, d: 600 }] }])[0].notes, [{ m: 127, t: 600, d: 600 }]);
  for (const instrument of INSTRUMENTS) assert.equal(cleanLines([{ ...ok, instrument }])[0].instrument, instrument);
});

test("adding, changing and removing a line", () => {
  assert.equal(nextLineName([]), "Line 1");
  let lines = addLine([], { id: "a1", instrument: "guitar" });
  lines = addLine(lines, { id: "b2", instrument: "flute", notes: [{ m: 70, t: 1, d: 1 }] });
  assert.deepEqual(lines.map(l => l.name), ["Line 1", "Line 2"]);
  lines = changeLine(lines, "a1", { name: "Riff" });
  assert.equal(nextLineName(lines), "Line 1");
  assert.deepEqual(changeLine(lines, "b2", { instrument: "organ" })[1].instrument, "organ");
  assert.throws(() => changeLine(lines, "b2", { instrument: "kazoo" }));
  assert.throws(() => changeLine(lines, "zz", { name: "x" }), /No such line/);
  let full = [];
  for (let i = 0; i < MAX_LINES; i++) full = addLine(full, { id: "l" + i, instrument: "piano" });
  assert.throws(() => addLine(full, { id: "x", instrument: "piano" }), new RegExp(`${MAX_LINES} lines`));
  const { lines: left, mix } = removeLine(lines, { "line-a1": { level: -6 }, "line-b2": { solo: true }, melody: { mute: true } }, "a1");
  assert.deepEqual(left.map(l => l.id), ["b2"]);
  assert.deepEqual(mix, { "line-b2": { solo: true }, melody: { mute: true } });
  assert.throws(() => removeLine(lines, {}, "zz"), /No such line/);
  assert.match(newLineId(), /^[a-z0-9]{12}$/);
  assert.equal(newLineId(n => new Uint8Array(n).fill(1)), "b".repeat(12));
});

test("a line's key, MIDI channel and stem file", () => {
  assert.equal(lineKey("g1"), "line-g1");
  assert.throws(() => lineKey("G!"));
  assert.ok(isLineKey("line-g1") && !isLineKey("layer-g1") && !isLineKey("line-") && !isLineKey("melody"));
  assert.equal(lineIdOf("line-g1"), "g1");
  assert.equal(lineIdOf("layer-g1"), null);
  const lines = song().lines;
  assert.equal(lineChannel(lines, "g1"), 3);
  assert.equal(lineChannel(lines, "f2"), 4);
  assert.throws(() => lineChannel(lines, "zz"));
  assert.equal(lineStemFile(lines, "g1"), "line-1.wav");
  assert.equal(lineStemFile(lines, "f2"), "line-2.wav");
  // The channels skip the drums' channel (9, General MIDI's 10) and the three fixed note parts', and never repeat.
  assert.equal(LINE_CHANNELS.length, MAX_LINES);
  assert.ok(!LINE_CHANNELS.includes(9) && !LINE_CHANNELS.some(c => c < 3 || c > 15));
  assert.equal(new Set(LINE_CHANNELS).size, LINE_CHANNELS.length);
  assert.deepEqual(lineTracks(song()).map(t => [t.key, t.channel, t.instrument]), [["line-g1", 3, "guitar"], ["line-f2", 4, "flute"]]);
  assert.deepEqual(lineTracks({}), []);
  assert.deepEqual(linesNotes(song()).map(n => n.m), [64, 67, 79]);
});

test("the backend mirrors the line limits, the line key and the uses name", async () => {
  const py = await read("tandem_backend.py");
  const model = py.slice(py.indexOf("class ProjectLine("), py.indexOf("def _unique_line_ids"));
  assert.match(model, /id: str = Field\(pattern=r"\^\[a-z0-9\]\{1,24\}\$"\)/);
  assert.match(model, new RegExp(`name: str = Field\\(min_length=1,max_length=${MAX_LINE_NAME}\\)`));
  assert.match(model, /instrument: Literal\[INSTRUMENTS\]/);
  assert.match(model, new RegExp(`notes: list\\[ProjectNote\\] = Field\\(default_factory=list,max_length=${MAX_LINE_NOTES}\\)`));
  assert.match(py, new RegExp(`lines: Annotated\\[list\\[ProjectLine\\],Field\\(max_length=${MAX_LINES}\\)`));
  assert.match(py, /LINE_KEY=re\.compile\(r"\^line-\[a-z0-9\]\{1,24\}\$"\)/);
  assert.ok(KNOWN_USES.includes("lines"));
});

test("the mixer has a channel per line, heard by default", () => {
  const p = song();
  assert.deepEqual(mixParts(p).filter(isLineKey), ["line-g1", "line-f2"]);
  assert.deepEqual(channel(p, "line-g1"), { level: 0, mute: false, solo: false });
  assert.deepEqual(cleanMix({ "line-g1": { level: -6, mute: false, solo: true } }), { "line-g1": { level: -6, solo: true } });
  assert.deepEqual(cleanMix({ "line-g1": { mute: true } }), { "line-g1": { mute: true } });
  assert.throws(() => cleanMix({ "line-G": { level: 1 } }));
  const gains = mixGains({ ...p, mix: { "line-g1": { solo: true } } }, ["melody", "line-g1", "line-f2"]);
  assert.equal(gains["line-g1"], 1);
  assert.equal(gains["line-f2"], 0);
  assert.equal(gains.melody, 0);
  assert.ok(Math.abs(mixGains({ ...p, mix: { "line-f2": { level: -6 } } })["line-f2"] - 10 ** (-6 / 20)) < 1e-12);
});

// A small reader for the MIDI file: each track's name, program change and note-ons.
function readMidi(bytes) {
  const u32 = at => ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0;
  const tracks = [];
  let at = 14;
  while (at < bytes.length) {
    const end = at + 8 + u32(at + 4);
    let i = at + 8, tick = 0, running = 0;
    const t = { name: "", program: null, ons: [] };
    while (i < end) {
      let delta = 0, b;
      do { b = bytes[i++]; delta = (delta << 7) | (b & 127); } while (b & 128);
      tick += delta;
      let status = bytes[i];
      if (status & 128) i++; else status = running;
      if (status === 0xff) {
        const type = bytes[i++];
        let len = 0;
        do { b = bytes[i++]; len = (len << 7) | (b & 127); } while (b & 128);
        if (type === 3) t.name = new TextDecoder().decode(bytes.slice(i, i + len));
        i += len;
      } else {
        running = status;
        const kind = status >> 4, ch = status & 15, size = kind === 0xc || kind === 0xd ? 1 : 2;
        if (kind === 0xc) t.program = [ch, bytes[i]];
        if (kind === 9 && bytes[i + 1] > 0) t.ons.push([tick, bytes[i], ch, bytes[i + 1]]);
        i += size;
      }
    }
    tracks.push(t);
    at = end;
  }
  return tracks;
}

test("the MIDI file has a named track per line on its channel and program, before the drums", () => {
  const tracks = readMidi(midiFile(song()));
  assert.deepEqual(tracks.map(t => t.name), ["Tandem", "Melody", "Guitar", "Flute", "Drums"]);
  const beat = TICKS_PER_BEAT * 120 / 60;
  assert.deepEqual(tracks[2].program, [3, PROGRAMS.guitar]);
  assert.deepEqual(tracks[2].ons, [[beat * 0.5, 64, 3, LINE_VELOCITY], [beat * 1, 67, 3, LINE_VELOCITY]]);
  assert.deepEqual(tracks[3].program, [4, PROGRAMS.flute]);
  assert.deepEqual(tracks[3].ons, [[beat * 2, 79, 4, LINE_VELOCITY]]);
  // An empty line has no track; a project without lines is byte for byte what it was.
  assert.deepEqual(readMidi(midiFile(song({ lines: [guitar([]), flute()] }))).map(t => t.name), ["Tandem", "Melody", "Flute", "Drums"]);
  const without = song();
  delete without.lines;
  assert.deepEqual(midiFile(song({ lines: [] })), midiFile(without));
  // The eighth line is on channel 12 (index 11): the drums' channel is skipped.
  const eight = Array.from({ length: MAX_LINES }, (_, i) => ({ id: "l" + i, name: "L" + i, instrument: "piano", notes: [{ m: 60 + i, t: 0, d: 1 }] }));
  assert.deepEqual(readMidi(midiFile(song({ lines: eight }))).slice(2, 2 + MAX_LINES).map(t => t.ons[0][2]), [...LINE_CHANNELS]);
});

test("a line counts in the arrangement's length, the Timeline and the song's length", () => {
  const p = song({ lines: [guitar([{ m: 64, t: 9, d: 2 }])], notes: [{ m: 60, t: 0, d: 1 }] });
  assert.equal(arrangementSeconds(p), 9 + 2 + 1 + 1);
  assert.equal(timelineEnd(p), 11);
  assert.equal(contentSeconds(p), 11);
  assert.equal(arrangementSeconds({ ...p, lines: [] }), 4 + 1);
});

test("MusicXML writes each line as a part named by the line, on its channel and program", () => {
  const xml = musicXml(song({ lines: [{ ...guitar(), name: "Riff <A&B>" }, flute()] }));
  const parts = [...xml.matchAll(/<score-part id="(P\d+)"><part-name>([^<]*)<\/part-name>.*?<midi-channel>(\d+)<\/midi-channel><midi-program>(\d+)<\/midi-program>/g)].map(m => m.slice(1));
  assert.deepEqual(parts, [["P1", "Melody", "1", "1"], ["P2", "Riff &lt;A&amp;B&gt;", "4", String(PROGRAMS.guitar + 1)], ["P3", "Flute", "5", String(PROGRAMS.flute + 1)]]);
  // P2 holds the guitar's notes: E4 then G4.
  const p2 = xml.slice(xml.indexOf('<part id="P2">'), xml.indexOf('<part id="P3">'));
  assert.deepEqual([...p2.matchAll(/<step>([A-G])<\/step>(?:<alter>-?\d<\/alter>)?<octave>(\d)<\/octave>/g)].map(m => m[1] + m[2]), ["E4", "G4"]);
  // A song whose only notes are in a line can be written as notation.
  assert.match(musicXml({ bpm: 100, notes: [], drums: [], lines: [guitar()] }), /<part-name>Guitar<\/part-name>/);
});

test("DAWproject writes each line as a note track on its channel", () => {
  const xml = projectXml(song(), { rate: 44100 });
  const tracks = [...xml.matchAll(/<Track contentType="notes"[^>]*name="([^"]*)"/g)].map(m => m[1]);
  assert.deepEqual(tracks, ["Melody", "Guitar", "Flute", "Drums"]);
  const clip = name => xml.slice(xml.indexOf(`name="${name}"><Notes`), xml.indexOf("</Notes>", xml.indexOf(`name="${name}"><Notes`)));
  const notes = name => [...clip(name).matchAll(/<Note time="([^"]+)" duration="([^"]+)" channel="(\d+)" key="(\d+)" vel="([^"]+)"/g)].map(m => [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4]), Number(m[5])]);
  const vel = Math.round(LINE_VELOCITY / 127 * 1e6) / 1e6;
  assert.deepEqual(notes("Guitar"), [[1, 0.5, 3, 64, vel], [2, 1, 3, 67, vel]]);
  assert.deepEqual(notes("Flute"), [[4, 2, 4, 79, vel]]);
});

test("MIDI out sends each line on its own channel after the harmony voice's", () => {
  assert.deepEqual(partChannels(0).lines, [3, 4, 5, 6, 7, 8, 10, 11]);
  assert.deepEqual(partChannels(6).lines, [10, 11, 12, 13, 14, 15, 0, 1]);
  for (let c = 0; c < 16; c++) {
    if (c === DRUM_CHANNEL) continue;
    const ch = partChannels(c), all = [ch.melody, ch.harmony, ch.voice2, ch.drums, ...ch.lines];
    assert.equal(new Set(all).size, all.length, "channel " + c);
    assert.ok(!ch.lines.includes(DRUM_CHANNEL));
  }
  const events = songEvents(song(), 0);
  const ons = ch => events.filter(e => (e.data[0] & 0xf0) === 0x90 && (e.data[0] & 15) === ch).map(e => [e.t, e.data[1], e.data[2]]);
  assert.deepEqual(ons(3), [[0.5, 64, LINE_VELOCITY], [1, 67, LINE_VELOCITY]]);
  assert.deepEqual(ons(4), [[2, 79, LINE_VELOCITY]]);
  assert.ok(events.some(e => e.t === 0 && e.data[0] === (0xc0 | 3) && e.data[1] === PROGRAMS.guitar));
  assert.ok(events.some(e => e.t === 0 && e.data[0] === (0xc0 | 4) && e.data[1] === PROGRAMS.flute));
  assert.deepEqual(ons(5), []);
});

test("the stems name each line by its place: line-1.wav, line-2.wav", async () => {
  const parts = { melody: new Float32Array([0.1, 0.1]), "line-f2": new Float32Array([0.25, 0.25, 0.25]), "line-g1": new Float32Array([0.5]) };
  const files = Object.fromEntries(await unzipFiles(stemsZip({ parts, lines: song().lines, rate: 8000, midi: new Uint8Array([1]) })));
  const names = Object.keys(files);
  assert.deepEqual(names, ["mix.wav", "melody.wav", "line-1.wav", "line-2.wav", "tandem.mid"]);
  // mix.wav sums the lines with the melody: three frames, the first 0.1 + 0.25 + 0.5.
  const mix = new DataView(files["mix.wav"].buffer, files["mix.wav"].byteOffset);
  assert.equal(mix.getUint32(40, true), 3 * 2);
  assert.ok(Math.abs(mix.getInt16(44, true) / 32767 - 0.85) < 1e-3);
  const g = new DataView(files["line-1.wav"].buffer, files["line-1.wav"].byteOffset);
  assert.ok(Math.abs(g.getInt16(44, true) / 32767 - 0.5) < 1e-3, "line-1.wav is the guitar (first in the list)");
});

test("clipping a song for Play from a time clips each line", () => {
  const c = clipProject(song(), 0.75, 2.5);
  assert.deepEqual(c.lines.map(l => [l.id, l.notes]), [["g1", [{ m: 67, t: 0.25, d: 0.5 }]], ["f2", [{ m: 79, t: 1.25, d: 0.5 }]]]);
  assert.ok(!("lines" in clipProject({ notes: [], drums: [] }, 0, 1)));
});

test("quantize snaps the lines on the song's grid", () => {
  const p = song({ notes: [{ m: 60, t: 0, d: 0.5 }, { m: 62, t: 0.5, d: 0.5 }], lines: [guitar([{ m: 64, t: 0.27, d: 0.2 }, { m: 65, t: 1.02, d: 0.2 }])] });
  const q = quantizeProject(p, { division: GRID_DIVISIONS["1/8"] ?? 2 });
  assert.deepEqual(q.lines[0].notes.map(n => n.t), [0.25, 1]);
  assert.equal(q.lines[0].name, "Guitar");
  assert.ok(!("lines" in quantizeProject({ ...p, lines: undefined }, { division: 2 })));
  // A song with notes only in a line is quantized too.
  const only = quantizeProject({ bpm: 120, notes: [], drums: [], lines: [guitar([{ m: 64, t: 0.27, d: 0.2 }])] }, { division: 2 });
  assert.deepEqual(only.lines[0].notes.map(n => n.t), [0.25]);
});

test("section edits carry the lines with the other note parts", () => {
  const sections = [{ name: "Verse", from: 0, to: 2 }, { name: "Chorus", from: 2, to: 4 }];
  const p = song({ sections, notes: [{ m: 60, t: 0, d: 0.5 }, { m: 62, t: 2, d: 0.5 }], lines: [guitar([{ m: 64, t: 0.5, d: 0.25 }, { m: 67, t: 2.5, d: 2 }])] });
  const times = r => r.lines[0].notes.map(n => [n.m, n.t, n.d]).sort((a, b) => a[1] - b[1]);
  assert.deepEqual(times(repeatSection(p, 0)), [[64, 0.5, 0.25], [64, 2.5, 0.25], [67, 4.5, 2]]);
  assert.deepEqual(times(deleteSection(p, 0)), [[67, 0.5, 2]]);
  assert.deepEqual(times(moveSection(p, 1, -1)), [[64, 2.5, 0.25], [67, 0.5, 2]].sort((a, b) => a[1] - b[1]));
  const intro = addIntro({ ...p, harmony: [{ m: 48, t: 0, d: 2 }] }, { bars: 1 });
  assert.deepEqual(times(intro), [[64, 2.5, 0.25], [67, 4.5, 2]]);
  const ending = addEnding(p, { key: { tonic: 0, mode: "major" } });
  assert.deepEqual(times(ending), [[64, 0.5, 0.25], [67, 2.5, 2]]);
  assert.equal(ending.later, 4.5, "a line held past the ending counts in `later`");
  // A repeat that would take a line past its note limit is refused, naming the line.
  const tight = song({ sections: [{ name: "Verse", from: 0, to: 100 }], lines: [guitar(Array.from({ length: 600 }, (_, i) => ({ m: 60, t: i * 0.1, d: 0.05 })))] });
  assert.throws(() => repeatSection(tight, 0), /line "Guitar" would have more than 1024 notes/);
  // Without a line list the results have none.
  const plain = song({ sections, lines: undefined });
  assert.ok(!("lines" in repeatSection(plain, 0)) && !("lines" in addEnding(plain, { key: { tonic: 0, mode: "major" } })));
});

test("a saved project keeps its lines and names them in uses; an older Tandem refuses it", () => {
  const p = projectFromState(song());
  assert.deepEqual(p.lines, song().lines);
  assert.deepEqual(p.uses, ["lines"]);
  assert.deepEqual(usesOf(song({ grid: { origin: 0 } })), ["grid", "lines"]);
  const none = projectFromState(song({ lines: [] }));
  assert.ok(!("lines" in none) && !("uses" in none));
  assert.deepEqual(checkUses(["lines"]), ["lines"]);
  assert.ok(hasWork({ notes: [], drums: [], lines: [guitar()] }));
  assert.ok(!hasWork({ notes: [], drums: [], lines: [] }));
});

test("Hear how it grew has the lines as one stage, after the sung harmony", () => {
  const keys = STAGES.map(s => s.key);
  assert.equal(keys.indexOf("lines"), keys.indexOf("voice2_sung") + 1);
});
