import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dawProject, projectXml, metadataXml, audibleVocal, audioPath, AUDIO_TRACKS, DAWPROJECT_FILES } from "../dawproject.js";
import { unzipFiles, isWav } from "../bundle.js";
import { STEM_FILES, arrangementSeconds } from "../daw.js";
import { fixtureSong } from "./fixtures/make_dawproject_fixture.mjs";

const attrs = s => Object.fromEntries([...s.matchAll(/(\w+)="([^"]*)"/g)].map(([, k, v]) => [k, v]));
// A small reader for what projectXml writes: each track with its channel and its clip.
function readProject(xml) {
  const tracks = [...xml.matchAll(/<Track ([^>]*)>([\s\S]*?)<\/Track>/g)].map(([, a, body]) => ({
    ...attrs(a),
    channel: attrs(body.match(/<Channel ([^>]*)>/)[1]),
    mute: body.match(/<Mute value="(\w+)"/)[1] === "true",
    volume: Number(body.match(/<Volume [^>]*value="([^"]+)"/)[1]),
  }));
  const lanes = {};
  for (const [, track, body] of xml.matchAll(/<Lanes track="(\w+)"[^>]*>([\s\S]*?)<\/Lanes>/g)) {
    lanes[track] = {
      clip: body.match(/<Clip ([^>]*)>/) && attrs(body.match(/<Clip ([^>]*)>/)[1]),
      notes: [...body.matchAll(/<Note ([^>]*)\/>/g)].map(([, a]) => attrs(a)),
      audio: body.match(/<Audio ([^>]*)>/) && attrs(body.match(/<Audio ([^>]*)>/)[1]),
      file: body.match(/<File path="([^"]+)"/)?.[1],
      warps: [...body.matchAll(/<Warp ([^>]*)\/>/g)].map(([, a]) => attrs(a)),
    };
  }
  const tempo = attrs(xml.match(/<Tempo ([^>]*)\/>/)[1]);
  const signature = attrs(xml.match(/<TimeSignature ([^>]*)\/>/)[1]);
  return { tracks, lanes, tempo, signature, byName: name => tracks.find(t => t.name === name) };
}

test("the parts are note tracks in beats at the project tempo, on the MIDI file's channels and drum keys", () => {
  const project = { bpm: 120, notes: [{ m: 60, t: 0.5, d: 0.25 }, { m: 200, t: 1, d: 1 }, { m: 62, t: 2, d: 0 }], harmony: [{ m: 48, t: 0, d: 2 }],
    drums: [{ k: "kick", t: 0 }, { k: "snare", t: 0.5 }, { k: "hat", t: 0.75 }, { k: "cowbell", t: 1 }] };
  const p = readProject(projectXml(project, { rate: 44100 }));
  assert.equal(p.tempo.value, "120");
  assert.equal(p.tempo.unit, "bpm");
  assert.deepEqual([p.signature.numerator, p.signature.denominator], ["4", "4"]);
  assert.deepEqual(p.tracks.map(t => [t.name, t.contentType]), [["Melody", "notes"], ["Harmony", "notes"], ["Drums", "notes"], ["Master", "audio notes"]]);
  const notes = name => p.lanes[p.byName(name).id].notes;
  // 120 bpm: two beats a second. The zero-length note is dropped and the out-of-range pitch clamped.
  assert.deepEqual(notes("Melody").map(n => [n.key, n.time, n.duration, n.channel]), [["60", "1", "0.5", "0"], ["127", "2", "2", "0"]]);
  assert.deepEqual(notes("Harmony").map(n => [n.key, n.time, n.duration, n.channel]), [["48", "0", "4", "1"]]);
  assert.deepEqual(notes("Drums").map(n => [n.key, n.time, n.channel]), [["36", "0", "9"], ["38", "1", "9"], ["42", "1.5", "9"]]);
  // Each note clip spans the arrangement.
  assert.equal(Number(p.lanes[p.byName("Melody").id].clip.duration), arrangementSeconds(project) * 2);
  // Every track's channel goes to the master channel.
  const master = p.byName("Master").channel;
  assert.equal(master.role, "master");
  for (const t of p.tracks.filter(t => t.name !== "Master")) assert.equal(t.channel.destination, master.id);
});

test("recordings are audio tracks from zero, warped so their seconds line up with the beats", () => {
  const p = readProject(projectXml({ bpm: 90, notes: [{ m: 60, t: 0, d: 1 }] }, {
    rate: 44100, audio: { band: { seconds: 8, gain: 0.8, muted: true }, tuned: { seconds: 6 } },
  }));
  assert.deepEqual(p.tracks.map(t => t.name), ["Melody", "Band", "Vocal (tuned)", "Master"]);
  const band = p.byName("Band"), lane = p.lanes[band.id];
  assert.equal(band.contentType, "audio");
  assert.equal(band.mute, true);
  assert.equal(band.volume, 0.8);
  assert.equal(lane.file, "audio/band.wav");
  assert.deepEqual([lane.audio.duration, lane.audio.sampleRate, lane.audio.channels], ["8", "44100", "1"]);
  // 8 seconds at 90 bpm are 12 beats.
  assert.deepEqual([lane.clip.time, lane.clip.duration], ["0", "12"]);
  assert.deepEqual(lane.warps, [{ time: "0", contentTime: "0" }, { time: "12", contentTime: "8" }]);
  assert.equal(p.byName("Vocal (tuned)").mute, false);
  assert.equal(p.byName("Vocal (tuned)").volume, 1);
});

