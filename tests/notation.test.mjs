import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { musicXml, partMeasures, spell, DIVISIONS, MEASURE } from "../notation.js";

// A small reader for what musicXml writes: parts -> measures -> notes, enough to check the score.
function readScore(xml) {
  const parts = {};
  for (const [, id, body] of xml.matchAll(/<part id="(P\d+)">([\s\S]*?)<\/part>/g)) {
    parts[id] = [...body.matchAll(/<measure number="(\d+)">([\s\S]*?)<\/measure>/g)].map(([, n, m]) => ({
      number: Number(n),
      notes: [...m.matchAll(/<note>([\s\S]*?)<\/note>/g)].map(([, note]) => ({
        chord: note.includes("<chord/>"),
        rest: note.includes("<rest"),
        step: note.match(/<step>(\w)<\/step>/)?.[1],
        alter: Number(note.match(/<alter>(-?\d)<\/alter>/)?.[1] || 0),
        octave: Number(note.match(/<octave>(\d)<\/octave>/)?.[1]),
        duration: Number(note.match(/<duration>(\d+)<\/duration>/)[1]),
        type: note.match(/<type>(\w+)<\/type>/)?.[1],
        dots: (note.match(/<dot\/>/g) || []).length,
        ties: [...note.matchAll(/<tie type="(\w+)"\/>/g)].map(x => x[1]),
        tied: [...note.matchAll(/<tied type="(\w+)"\/>/g)].map(x => x[1]),
      })),
    }));
  }
  return parts;
}
const STEPS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const midiOf = n => (n.octave + 1) * 12 + STEPS[n.step] + n.alter;
const TYPE_LENGTH = { whole: 16, half: 8, quarter: 4, eighth: 2, "16th": 1 };
const written = n => TYPE_LENGTH[n.type] * (n.dots ? 1.5 : 1);

test("the grid is sixteenth notes in 4/4", () => {
  assert.equal(DIVISIONS, 4);
  assert.equal(MEASURE, 16);
});

test("pitches are spelled with sharps, or with flats in a flat key", () => {
  assert.deepEqual(spell(60, 0), { step: "C", alter: 0, octave: 4 });
  assert.deepEqual(spell(61, 0), { step: "C", alter: 1, octave: 4 });
  assert.deepEqual(spell(61, 2), { step: "C", alter: 1, octave: 4 });
  assert.deepEqual(spell(70, -1), { step: "B", alter: -1, octave: 4 });
  assert.deepEqual(spell(59, -3), { step: "B", alter: 0, octave: 3 });
  assert.deepEqual(spell(36, 0), { step: "C", alter: 0, octave: 2 });
});

test("notes snap to the grid at the project tempo and gaps become rests", () => {
  // 120 bpm: a sixteenth is 0.125 s. The second note is sung a little late (0.51 s -> beat 2).
  const measures = partMeasures([{ m: 60, t: 0, d: 0.5 }, { m: 62, t: 0.51, d: 0.24 }, { m: 64, t: 1.5, d: 0.5 }], 120);
  assert.equal(measures.length, 1);
  assert.deepEqual(measures[0].map(e => [e.rest ? "rest" : e.pitches.join("+"), e.at, e.length]), [
    ["60", 0, 4], ["62", 4, 2], ["rest", 6, 2], ["rest", 8, 4], ["64", 12, 4],
  ]);
});

test("a note a sixteenth short of the next note, or of the beat before a rest, is held to it", () => {
  // 120 bpm. A sung quarter released a sixteenth early, then a whole bar sung 5% short.
  const [one, two] = partMeasures([{ m: 60, t: 0, d: 0.375 }, { m: 62, t: 0.5, d: 0.25 }, { m: 65, t: 2, d: 1.9 }], 120);
  assert.deepEqual(one.map(e => [e.rest ? "rest" : e.pitches[0], e.length]), [[60, 4], [62, 2], ["rest", 2], ["rest", 8]]);
  assert.deepEqual(two.map(e => [e.rest ? "rest" : e.pitches[0], e.length]), [[65, 16]]);
  // A gap of an eighth stays a rest.
  const [three] = partMeasures([{ m: 60, t: 0, d: 0.25 }, { m: 62, t: 0.5, d: 0.5 }], 120);
  assert.deepEqual(three.slice(0, 3).map(e => [e.rest ? "rest" : e.pitches[0], e.length]), [[60, 2], ["rest", 2], [62, 4]]);
});

