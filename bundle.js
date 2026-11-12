// One file for a song idea or project (MOB.3): a zip holding the project folder that the Mac app keeps
// on disk (DESK.3), so a file shared from the phone opens in the studio, and the same folder unzipped
// (or zipped again by Finder) opens too.
//
//   tandem.json   {"format":"tandem-bundle","version":1,"name","savedAt"}   (optional when reading)
//   project.json  the portable project, exactly what Save project writes; never any audio
//   original.wav  the recording; polished.wav and tuned.wav when the studio made them; vocal.wav and
//                 accompaniment.wav when it was separated (SEP.1); band.wav when a band was generated (GEN.2);
//                 timbre.wav when the voice was played as an instrument (TIMBRE.1)
//
// Written uncompressed (WAV hardly compresses, and every zip tool reads stored entries); read stored or
// deflated, at the top or inside one folder, ignoring Finder's __MACOSX entries. DOM-free so Node tests
// import it directly; WAV decoding of other formats is passed in.

import { AUDIO_SLOTS, monoSamples } from "./recordings.js";

export const BUNDLE_EXT = ".tandem.zip";
export const BUNDLE_TYPE = "application/zip";
export const BUNDLE_FILES = { meta: "tandem.json", project: "project.json", original: "original.wav", polished: "polished.wav", tuned: "tuned.wav",
  vocal: "vocal.wav", accompaniment: "accompaniment.wav", band: "band.wav",
  timbre: "timbre.wav" };
// Larger than any recording the studio handles (90 s hosted, minutes in the Mac app) with room to spare.
export const MAX_BUNDLE_BYTES = 512 * 1024 * 1024;
const MAX_NAME = 60;

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const notTandem = () => Error("This is not a Tandem file (a .tandem.zip shared from Tandem).");
const encoder = new TextEncoder();