test("ids are unique and every reference points at one", () => {
  const xml = projectXml({ bpm: 100, notes: [{ m: 60, t: 0, d: 1 }], drums: [{ k: "kick", t: 0 }] }, { rate: 44100, audio: { original: { seconds: 3 } } });
  const ids = [...xml.matchAll(/ id="(\w+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, ref] of xml.matchAll(/ (?:track|destination)="(\w+)"/g)) assert.ok(ids.includes(ref), ref);
});

test("only the most finished vocal take plays", () => {
  assert.equal(audibleVocal(["original", "polished", "tuned"]), "tuned");
  assert.equal(audibleVocal(["original", "polished"]), "polished");
  assert.equal(audibleVocal(["original", "vocal", "accompaniment"]), "vocal");
  assert.equal(audibleVocal(["original"]), "original");
  assert.equal(audibleVocal(["band", "accompaniment"]), null);
});

test("the file is a zip of project.xml, metadata.xml and one WAV per recording", async () => {
  const rate = 44100, samples = n => Float32Array.from({ length: n }, (_, i) => Math.sin(i / 10) / 2);
  const zip = dawProject({
    project: { bpm: 100, notes: [{ m: 60, t: 0, d: 1 }], drums: [] }, rate, key: { tonic: 9, mode: "minor" }, title: "Song & <draft>",
    audio: { original: { samples: samples(rate * 2) }, polished: { samples: samples(rate) }, accompaniment: { samples: samples(rate * 2) },
      band: { samples: samples(rate * 3), gain: 0.8, muted: false }, timbre: { samples: new Float32Array(0) } },
  });
  const files = await unzipFiles(zip);
  assert.deepEqual([...files.keys()], [DAWPROJECT_FILES.project, DAWPROJECT_FILES.metadata, "audio/band.wav", "audio/vocal-polished.wav", "audio/vocal-original.wav", "audio/accompaniment.wav"]);
  for (const [name, data] of files) if (name.startsWith("audio/")) assert.ok(isWav(data), name);
  // 16-bit mono: 44 header bytes and two bytes a sample.
  assert.equal(files.get("audio/band.wav").length, 44 + rate * 3 * 2);
  const p = readProject(new TextDecoder().decode(files.get(DAWPROJECT_FILES.project)));
  assert.deepEqual(p.tracks.map(t => [t.name, t.mute]), [["Melody", false], ["Band", false], ["Vocal (polished)", false], ["Vocal (original)", true], ["Music (separated)", false], ["Master", false]]);
  assert.equal(p.lanes[p.byName("Vocal (original)").id].audio.duration, "2");
  const meta = new TextDecoder().decode(files.get(DAWPROJECT_FILES.metadata));
  assert.match(meta, /<Title>Song &amp; &lt;draft&gt;<\/Title>/);
  assert.match(meta, /<Comment>Key: A minor<\/Comment>/);
});

test("each audio track's file is the stem of the same name", () => {
  for (const { slot } of AUDIO_TRACKS) assert.equal(audioPath(slot), "audio/" + STEM_FILES[slot]);
});

test("names are escaped, an empty project is refused and an unknown key is left out", () => {
  assert.match(projectXml({ bpm: 100, notes: [{ m: 60, t: 0, d: 1 }] }, { rate: 44100, application: 'a"b' }), /version="a&quot;b"/);
  assert.throws(() => projectXml({ bpm: 100, notes: [], drums: [] }, { rate: 44100 }), /Nothing to export yet/);
  assert.throws(() => dawProject({ project: { bpm: 100, notes: [] }, rate: 44100, audio: { tuned: { samples: new Float32Array(0) } } }), /Nothing to export yet/);
  assert.throws(() => projectXml({ bpm: 100, notes: [] }, { rate: 44100, audio: { tuned: { seconds: 0 } } }), /has no length/);
  assert.doesNotMatch(metadataXml({ title: "x" }), /Comment/);
});

test("projectXml and metadataXml still write the fixture tests/test_dawproject.py validates", async () => {
  const { title, key, project, audio } = await fixtureSong();
  assert.equal(projectXml(project, { audio, rate: 44100 }), await readFile(new URL("./fixtures/dawproject-project.xml", import.meta.url), "utf8"));
  assert.equal(metadataXml({ title, key }), await readFile(new URL("./fixtures/dawproject-metadata.xml", import.meta.url), "utf8"));
});
