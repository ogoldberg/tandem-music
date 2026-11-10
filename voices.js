// Melody instrument voices (ARR.1b). Each voice is a few layered oscillators, an optional
// filter with its own envelope, an amplitude envelope and optional vibrato. planNote() turns a
// note into plain numbers (pure, tested in Node); playNote() builds the Web Audio graph from
// that plan, the same way for live playback (AudioContext) and WAV export (OfflineAudioContext).

// Exponential ramps cannot reach 0; this is the silent floor.
export const FLOOR = 1e-4;

// layers: oscillator type, frequency ratio to the note, detune in cents and relative weight
// (weights are normalised so the layers sum to the voice's peak gain).
// env: attack and decay in seconds, sustain as a fraction of peak, release in seconds.
// filter: cutoff as a ratio of the note frequency, swept from `from` to `to` over `time` s.
// vibrato: rate in Hz, depth in cents, delay in seconds before it starts.
export const VOICES = Object.freeze({
  piano: {
    label: "Piano", peak: 0.15,
    layers: [{ type: "triangle", ratio: 1, weight: 0.7 }, { type: "sine", ratio: 2, weight: 0.2 }, { type: "sine", ratio: 3, weight: 0.1 }],
    env: { attack: 0.005, decay: 0.9, sustain: 0.25, release: 0.25 },
    filter: { type: "lowpass", q: 0.7, from: 10, to: 3, time: 0.6 },
  },
  marimba: {
    label: "Marimba", peak: 0.16,
    layers: [{ type: "sine", ratio: 1, weight: 0.8 }, { type: "sine", ratio: 4, weight: 0.2 }],
    env: { attack: 0.004, decay: 0.7, sustain: 0, release: 0.12 },
  },
  strings: {
    label: "Strings", peak: 0.12,
    layers: [{ type: "sawtooth", ratio: 1, detune: -7, weight: 0.5 }, { type: "sawtooth", ratio: 1, detune: 7, weight: 0.5 }],
    env: { attack: 0.18, decay: 0.3, sustain: 0.85, release: 0.35 },
    filter: { type: "lowpass", q: 0.8, from: 5, to: 5, time: 0 },
    vibrato: { rate: 5.5, depth: 8, delay: 0.25 },
  },
  bass: {
    label: "Bass", peak: 0.13,
    layers: [{ type: "square", ratio: 1, weight: 0.55 }, { type: "sine", ratio: 1, weight: 0.45 }],
    env: { attack: 0.008, decay: 0.25, sustain: 0.6, release: 0.12 },
    filter: { type: "lowpass", q: 2, from: 8, to: 2.5, time: 0.25 },
  },
  chip: {
    label: "8-bit", peak: 0.1,
    layers: [{ type: "square", ratio: 1, weight: 1 }],
    env: { attack: 0.002, decay: 0.05, sustain: 0.9, release: 0.03 },
  },
  organ: {
    label: "Organ", peak: 0.12,
    layers: [{ type: "sine", ratio: 1, weight: 0.45 }, { type: "sine", ratio: 2, weight: 0.3 }, { type: "sine", ratio: 3, weight: 0.15 }, { type: "sine", ratio: 4, weight: 0.1 }],
    env: { attack: 0.012, decay: 0.05, sustain: 1, release: 0.08 },
  },
  guitar: {
    label: "Guitar", peak: 0.15,
    layers: [{ type: "sawtooth", ratio: 1, weight: 0.6 }, { type: "triangle", ratio: 2, weight: 0.4 }],
    env: { attack: 0.003, decay: 1.4, sustain: 0, release: 0.15 },
    filter: { type: "lowpass", q: 1.2, from: 9, to: 1.5, time: 0.5 },
  },
  flute: {
    label: "Flute", peak: 0.13,
    layers: [{ type: "sine", ratio: 1, weight: 0.85 }, { type: "triangle", ratio: 2, weight: 0.15 }],
    env: { attack: 0.08, decay: 0.2, sustain: 0.85, release: 0.15 },
    vibrato: { rate: 5, depth: 12, delay: 0.2 },
  },
});

export const INSTRUMENTS = Object.freeze(Object.keys(VOICES));

export const midiToHz = m => 440 * Math.pow(2, (m - 69) / 12);

// Level of an exponential segment from (x0, v0) to (x1, v1) at time x.
const expAt = (x0, v0, x1, v1, x) => (x1 <= x0 ? v1 : v0 * Math.pow(v1 / v0, Math.min(1, Math.max(0, (x - x0) / (x1 - x0)))));

