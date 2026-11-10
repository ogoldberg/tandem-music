// Sampled General MIDI instruments (SND.1). The melody, harmony and drums play recorded notes
// rendered from the FluidR3_GM SoundFont by tools/gm-samples/build.py and self-hosted under
// SAMPLE_BASE. There is a root sample every 3 semitones; a note plays its nearest root, pitched
// by playback rate. Sustained instruments loop a crossfaded stretch of their held note while the
// key is held longer than the recording. The same functions schedule live playback
// (AudioContext) and the WAV export (OfflineAudioContext), so both sound alike. An instrument
// whose samples are missing or still loading plays its oscillator voice (voices.js) instead.

import { VOICES, FLOOR } from "./voices.js";

export const SAMPLE_BASE = "/vendor/gm-samples-1/";
export const DRUM_KINDS = Object.freeze(["kick", "snare", "hat"]);
// Output level of each instrument's loudest sample (the build normalises them all to the same
// peak), chosen so the sampled parts sit at about the loudness of the oscillator voices.
export const LEVELS = Object.freeze({
  piano: 0.32, marimba: 0.22, strings: 0.2, bass: 0.3, chip: 0.15, organ: 0.16, guitar: 0.24, flute: 0.22,
});
export const DRUM_LEVELS = Object.freeze({ kick: 0.3, snare: 0.22, hat: 0.1 });

// Check the shape of manifest.json before anything is fetched from it; file names must stay
// inside SAMPLE_BASE.
export function checkManifest(m, instruments) {
  const fail = why => { throw new Error("Invalid sample manifest: " + why); };
  if (!m || m.format !== "tandem-gm-samples" || m.version !== 1) fail("unknown format");
  if (!(m.sample_rate > 0)) fail("no sample rate");
  const file = f => typeof f === "string" && /^[a-z]+\/[a-z0-9]+\.mp3$/.test(f);
  for (const name of instruments) {
    const inst = m.instruments?.[name];
    if (!inst || typeof inst.samples !== "object") fail("missing instrument " + name);
    const roots = Object.keys(inst.samples);
    if (!roots.length) fail("no samples for " + name);
    for (const r of roots) {
      const s = inst.samples[r];
      if (!/^\d+$/.test(r) || !file(s.file)) fail(`bad sample ${name} ${r}`);
      if (inst.sustains && !(Array.isArray(s.loop) && s.loop[0] > 0 && s.loop[1] > s.loop[0])) fail(`bad loop ${name} ${r}`);
    }
  }
  for (const k of DRUM_KINDS) if (!file(m.drums?.[k]?.file)) fail("missing drum " + k);
  return m;
}

// The root (MIDI number) nearest to m; on a tie, the lower root, so the note is pitched up.
export function nearestRoot(roots, m) {
  let best = roots[0];
  for (const r of roots) if (Math.abs(r - m) < Math.abs(best - m) || (Math.abs(r - m) === Math.abs(best - m) && r < best)) best = r;
  return best;
}

// Everything playSample needs for one note, as plain numbers. `sample` is {duration, loop} for
// the chosen root: the buffer length in seconds and, for sustained instruments, the loop points
// in seconds (or null). The note sounds from t at `level`, and from the key release at t + d it
// fades over the voice's release time. A recording that ends before the key release (a decaying
// instrument rendered for a few seconds, which may still be audible when it was cut) fades over
// the release time up to its end instead, so a long held note never stops abruptly.
export function planSample(instrument, root, sample, m, t, d) {
  if (!(instrument in LEVELS)) throw new Error(`Unknown instrument: ${instrument}`);
  if (!(d > 0)) throw new Error("Note duration must be positive.");
  const rate = Math.pow(2, (m - root) / 12);
  const level = LEVELS[instrument], release = VOICES[instrument].env.release, off = t + d;
  const natural = sample.loop ? Infinity : t + sample.duration / rate;
  const gain = [{ kind: "set", time: t, value: level }];
  let stop;
  if (natural <= off) {
    gain.push({ kind: "set", time: Math.max(t, natural - release), value: level }, { kind: "exp", time: natural, value: FLOOR });
    stop = natural;
  } else {
    gain.push({ kind: "set", time: off, value: level }, { kind: "exp", time: off + release, value: FLOOR });
    stop = Math.min(natural, off + release + 0.02);
  }
  return { root, rate, loop: sample.loop, gain, start: t, stop };
}

