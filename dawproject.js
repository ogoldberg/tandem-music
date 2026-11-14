// Export the song as a DAWproject file (EXP.3): the open exchange format of Bitwig, Studio One and
// Cubase (https://github.com/bitwig/dawproject, version 1.0). A .dawproject file is a zip with
// project.xml (tracks, mixer and arrangement), metadata.xml and the audio files. Melody, harmony, the
// harmony voice (HARM.1) and drums are note clips on their own tracks (the same channels and drum keys
// as the MIDI file), and every recording the studio holds (the takes, the separated music, the band
// and the voice played as an instrument) is an audio clip on its own track, from zero, so it lines up
// with the notes as the stems do. The tempo is the project tempo in 4/4; the key has no place in the format and goes in
// the metadata comment. DOM-free so Node tests import it directly.

import { encodeWav, zipFiles } from "./bundle.js";
import { arrangementSeconds, DRUM_NOTES, DRUM_SECONDS, STEM_FILES } from "./daw.js";
import { keyLabel } from "./harmony.js";

export const DAWPROJECT_FILES = Object.freeze({ project: "project.xml", metadata: "metadata.xml" });
export const DAWPROJECT_TYPE = "application/zip";
export const FORMAT_VERSION = "1.0";
// Note parts: name, MIDI channel (0-based, as in the MIDI file) and velocity (0..1, the MIDI file's
// 90 and 70 of 127).
const NOTE_TRACKS = [
  { key: "notes", name: "Melody", channel: 0, vel: 90 / 127, color: "#3b82f6" },
  { key: "harmony", name: "Harmony", channel: 1, vel: 70 / 127, color: "#a855f7" },
  { key: "voice2", name: "Harmony voice", channel: 2, vel: 80 / 127, color: "#14b8a6" },
];
const DRUMS = { name: "Drums", channel: 9, vel: 90 / 127, color: "#f97316" };
// Audio tracks in the order they are listed, with their names in the DAW.
export const AUDIO_TRACKS = Object.freeze([
  { slot: "band", name: "Band", color: "#22c55e" },
  { slot: "timbre", name: "Voice as instrument", color: "#14b8a6" },
  { slot: "voice2_sung", name: "Harmony voice (sung)", color: "#0d9488" },
  { slot: "tuned", name: "Vocal (tuned)", color: "#ef4444" },
  { slot: "polished", name: "Vocal (polished)", color: "#f43f5e" },
  { slot: "vocal", name: "Vocal (separated)", color: "#ec4899" },
  { slot: "original", name: "Vocal (original)", color: "#e11d48" },
  { slot: "accompaniment", name: "Music (separated)", color: "#eab308" },
]);
// The vocal takes are versions of one performance: only the most finished one plays, the others are
// muted so they can be compared without singing over each other.
const VOCAL_ORDER = ["tuned", "polished", "vocal", "original"];

const finite = x => typeof x === "number" && Number.isFinite(x);
const escape = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// Plain decimals, rounded to a millionth: no exponents, no float noise.
const num = x => String(Math.round(x * 1e6) / 1e6);
export const audioPath = slot => `audio/${STEM_FILES[slot]}`;

// The vocal take that plays (the others are muted): tuned, else polished, else the separated vocal,
// else the original; null when there is none.
export function audibleVocal(slots) {
  return VOCAL_ORDER.find(s => slots.includes(s)) || null;
}

