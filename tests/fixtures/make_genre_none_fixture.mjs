// Writes tests/fixtures/genre-none.json: the harmony and tempo with no genre, which tests/genre.test.mjs
// checks byte for byte. Rerun when Tandem's own harmony or tempo choices change on purpose (HARM.4 did).
import { writeFileSync } from "node:fs";
import { generateHarmony } from "../../harmony.js";
import { estimateTempo } from "../../groove.js";
import { tempoRange } from "../../genre.js";

const NOTES = [60, 64, 67, 69, 67, 64, 62, 60, 65, 69, 72, 69, 67, 64, 62, 60, 57, 60, 64, 62].map((m, i) => ({ m, t: Math.round(i * 0.55 * 1000) / 1000, d: 0.45 }));
const out = {
  chords: generateHarmony({ bpm: 96, notes: NOTES }, { style: "chords" }),
  bass: generateHarmony({ bpm: 96, notes: NOTES }, { style: "bass" }),
  minor: generateHarmony({ bpm: 120, notes: NOTES.map(n => ({ ...n, m: n.m - 3 })) }, { style: "chords", key: { tonic: 9, mode: "minor" } }),
  tempo: [estimateTempo(NOTES.map(n => n.t), { prefer: tempoRange(null) }), estimateTempo(Array.from({ length: 16 }, (_, i) => i * 0.4), { prefer: tempoRange(null) })],
};
writeFileSync(new URL("./genre-none.json", import.meta.url), JSON.stringify(out) + "\n");
