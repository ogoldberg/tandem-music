import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  crc32, zipFiles, unzipFiles, inflateWithin, encodeWav, isWav, toWav, writeBundle, readBundle, isBundle,
  bundleFileName, ideaProject, BUNDLE_FILES, MAX_BUNDLE_BYTES,
} from "../bundle.js";

const text = s => new TextEncoder().encode(s);
const json = bytes => JSON.parse(new TextDecoder().decode(bytes));
const wav = (n = 100, rate = 8000) => encodeWav(Float32Array.from({ length: n }, (_, i) => Math.sin(i / 3) * 0.5), rate);
const project = () => ({ ...ideaProject(), bpm: 96, notes: [{ m: 62, t: 0.5, d: 0.25 }], drums: [{ k: "snare", t: 1 }] });

test("crc32 matches the standard check value", () => {
  assert.equal(crc32(text("123456789")), 0xcbf43926);
  assert.equal(crc32(new Uint8Array()), 0);
});

test("zips and unzips files byte for byte", async () => {
  const files = [{ name: "a.txt", data: text("hello") }, { name: "dir/b.bin", data: Uint8Array.from([0, 255, 7]) }];
  const zip = zipFiles(files, { date: new Date(2026, 10, 11, 1, 2, 4) });
  assert.deepEqual([...zip.slice(0, 4)], [0x50, 0x4b, 0x03, 0x04]);
  const out = await unzipFiles(zip);
  assert.deepEqual([...out.keys()], ["a.txt", "dir/b.bin"]);
  assert.deepEqual(out.get("a.txt"), text("hello"));
  assert.deepEqual(out.get("dir/b.bin"), Uint8Array.from([0, 255, 7]));
});

test("the same files and date give the same zip", () => {
  const files = [{ name: "x", data: text("same") }], date = new Date(2026, 0, 2);
  assert.deepEqual(zipFiles(files, { date }), zipFiles(files, { date }));
});

test("a damaged zip is refused", async () => {
  const zip = zipFiles([{ name: "a.txt", data: text("hello") }]);
  const bad = zip.slice();
  bad[30 + 5] ^= 1; // a byte of the stored data: the CRC no longer matches
  await assert.rejects(unzipFiles(bad), /damaged/);
  await assert.rejects(unzipFiles(text("not a zip at all")), /not a Tandem file/);
  await assert.rejects(unzipFiles(zip.slice(0, zip.length - 4)), /not a Tandem file/);
});

test("an entry larger than the limit is refused before it is inflated", async () => {
  const zip = zipFiles([{ name: "big", data: new Uint8Array(1000) }]);
  await assert.rejects(unzipFiles(zip, { maxBytes: 999 }), /too large/);
  assert.ok(MAX_BUNDLE_BYTES >= 100 * 1024 * 1024);
});

test("inflating stops as soon as the data grows past the declared size", async () => {
  const { deflateRawSync } = await import("node:zlib");
  const packed = new Uint8Array(deflateRawSync(Buffer.alloc(1_000_000)));
  assert.equal((await inflateWithin(packed, 1_000_000)).length, 1_000_000);
  // A zip bomb declares a small size: reading stops at the limit, long before the whole stream is inflated.
  await assert.rejects(inflateWithin(packed, 10), /damaged/);
});

test("encodes 16-bit mono PCM WAV", () => {
  const bytes = encodeWav(Float32Array.from([0, 1, -1, 2]), 22050);
  const v = new DataView(bytes.buffer);
  assert.ok(isWav(bytes));
  assert.equal(bytes.length, 44 + 8);
  assert.equal(v.getUint16(22, true), 1);
  assert.equal(v.getUint32(24, true), 22050);
  assert.equal(v.getUint16(34, true), 16);
  assert.deepEqual([0, 1, 2, 3].map(i => v.getInt16(44 + i * 2, true)), [0, 32767, -32767, 32767]);
  assert.ok(!isWav(text("RIFF....WEBM")));
});

test("toWav keeps WAV bytes and decodes anything else to mono WAV", async () => {
  const already = wav(10);
  let decodes = 0;
  const decode = async () => {
    decodes++;
    return { sampleRate: 48000, length: 3, numberOfChannels: 2, getChannelData: c => Float32Array.from(c ? [1, 1, 0] : [0, 1, 0]) };
  };
  assert.deepEqual(await toWav(new Blob([already], { type: "audio/wav" }), decode), already);
  assert.equal(decodes, 0);
  const out = await toWav(new Blob([text("webm audio")], { type: "audio/webm" }), decode);
  const v = new DataView(out.buffer);
  assert.equal(decodes, 1);
  assert.equal(v.getUint32(24, true), 48000);
  assert.deepEqual([0, 1, 2].map(i => v.getInt16(44 + i * 2, true)), [16384, 32767, 0]);
});