test("a note across the barline is split into tied notes", () => {
  const [one, two] = partMeasures([{ m: 67, t: 1.5, d: 1 }], 120);
  const last = one.at(-1), first = two[0];
  assert.deepEqual([last.pitches, last.at, last.length, last.tieStart, last.tieStop], [[67], 12, 4, true, false]);
  assert.deepEqual([first.pitches, first.at, first.length, first.tieStart, first.tieStop], [[67], 0, 4, false, true]);
});

test("every length is a notatable value and a long note is tied across them", () => {
  // Five sixteenths from the bar start: a quarter tied to a sixteenth, never a "five-sixteenth" note.
  const [bar] = partMeasures([{ m: 60, t: 0, d: 0.625 }], 120);
  assert.deepEqual(bar.filter(e => !e.rest).map(e => e.length), [4, 1]);
  const notatable = new Set([16, 12, 8, 6, 4, 3, 2, 1]);
  const many = partMeasures(Array.from({ length: 40 }, (_, i) => ({ m: 60 + (i % 12), t: i * 0.37, d: 0.11 + (i % 7) * 0.13 })), 97);
  for (const bar of many) {
    assert.equal(bar.reduce((s, e) => s + e.length, 0), MEASURE);
    for (const e of bar) assert.ok(notatable.has(e.length), "length " + e.length);
  }
});

test("notes that start together are one chord; an overlap is cut at the next onset", () => {
  const [bar] = partMeasures([{ m: 64, t: 0, d: 2 }, { m: 60, t: 0, d: 1 }, { m: 67, t: 0, d: 1 }, { m: 65, t: 1, d: 1 }], 120);
  const notes = bar.filter(e => !e.rest);
  assert.deepEqual(notes[0].pitches, [60, 64, 67]);
  assert.equal(notes[0].at, 0);
  assert.equal(notes.filter(e => !e.tieStop).reduce((s, e) => s + (e.pitches[0] === 60 ? e.length : 0), 0), 8);
  assert.deepEqual(notes.at(-1).pitches, [65]);
});

test("the score has the key, 4/4, the tempo, a part per non-empty part and the instruments", () => {
  const xml = musicXml({
    bpm: 90, instrument: "flute", harmony_instrument: "piano",
    notes: [{ m: 65, t: 0, d: 0.6 }, { m: 70, t: 0.7, d: 0.6 }],
    harmony: [{ m: 41, t: 0, d: 2.6 }, { m: 48, t: 0, d: 2.6 }],
    drums: [{ k: "kick", t: 0 }],
  }, { key: { tonic: 5, mode: "major" } });
  assert.match(xml, /^<\?xml version="1.0" encoding="UTF-8"\?>\n<!DOCTYPE score-partwise PUBLIC "-\/\/Recordare\/\/DTD MusicXML 4.0 Partwise\/\/EN"/);
  assert.match(xml, /<score-partwise version="4.0">/);
  assert.match(xml, /<key><fifths>-1<\/fifths><mode>major<\/mode><\/key>/);
  assert.match(xml, /<time><beats>4<\/beats><beat-type>4<\/beat-type><\/time>/);
  assert.match(xml, /<per-minute>90<\/per-minute>/);
  assert.match(xml, /<sound tempo="90"\/>/);
  assert.match(xml, /<part-name>Melody<\/part-name>[\s\S]*<midi-program>74<\/midi-program>/);
  assert.match(xml, /<part-name>Harmony<\/part-name>[\s\S]*<midi-program>1<\/midi-program>/);
  assert.doesNotMatch(xml, /Drums/);
  const parts = readScore(xml);
  assert.deepEqual(Object.keys(parts), ["P1", "P2"]);
  // The melody stays in treble clef; the low harmony gets the bass clef.
  assert.match(xml.split('<part id="P2">')[0], /<sign>G<\/sign><line>2<\/line>/);
  assert.match(xml.split('<part id="P2">')[1], /<sign>F<\/sign><line>4<\/line>/);
  // B flat, spelled as a flat in F major.
  assert.ok(parts.P1[0].notes.some(n => n.step === "B" && n.alter === -1));
});

