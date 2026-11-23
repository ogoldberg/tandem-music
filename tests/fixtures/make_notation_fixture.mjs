// Writes tests/fixtures/notation-project.json and notation.musicxml (EXP.2): a sung-style melody in
// F major at 96 bpm with timing jitter, a rest and a note held across the barline, and the chords
// generateHarmony makes for it, with lyrics (LYR.1): words split into syllables and one held over
// two notes. tests/test_notation.py validates the score against the MusicXML 4.0
// schema and reads it back with music21; tests/notation.test.mjs checks musicXml still writes it.
// SHEET.1: it also writes notation-chords.json and notation-chords.musicxml, a short song whose chords part has a flat root,
// sevenths and a chord struck halfway through a held melody note, for the chord symbols (<harmony>) over the melody.
// The notation project is kept as it was made (other fixtures and spikes read it): only with --project is it made again.
// Run from the repository root: node tests/fixtures/make_notation_fixture.mjs [--project]
import { readFile, writeFile } from "node:fs/promises";
import { generateHarmony, detectKey } from "../../harmony.js";
import { musicXml } from "../../notation.js";

if (process.argv.includes("--project")) {
  const beat = 60 / 96;
  // [MIDI pitch, onset in beats, length in beats]; the onsets are sung a little early or late.
  const sung = [
    [65, 0.02, 1], [67, 0.98, 1], [69, 2.03, 0.5], [70, 2.49, 0.5], [72, 3.0, 2.0],
    [70, 5.01, 0.75], [69, 5.76, 0.25], [67, 6.0, 1.5],
    [65, 9.0, 0.5], [64, 9.52, 0.5], [62, 10.0, 1], [60, 11.02, 0.5], [61, 11.5, 0.5], [65, 12.0, 4],
  ];
  const notes = sung.map(([m, t, d]) => ({ m, t: Math.round(t * beat * 1000) / 1000, d: Math.round(d * beat * 0.95 * 1000) / 1000 }));
  const lyrics = "Sing it slow-ly, sing it _ low, and let the morn-ing come";
  const project = { format: "tandem-project", version: 1, bpm: 96, instrument: "flute", melody_locked: true, notes, drums: [], harmony_instrument: "piano", lyrics };
  const key = detectKey(notes);
  project.harmony = generateHarmony(project, { style: "chords", key }).notes;
  const fixture = { title: "Notation fixture", key: { tonic: key.tonic, mode: key.mode }, project };
  await writeFile(new URL("./notation-project.json", import.meta.url), JSON.stringify(fixture, null, 2) + "\n");
}
const fixture = JSON.parse(await readFile(new URL("./notation-project.json", import.meta.url), "utf8"));
await writeFile(new URL("./notation.musicxml", import.meta.url), musicXml(fixture.project, { key: fixture.key, title: fixture.title }));

// Four bars at 120 bpm in F major: F, Gm7, B♭maj7, then F for two beats and C7 for two under a held whole note.
const b2 = 0.5, bar = 2;
const chord = (ms, t, d) => ms.map(m => ({ m, t, d }));
const chords = {
  title: "Chord symbols fixture",
  key: { tonic: 5, mode: "major" },
  project: {
    format: "tandem-project", version: 1, bpm: 120, instrument: "flute", melody_locked: true, drums: [], harmony_instrument: "piano",
    notes: [[65, 0, 2], [67, 2, 2], [69, 4, 2], [70, 6, 2], [72, 8, 4], [70, 12, 4]].map(([m, t, d]) => ({ m, t: t * b2, d: d * b2 })),
    harmony: [...chord([53, 57, 60], 0, bar), ...chord([55, 58, 62, 65], bar, bar), ...chord([58, 62, 65, 69], 2 * bar, bar),
      ...chord([53, 57, 60], 3 * bar, bar / 2), ...chord([48, 52, 55, 58], 3.5 * bar, bar / 2)],
    lyrics: "Here the chords come, and go",
  },
};
await writeFile(new URL("./notation-chords.json", import.meta.url), JSON.stringify(chords, null, 2) + "\n");
await writeFile(new URL("./notation-chords.musicxml", import.meta.url), musicXml(chords.project, { key: chords.key, title: chords.title }));
console.log("wrote notation.musicxml and notation-chords.musicxml");
