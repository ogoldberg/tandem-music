// TRACK.1: recorded layers. The first take (with what Polish, Tune and Separate make from it) is the song's
// first track, "Your voice"; every layer recorded over the song after it is a track of its own, kept in the
// project's optional `layers` list: {id, name, seconds, into}. `into` names the part the layer was last
// transcribed into (melody, harmony or drums), when it was. A layer's audio is a recording kept beside the
// project, never in it, like the band's: linked from the draft and versions under its key (layerKey), written
// into Tandem files and project folders as layerFile(id), exported as layerStemFile. Its mixer channel is
// the layer's key in the project's `mix` (mixer.js). A project with no layers has no `layers` field, so an
// older project or Tandem file opens, saves and exports exactly as before.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectLayer mirrors cleanLayers.

export const MAX_LAYERS = 8;
export const LAYER_TARGETS = Object.freeze(["melody", "harmony", "drums"]);
export const MAX_LAYER_NAME = 40;
export const MAX_LAYER_SECONDS = 600;
const ID = /^[a-z0-9]{1,24}$/;
// A layer's key: its mixer channel and its recording link in the draft and versions.
export const LAYER_KEY = /^layer-([a-z0-9]{1,24})$/;
// A layer's recording in a Tandem file or project folder.
export const LAYER_FILE = /^layer-([a-z0-9]{1,24})\.wav$/;
export const layerKey = id => {
  if (!ID.test(id)) throw Error("Invalid layer id");
  return "layer-" + id;
};
export const layerFile = id => layerKey(id) + ".wav";
export const isLayerKey = key => typeof key === "string" && LAYER_KEY.test(key);
export const layerIdOf = key => (isLayerKey(key) ? key.slice(6) : null);

const isObject = x => !!x && typeof x === "object" && !Array.isArray(x);

// The layer list with every value checked. Throws on anything else, like the other project checks, so a
// bad file is refused rather than half read. A missing list is no layers.
export function cleanLayers(layers) {
  if (layers == null) return [];
  if (!Array.isArray(layers) || layers.length > MAX_LAYERS) throw Error("Invalid layers");
  const seen = new Set();
  return layers.map(l => {
    if (!isObject(l)) throw Error("Invalid layer");
    for (const k of Object.keys(l)) if (!["id", "name", "seconds", "into"].includes(k)) throw Error("Invalid layer");
    if (typeof l.id !== "string" || !ID.test(l.id) || seen.has(l.id)) throw Error("Invalid layer id");
    seen.add(l.id);
    const name = typeof l.name === "string" ? l.name.trim() : "";
    if (!name || name.length > MAX_LAYER_NAME) throw Error("Invalid layer name");
    if (typeof l.seconds !== "number" || !Number.isFinite(l.seconds) || l.seconds <= 0 || l.seconds > MAX_LAYER_SECONDS) throw Error("Invalid layer length");
    if (l.into != null && !LAYER_TARGETS.includes(l.into)) throw Error("Invalid layer part");
    return { id: l.id, name, seconds: l.seconds, ...(l.into ? { into: l.into } : {}) };
  });
}

// A new layer id: 12 lowercase letters and digits from `random` (crypto.getRandomValues by default).
export function newLayerId(random = n => crypto.getRandomValues(new Uint8Array(n))) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  return [...random(12)].map(b => chars[b % chars.length]).join("");
}

// "Layer 2", "Layer 3", ...: the song's first track is the take, so layers are numbered from 2, each the
// lowest number no layer is named with.
export function nextLayerName(layers) {
  const used = new Set(cleanLayers(layers).map(l => l.name));
  let n = 2;
  while (used.has("Layer " + n)) n++;
  return "Layer " + n;
}

// The list with a new layer at the end. Throws when the list is full.
export function addLayer(layers, { id, seconds, name = null }) {
  const list = cleanLayers(layers);
  if (list.length >= MAX_LAYERS) throw Error(`A song can have ${MAX_LAYERS} layers besides the take; remove one first.`);
  const rounded = Math.round(seconds * 1000) / 1000;
  return cleanLayers([...list, { id, name: name ?? nextLayerName(list), seconds: rounded }]);
}

// The layers and the mix without the layer `id` (its mixer channel goes with it).
export function removeLayer(layers, mix, id) {
  const list = cleanLayers(layers);
  const out = { ...(isObject(mix) ? mix : {}) };
  delete out[layerKey(id)];
  return { layers: list.filter(l => l.id !== id), mix: out };
}

// The list with layer `id` marked as transcribed into `into`.
export function setInto(layers, id, into) {
  if (!LAYER_TARGETS.includes(into)) throw Error("Unknown part: " + into);
  const list = cleanLayers(layers);
  if (!list.some(l => l.id === id)) throw Error("No such layer");
  return list.map(l => (l.id === id ? { ...l, into } : l));
}

// The list with layer `id` renamed.
export function renameLayer(layers, id, name) {
  const list = cleanLayers(layers);
  if (!list.some(l => l.id === id)) throw Error("No such layer");
  return cleanLayers(list.map(l => (l.id === id ? { ...l, name: String(name ?? "").trim().slice(0, MAX_LAYER_NAME) } : l)));
}

// A layer's stem and DAWproject audio file: "layer-2.wav" for the first layer (the take is the first track),
// by its place in the list, so the files sort in the order of the tracks.
export function layerStemFile(layers, id) {
  const i = (Array.isArray(layers) ? layers : []).findIndex(l => l?.id === id);
  if (i < 0) throw Error("No such layer");
  return `layer-${i + 2}.wav`;
}

// The lengths of the project's layers, for how long the song is. With heard, a layer muted in the mixer is
// left out (the arrangement's length for Export WAV); the timeline shows every layer, muted or not.
export function layerSeconds(project, { heard = false } = {}) {
  const layers = Array.isArray(project?.layers) ? project.layers : [];
  const mix = isObject(project?.mix) ? project.mix : {};
  return layers.filter(l => l && Number.isFinite(l.seconds) && ID.test(l.id) && !(heard && mix[layerKey(l.id)]?.mute === true)).map(l => l.seconds);
}
