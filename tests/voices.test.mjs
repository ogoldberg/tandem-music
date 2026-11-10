import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { VOICES, INSTRUMENTS, FLOOR, envelope, planNote, playNote, midiToHz } from "../voices.js";

const close = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

// A minimal AudioContext that records what playNote schedules.
function mockContext(sampleRate = 48000) {
  const nodes = [];
  const param = v => {
    const p = { value: v, calls: [], connections: [] };
    for (const name of ["setValueAtTime", "linearRampToValueAtTime", "exponentialRampToValueAtTime"]) {
      p[name] = (value, time) => {
        if (name === "exponentialRampToValueAtTime" && !(value > 0)) throw new RangeError("exponential ramp to non-positive value");
        p.calls.push([name, value, time]);
      };
    }
    return p;
  };
  const node = (kind, extra) => {
    const n = { kind, outputs: [], connect(dest) { n.outputs.push(dest); if (dest && dest.calls) dest.connections.push(n); }, ...extra };
    nodes.push(n);
    return n;
  };
  return {
    sampleRate, nodes, destination: { kind: "destination" },
    createGain: () => node("gain", { gain: param(1) }),
    createBiquadFilter: () => node("filter", { type: "lowpass", frequency: param(350), Q: param(1) }),
    createOscillator: () => node("osc", { type: "sine", frequency: param(440), detune: param(0), start(t) { this.started = t; }, stop(t) { this.stopped = t; } }),
  };
}

test("instrument list keeps the original five and adds organ, guitar and flute", () => {
  assert.deepEqual(INSTRUMENTS, ["piano", "marimba", "strings", "bass", "chip", "organ", "guitar", "flute"]);
  for (const name of INSTRUMENTS) assert.ok(VOICES[name].label, `${name} has a label`);
});

test("the backend allows exactly the instruments voices.js can play", () => {
  // tandem_backend.py validates projects and AI actions against its own INSTRUMENTS tuple.
  const src = readFileSync(new URL("../tandem_backend.py", import.meta.url), "utf8");
  const m = src.match(/^INSTRUMENTS\s*=\s*\(([^)]*)\)/m);
  assert.ok(m, "INSTRUMENTS tuple found in tandem_backend.py");
  const backend = [...m[1].matchAll(/"([a-z]+)"/g)].map(x => x[1]);
  assert.deepEqual(backend, [...INSTRUMENTS]);
});

test("every voice is well formed", () => {
  for (const [name, v] of Object.entries(VOICES)) {
    assert.ok(v.peak > 0 && v.peak <= 0.2, `${name} peak`);
    assert.ok(v.layers.length >= 1, `${name} layers`);
    for (const l of v.layers) {
      assert.ok(["sine", "square", "sawtooth", "triangle"].includes(l.type), `${name} layer type`);
      assert.ok(l.ratio > 0 && l.weight > 0, `${name} layer ratio/weight`);
    }
    const e = v.env;
    assert.ok(e.attack > 0 && e.decay >= 0 && e.sustain >= 0 && e.sustain <= 1 && e.release > 0, `${name} env`);
  }
});

test("midiToHz maps A4 to 440 Hz and octaves to doublings", () => {
  assert.equal(midiToHz(69), 440);
  assert.ok(close(midiToHz(81), 880));
  assert.ok(close(midiToHz(60), 261.6255653005986));
});

test("envelope rises to peak, decays to sustain and releases after the note", () => {
  const env = { attack: 0.1, decay: 0.2, sustain: 0.5, release: 0.3 };
  const { events, end } = envelope(env, 0.2, 1, 1);
  assert.deepEqual(events[0], { kind: "set", time: 1, value: 0 });
  assert.deepEqual(events[1], { kind: "linear", time: 1.1, value: 0.2 });
  assert.equal(events[2].kind, "exp");
  assert.ok(close(events[2].time, 1.3) && close(events[2].value, 0.1));
  assert.deepEqual(events[3], { kind: "set", time: 2, value: 0.1 });
  assert.deepEqual(events[4], { kind: "exp", time: 2.3, value: FLOOR });
  assert.ok(close(end, 2.3));
});

test("a note shorter than the decay releases from where the decay had got to", () => {
  const env = { attack: 0.1, decay: 1, sustain: 0.01, release: 0.2 };
  const { events, end } = envelope(env, 0.2, 0, 0.6);
  const cut = events[2];
  assert.equal(cut.kind, "exp");
  assert.ok(close(cut.time, 0.6));
  // Half-way through an exponential decay from 0.2 to 0.002 is the geometric mean.
  assert.ok(close(cut.value, Math.sqrt(0.2 * 0.002), 1e-12), `${cut.value}`);
  assert.ok(close(end, 0.8));
});

