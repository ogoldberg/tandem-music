import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { INSTRUMENTS, VOICES, FLOOR } from "../voices.js";
import {
  SAMPLE_BASE, LEVELS, DRUM_LEVELS, DRUM_KINDS, checkManifest, nearestRoot, planSample,
  createSampleBank, playSample, playDrumSample,
} from "../samples.js";

const manifest = JSON.parse(readFileSync(new URL("../vendor/gm-samples-1/manifest.json", import.meta.url), "utf8"));
const sums = readFileSync(new URL("../vendor/gm-samples-1/SHA256SUMS", import.meta.url), "utf8")
  .split("\n").filter(Boolean).map(l => l.split("  ")[1]);

// A minimal AudioContext that records what playSample schedules.
function mockContext() {
  const nodes = [];
  const param = v => {
    const p = { value: v, calls: [] };
    for (const name of ["setValueAtTime", "linearRampToValueAtTime", "exponentialRampToValueAtTime"]) {
      p[name] = (value, time) => {
        if (name === "exponentialRampToValueAtTime" && !(value > 0)) throw new RangeError("exponential ramp to non-positive value");
        p.calls.push([name, value, time]);
      };
    }
    return p;
  };
  const node = (kind, extra) => {
    const n = { kind, outputs: [], connect(dest) { n.outputs.push(dest); }, ...extra };
    nodes.push(n);
    return n;
  };
  return {
    nodes, destination: { kind: "destination" },
    createGain: () => node("gain", { gain: param(1) }),
    createBufferSource: () => node("source", {
      buffer: null, loop: false, loopStart: 0, loopEnd: 0, playbackRate: param(1),
      start(t) { this.started = t; }, stop(t) { this.stopped = t; },
    }),
  };
}

// A bank whose "decoded" buffers are {duration, file} objects, loading from the real manifest.
function fakeBank({ fail = () => false } = {}) {
  const fetched = [];
  const bank = createSampleBank({
    fetchBytes: async url => {
      fetched.push(url);
      if (fail(url)) throw new Error("HTTP 404 for " + url);
      if (url.endsWith("manifest.json")) return new TextEncoder().encode(JSON.stringify(manifest)).buffer;
      return { url };
    },
    decode: async bytes => ({ duration: 2, url: bytes.url }),
  });
  return { bank, fetched };
}

test("the committed samples cover every instrument and the drum kit, and only listed files are referenced", () => {
  assert.deepEqual(Object.keys(LEVELS), [...INSTRUMENTS]);
  assert.deepEqual(Object.keys(manifest.instruments).sort(), [...INSTRUMENTS].sort());
  checkManifest(manifest, INSTRUMENTS);
  const files = [manifest.drums.kick.file, manifest.drums.snare.file, manifest.drums.hat.file];
  for (const name of INSTRUMENTS) {
    const roots = Object.keys(manifest.instruments[name].samples).map(Number).sort((a, b) => a - b);
    // A root every 3 semitones: no note in range is pitched more than 1 semitone from its root.
    for (let i = 1; i < roots.length; i++) assert.equal(roots[i] - roots[i - 1], 3, `${name} root spacing`);
    for (const s of Object.values(manifest.instruments[name].samples)) files.push(s.file);
  }
  for (const f of files) assert.ok(sums.includes(f), `${f} is in SHA256SUMS`);
  assert.ok(sums.includes("manifest.json") && sums.includes("LICENSES.txt"));
  assert.equal(manifest.source.license, "MIT");
});