function dosTime(date) {
  const year = Math.min(Math.max(date.getFullYear(), 1980), 2107);
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

// A zip of stored (uncompressed) entries with UTF-8 names.
export function zipFiles(files, { date = new Date() } = {}) {
  const { time, date: day } = dosTime(date);
  const entries = files.map(f => ({ name: encoder.encode(f.name), data: f.data, crc: crc32(f.data) }));
  const localSize = entries.reduce((n, e) => n + 30 + e.name.length + e.data.length, 0);
  const centralSize = entries.reduce((n, e) => n + 46 + e.name.length, 0);
  if (localSize + centralSize + 22 > 0xffffffff || entries.length > 0xffff) throw Error("Too much to put in one file.");
  const out = new Uint8Array(localSize + centralSize + 22), v = new DataView(out.buffer);
  let at = 0;
  const offsets = [];
  for (const e of entries) {
    offsets.push(at);
    v.setUint32(at, 0x04034b50, true); v.setUint16(at + 4, 20, true); v.setUint16(at + 6, 0x0800, true);
    v.setUint16(at + 8, 0, true); v.setUint16(at + 10, time, true); v.setUint16(at + 12, day, true);
    v.setUint32(at + 14, e.crc, true); v.setUint32(at + 18, e.data.length, true); v.setUint32(at + 22, e.data.length, true);
    v.setUint16(at + 26, e.name.length, true); v.setUint16(at + 28, 0, true);
    out.set(e.name, at + 30); out.set(e.data, at + 30 + e.name.length);
    at += 30 + e.name.length + e.data.length;
  }
  entries.forEach((e, i) => {
    v.setUint32(at, 0x02014b50, true); v.setUint16(at + 4, 20, true); v.setUint16(at + 6, 20, true);
    v.setUint16(at + 8, 0x0800, true); v.setUint16(at + 10, 0, true); v.setUint16(at + 12, time, true); v.setUint16(at + 14, day, true);
    v.setUint32(at + 16, e.crc, true); v.setUint32(at + 20, e.data.length, true); v.setUint32(at + 24, e.data.length, true);
    v.setUint16(at + 28, e.name.length, true); // extra, comment, disk, internal and external attributes stay 0
    v.setUint32(at + 42, offsets[i], true);
    out.set(e.name, at + 46);
    at += 46 + e.name.length;
  });
  v.setUint32(at, 0x06054b50, true); v.setUint16(at + 8, entries.length, true); v.setUint16(at + 10, entries.length, true);
  v.setUint32(at + 12, centralSize, true); v.setUint32(at + 16, localSize, true);
  return out;
}

// Inflate raw deflate data, stopping as soon as it grows past `limit` bytes.
export async function inflateWithin(data, limit) {
  if (typeof DecompressionStream !== "function") throw Error("This browser cannot open compressed zip files; share the file from Tandem instead.");
  const reader = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw")).getReader();
  const parts = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > limit) { await reader.cancel().catch(() => {}); throw Error("The file is damaged."); }
    parts.push(value);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

// Every file in a zip, by name (folders left out). Refuses encrypted, damaged and oversized entries.
export async function unzipFiles(bytes, { maxBytes = MAX_BUNDLE_BYTES } = {}) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 0xffff); i--) {
    if (v.getUint32(i, true) === 0x06054b50) { end = i; break; }
  }
  if (end < 0) throw notTandem();
  const count = v.getUint16(end + 10, true), cdOffset = v.getUint32(end + 16, true);
  const decoder = new TextDecoder();
  const files = new Map();
  let at = cdOffset, total = 0;
  for (let i = 0; i < count; i++) {
    if (at + 46 > bytes.length || v.getUint32(at, true) !== 0x02014b50) throw notTandem();
    const flags = v.getUint16(at + 8, true), method = v.getUint16(at + 10, true), crc = v.getUint32(at + 16, true);
    const packed = v.getUint32(at + 20, true), size = v.getUint32(at + 24, true);
    const nameLen = v.getUint16(at + 28, true), extraLen = v.getUint16(at + 30, true), commentLen = v.getUint16(at + 32, true);
    const local = v.getUint32(at + 42, true);
    const name = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLen));
    at += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith("/")) continue;
    if (flags & 1) throw Error("The file is encrypted.");
    if (size === 0xffffffff || packed === 0xffffffff || size > maxBytes || (total += size) > maxBytes) throw Error("The file is too large to open.");
    if (local + 30 > bytes.length || v.getUint32(local, true) !== 0x04034b50) throw notTandem();
    const start = local + 30 + v.getUint16(local + 26, true) + v.getUint16(local + 28, true);
    if (start + packed > bytes.length) throw Error("The file is damaged.");
    const raw = bytes.subarray(start, start + packed);
    let data;
    if (method === 0) data = raw.slice();
    else if (method === 8) data = await inflateWithin(raw, size);
    else throw Error("The file uses a zip compression Tandem cannot read.");
    if (data.length !== size || crc32(data) !== crc) throw Error("The file is damaged.");
    files.set(name, data);
  }
  return files;
}

// 16-bit PCM mono WAV.
export function encodeWav(samples, sampleRate) {
  const out = new Uint8Array(44 + samples.length * 2), v = new DataView(out.buffer);
  const tag = (o, s) => { for (let i = 0; i < s.length; i++) out[o + i] = s.charCodeAt(i); };
  tag(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); tag(8, "WAVE"); tag(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  tag(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), true);
  return out;
}

export function isWav(bytes) {
  const tag = (o, s) => [...s].every((c, i) => bytes[o + i] === c.charCodeAt(0));
  return bytes.length >= 12 && tag(0, "RIFF") && tag(8, "WAVE");
}

// A recording as WAV bytes: WAV is kept as it is; anything else (the phone's WebM or MP4 take) is decoded
// with `decode(arrayBuffer) -> AudioBuffer` and mixed down to mono.
export async function toWav(blob, decode) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  if (isWav(bytes)) return bytes;
  const buffer = await decode(bytes.buffer.slice(0));
  return encodeWav(monoSamples(buffer), buffer.sampleRate);
}