test("a note shorter than the attack ramps only part of the way up", () => {
  const { events } = envelope({ attack: 0.2, decay: 0.1, sustain: 0.5, release: 0.1 }, 0.1, 0, 0.05);
  assert.deepEqual(events[1], { kind: "linear", time: 0.05, value: 0.025 });
  assert.equal(events.length, 3);
});

test("a decaying voice that has faded does not hold silence for its release", () => {
  const { end } = envelope({ attack: 0.01, decay: 0.3, sustain: 0, release: 0.5 }, 0.15, 0, 2);
  assert.ok(close(end, 2.01));
});

test("envelope times never go backwards and exp ramps stay positive", () => {
  for (const name of INSTRUMENTS) {
    for (const d of [0.001, 0.05, 0.2, 0.5, 1, 3]) {
      const { events, end } = envelope(VOICES[name].env, VOICES[name].peak, 2, d);
      for (let i = 1; i < events.length; i++) assert.ok(events[i].time >= events[i - 1].time, `${name} d=${d} event ${i}`);
      for (const e of events) if (e.kind === "exp") assert.ok(e.value > 0, `${name} d=${d}`);
      assert.ok(end > 2 + d, `${name} d=${d} ends after the note`);
      assert.ok(Math.max(...events.map(e => e.value)) <= VOICES[name].peak + 1e-12);
    }
  }
});

test("planNote normalises layer gains and tunes layers to the note", () => {
  const plan = planNote("organ", 60, 0, 1, 48000);
  assert.ok(close(plan.layers.reduce((s, l) => s + l.gain, 0), 1));
  assert.deepEqual(plan.layers.map(l => l.frequency / midiToHz(60)).map(x => Math.round(x * 1e9) / 1e9), [1, 2, 3, 4]);
});

test("planNote drops partials at or above Nyquist and clamps the filter", () => {
  // Export renders at 22050 Hz: C8's 4th marimba partial (16.7 kHz) would alias, so it is dropped.
  const plan = planNote("marimba", 108, 0, 0.5, 22050);
  assert.equal(plan.layers.length, 1);
  assert.equal(plan.layers[0].frequency, midiToHz(108));
  assert.equal(planNote("marimba", 96, 0, 0.5, 22050).layers.length, 2, "C7's partials are all below Nyquist");
  const p = planNote("piano", 96, 0, 0.5, 22050);
  assert.ok(p.filter.from <= 22050 / 2 * 0.9 && p.filter.to <= 22050 / 2 * 0.9);
});

test("planNote rejects unknown instruments and empty notes", () => {
  assert.throws(() => planNote("kazoo", 60, 0, 1, 48000), /Unknown instrument: kazoo/);
  assert.throws(() => planNote("piano", 60, 0, 0, 48000), /duration/);
});

test("vibrato only starts when the note lasts past its delay", () => {
  assert.equal(planNote("flute", 72, 0, 0.05, 48000).vibrato, null);
  const v = planNote("flute", 72, 1, 1, 48000).vibrato;
  assert.ok(v && close(v.start, 1.2) && v.depth === 12);
});

test("playNote builds layered oscillators through filter and envelope to the destination", () => {
  const ac = mockContext();
  const plan = playNote(ac, "strings", 64, 0.5, 1, ac.destination);
  const oscs = ac.nodes.filter(n => n.kind === "osc");
  // Two detuned saws plus the vibrato LFO.
  assert.equal(oscs.length, 3);
  const voices = oscs.filter(o => o.type === "sawtooth");
  assert.deepEqual(voices.map(o => o.detune.value), [-7, 7]);
  for (const o of voices) {
    assert.equal(o.started, 0.5);
    assert.equal(o.stopped, plan.stop);
    assert.equal(o.detune.connections.length, 1, "vibrato drives detune");
  }
  const filter = ac.nodes.find(n => n.kind === "filter");
  const amp = filter.outputs[0];
  assert.equal(amp.outputs[0], ac.destination);
  assert.deepEqual(amp.gain.calls.map(c => c[0]), plan.gain.map(e => ({ set: "setValueAtTime", linear: "linearRampToValueAtTime", exp: "exponentialRampToValueAtTime" })[e.kind]));
});

test("playNote works for every instrument across the pitch range at export rate", () => {
  for (const name of INSTRUMENTS) {
    for (const m of [36, 60, 96]) {
      const ac = mockContext(22050);
      const plan = playNote(ac, name, m, 0, 0.4);
      assert.ok(plan.stop > 0.4);
      assert.ok(ac.nodes.some(n => n.outputs.includes(ac.destination)), `${name} ${m} reaches the destination`);
    }
  }
});

test("chip stays an unfiltered single square wave", () => {
  const ac = mockContext();
  playNote(ac, "chip", 60, 0, 0.3);
  assert.equal(ac.nodes.filter(n => n.kind === "filter").length, 0);
  assert.deepEqual(ac.nodes.filter(n => n.kind === "osc").map(o => o.type), ["square"]);
});
