// Hand a song on to any DAW (EXP.1): a type-1 Standard MIDI File with one named track per part,
// and the stems, one WAV per part plus the recorded vocals, laid out to line up when dropped
// into a DAW at zero. The studio renders each part on its own (index.html) and passes the
// samples here; the mixed WAV is the sum of the part stems, so they match it sample for sample.
// DOM-free so Node tests import it directly.

import { encodeWav, zipFiles } from "./bundle.js";
import { detectKey, MODES } from "./harmony.js";

// 960 ticks per quarter note, the same resolution the single-track export used for its timing.
export const TICKS_PER_BEAT = 960;
export const STEM_RATE = 44100;
// General MIDI programs (0-based) of the sampled instruments; tools/gm-samples/build.py renders
// the same programs, which a Node test checks against the sample manifest.
export const PROGRAMS = Object.freeze({ piano: 0, marimba: 12, strings: 48, bass: 33, chip: 80, organ: 16, guitar: 24, flute: 73 });
export const DRUM_NOTES = Object.freeze({ kick: 36, snare: 38, hat: 42 });
const DRUM_SECONDS = 0.1;
const PARTS = [
  { key: "notes", name: "Melody", channel: 0, velocity: 90, instrument: "instrument" },
  { key: "harmony", name: "Harmony", channel: 1, velocity: 70, instrument: "harmony_instrument" },
];
const DRUM_CHANNEL = 9;
export const STEM_FILES = Object.freeze({
  mix: "mix.wav", melody: "melody.wav", harmony: "harmony.wav", drums: "drums.wav",
  original: "vocal-original.wav", polished: "vocal-polished.wav", tuned: "vocal-tuned.wav",
  vocal: "vocal-separated.wav", accompaniment: "accompaniment.wav", midi: "tandem.mid",
});
const PART_STEMS = ["melody", "harmony", "drums"];
const VOCAL_STEMS = ["original", "polished", "tuned", "vocal", "accompaniment"];

const encoder = new TextEncoder();
const finite = x => typeof x === "number" && Number.isFinite(x);

function vlq(n) {
  const out = [n & 127];
  while ((n >>>= 7)) out.unshift((n & 127) | 128);
  return out;
}

const be = (n, bytes) => Array.from({ length: bytes }, (_, i) => (n >>> ((bytes - i - 1) * 8)) & 255);
const meta = (type, data) => [0xff, type, ...vlq(data.length), ...data];
const nameEvent = name => meta(0x03, [...encoder.encode(name)]);

// Sharps (+) or flats (-) of each major key by tonic pitch class.
const MAJOR_SF = [0, -5, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5];

// The MIDI key signature of {tonic 0..11, mode}: a minor key has the signature of its relative major.
export function keySignature(key) {
  if (!MODES.includes(key.mode)) throw Error("Unknown mode: " + key.mode);
  const minor = key.mode === "minor";
  return { sf: MAJOR_SF[(key.tonic + (minor ? 3 : 0)) % 12], mi: minor ? 1 : 0 };
}

// The key written into the MIDI file: the harmony key chosen in the studio ("tonic:mode"), else the
// key detected from the melody, else from the harmony; null when none can be told.
export function exportKey(project, choice) {
  const [tonic, mode] = String(choice || "").split(":");
  const t = Number(tonic);
  if (Number.isInteger(t) && t >= 0 && t < 12 && MODES.includes(mode)) return { tonic: t, mode };
  const found = detectKey(project.notes) || detectKey(project.harmony);
  return found && { tonic: found.tonic, mode: found.mode };
}

// One track from [tick, order, bytes] events: note-offs (order 0) before note-ons (order 1) at the same tick.
function track(head, events) {
  events.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const data = [];
  let prev = 0;
  for (const bytes of head) data.push(0, ...bytes);
  for (const [tick, , bytes] of events) {
    data.push(...vlq(tick - prev), ...bytes);
    prev = tick;
  }
  data.push(0, 0xff, 0x2f, 0);
  return [..."MTrk"].map(c => c.charCodeAt(0)).concat(be(data.length, 4), data);
}

