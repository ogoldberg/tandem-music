import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  midiFile, keySignature, exportKey, arrangementSeconds, sumStems, monoOf, stemsZip,
  PROGRAMS, DRUM_NOTES, TICKS_PER_BEAT, STEM_RATE, STEM_FILES,
} from "../daw.js";
import { INSTRUMENTS } from "../voices.js";
import { unzipFiles } from "../bundle.js";

// A small reader for type-1 Standard MIDI Files, enough to check what midiFile writes.
function readMidi(bytes) {
  const text = (at, n) => String.fromCharCode(...bytes.slice(at, at + n));
  const u32 = at => ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0;
  const u16 = at => (bytes[at] << 8) | bytes[at + 1];
  assert.equal(text(0, 4), "MThd");
  assert.equal(u32(4), 6);
  const format = u16(8), count = u16(10), division = u16(12), tracks = [];
  let at = 14;
  for (let n = 0; n < count; n++) {
    assert.equal(text(at, 4), "MTrk");
    const end = at + 8 + u32(at + 4);
    let i = at + 8, tick = 0, running = 0;
    const events = [];
    while (i < end) {
      let delta = 0, b;
      do { b = bytes[i++]; delta = (delta << 7) | (b & 127); } while (b & 128);
      tick += delta;
      let status = bytes[i];
      if (status & 128) i++; else status = running;
      if (status === 0xff) {
        const type = bytes[i], len = bytes[i + 1];
        events.push({ tick, meta: type, data: [...bytes.slice(i + 2, i + 2 + len)] });
        i += 2 + len;
      } else {
        running = status;
        const kind = status >> 4, channel = status & 15, size = kind === 0xc || kind === 0xd ? 1 : 2;
        events.push({ tick, kind, channel, data: [...bytes.slice(i, i + size)] });
        i += size;
      }
    }
    assert.equal(i, end, "track " + n + " ends where its length says");
    tracks.push(events);
    at = end;
  }
  assert.equal(at, bytes.length);
  const name = t => String.fromCharCode(...(t.find(e => e.meta === 3)?.data || []));
  return { format, division, tracks, name };
}

const notesOn = track => track.filter(e => e.kind === 9 && e.data[1] > 0).map(e => [e.tick, e.data[0], e.channel]);
const notesOff = track => track.filter(e => e.kind === 8 || (e.kind === 9 && e.data[1] === 0)).map(e => [e.tick, e.data[0]]);

const song = () => ({
  bpm: 120, instrument: "flute", harmony_instrument: "organ", melody_locked: true,
  notes: [{ m: 60, t: 0, d: 0.5 }, { m: 64, t: 0.5, d: 0.5 }, { m: 67, t: 1, d: 1 }],
  harmony: [{ m: 48, t: 0, d: 2 }, { m: 52, t: 0, d: 2 }],
  drums: [{ k: "kick", t: 0 }, { k: "snare", t: 0.5 }, { k: "hat", t: 0.75 }],
});

test("programs cover exactly the instruments and match the sample manifest", async () => {
  assert.deepEqual(Object.keys(PROGRAMS), [...INSTRUMENTS]);
  const manifest = JSON.parse(await readFile(new URL("../vendor/gm-samples-1/manifest.json", import.meta.url)));
  for (const name of INSTRUMENTS) assert.equal(PROGRAMS[name], manifest.instruments[name].program, name);
  assert.deepEqual(DRUM_NOTES, { kick: 36, snare: 38, hat: 42 });
});

test("the MIDI file is type 1 with a conductor track and one named track per part", () => {
  const midi = readMidi(midiFile(song(), { key: { tonic: 7, mode: "major" } }));
  assert.equal(midi.format, 1);
  assert.equal(midi.division, TICKS_PER_BEAT);
  assert.deepEqual(midi.tracks.map(midi.name), ["Tandem", "Melody", "Harmony", "Drums"]);
  const conductor = midi.tracks[0];
  const tempo = conductor.find(e => e.meta === 0x51).data;
  assert.equal((tempo[0] << 16) | (tempo[1] << 8) | tempo[2], 500000);
  assert.deepEqual(conductor.find(e => e.meta === 0x58).data, [4, 2, 24, 8]);
  assert.deepEqual(conductor.find(e => e.meta === 0x59).data, [1, 0]);
  for (const t of midi.tracks) assert.deepEqual(t.at(-1), { tick: t.at(-1).tick, meta: 0x2f, data: [] });
  assert.ok(conductor.every(e => e.kind === undefined), "no channel events on the conductor track");
});