// The project a captured idea starts as in the studio.
export function ideaProject() {
  return { format: "tandem-project", version: 1, bpm: 100, instrument: "piano", melody_locked: true, notes: [], drums: [], harmony: [], harmony_instrument: "piano" };
}

const isProject = p => !!p && typeof p === "object" && !Array.isArray(p) && Array.isArray(p.notes) && Array.isArray(p.drums)
  && (p.format === undefined || p.format === "tandem-project");

export function writeBundle({ name = "", savedAt = null, project, recordings = {} }, options) {
  if (!isProject(project)) throw Error("Not a Tandem project: it needs notes and drums.");
  const meta = { format: "tandem-bundle", version: 1, name: String(name).trim().slice(0, MAX_NAME), savedAt: Number.isFinite(savedAt) ? savedAt : null };
  const files = [
    { name: BUNDLE_FILES.meta, data: encoder.encode(JSON.stringify(meta, null, 2)) },
    { name: BUNDLE_FILES.project, data: encoder.encode(JSON.stringify({ format: "tandem-project", version: 1, ...project }, null, 2)) },
  ];
  for (const slot of AUDIO_SLOTS) {
    if (!recordings[slot]) continue;
    if (!isWav(recordings[slot])) throw Error(`The ${slot} recording must be WAV.`);
    files.push({ name: BUNDLE_FILES[slot], data: recordings[slot] });
  }
  return zipFiles(files, options);
}

export const isBundle = bytes => bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 3 && bytes[3] === 4;

function parse(bytes, file) {
  try { return JSON.parse(new TextDecoder().decode(bytes)); } catch (err) { throw Error(`${file} could not be read: ${err.message}`); }
}

// {name, savedAt, project, recordings: {original?, polished?, tuned?, vocal?, accompaniment?, band?, timbre?}} with each recording as WAV bytes.
export async function readBundle(bytes, options) {
  const all = await unzipFiles(bytes, options);
  const files = new Map([...all].filter(([n]) => !n.startsWith("__MACOSX/") && !n.split("/").pop().startsWith("._")));
  const projects = [...files.keys()].filter(n => n.split("/").pop() === BUNDLE_FILES.project);
  if (projects.length > 1) throw Error("The file holds more than one project.");
  if (!projects.length) throw Error("The file has no project.json, so it is not a Tandem project.");
  const folder = projects[0].slice(0, -BUNDLE_FILES.project.length);
  const project = parse(files.get(projects[0]), BUNDLE_FILES.project);
  if (!isProject(project)) throw Error("project.json is not a Tandem project.");
  let name = "", savedAt = null;
  if (files.has(folder + BUNDLE_FILES.meta)) {
    const meta = parse(files.get(folder + BUNDLE_FILES.meta), BUNDLE_FILES.meta);
    if (meta && typeof meta === "object") {
      if (typeof meta.name === "string") name = meta.name.trim().slice(0, MAX_NAME);
      if (Number.isFinite(meta.savedAt)) savedAt = meta.savedAt;
    }
  }
  const recordings = {};
  for (const slot of AUDIO_SLOTS) {
    const data = files.get(folder + BUNDLE_FILES[slot]);
    if (!data) continue;
    if (!isWav(data)) throw Error(`${BUNDLE_FILES[slot]} is not a WAV recording.`);
    recordings[slot] = data;
  }
  return { name, savedAt, project, recordings };
}

// "<name>.tandem.zip", with characters that some file systems refuse replaced.
export function bundleFileName(name) {
  const clean = String(name ?? "").replace(/[\/\\:*?"<>|\x00-\x1f]+/g, "-").replace(/-+/g, "-").replace(/^[\s.-]+|[\s.-]+$/g, "").slice(0, MAX_NAME).trim();
  return (clean || "Tandem idea") + BUNDLE_EXT;
}
