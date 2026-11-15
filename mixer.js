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
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectMix mirrors cleanMix.

export const MIX_PARTS = Object.freeze(["voice", "melody", "harmony", "voice2", "voice2_sung", "drums", "band", "timbre"]);
// Parts whose mute is the part's own `muted` field.
export const OWN_MUTE = Object.freeze(["band", "timbre", "voice2_sung"]);
export const LEVEL_MIN = -30;
export const LEVEL_MAX = 6;
export const LEVEL_STEP = 0.5;
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
  return { level: Number.isFinite(ch.level) ? ch.level : 0, mute, solo: ch.solo === true };
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

// The project's mix with one part's level or solo (or, for a part without its own mute, mute)
// changed, cleaned. The band's, instrument's and sung harmony's mute are their own `muted` field.
export function setChannel(mix, part, change) {
  if (!isPart(part)) throw Error("Unknown mix part: " + part);
  if ("mute" in change && OWN_MUTE.includes(part)) throw Error("The " + part + " part keeps its own mute");
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