test("checkManifest rejects unknown formats, missing parts, bad file names and bad loops", () => {
  const good = () => JSON.parse(JSON.stringify(manifest));
  assert.throws(() => checkManifest({ ...good(), format: "x" }, INSTRUMENTS), /unknown format/);
  const noFlute = good(); delete noFlute.instruments.flute;
  assert.throws(() => checkManifest(noFlute, INSTRUMENTS), /missing instrument flute/);
  const escape = good(); escape.instruments.piano.samples["60"].file = "../../tandem_backend.py";
  assert.throws(() => checkManifest(escape, INSTRUMENTS), /bad sample piano 60/);
  const abs = good(); abs.drums.kick.file = "https://example.com/kick.mp3";
  assert.throws(() => checkManifest(abs, INSTRUMENTS), /missing drum kick/);
  const loop = good(); loop.instruments.strings.samples["60"].loop = [100, 50];
  assert.throws(() => checkManifest(loop, INSTRUMENTS), /bad loop strings 60/);
});

test("nearestRoot picks the closest root, the lower one on a tie, and the edge root out of range", () => {
  const roots = [36, 39, 42, 45];
  assert.equal(nearestRoot(roots, 40), 39);
  assert.equal(nearestRoot(roots, 41), 42);
  assert.equal(nearestRoot(roots, 42), 42);
  assert.equal(nearestRoot([36, 38], 37), 36);
  assert.equal(nearestRoot(roots, 20), 36);
  assert.equal(nearestRoot(roots, 90), 45);
});

test("planSample pitches by playback rate and fades over the voice's release at the key release", () => {
  const p = planSample("piano", 60, { duration: 4, loop: null }, 62, 1, 0.5);
  assert.ok(Math.abs(p.rate - Math.pow(2, 2 / 12)) < 1e-12);
  assert.deepEqual(p.gain, [
    { kind: "set", time: 1, value: LEVELS.piano },
    { kind: "set", time: 1.5, value: LEVELS.piano },
    { kind: "exp", time: 1.5 + VOICES.piano.env.release, value: FLOOR },
  ]);
  assert.ok(Math.abs(p.stop - (1.5 + VOICES.piano.env.release + 0.02)) < 1e-12);
});

test("planSample lets a recording that dies away before the key release end by itself", () => {
  // A 1 s marimba sample played an octave up lasts 0.5 s; the key is held for 2 s.
  const p = planSample("marimba", 48, { duration: 1, loop: null }, 60, 0, 2);
  assert.deepEqual(p.gain, [{ kind: "set", time: 0, value: LEVELS.marimba }]);
  assert.ok(Math.abs(p.stop - 0.5) < 1e-12);
});

test("planSample keeps a looped (sustained) note sounding for as long as the key is held", () => {
  const p = planSample("strings", 60, { duration: 3, loop: [0.8, 2.95] }, 60, 0, 10);
  assert.deepEqual(p.loop, [0.8, 2.95]);
  assert.ok(Math.abs(p.stop - (10 + VOICES.strings.env.release + 0.02)) < 1e-12);
  assert.throws(() => planSample("strings", 60, { duration: 3, loop: null }, 60, 0, 0), /positive/);
  assert.throws(() => planSample("kazoo", 60, { duration: 3, loop: null }, 60, 0, 1), /Unknown instrument/);
});

test("the bank loads an instrument's samples once, from this app only, sorted by root", async () => {
  const { bank, fetched } = fakeBank();
  assert.equal(bank.ready("piano"), false);
  await Promise.all([bank.load(["piano", "drums"]), bank.load(["piano"])]);
  assert.ok(bank.ready("piano") && bank.ready("drums"));
  const piano = bank.get("piano");
  assert.deepEqual(piano.roots, Object.keys(manifest.instruments.piano.samples).map(Number).sort((a, b) => a - b));
  const n = Object.keys(manifest.instruments.piano.samples).length;
  assert.equal(fetched.length, 1 + n + DRUM_KINDS.length, "manifest once, each file once");
  assert.ok(fetched.every(u => u.startsWith(SAMPLE_BASE)));
  await bank.load(["piano"]);
  assert.equal(fetched.length, 1 + n + DRUM_KINDS.length, "a loaded instrument is not fetched again");
  // Loop points are converted from sample offsets to seconds.
  await bank.load(["strings"]);
  const [start, end] = manifest.instruments.strings.samples["60"].loop;
  assert.deepEqual(bank.get("strings").samples.get(60).loop, [start / manifest.sample_rate, end / manifest.sample_rate]);
});

