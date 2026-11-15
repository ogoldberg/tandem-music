// TRACK.1: recorded layers, each a track of its own: the layer list in the project, its mixer channels, its
// recording links, Tandem files, stems and DAWproject audio tracks, and older projects opening unchanged.
import test from "node:test";
import assert from "node:assert/strict";
import {
  cleanLayers, addLayer, removeLayer, setInto, renameLayer, newLayerId, nextLayerName, layerKey, layerFile, layerIdOf,
  isLayerKey, layerStemFile, layerSeconds, MAX_LAYERS,
} from "../layers.js";
import { cleanMix, channel, mixGains, mixParts, setChannel, MIX_PARTS } from "../mixer.js";
import { cleanLinks, linkedIds } from "../recordings.js";
import { projectFromState, createVersionStore } from "../versions.js";
import { writeBundle, readBundle, unzipFiles, encodeWav, ideaProject } from "../bundle.js";
import { stemsZip, arrangementSeconds } from "../daw.js";
import { dawProject, projectXml, audioPath } from "../dawproject.js";
import { timelineEnd } from "../playhead.js";
import { contentSeconds } from "../evolution.js";

const HEX = "a".repeat(64), HEX2 = "b".repeat(64);
const wav = (n = 100, rate = 8000, v = 0.5) => encodeWav(Float32Array.from({ length: n }, (_, i) => Math.sin(i / 3) * v), rate);
const json = bytes => JSON.parse(new TextDecoder().decode(bytes));
const song = (extra = {}) => ({ ...ideaProject(), bpm: 96, notes: [{ m: 62, t: 0.5, d: 0.25 }], drums: [{ k: "snare", t: 1 }], ...extra });
const two = [{ id: "harm1", name: "Layer 2", seconds: 3.5, into: "harmony" }, { id: "beat1", name: "Layer 3", seconds: 2 }];

test("a layer list is checked like the rest of the project", () => {
  assert.deepEqual(cleanLayers(undefined), []);
  assert.deepEqual(cleanLayers(null), []);
  assert.deepEqual(cleanLayers(two), two);
  assert.deepEqual(cleanLayers([{ id: "x1", name: "  Ooh  ", seconds: 1 }]), [{ id: "x1", name: "Ooh", seconds: 1 }]);
  for (const bad of [
    {}, "x", [{ id: "A1", name: "x", seconds: 1 }], [{ id: "x", name: "", seconds: 1 }], [{ id: "x", name: "x", seconds: 0 }],
    [{ id: "x", name: "x", seconds: 601 }], [{ id: "x", name: "x", seconds: 1, into: "band" }], [{ id: "x", name: "x", seconds: 1, extra: 1 }],
    [{ id: "x", name: "x", seconds: 1 }, { id: "x", name: "y", seconds: 1 }], [{ id: "x", name: "n".repeat(41), seconds: 1 }],
    Array.from({ length: MAX_LAYERS + 1 }, (_, i) => ({ id: "l" + i, name: "L" + i, seconds: 1 })),
  ]) assert.throws(() => cleanLayers(bad), /Invalid/, JSON.stringify(bad));
});

test("adding, naming, transcribing, renaming and removing layers", () => {
  let layers = addLayer([], { id: "one", seconds: 3.21049 });
  assert.deepEqual(layers, [{ id: "one", name: "Layer 2", seconds: 3.21 }]);
  layers = addLayer(layers, { id: "two", seconds: 2 });
  assert.equal(layers[1].name, "Layer 3");
  // A removed layer's number is used again by the next one.
  const mix = setChannel(setChannel({}, layerKey("one"), { mute: true }), "melody", { level: -3 });
  const removed = removeLayer(layers, mix, "one");
  assert.deepEqual(removed.layers.map(l => l.id), ["two"]);
  assert.deepEqual(removed.mix, { melody: { level: -3 } }, "the layer's mixer channel goes with it");
  assert.equal(nextLayerName(removed.layers), "Layer 2");
  assert.deepEqual(setInto(layers, "two", "drums")[1], { id: "two", name: "Layer 3", seconds: 2, into: "drums" });
  assert.throws(() => setInto(layers, "two", "band"), /Unknown part/);
  assert.throws(() => setInto(layers, "nope", "melody"), /No such layer/);
  assert.equal(renameLayer(layers, "one", " Backing ooh ")[0].name, "Backing ooh");
  const full = Array.from({ length: MAX_LAYERS }, (_, i) => ({ id: "l" + i, name: "L" + i, seconds: 1 }));
  assert.throws(() => addLayer(full, { id: "more", seconds: 1 }), /layers besides the take/);
  const id = newLayerId(n => Uint8Array.from({ length: n }, (_, i) => i * 7));
  assert.match(id, /^[a-z0-9]{12}$/);
  assert.equal(layerKey(id), "layer-" + id);
  assert.equal(layerIdOf(layerKey(id)), id);
  assert.equal(layerFile("abc"), "layer-abc.wav");
  assert.ok(isLayerKey("layer-abc") && !isLayerKey("layer-") && !isLayerKey("band") && !isLayerKey("layer-ABC"));
  assert.throws(() => layerKey("../x"), /Invalid layer id/);
});