test("notes land on the right ticks, channels and programs", () => {
  const [, melody, harmony, drums] = readMidi(midiFile(song())).tracks;
  const beat = TICKS_PER_BEAT; // 120 bpm: 0.5 s is one beat
  assert.deepEqual(melody.find(e => e.kind === 0xc), { tick: 0, kind: 0xc, channel: 0, data: [PROGRAMS.flute] });
  assert.deepEqual(notesOn(melody), [[0, 60, 0], [beat, 64, 0], [2 * beat, 67, 0]]);
  assert.deepEqual(notesOff(melody), [[beat, 60], [2 * beat, 64], [4 * beat, 67]]);
  assert.deepEqual(harmony.find(e => e.kind === 0xc), { tick: 0, kind: 0xc, channel: 1, data: [PROGRAMS.organ] });
  assert.deepEqual(notesOn(harmony), [[0, 48, 1], [0, 52, 1]]);
  assert.deepEqual(notesOff(harmony), [[4 * beat, 48], [4 * beat, 52]]);
  assert.equal(drums.find(e => e.kind === 0xc), undefined, "General MIDI drums need no program");
  assert.deepEqual(notesOn(drums), [[0, 36, 9], [beat, 38, 9], [1.5 * beat, 42, 9]]);
});

test("a note-off comes before a note-on of the same pitch at the same tick", () => {
  const p = { ...song(), notes: [{ m: 60, t: 0, d: 0.5 }, { m: 60, t: 0.5, d: 0.5 }], harmony: [], drums: [] };
  const melody = readMidi(midiFile(p)).tracks[1].filter(e => e.kind === 8 || e.kind === 9);
  assert.deepEqual(melody.map(e => [e.tick, e.kind]), [[0, 9], [960, 8], [960, 9], [1920, 8]]);
});

test("empty parts get no track, and an empty project is still a valid file", () => {
  const onlyDrums = readMidi(midiFile({ ...song(), notes: [], harmony: [] }));
  assert.deepEqual(onlyDrums.tracks.map(onlyDrums.name), ["Tandem", "Drums"]);
  const empty = readMidi(midiFile({ bpm: 90, notes: [], drums: [] }));
  assert.equal(empty.tracks.length, 1);
  assert.equal(empty.tracks[0].find(e => e.meta === 0x59), undefined, "no key without a key");
});

test("tempo is rounded to whole microseconds and timing follows the bpm", () => {
  const p = { bpm: 133, notes: [{ m: 62, t: 60 / 133, d: 60 / 133 }], drums: [] };
  const midi = readMidi(midiFile(p));
  const tempo = midi.tracks[0].find(e => e.meta === 0x51).data;
  assert.equal((tempo[0] << 16) | (tempo[1] << 8) | tempo[2], Math.round(60e6 / 133));
  assert.deepEqual(notesOn(midi.tracks[1]), [[960, 62, 0]]);
});

test("pitches are clamped to MIDI and bad notes are skipped", () => {
  const p = { bpm: 100, notes: [{ m: 130, t: 0, d: 1 }, { m: -3, t: 1, d: 1 }, { m: 60, t: NaN, d: 1 }, { m: 61, t: 1, d: 0 }], drums: [{ k: "cowbell", t: 0 }] };
  const midi = readMidi(midiFile(p));
  assert.deepEqual(notesOn(midi.tracks[1]).map(n => n[1]), [127, 0]);
  assert.deepEqual(midi.tracks.map(midi.name), ["Tandem", "Melody"], "an unknown drum is not written");
});

test("key signatures: sharps and flats of major and minor keys", () => {
  assert.deepEqual(keySignature({ tonic: 0, mode: "major" }), { sf: 0, mi: 0 });
  assert.deepEqual(keySignature({ tonic: 2, mode: "major" }), { sf: 2, mi: 0 });
  assert.deepEqual(keySignature({ tonic: 5, mode: "major" }), { sf: -1, mi: 0 });
  assert.deepEqual(keySignature({ tonic: 3, mode: "major" }), { sf: -3, mi: 0 });
  assert.deepEqual(keySignature({ tonic: 9, mode: "minor" }), { sf: 0, mi: 1 });
  assert.deepEqual(keySignature({ tonic: 4, mode: "minor" }), { sf: 1, mi: 1 });
  assert.deepEqual(keySignature({ tonic: 2, mode: "minor" }), { sf: -1, mi: 1 });
  const bytes = readMidi(midiFile({ bpm: 100, notes: [], drums: [] }, { key: { tonic: 2, mode: "minor" } })).tracks[0].find(e => e.meta === 0x59).data;
  assert.deepEqual(bytes, [255, 1], "-1 is written as a signed byte");
  assert.throws(() => keySignature({ tonic: 0, mode: "dorian" }), /Unknown mode/);
});