// Gain automation for one note: a list of {kind, time, value} in schedule order, starting with a
// "set" at the note start. kind is set, linear or exp (the Web Audio ramp to use). The release
// starts at t + d from wherever the attack or decay had reached, and ends at the returned `end`.
export function envelope(env, peak, t, d) {
  const { attack, decay, sustain, release } = env;
  const sus = Math.max(FLOOR, sustain * peak), off = t + d;
  const events = [{ kind: "set", time: t, value: 0 }];
  let level;
  if (d <= attack) {
    level = peak * (attack > 0 ? d / attack : 1);
    events.push({ kind: "linear", time: off, value: level });
  } else {
    events.push({ kind: "linear", time: t + attack, value: peak });
    const decayEnd = t + attack + decay;
    level = expAt(t + attack, peak, decayEnd, sus, Math.min(off, decayEnd));
    events.push({ kind: "exp", time: Math.min(off, decayEnd), value: level });
    if (off > decayEnd) events.push({ kind: "set", time: off, value: level });
  }
  level = Math.max(FLOOR, level);
  // Decaying voices (sustain 0) have already faded; do not hold silence for the release.
  const end = off + (level <= FLOOR * 1.0001 ? 0.01 : release);
  events.push({ kind: "exp", time: end, value: FLOOR });
  return { events, end };
}

// Everything playNote needs, as plain numbers. sampleRate limits filter and partial frequencies
// to below Nyquist, since export renders at a lower rate than live playback.
export function planNote(instrument, m, t, d, sampleRate) {
  const voice = VOICES[instrument];
  if (!voice) throw new Error(`Unknown instrument: ${instrument}`);
  if (!(d > 0)) throw new Error("Note duration must be positive.");
  const hz = midiToHz(m), nyquist = sampleRate / 2;
  const total = voice.layers.reduce((s, l) => s + l.weight, 0);
  const layers = voice.layers
    .map(l => ({ type: l.type, frequency: hz * l.ratio, detune: l.detune || 0, gain: l.weight / total }))
    .filter(l => l.frequency < nyquist * 0.95);
  const { events, end } = envelope(voice.env, voice.peak, t, d);
  const clampHz = x => Math.min(nyquist * 0.9, Math.max(20, x));
  const filter = voice.filter
    ? { type: voice.filter.type, q: voice.filter.q, from: clampHz(hz * voice.filter.from), to: clampHz(hz * voice.filter.to), sweepEnd: t + voice.filter.time }
    : null;
  const vibrato = voice.vibrato && t + voice.vibrato.delay < end
    ? { rate: voice.vibrato.rate, depth: voice.vibrato.depth, start: t + voice.vibrato.delay }
    : null;
  return { layers, gain: events, filter, vibrato, start: t, stop: end + 0.02 };
}

const RAMP = { set: "setValueAtTime", linear: "linearRampToValueAtTime", exp: "exponentialRampToValueAtTime" };

// Build and schedule the Web Audio nodes for one note. Returns the plan for inspection.
export function playNote(ac, instrument, m, t, d, destination = ac.destination) {
  const plan = planNote(instrument, m, t, d, ac.sampleRate);
  const amp = ac.createGain();
  for (const e of plan.gain) amp.gain[RAMP[e.kind]](e.value, e.time);
  amp.connect(destination);
  let input = amp;
  if (plan.filter) {
    const f = ac.createBiquadFilter();
    f.type = plan.filter.type;
    f.Q.value = plan.filter.q;
    f.frequency.setValueAtTime(plan.filter.from, t);
    if (plan.filter.sweepEnd > t && plan.filter.to !== plan.filter.from) f.frequency.exponentialRampToValueAtTime(plan.filter.to, plan.filter.sweepEnd);
    f.connect(amp);
    input = f;
  }
  let lfoGain = null;
  if (plan.vibrato) {
    const lfo = ac.createOscillator();
    lfo.type = "sine";
    lfo.frequency.value = plan.vibrato.rate;
    lfoGain = ac.createGain();
    lfoGain.gain.value = plan.vibrato.depth;
    lfo.connect(lfoGain);
    lfo.start(plan.vibrato.start);
    lfo.stop(plan.stop);
  }
  for (const l of plan.layers) {
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = l.type;
    o.frequency.value = l.frequency;
    o.detune.value = l.detune;
    if (lfoGain) lfoGain.connect(o.detune);
    g.gain.value = l.gain;
    o.connect(g);
    g.connect(input);
    o.start(plan.start);
    o.stop(plan.stop);
  }
  return plan;
}