test("a bundle round-trips its name, project and recordings", async () => {
  const recordings = { original: wav(100), tuned: wav(50) };
  const zip = writeBundle({ name: "Bus stop", savedAt: 1762819200000, project: project(), recordings });
  assert.ok(isBundle(zip));
  const files = await unzipFiles(zip);
  assert.deepEqual([...files.keys()], ["tandem.json", "project.json", "original.wav", "tuned.wav"]);
  assert.deepEqual(json(files.get("tandem.json")), { format: "tandem-bundle", version: 1, name: "Bus stop", savedAt: 1762819200000 });
  // project.json is the same portable project that Save project writes, with no audio in it.
  assert.deepEqual(json(files.get("project.json")), project());
  const back = await readBundle(zip);
  assert.equal(back.name, "Bus stop");
  assert.equal(back.savedAt, 1762819200000);
  assert.deepEqual(back.project, project());
  assert.deepEqual(Object.keys(back.recordings), ["original", "tuned"]);
  assert.deepEqual(back.recordings.original, recordings.original);
  assert.deepEqual(back.recordings.tuned, recordings.tuned);
});

test("the file names are the DESK.3 project folder's", () => {
  assert.deepEqual(BUNDLE_FILES, { meta: "tandem.json", project: "project.json", original: "original.wav", polished: "polished.wav", tuned: "tuned.wav" });
});

test("writing refuses a recording that is not WAV and a project without notes or drums", () => {
  assert.throws(() => writeBundle({ name: "", project: project(), recordings: { original: text("webm") } }), /WAV/);
  assert.throws(() => writeBundle({ name: "", project: { bpm: 100 }, recordings: {} }), /project/);
});

test("reads a project folder zipped by Finder: deflated, inside its folder, with __MACOSX entries", async () => {
  const bytes = new Uint8Array(await readFile(new URL("./fixtures/finder-rezipped.tandem.zip", import.meta.url)));
  const back = await readBundle(bytes);
  assert.equal(back.name, "Folder re-zipped");
  assert.equal(back.project.instrument, "flute");
  assert.deepEqual(back.project.notes, [{ m: 60, t: 0, d: 0.5 }]);
  assert.deepEqual(Object.keys(back.recordings), ["original"]);
  assert.ok(isWav(back.recordings.original));
  assert.equal(back.recordings.original.length, 1644);
});

test("a bundle without tandem.json still opens, named by nothing", async () => {
  const zip = zipFiles([{ name: "project.json", data: text(JSON.stringify(project())) }]);
  const back = await readBundle(zip);
  assert.equal(back.name, "");
  assert.equal(back.savedAt, null);
  assert.deepEqual(back.recordings, {});
});

test("reading refuses files that are not Tandem projects", async () => {
  await assert.rejects(readBundle(zipFiles([{ name: "song.mp3", data: text("x") }])), /no project\.json/);
  await assert.rejects(readBundle(zipFiles([{ name: "project.json", data: text("{") }])), /project\.json/);
  await assert.rejects(readBundle(zipFiles([{ name: "project.json", data: text('{"notes":[]}') }])), /not a Tandem project/);
  await assert.rejects(readBundle(zipFiles([
    { name: "project.json", data: text(JSON.stringify(project())) },
    { name: "original.wav", data: text("not wav") },
  ])), /original\.wav is not a WAV/);
  await assert.rejects(readBundle(zipFiles([
    { name: "a/project.json", data: text(JSON.stringify(project())) },
    { name: "b/project.json", data: text(JSON.stringify(project())) },
  ])), /more than one project/);
});

test("a bundle file name comes from the idea's name and is safe on every system", () => {
  assert.equal(bundleFileName("Bus stop"), "Bus stop.tandem.zip");
  assert.equal(bundleFileName('a/b:c*?"<>|\\d. '), "a-b-c-d.tandem.zip");
  assert.equal(bundleFileName(""), "Tandem idea.tandem.zip");
  assert.equal(bundleFileName("..."), "Tandem idea.tandem.zip");
});

test("an idea's project is empty, at 100 bpm on piano, with the melody protected", () => {
  assert.deepEqual(ideaProject(), {
    format: "tandem-project", version: 1, bpm: 100, instrument: "piano", melody_locked: true,
    notes: [], drums: [], harmony: [], harmony_instrument: "piano",
  });
});