test("a failed load is reported, leaves the instrument unloaded, and is retried by the next load", async () => {
  let broken = true;
  const { bank } = fakeBank({ fail: url => broken && url.includes("/organ/") });
  await bank.load(["organ", "flute"]);
  assert.equal(bank.ready("organ"), false);
  assert.match(bank.error("organ").message, /HTTP 404/);
  assert.equal(bank.ready("flute"), true);
  assert.equal(bank.error("flute"), null);
  broken = false;
  await bank.load(["organ"]);
  assert.equal(bank.ready("organ"), true);
  assert.equal(bank.error("organ"), null);
});

test("playSample schedules a buffer source through a gain envelope, looping sustained voices", async () => {
  const { bank } = fakeBank();
  await bank.load(["strings", "piano"]);
  const ac = mockContext(), out = { kind: "bus" };
  const plan = playSample(ac, bank, "strings", 61, 1, 4, out);
  const [src, amp] = ac.nodes;
  assert.equal(src.kind, "source");
  assert.equal(src.buffer.url, SAMPLE_BASE + manifest.instruments.strings.samples["60"].file);
  assert.ok(Math.abs(src.playbackRate.value - Math.pow(2, 1 / 12)) < 1e-12);
  assert.equal(src.loop, true);
  assert.deepEqual([src.loopStart, src.loopEnd], plan.loop);
  assert.deepEqual(src.outputs, [amp]);
  assert.deepEqual(amp.outputs, [out]);
  assert.equal(amp.gain.calls[0][1], LEVELS.strings);
  assert.equal(src.started, 1);
  assert.equal(src.stopped, plan.stop);
  const ac2 = mockContext();
  playSample(ac2, bank, "piano", 60, 0, 1);
  assert.equal(ac2.nodes[0].loop, false);
  assert.equal(ac2.nodes[1].outputs[0], ac2.destination);
});

test("playSample and playDrumSample do nothing until their samples are loaded", async () => {
  const { bank } = fakeBank();
  const ac = mockContext();
  assert.equal(playSample(ac, bank, "flute", 60, 0, 1), null);
  assert.equal(playDrumSample(ac, bank, "kick", 0), false);
  assert.equal(ac.nodes.length, 0);
  await bank.load(["drums"]);
  assert.equal(playDrumSample(ac, bank, "snare", 0.5), true);
  const [src, amp] = ac.nodes;
  assert.equal(src.buffer.url, SAMPLE_BASE + "drums/snare.mp3");
  assert.equal(amp.gain.value, DRUM_LEVELS.snare);
  assert.equal(src.started, 0.5);
});

test("index.html falls back to the oscillator voice only when an instrument's samples are not loaded", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /if\(!playSample\(ac,samples,instrument,m,t,d,destination\)\)playNote\(ac,instrument,m,t,d,destination\)/);
  assert.match(html, /if\(!playDrumSample\(ac,samples,k,t,destination\)\)synthDrum\(ac,k,t,destination\)/);
});

test("parts loading together share one manifest request, and a failed manifest is fetched again", async () => {
  let broken = true;
  const { bank, fetched } = fakeBank({ fail: url => broken && url.endsWith("manifest.json") });
  await bank.load(["piano", "flute", "drums"]);
  assert.equal(fetched.filter(u => u.endsWith("manifest.json")).length, 1);
  for (const n of ["piano", "flute", "drums"]) assert.match(bank.error(n).message, /manifest\.json/);
  broken = false;
  await bank.load(["piano"]);
  assert.equal(fetched.filter(u => u.endsWith("manifest.json")).length, 2);
  assert.ok(bank.ready("piano"));
});