test("the export key is the harmony's chosen key, else the one detected from the melody", () => {
  const melody = [60, 64, 67, 65, 62, 60].map((m, i) => ({ m, t: i / 2, d: 0.45 }));
  assert.deepEqual(exportKey({ notes: melody, harmony: [] }, "9:minor"), { tonic: 9, mode: "minor" });
  assert.deepEqual(exportKey({ notes: melody, harmony: [] }, "auto"), { tonic: 0, mode: "major" });
  assert.equal(exportKey({ notes: [], harmony: [] }, "auto"), null);
  assert.deepEqual(exportKey({ notes: melody, harmony: [] }, "13:major"), { tonic: 0, mode: "major" }, "a bad choice falls back to detection");
  assert.deepEqual(exportKey({ notes: [], harmony: melody }, "auto"), { tonic: 0, mode: "major" }, "else from the harmony");
});

test("the arrangement length covers every note and drum with a tail, at least four seconds", () => {
  assert.equal(arrangementSeconds({ notes: [], harmony: [], drums: [] }), 5);
  assert.equal(arrangementSeconds({ notes: [{ m: 60, t: 6, d: 1 }], harmony: [{ m: 48, t: 0, d: 9 }], drums: [{ k: "kick", t: 3 }] }), 11);
  assert.equal(arrangementSeconds({ notes: [], drums: [{ k: "kick", t: 7 }] }), 9);
});

test("stems are summed sample by sample into the mix", () => {
  const a = Float32Array.of(0.1, 0.2, 0.3), b = Float32Array.of(0.5, -0.5);
  assert.deepEqual([...sumStems([a, b], 4)], [...Float32Array.of(0.1 + 0.5, 0.2 - 0.5, 0.3, 0)]);
  assert.deepEqual([...sumStems([], 2)], [0, 0]);
});

test("monoOf averages the channels of a decoded buffer", () => {
  const left = Float32Array.of(1, 0.5), right = Float32Array.of(0, 0.5);
  const buffer = { numberOfChannels: 2, length: 2, getChannelData: c => (c ? right : left) };
  assert.deepEqual([...monoOf(buffer)], [0.5, 0.5]);
});

test("the stems zip holds same-length WAVs from zero, the mix of the parts, the vocals and the MIDI", async () => {
  const melody = Float32Array.from({ length: 300 }, (_, i) => Math.sin(i / 5) * 0.3);
  const drums = Float32Array.from({ length: 300 }, (_, i) => (i % 50 === 0 ? 0.6 : 0));
  const original = Float32Array.from({ length: 450 }, () => 0.25);
  const midi = midiFile(song());
  const zip = stemsZip({ parts: { melody, drums }, vocals: { original }, rate: 8000, midi });
  const files = await unzipFiles(zip);
  assert.deepEqual([...files.keys()], [STEM_FILES.mix, STEM_FILES.melody, STEM_FILES.drums, STEM_FILES.original, STEM_FILES.midi]);
  assert.deepEqual(files.get(STEM_FILES.midi), midi);
  const pcm = name => { const b = files.get(name); const v = new DataView(b.buffer, b.byteOffset); assert.equal(v.getUint32(24, true), 8000); return Int16Array.from({ length: (b.length - 44) / 2 }, (_, i) => v.getInt16(44 + i * 2, true)); };
  const [mix, m, d, o] = [STEM_FILES.mix, STEM_FILES.melody, STEM_FILES.drums, STEM_FILES.original].map(pcm);
  for (const x of [mix, m, d, o]) assert.equal(x.length, 450, "every stem is as long as the longest");
  for (let i = 0; i < 450; i++) assert.ok(Math.abs(mix[i] - (m[i] + d[i])) <= 1, "mix = melody + drums within rounding at " + i);
  assert.equal(m[0], 0);
  assert.equal(d[0], Math.round(0.6 * 32767), "the drum hit at zero stays at zero");
  assert.equal(o[449], Math.round(0.25 * 32767), "the vocal is not trimmed");
  assert.equal(m[449], 0, "parts are padded with silence");
});

test("vocals alone make no mix; nothing at all is refused", async () => {
  const files = await unzipFiles(stemsZip({ parts: {}, vocals: { tuned: Float32Array.of(0.1, 0.2) }, rate: 8000, midi: midiFile(song()) }));
  assert.deepEqual([...files.keys()], [STEM_FILES.tuned, STEM_FILES.midi]);
  assert.throws(() => stemsZip({ parts: {}, vocals: {}, rate: 8000, midi: midiFile(song()) }), /Nothing to export/);
});

test("the file names", () => {
  assert.equal(STEM_RATE, 44100);
  assert.deepEqual(STEM_FILES, {
    mix: "mix.wav", melody: "melody.wav", harmony: "harmony.wav", drums: "drums.wav",
    original: "vocal-original.wav", polished: "vocal-polished.wav", tuned: "vocal-tuned.wav", midi: "tandem.mid",
  });
});