test("the layer list is in the project only when there are layers, so older projects are unchanged", () => {
  const state = { ...song(), layers: [] };
  const plain = projectFromState(state);
  assert.equal("layers" in plain, false);
  assert.deepEqual(plain, projectFromState(song()));
  assert.deepEqual(projectFromState({ ...song(), layers: two }).layers, two);
});

test("every layer has a mixer channel of its own, heard by default", () => {
  const p = song({ layers: two });
  assert.deepEqual(mixParts(p), [...MIX_PARTS, "layer-harm1", "layer-beat1"]);
  assert.deepEqual(mixParts(song()), MIX_PARTS);
  assert.deepEqual(channel(p, "layer-harm1"), { level: 0, mute: false, solo: false });
  const mix = setChannel(setChannel({}, "layer-harm1", { mute: true }), "layer-beat1", { level: -6 });
  assert.deepEqual(mix, { "layer-harm1": { mute: true }, "layer-beat1": { level: -6 } });
  assert.deepEqual(cleanMix(mix), mix);
  assert.deepEqual(cleanMix({ "layer-harm1": { mute: false, level: 0 } }), {}, "the defaults are left out");
  assert.throws(() => cleanMix({ "layer-": { mute: true } }), /Invalid mix/);
  assert.throws(() => cleanMix({ "layer-x": { muted: true } }), /Invalid mix/);
  const gains = mixGains({ ...p, mix });
  assert.equal(gains["layer-harm1"], 0);
  assert.ok(Math.abs(gains["layer-beat1"] - 10 ** (-6 / 20)) < 1e-12);
  assert.equal(gains.melody, 1);
  // A solo on a layer silences the parts and the other layers.
  const solo = mixGains({ ...p, mix: { "layer-beat1": { solo: true } } }, ["melody", "drums", "layer-harm1", "layer-beat1"]);
  assert.deepEqual([solo.melody, solo.drums, solo["layer-harm1"], solo["layer-beat1"]], [0, 0, 0, 1]);
});

test("a layer's recording is linked from the draft and versions, and kept from clean-up", async () => {
  const links = cleanLinks({ original: { id: HEX, type: "audio/wav" }, "layer-harm1": { id: HEX2, type: "audio/wav" }, "layer-BAD": { id: HEX2 }, nonsense: { id: HEX } });
  assert.deepEqual(links, { original: { id: HEX, type: "audio/wav" }, "layer-harm1": { id: HEX2, type: "audio/wav" } });
  assert.deepEqual([...linkedIds([links])].sort(), [HEX, HEX2]);
  const data = new Map();
  const kv = { get: async k => data.get(k), update: async (k, fn) => { const [v, r] = fn(data.get(k)); data.set(k, v); return r } };
  const store = createVersionStore(kv, { now: () => 5 });
  const { id } = await store.save("Two layers", { ...song(), layers: two }, links);
  assert.deepEqual((await store.get(id)).layers, two);
  assert.deepEqual(await store.audio(id), links);
  assert.ok((await store.audioIds()).has(HEX2));
});

test("a Tandem file keeps each layer's recording beside the project", async () => {
  const project = song({ layers: two });
  const recordings = { original: wav(100), "layer-harm1": wav(60), "layer-beat1": wav(40) };
  const zip = writeBundle({ name: "Layers", savedAt: 1, project, recordings });
  const files = await unzipFiles(zip);
  assert.deepEqual([...files.keys()], ["tandem.json", "project.json", "original.wav", "layer-harm1.wav", "layer-beat1.wav"]);
  assert.deepEqual(json(files.get("project.json")).layers, two);
  const back = await readBundle(zip);
  assert.deepEqual(back.project.layers, two);
  assert.deepEqual(Object.keys(back.recordings).sort(), ["layer-beat1", "layer-harm1", "original"]);
  assert.deepEqual(back.recordings["layer-harm1"], recordings["layer-harm1"]);
  assert.throws(() => writeBundle({ project, recordings: { original: wav(), "layer-harm1": new Uint8Array([1, 2, 3]) } }), /must be WAV/);
});

test("an older Tandem file, with one take and no layers, opens unchanged", async () => {
  const project = song();
  const zip = writeBundle({ name: "Old", savedAt: 2, project, recordings: { original: wav(100) } });
  const back = await readBundle(zip);
  assert.deepEqual(back.project, project);
  assert.equal("layers" in back.project, false);
  assert.deepEqual(Object.keys(back.recordings), ["original"]);
  assert.deepEqual(cleanLayers(back.project.layers), []);
});