// The project as a type-1 MIDI file: a conductor track (tempo, 4/4, the key when known) and one
// named track per part that has notes: Melody on channel 1 and Harmony on channel 2 with their
// General MIDI programs, Drums on channel 10.
export function midiFile(project, { key = null } = {}) {
  const bpm = finite(project.bpm) && project.bpm > 0 ? project.bpm : 100;
  const ticks = t => Math.max(0, Math.round(t * TICKS_PER_BEAT * bpm / 60));
  const tempo = Math.round(60e6 / bpm);
  const conductor = [nameEvent("Tandem"), meta(0x51, be(tempo, 3)), meta(0x58, [4, 2, 24, 8])];
  if (key) {
    const { sf, mi } = keySignature(key);
    conductor.push(meta(0x59, [sf & 255, mi]));
  }
  const tracks = [track(conductor, [])];
  for (const part of PARTS) {
    const notes = (project[part.key] || []).filter(n => n && finite(n.m) && finite(n.t) && finite(n.d) && n.d > 0);
    if (!notes.length) continue;
    const head = [nameEvent(part.name)];
    const program = PROGRAMS[project[part.instrument]];
    if (program != null) head.push([0xc0 | part.channel, program]);
    const events = [];
    for (const n of notes) {
      const m = Math.min(127, Math.max(0, Math.round(n.m))), on = ticks(n.t);
      events.push([on, 1, [0x90 | part.channel, m, part.velocity]], [Math.max(on + 1, ticks(n.t + n.d)), 0, [0x80 | part.channel, m, 0]]);
    }
    tracks.push(track(head, events));
  }
  const hits = (project.drums || []).filter(h => h && finite(h.t) && DRUM_NOTES[h.k] != null);
  if (hits.length) {
    const events = [];
    for (const h of hits) {
      const on = ticks(h.t), note = DRUM_NOTES[h.k];
      events.push([on, 1, [0x90 | DRUM_CHANNEL, note, 90]], [Math.max(on + 1, ticks(h.t + DRUM_SECONDS)), 0, [0x80 | DRUM_CHANNEL, note, 0]]);
    }
    tracks.push(track([nameEvent("Drums")], events));
  }
  const header = [..."MThd"].map(c => c.charCodeAt(0)).concat(be(6, 4), be(1, 2), be(tracks.length, 2), be(TICKS_PER_BEAT, 2));
  return Uint8Array.from(header.concat(...tracks));
}

// Seconds of audio the arrangement needs: every note and hit with a second of tail, at least four,
// and one more second so the last release is not cut.
export function arrangementSeconds(project) {
  const ends = [...(project.notes || []), ...(project.harmony || [])].map(n => n.t + n.d + 1)
    .concat((project.drums || []).map(h => h.t + 1));
  return Math.max(4, ...ends) + 1;
}

// The sample-by-sample sum of the stems, `frames` long.
export function sumStems(stems, frames) {
  const out = new Float32Array(frames);
  for (const s of stems) for (let i = 0; i < Math.min(frames, s.length); i++) out[i] += s[i];
  return out;
}

// A decoded AudioBuffer mixed down to mono.
export function monoOf(buffer) {
  const out = new Float32Array(buffer.length);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < out.length; i++) out[i] += data[i] / buffer.numberOfChannels;
  }
  return out;
}

const padded = (samples, frames) => {
  if (samples.length === frames) return samples;
  const out = new Float32Array(frames);
  out.set(samples);
  return out;
};

// The stems as one zip: mix.wav (the parts summed; only when there are parts), a WAV per part and
// per recorded vocal, all mono at `rate`, starting at zero and as long as the longest of them, and
// the MIDI file. `parts` and `vocals` map stem names to Float32Array samples; absent ones are left out.
export function stemsZip({ parts = {}, vocals = {}, rate, midi, date }) {
  const present = names => names.filter(n => parts[n] || vocals[n]);
  const partNames = present(PART_STEMS), vocalNames = present(VOCAL_STEMS);
  if (!partNames.length && !vocalNames.length) throw Error("Nothing to export yet: add notes or drums, or record a take.");
  const frames = Math.max(...partNames.map(n => parts[n].length), ...vocalNames.map(n => vocals[n].length));
  const files = [];
  if (partNames.length) files.push({ name: STEM_FILES.mix, data: encodeWav(sumStems(partNames.map(n => parts[n]), frames), rate) });
  for (const n of partNames) files.push({ name: STEM_FILES[n], data: encodeWav(padded(parts[n], frames), rate) });
  for (const n of vocalNames) files.push({ name: STEM_FILES[n], data: encodeWav(padded(vocals[n], frames), rate) });
  files.push({ name: STEM_FILES.midi, data: midi });
  return zipFiles(files, date ? { date } : undefined);
}