test("an unknown key writes no mode, and a part with no notes is left out", () => {
  const xml = musicXml({ bpm: 100, instrument: "piano", notes: [{ m: 60, t: 0, d: 1 }], harmony: [], drums: [] });
  assert.match(xml, /<key><fifths>0<\/fifths><\/key>/);
  assert.equal((xml.match(/<score-part /g) || []).length, 1);
});

test("notes below C0 are refused, since MusicXML has no octave below 0", () => {
  const notes = [{ m: 60, t: 0, d: 0.5 }, { m: 11, t: 0.5, d: 0.5 }, { m: 0, t: 1, d: 0.5 }];
  assert.throws(() => musicXml({ bpm: 120, notes, harmony: [{ m: 5, t: 0, d: 2 }] }), /3 notes are below C0/);
  assert.throws(() => musicXml({ bpm: 120, notes: [{ m: 11.4, t: 0, d: 1 }] }), /1 note is below C0/);
  // The lowest and highest writable pitches are written in octaves 0 and 9.
  const xml = musicXml({ bpm: 120, notes: [{ m: 12, t: 0, d: 0.5 }, { m: 127, t: 0.5, d: 0.5 }, { m: 11.6, t: 1, d: 0.5 }] });
  assert.match(xml, /<step>C<\/step><octave>0<\/octave>/);
  assert.match(xml, /<step>G<\/step><octave>9<\/octave>/);
  assert.equal((xml.match(/<octave>0<\/octave>/g) || []).length, 2);
});

test("a project without melody or harmony notes is refused", () => {
  assert.throws(() => musicXml({ bpm: 100, notes: [], harmony: [], drums: [{ k: "kick", t: 0 }] }), /Nothing to write as notation/);
});

test("ties and written lengths agree with the durations in every measure", () => {
  const xml = musicXml({
    bpm: 113, instrument: "piano",
    notes: Array.from({ length: 30 }, (_, i) => ({ m: 55 + ((i * 5) % 17), t: i * 0.41, d: 0.2 + (i % 5) * 0.31 })),
    harmony: [],
  });
  const [bars] = Object.values(readScore(xml));
  const open = new Set();
  for (const bar of bars) {
    assert.equal(bar.notes.filter(n => !n.chord).reduce((s, n) => s + n.duration, 0), MEASURE, "measure " + bar.number);
    for (const n of bar.notes) {
      if (!(n.rest && n.type === undefined)) assert.equal(written(n), n.duration);
      assert.deepEqual(n.ties, n.tied);
      if (n.rest) continue;
      const m = midiOf(n);
      if (n.ties.includes("stop")) assert.ok(open.delete(m), "tie stop without a start at " + m);
      if (n.ties.includes("start")) open.add(m);
    }
  }
  assert.equal(open.size, 0);
});

test("text in the title is escaped", () => {
  const xml = musicXml({ bpm: 100, notes: [{ m: 60, t: 0, d: 1 }], harmony: [] }, { title: 'Rock & "roll" <live>' });
  assert.match(xml, /<work-title>Rock &amp; &quot;roll&quot; &lt;live&gt;<\/work-title>/);
});

test("the fixture project writes exactly the checked-in score the schema test validates", async () => {
  const project = JSON.parse(await readFile(new URL("./fixtures/notation-project.json", import.meta.url), "utf8"));
  const expected = await readFile(new URL("./fixtures/notation.musicxml", import.meta.url), "utf8");
  assert.equal(musicXml(project.project, { key: project.key, title: project.title }), expected);
});