test("every layer is a stem of its own and the heard ones are in mix.wav", async () => {
  const a = Float32Array.from({ length: 8 }, () => 0.25), b = Float32Array.from({ length: 12 }, () => 0.5), mel = Float32Array.from({ length: 10 }, () => 0.1);
  const zip = stemsZip({
    parts: { melody: mel, "layer-harm1": a },
    layers: [{ file: "layer-2.wav", samples: a }, { file: "layer-3.wav", samples: b }],
    rate: 8000, midi: new Uint8Array([1]),
  });
  const files = await unzipFiles(zip);
  assert.deepEqual([...files.keys()], ["mix.wav", "melody.wav", "layer-2.wav", "layer-3.wav", "tandem.mid"]);
  const samples = bytes => { const v = new DataView(bytes.buffer, bytes.byteOffset); return Array.from({ length: (bytes.length - 44) / 2 }, (_, i) => v.getInt16(44 + i * 2, true) / 32767) };
  const mix = samples(files.get("mix.wav"));
  assert.equal(mix.length, 12, "as long as the longest stem, muted layers included");
  assert.ok(Math.abs(mix[0] - 0.35) < 1e-3, "the melody and the heard layer");
  assert.ok(Math.abs(mix[9] - 0.1) < 1e-3);
  assert.ok(Math.abs(mix[11]) < 1e-4, "the muted layer is not in the mix");
  assert.ok(Math.abs(samples(files.get("layer-3.wav"))[11] - 0.5) < 1e-3, "but it is a stem");
  assert.equal(samples(files.get("layer-2.wav")).length, 12);
  // Layers alone are something to export.
  assert.ok(stemsZip({ layers: [{ file: "layer-2.wav", samples: a }], rate: 8000, midi: new Uint8Array([1]) }).length > 0);
});

test("layer stems and DAWproject files are numbered by the layer's place, after the take", () => {
  assert.equal(layerStemFile(two, "harm1"), "layer-2.wav");
  assert.equal(layerStemFile(two, "beat1"), "layer-3.wav");
  assert.throws(() => layerStemFile(two, "gone"), /No such layer/);
  assert.equal(audioPath("layer-beat1", { layers: two }), "audio/layer-3.wav");
  assert.equal(audioPath("original"), "audio/vocal-original.wav");
});

test("each layer is a DAWproject audio track named as in the studio", async () => {
  const project = song({ layers: two, mix: { "layer-harm1": { mute: true } } });
  const rate = 8000, s = n => Float32Array.from({ length: n }, () => 0.2);
  const zip = dawProject({ project, rate, audio: { original: { samples: s(rate) }, "layer-harm1": { samples: s(rate * 2) }, "layer-beat1": { samples: s(rate / 2) } } });
  const files = await unzipFiles(zip);
  assert.ok(files.has("audio/vocal-original.wav") && files.has("audio/layer-2.wav") && files.has("audio/layer-3.wav"));
  const xml = new TextDecoder().decode(files.get("project.xml"));
  const tracks = [...xml.matchAll(/<Track contentType="audio" [^>]*name="([^"]+)"[^>]*>(.*?)<\/Track>/g)].map(m => ({ name: m[1], muted: /<Mute value="true"/.test(m[2]) }));
  assert.deepEqual(tracks.map(t => t.name), ["Vocal (original)", "Layer 2", "Layer 3"]);
  // Like every other track, a layer's track ignores the studio's mix: it is there, unmuted, to mix in the DAW.
  assert.deepEqual(tracks.filter(t => t.name.startsWith("Layer")).map(t => t.muted), [false, false]);
  assert.match(xml, /<File path="audio\/layer-2.wav"\/>/);
  assert.match(xml, /<Audio channels="1" duration="2" sampleRate="8000"/);
  // A project without layers writes exactly what it did before.
  const plain = song();
  assert.equal(projectXml(plain, { audio: { original: { seconds: 1 } }, rate }), projectXml({ ...plain, layers: [] }, { audio: { original: { seconds: 1 } }, rate }));
});

test("the song is as long as its layers", () => {
  const p = song({ layers: [{ id: "long", name: "Layer 2", seconds: 20 }] });
  assert.equal(timelineEnd(p), 20);
  assert.equal(contentSeconds(p), 20);
  assert.equal(arrangementSeconds(p), 21);
  const muted = { ...p, mix: { "layer-long": { mute: true } } };
  assert.deepEqual(layerSeconds(muted, { heard: true }), []);
  assert.equal(timelineEnd(muted), 20, "the timeline shows a muted layer");
  assert.equal(arrangementSeconds(muted), arrangementSeconds(song()), "a muted layer does not lengthen Export WAV");
});
