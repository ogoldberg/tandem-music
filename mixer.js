// MIX.1: the mixer. Every part has a level (in dB), a mute and a solo, used by Play, Export WAV and the
// stems and kept in the project's optional `mix` field. Only what differs from the defaults is stored,
// so a project nobody mixed has no `mix` and plays exactly as before.
//
// - The band, the voice as instrument and the sung harmony keep their mute in their own `muted` field
//   (GEN.2, TIMBRE.1, HARM.3), so their mixer entry holds only a level and a solo.
// - "voice" is the most finished take (tuned, else polished, else the take). It is muted by default:
//   until it is unmuted, Play and Export WAV are the arrangement alone, as before the mixer.
// - A solo on any part that is present silences every part that is not soloed; a muted part stays
//   silent even when soloed.
// - TRACK.1: every recorded layer has a channel of its own, under its key (layers.js layerKey, "layer-<id>"),
//   with a level, a mute and a solo like a part; a layer is heard by default.
// - FX.1: the voice also has a Room amount, 0 (dry, the default) to 1: a short reverb from a generated impulse
//   (roomImpulse) mixed under the dry voice (roomGains). Play and the exports run the same impulse through a
//   ConvolverNode, so what is heard is what is exported; no other part has one.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectMix mirrors cleanMix.

export const MIX_PARTS = Object.freeze(["voice", "melody", "harmony", "voice2", "voice2_sung", "drums", "band", "timbre"]);
// Parts whose mute is the part's own `muted` field.
export const OWN_MUTE = Object.freeze(["band", "timbre", "voice2_sung"]);
export const LEVEL_MIN = -30;
export const LEVEL_MAX = 6;
export const LEVEL_STEP = 0.5;
// FX.1: the voice's Room amount, in steps of 5 %; the tail (to -60 dB) and the gap before it, in seconds.
export const ROOM_STEP = 0.05;
export const ROOM_SECONDS = 0.8;
export const ROOM_PREDELAY = 0.012;
// The wet level at a Room amount of 1, as a factor of the dry voice: about -6 dB, so it stays "a little room".
export const ROOM_WET = 0.5;
import { isLayerKey, layerKey } from "./layers.js";

const isPart = part => MIX_PARTS.includes(part) || isLayerKey(part);
// Every channel of a project: the parts, then one per layer it has.
export function mixParts(project) {
  const layers = Array.isArray(project?.layers) ? project.layers : [];
  return [...MIX_PARTS, ...layers.filter(l => l && typeof l.id === "string").map(l => layerKey(l.id))];
}

const DEFAULT_MUTE = part => part === "voice";
const isObject = x => !!x && typeof x === "object" && !Array.isArray(x);

// The mix with every value checked and the defaults left out. Throws on anything else, like the other
// project checks in the studio, so a bad file is refused rather than half read.
export function cleanMix(mix) {
  if (mix == null) return {};
  if (!isObject(mix)) throw Error("Invalid mix");
  const out = {};
  for (const [part, ch] of Object.entries(mix)) {
    if (!isPart(part) || !isObject(ch)) throw Error("Invalid mix");
    const entry = {};
    for (const [key, value] of Object.entries(ch)) {
      if (key === "level") {
        if (typeof value !== "number" || !Number.isFinite(value) || value < LEVEL_MIN || value > LEVEL_MAX) throw Error("Invalid mix level");
        const level = Math.round(value / LEVEL_STEP) * LEVEL_STEP;
        if (level !== 0) entry.level = level;
      } else if (key === "mute" && !OWN_MUTE.includes(part)) {
        if (typeof value !== "boolean") throw Error("Invalid mix");
        if (value !== DEFAULT_MUTE(part)) entry.mute = value;
      } else if (key === "room" && part === "voice") {
        if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) throw Error("Invalid mix room");
        const room = roundRoom(value);
        if (room !== 0) entry.room = room;
      } else if (key === "solo") {
        if (typeof value !== "boolean") throw Error("Invalid mix");
        if (value) entry.solo = true;
      } else throw Error("Invalid mix");
    }
    if (Object.keys(entry).length) out[part] = entry;
  }
  return out;
}