const RAMP = { set: "setValueAtTime", linear: "linearRampToValueAtTime", exp: "exponentialRampToValueAtTime" };

// The loaded samples. `fetchBytes(url)` returns an ArrayBuffer and `decode(bytes)` an AudioBuffer
// (in the browser: fetch and an OfflineAudioContext's decodeAudioData). Each instrument (and the
// drum kit) loads once; a failed load is remembered and reported by error(), and retried by the
// next load() call.
export function createSampleBank({ fetchBytes, decode, base = SAMPLE_BASE }) {
  // One manifest request shared by parts loading at the same time; dropped if it fails.
  let manifest = null;
  const loaded = new Map(), pending = new Map(), errors = new Map();
  const getManifest = () => manifest ||= (async () => {
    const text = new TextDecoder().decode(await fetchBytes(base + "manifest.json"));
    return checkManifest(JSON.parse(text), Object.keys(LEVELS));
  })().catch(e => { manifest = null; throw e; });
  const buffer = async file => decode(await fetchBytes(base + file));
  async function loadOne(name) {
    const m = await getManifest();
    if (name === "drums") {
      const kit = {};
      await Promise.all(DRUM_KINDS.map(async k => { kit[k] = await buffer(m.drums[k].file); }));
      return kit;
    }
    const inst = m.instruments[name];
    if (!inst) throw new Error(`No samples for instrument ${name}`);
    const entries = await Promise.all(Object.entries(inst.samples).map(async ([r, s]) => {
      const b = await buffer(s.file);
      return [Number(r), { buffer: b, loop: s.loop ? [s.loop[0] / m.sample_rate, s.loop[1] / m.sample_rate] : null }];
    }));
    entries.sort((a, b) => a[0] - b[0]);
    return { roots: entries.map(e => e[0]), samples: new Map(entries) };
  }
  // Load the named instruments ("drums" for the kit). Resolves when all have settled; never
  // rejects: check ready() and error() afterwards.
  function load(names) {
    return Promise.all([...new Set(names)].map(name => {
      if (loaded.has(name)) return null;
      if (!pending.has(name)) {
        errors.delete(name);
        pending.set(name, loadOne(name)
          .then(v => { loaded.set(name, v); })
          .catch(e => { errors.set(name, e); })
          .finally(() => pending.delete(name)));
      }
      return pending.get(name);
    })).then(() => undefined);
  }
  return {
    load,
    ready: name => loaded.has(name),
    error: name => errors.get(name) || null,
    get: name => loaded.get(name) || null,
  };
}

// Load the named parts, but wait at most `ms` milliseconds. Resolves true if all of them are
// loaded by then; a part still loading keeps loading in the background for the next use.
export function loadWithin(bank, names, ms) {
  let timer;
  const limit = new Promise(resolve => { timer = setTimeout(resolve, ms); });
  return Promise.race([bank.load(names), limit])
    .then(() => names.every(name => bank.ready(name)))
    .finally(() => clearTimeout(timer));
}

// Schedule one sampled note. Returns the plan, or null if the instrument is not loaded.
export function playSample(ac, bank, instrument, m, t, d, destination = ac.destination) {
  const inst = bank.get(instrument);
  if (!inst) return null;
  const root = nearestRoot(inst.roots, m), s = inst.samples.get(root);
  const plan = planSample(instrument, root, { duration: s.buffer.duration, loop: s.loop }, m, t, d);
  const src = ac.createBufferSource(), amp = ac.createGain();
  src.buffer = s.buffer;
  src.playbackRate.value = plan.rate;
  if (plan.loop) { src.loop = true; src.loopStart = plan.loop[0]; src.loopEnd = plan.loop[1]; }
  for (const e of plan.gain) amp.gain[RAMP[e.kind]](e.value, e.time);
  src.connect(amp);
  amp.connect(destination);
  src.start(plan.start);
  src.stop(plan.stop);
  return plan;
}

// Schedule one sampled drum hit. Returns false if the kit is not loaded.
export function playDrumSample(ac, bank, kind, t, destination = ac.destination) {
  const kit = bank.get("drums");
  if (!kit || !kit[kind]) return false;
  const src = ac.createBufferSource(), amp = ac.createGain();
  src.buffer = kit[kind];
  amp.gain.value = DRUM_LEVELS[kind];
  src.connect(amp);
  amp.connect(destination);
  src.start(t);
  return true;
}
