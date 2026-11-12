// Writes tests/fixtures/notation-project.json and notation.musicxml (EXP.2): a sung-style melody in
// F major at 96 bpm with timing jitter, a rest and a note held across the barline, and the chords
// generateHarmony makes for it. tests/test_notation.py validates the score against the MusicXML 4.0
// schema and reads it back with music21; tests/notation.test.mjs checks musicXml still writes it.
// Run from the repository root: node tests/fixtures/make_notation_fixture.mjs
import { writeFile } from "node:fs/promises";
import { generateHarmony, detectKey } from "../../harmony.js";
import { musicXml } from "../../notation.js";

const beat = 60 / 96;
// [MIDI pitch, onset in beats, length in beats]; the onsets are sung a little early or late.
const sung = [
  [65, 0.02, 1], [67, 0.98, 1], [69, 2.03, 0.5], [70, 2.49, 0.5], [72, 3.0, 2.0],
  [70, 5.01, 0.75], [69, 5.76, 0.25], [67, 6.0, 1.5],
  [65, 9.0, 0.5], [64, 9.52, 0.5], [62, 10.0, 1], [60, 11.02, 0.5], [61, 11.5, 0.5], [65, 12.0, 4],
];
const notes = sung.map(([m, t, d]) => ({ m, t: Math.round(t * beat * 1000) / 1000, d: Math.round(d * beat * 0.95 * 1000) / 1000 }));
const project = { format: "tandem-project", version: 1, bpm: 96, instrument: "flute", melody_locked: true, notes, drums: [], harmony_instrument: "piano" };
const key = detectKey(notes);
project.harmony = generateHarmony(project, { style: "chords", key }).notes;
const fixture = { title: "Notation fixture", key: { tonic: key.tonic, mode: key.mode }, project };
await writeFile(new URL("./notation-project.json", import.meta.url), JSON.stringify(fixture, null, 2) + "\n");
await writeFile(new URL("./notation.musicxml", import.meta.url), musicXml(project, { key: fixture.key, title: fixture.title }));
console.log("key", key, "melody", notes.length, "harmony", project.harmony.length);