// One part's channel as heard: {level, mute, solo}. project is the studio state or a saved project.
export function channel(project, part) {
  if (!isPart(part)) throw Error("Unknown mix part: " + part);
  const ch = (isObject(project?.mix) && isObject(project.mix[part])) ? project.mix[part] : {};
  const mute = OWN_MUTE.includes(part) ? !!project?.[part]?.muted : typeof ch.mute === "boolean" ? ch.mute : DEFAULT_MUTE(part);
  const out = { level: Number.isFinite(ch.level) ? ch.level : 0, mute, solo: ch.solo === true };
  if (part === "voice") out.room = Number.isFinite(ch.room) ? ch.room : 0; // FX.1: only the voice has a room
  return out;
}

export const dbToGain = db => Math.pow(10, db / 20);

// The gain of every part: 0 when muted or when another present part is soloed, else the level as a
// factor. present lists the parts there is something to hear in, so a solo left on a part that was
// removed does not silence the song.
export function mixGains(project, present = mixParts(project)) {
  const parts = mixParts(project);
  const channels = Object.fromEntries(parts.map(p => [p, channel(project, p)]));
  const soloing = present.some(p => parts.includes(p) && channels[p].solo && !channels[p].mute);
  return Object.fromEntries(parts.map(p => {
    const c = channels[p];
    return [p, c.mute || (soloing && !c.solo) ? 0 : dbToGain(c.level)];
  }));
}

// FX.1: the Room amount on the 5 % grid, as cleanMix keeps it (two decimals, so 0.15 is 0.15, not 0.15000000000000002).
export const roundRoom = amount => Math.round(Math.round(amount / ROOM_STEP) * ROOM_STEP * 100) / 100;

// FX.1: the dry and wet gains of the voice at a Room amount: the dry voice is never turned down, and zero is the dry voice alone.
export function roomGains(amount) {
  const a = Number.isFinite(amount) ? Math.min(1, Math.max(0, amount)) : 0;
  return { dry: 1, wet: a * ROOM_WET };
}

// "Dry", "30 %"
export const roomText = amount => (roundRoom(amount) === 0 ? "Dry" : Math.round(roundRoom(amount) * 100) + " %");

// FX.1: the room's impulse response at a sample rate: ROOM_PREDELAY of silence, then noise that falls 60 dB over ROOM_SECONDS
// and grows darker as it falls (a one-pole low-pass closing from about 9 kHz to 2 kHz), scaled to unit energy so the wet
// voice is about as loud as the dry one before ROOM_WET. Seeded, so every render of a song has the same tail.
export function roomImpulse(rate) {
  if (!Number.isFinite(rate) || rate <= 0) throw Error("Invalid sample rate");
  const gap = Math.round(ROOM_PREDELAY * rate), tail = Math.round(ROOM_SECONDS * rate), out = new Float32Array(gap + tail);
  let seed = 0x5eed1, lp = 0, energy = 0;
  const noise = () => { // mulberry32
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296 * 2 - 1;
  };
  for (let i = 0; i < tail; i++) {
    const s = i / tail, cutoff = 9000 - 7000 * s, k = 1 - Math.exp(-2 * Math.PI * Math.min(cutoff, rate * 0.45) / rate);
    lp += k * (noise() - lp);
    const v = lp * Math.pow(10, -3 * s); // -60 dB at the end of the tail
    out[gap + i] = v;
    energy += v * v;
  }
  const scale = 1 / Math.sqrt(energy);
  for (let i = gap; i < out.length; i++) out[i] *= scale;
  return out;
}

// The project's mix with one part's level or solo (or, for a part without its own mute, mute; or the voice's room)
// changed, cleaned. The band's, instrument's and sung harmony's mute are their own `muted` field.
export function setChannel(mix, part, change) {
  if (!isPart(part)) throw Error("Unknown mix part: " + part);
  if ("mute" in change && OWN_MUTE.includes(part)) throw Error("The " + part + " part keeps its own mute");
  if ("room" in change && part !== "voice") throw Error("Only your voice has a room");
  const current = cleanMix(mix);
  return cleanMix({ ...current, [part]: { ...current[part], ...change } });
}

// "0 dB", "-6 dB", "+3 dB", with a real minus sign.
export function levelText(db) {
  const v = Math.round(db / LEVEL_STEP) * LEVEL_STEP;
  if (v === 0) return "0 dB";
  return (v > 0 ? "+" : "−") + Math.abs(v) + " dB";
}

// Multiplies samples by gain into a new array, for a stem at its level.
export function scaled(samples, gain) {
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) out[i] = samples[i] * gain;
  return out;
}