// project.xml for `project`, with an audio track for each entry of `audio`: {slot: {seconds, gain,
// muted}}, where `seconds` is the length of the file at audioPath(slot), `gain` its linear track
// volume (default 1) and `muted` whether its track starts muted. `rate` is the files' sample rate.
export function projectXml(project, { audio = {}, rate, application = "alpha" } = {}) {
  const bpm = finite(project.bpm) && project.bpm > 0 ? project.bpm : 100;
  const beats = t => (t * bpm) / 60;
  let next = 0;
  const id = () => `id${next++}`;
  const tempoId = id(), signatureId = id();
  const masterTrack = id(), master = id();
  const tracks = [], lanes = [];
  const channel = (role, { destination, gain = 1, muted = false } = {}) => {
    const cid = role === "master" ? master : id();
    return `<Channel audioChannels="${role === "master" ? 2 : 1}"${destination ? ` destination="${destination}"` : ""} role="${role}" solo="false" id="${cid}">`
      + `<Mute value="${muted}" id="${id()}" name="Mute"/>`
      + `<Pan max="1" min="0" unit="normalized" value="0.5" id="${id()}" name="Pan"/>`
      + `<Volume max="2" min="0" unit="linear" value="${num(gain)}" id="${id()}" name="Volume"/></Channel>`;
  };
  const length = beats(arrangementSeconds(project));
  const noteTrack = (name, color, notes) => {
    const tid = id();
    tracks.push(`<Track contentType="notes" loaded="true" id="${tid}" name="${escape(name)}" color="${color}">${channel("regular", { destination: master })}</Track>`);
    lanes.push(`<Lanes track="${tid}" id="${id()}"><Clips id="${id()}"><Clip time="0" duration="${num(length)}" playStart="0" name="${escape(name)}">`
      + `<Notes id="${id()}">${notes.join("")}</Notes></Clip></Clips></Lanes>`);
  };
  const note = (time, duration, channelNo, key, vel) =>
    `<Note time="${num(beats(time))}" duration="${num(Math.max(beats(duration), 1e-6))}" channel="${channelNo}" key="${key}" vel="${num(vel)}" rel="${num(vel)}"/>`;
  for (const part of NOTE_TRACKS) {
    const notes = (project[part.key] || []).filter(n => n && finite(n.m) && finite(n.t) && finite(n.d) && n.d > 0);
    if (notes.length) noteTrack(part.name, part.color, notes.map(n => note(Math.max(0, n.t), n.d, part.channel, Math.min(127, Math.max(0, Math.round(n.m))), part.vel)));
  }
  const hits = (project.drums || []).filter(h => h && finite(h.t) && DRUM_NOTES[h.k] != null);
  if (hits.length) noteTrack(DRUMS.name, DRUMS.color, hits.map(h => note(Math.max(0, h.t), DRUM_SECONDS, DRUMS.channel, DRUM_NOTES[h.k], DRUMS.vel)));
  for (const { slot, name, color } of AUDIO_TRACKS) {
    const a = audio[slot];
    if (!a) continue;
    if (!finite(a.seconds) || a.seconds <= 0) throw Error(`The ${name} recording has no length.`);
    const tid = id(), span = beats(a.seconds);
    tracks.push(`<Track contentType="audio" loaded="true" id="${tid}" name="${escape(name)}" color="${color}">${channel("regular", { destination: master, gain: finite(a.gain) ? a.gain : 1, muted: !!a.muted })}</Track>`);
    lanes.push(`<Lanes track="${tid}" id="${id()}"><Clips id="${id()}"><Clip time="0" duration="${num(span)}" playStart="0" name="${escape(name)}">`
      + `<Warps contentTimeUnit="seconds" timeUnit="beats" id="${id()}">`
      + `<Audio channels="1" duration="${num(a.seconds)}" sampleRate="${rate}" id="${id()}"><File path="${audioPath(slot)}"/></Audio>`
      + `<Warp time="0" contentTime="0"/><Warp time="${num(span)}" contentTime="${num(a.seconds)}"/></Warps></Clip></Clips></Lanes>`);
  }
  if (!tracks.length) throw Error("Nothing to export yet: add notes or drums, or record a take.");
  tracks.push(`<Track contentType="audio notes" loaded="true" id="${masterTrack}" name="Master">${channel("master")}</Track>`);
  lanes.push(`<Lanes track="${masterTrack}" id="${id()}"><Clips id="${id()}"/></Lanes>`);
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n`
    + `<Project version="${FORMAT_VERSION}"><Application name="Tandem" version="${escape(application)}"/>`
    + `<Transport><Tempo max="999" min="20" unit="bpm" value="${num(bpm)}" id="${tempoId}" name="Tempo"/>`
    + `<TimeSignature denominator="4" numerator="4" id="${signatureId}"/></Transport>`
    + `<Structure>${tracks.join("")}</Structure>`
    + `<Arrangement id="${id()}"><Lanes timeUnit="beats" id="${id()}">${lanes.join("")}</Lanes></Arrangement>`
    + `<Scenes/></Project>\n`;
}

// metadata.xml: the title, and the key in the comment (DAWproject has no key field).
export function metadataXml({ title = "Tandem", key = null } = {}) {
  const comment = key ? `<Comment>Key: ${escape(keyLabel(key))}</Comment>` : "";
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<MetaData><Title>${escape(title)}</Title>${comment}</MetaData>\n`;
}

// The .dawproject file. `audio` maps track slots (AUDIO_TRACKS) to {samples (mono Float32Array at
// `rate`, starting at zero), gain, muted}; vocal takes other than audibleVocal are muted.
export function dawProject({ project, audio = {}, rate, key = null, title = "Tandem", date }) {
  const slots = AUDIO_TRACKS.map(t => t.slot).filter(s => audio[s] && audio[s].samples && audio[s].samples.length);
  const playing = audibleVocal(slots);
  const info = {}, files = [];
  for (const slot of slots) {
    const a = audio[slot];
    info[slot] = { seconds: a.samples.length / rate, gain: a.gain, muted: VOCAL_ORDER.includes(slot) ? slot !== playing : !!a.muted };
    files.push({ name: audioPath(slot), data: encodeWav(a.samples, rate) });
  }
  const encoder = new TextEncoder();
  return zipFiles([
    { name: DAWPROJECT_FILES.project, data: encoder.encode(projectXml(project, { audio: info, rate })) },
    { name: DAWPROJECT_FILES.metadata, data: encoder.encode(metadataXml({ title, key })) },
    ...files,
  ], date ? { date } : undefined);
}
