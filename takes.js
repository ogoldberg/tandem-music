// TAKE.1: every take of your voice is kept. Recording (or importing) again once there is a take adds a take
// instead of replacing it, and the take the song uses (the recording Polish, Transcribe, Tune and Separate
// work on, played as "Your voice") is a comp: sections of the takes, one after another. Picking a take is the
// comp of the whole of it; comping a section puts that stretch of another take in place of what the comp
// held there. The project's optional `takes` field is {list: [{id, name, seconds}], comp: [{take, from, to}]};
// it is written once there is a second take, so an older project, version or Tandem file opens, saves and
// exports exactly as before. Each take's audio is a recording kept beside the project, never in it, like a
// layer's (layers.js): linked from the draft and versions under takeKey(id), written into Tandem files and
// project folders as takeFile(id). The comp itself is the `original` recording, as the one take was before.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectTakes mirrors cleanTakes.

import { isLayerKey } from "./layers.js";

export const MAX_TAKES = 8;
export const MAX_SECTIONS = 64;
export const MAX_TAKE_NAME = 40;
export const MAX_TAKE_SECONDS = 600;
// The shortest section that can be comped in.
export const MIN_SECTION = 0.1;
// Each section fades in and out over this long, centred on its edges, so a comp has no clicks at the joins.
export const COMP_FADE = 0.02;
const ID = /^[a-z0-9]{1,24}$/;
export const TAKE_KEY = /^take-([a-z0-9]{1,24})$/;
export const TAKE_FILE = /^take-([a-z0-9]{1,24})\.wav$/;
export const takeKey = id => {
  if (!ID.test(id)) throw Error("Invalid take id");
  return "take-" + id;
};
export const takeFile = id => takeKey(id) + ".wav";
export const isTakeKey = key => typeof key === "string" && TAKE_KEY.test(key);
export const takeIdOf = key => (isTakeKey(key) ? key.slice(5) : null);
// The recordings kept by key beside the fixed slots: a layer's (TRACK.1) or a take's.
export const isExtraKey = key => isLayerKey(key) || isTakeKey(key);

const isObject = x => !!x && typeof x === "object" && !Array.isArray(x);
const ms = x => Math.round(x * 1000) / 1000;
const finite = x => typeof x === "number" && Number.isFinite(x);

// The takes with every value checked. Throws on anything else, like the other project checks, so a bad file is
// refused rather than half read. A missing field is null: the one take, if any, is the recording itself.
export function cleanTakes(takes) {
  if (takes == null) return null;
  if (!isObject(takes)) throw Error("Invalid takes");
  for (const k of Object.keys(takes)) if (!["list", "comp"].includes(k)) throw Error("Invalid takes");
  const { list, comp } = takes;
  if (!Array.isArray(list) || !list.length || list.length > MAX_TAKES) throw Error("Invalid takes");
  const seen = new Map();
  const outList = list.map(t => {
    if (!isObject(t)) throw Error("Invalid take");
    for (const k of Object.keys(t)) if (!["id", "name", "seconds"].includes(k)) throw Error("Invalid take");
    if (typeof t.id !== "string" || !ID.test(t.id) || seen.has(t.id)) throw Error("Invalid take id");
    const name = typeof t.name === "string" ? t.name.trim() : "";
    if (!name || name.length > MAX_TAKE_NAME) throw Error("Invalid take name");
    if (!finite(t.seconds) || t.seconds <= 0 || t.seconds > MAX_TAKE_SECONDS) throw Error("Invalid take length");
    seen.set(t.id, t.seconds);
    return { id: t.id, name, seconds: t.seconds };
  });
  if (!Array.isArray(comp) || !comp.length || comp.length > MAX_SECTIONS) throw Error("Invalid comp");
  let end = 0;
  const outComp = comp.map(s => {
    if (!isObject(s)) throw Error("Invalid comp section");
    for (const k of Object.keys(s)) if (!["take", "from", "to"].includes(k)) throw Error("Invalid comp section");
    if (!seen.has(s.take)) throw Error("The comp names a take the project does not have");
    if (!finite(s.from) || !finite(s.to) || s.from < 0 || s.to <= s.from || s.to > seen.get(s.take) + 0.001) throw Error("Invalid comp section");
    if (s.from < end - 0.0005) throw Error("Comp sections must be in order and not overlap");
    end = s.to;
    return { take: s.take, from: s.from, to: s.to };
  });
  return { list: outList, comp: outComp };
}

// A new take id: 12 lowercase letters and digits from `random` (crypto.getRandomValues by default).
export function newTakeId(random = n => crypto.getRandomValues(new Uint8Array(n))) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  return [...random(12)].map(b => chars[b % chars.length]).join("");
}

// "Take 1", "Take 2", ...: the lowest number no take is named with.
export function nextTakeName(list) {
  const used = new Set((list || []).map(t => t.name));
  let n = 1;
  while (used.has("Take " + n)) n++;
  return "Take " + n;
}

const whole = t => [{ take: t.id, from: 0, to: t.seconds }];

// The takes with a new one at the end, which the comp then is the whole of (a new take is the one heard, as a
// new recording always was). With no takes yet, `first` is the recording the song had, which becomes Take 1.
export function addTake(takes, { id, seconds, first = null }) {
  let t = cleanTakes(takes);
  if (!t) {
    if (!first) throw Error("The first take is needed to start the list");
    const one = { id: first.id, name: "Take 1", seconds: ms(first.seconds) };
    t = cleanTakes({ list: [one], comp: whole(one) });
  }
  if (t.list.length >= MAX_TAKES) throw Error(`A song keeps at most ${MAX_TAKES} takes; remove one first.`);
  const take = { id, name: nextTakeName(t.list), seconds: ms(seconds) };
  return cleanTakes({ list: [...t.list, take], comp: whole(take) });
}

const find = (t, id) => {
  const take = t?.list.find(x => x.id === id);
  if (!take) throw Error("No such take");
  return take;
};

// The comp of the whole of take `id`.
export function pickTake(takes, id) {
  const t = cleanTakes(takes);
  return cleanTakes({ list: t.list, comp: whole(find(t, id)) });
}

// The comp with take `id` from `from` to `to` (seconds of the song, which are seconds of every take, since each
// was recorded from the song's zero) in place of what it held there. A section past the end of that take is
// cut at its end; one past the comp's end makes it longer; a gap before it is silence.
export function compSection(takes, id, from, to) {
  const t = cleanTakes(takes), take = find(t, id);
  const a = ms(Math.max(0, Number(from))), b = ms(Math.min(Number(to), take.seconds));
  if (!finite(a) || !finite(b) || b - a < MIN_SECTION - 0.0005) throw Error(`A section must be at least ${MIN_SECTION} s of ${take.name}.`);
  const out = [];
  for (const s of t.comp) {
    if (s.to <= a || s.from >= b) out.push(s);
    else {
      if (s.from < a) out.push({ ...s, to: a });
      if (s.to > b) out.push({ ...s, from: b });
    }
  }
  out.push({ take: id, from: a, to: b });
  out.sort((x, y) => x.from - y.from);
  const merged = [];
  for (const s of out) {
    const last = merged.at(-1);
    if (last && last.take === s.take && Math.abs(last.to - s.from) < 0.0005) last.to = s.to;
    else merged.push({ ...s });
  }
  if (merged.length > MAX_SECTIONS) throw Error(`A comp holds at most ${MAX_SECTIONS} sections.`);
  return cleanTakes({ list: t.list, comp: merged });
}

// The takes without take `id`. A take the comp uses, or the only take, stays.
export function removeTake(takes, id) {
  const t = cleanTakes(takes), take = find(t, id);
  if (t.comp.some(s => s.take === id)) throw Error(`${take.name} is in the take the song uses; use another take there first.`);
  return cleanTakes({ list: t.list.filter(x => x.id !== id), comp: t.comp });
}

// The ids of the takes the comp uses.
export const usedTakes = takes => new Set((takes?.comp || []).map(s => s.take));

// The take whose whole the comp is, else null: then its recording is the comp as it is, with nothing rendered.
export function wholeTake(takes) {
  const t = cleanTakes(takes);
  if (!t || t.comp.length !== 1) return null;
  const [s] = t.comp, take = find(t, s.take);
  return s.from === 0 && Math.abs(s.to - take.seconds) < 0.0005 ? s.take : null;
}

// What the comp is, as a key: two states of the project with the same key use the same recording.
export const compSig = takes => (takes ? JSON.stringify(takes.comp) : "");

// For history.rewrite: drops the vocal targets from the snapshots (snap() JSON) of the comp with key `sig` and leaves
// the other comps' snapshots as they are, since their targets were set on recordings that did not change.
export const dropCompVocal = sig => s => {
  const x = JSON.parse(s);
  if (compSig(x.project?.takes ?? null) !== sig || x.vocal == null) return s;
  x.vocal = null;
  return JSON.stringify(x);
};

// The comp's length in seconds.
export const compSeconds = takes => (takes?.comp?.length ? takes.comp.at(-1).to : 0);

const clock = x => {
  const m = Math.floor(x / 60), s = x - m * 60;
  return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
};
// "Take 2 0:00.0-0:04.0, Take 1 0:04.0-0:10.0".
export function compText(takes) {
  const t = cleanTakes(takes);
  if (!t) return "";
  return t.comp.map(s => `${find(t, s.take).name} ${clock(s.from)}-${clock(s.to)}`).join(", ");
}

// The comp's samples at `rate`, from each take's mono samples at that rate (`sources`, by take id). Each section
// is its take's samples over the same stretch of the song, faded in and out with equal-power curves over `fade`
// seconds centred on its edges (not at the song's zero, nor at the comp's end), so two takes cross over at a join
// at constant loudness and an edge beside a gap does not click. A take shorter than a section is silence past
// its end.
export function renderComp(takes, sources, rate, fade = COMP_FADE) {
  const t = cleanTakes(takes);
  if (!t) throw Error("There are no takes to comp");
  if (!(rate > 0)) throw Error("Invalid sample rate");
  for (const s of t.comp) if (!(sources[s.take] instanceof Float32Array)) throw Error(`The recording of ${find(t, s.take).name} is not on this device.`);
  const total = Math.round(compSeconds(t) * rate), out = new Float32Array(total), half = (fade * rate) / 2;
  const gain = (i, edge, rising) => {
    // Equal power: sin over the rise, cos over the fall, so a rise and a fall at the same edge sum to unit power.
    if (half <= 0) return (rising ? i >= edge : i < edge) ? 1 : 0;
    const x = Math.min(1, Math.max(0, (i - (edge - half)) / (2 * half)));
    return rising ? Math.sin((x * Math.PI) / 2) : Math.cos((x * Math.PI) / 2);
  };
  t.comp.forEach((s, n) => {
    const src = sources[s.take], a = s.from * rate, b = s.to * rate;
    const fadeIn = a > 0, fadeOut = n < t.comp.length - 1;
    const lo = Math.max(0, Math.floor(fadeIn ? a - half : a)), hi = Math.min(total, Math.ceil(fadeOut ? b + half : b), src.length);
    for (let i = lo; i < hi; i++) {
      let g = 1;
      if (fadeIn && i < a + half) g *= gain(i, a, true);
      else if (!fadeIn && i < a) g = 0;
      if (fadeOut && i >= b - half) g *= gain(i, b, false);
      else if (!fadeOut && i >= b) g = 0;
      out[i] += src[i] * g;
    }
  });
  return out;
}

// FIX.4: the recordings sung to a count-in, a click or the song, with the tempo they were sung to, by
// recordings.js recordingId (the SHA-256 the recording is stored under), so Detect tempo keeps that tempo
// after a reload or a restored version too. Kept on the device under TIMED_KEY, never in the project;
// the newest MAX_TIMED are kept.
export const TIMED_KEY = "timed-takes";
export const MAX_TIMED = 500;
const RECORDING_ID = /^[0-9a-f]{64}$/;
const tempoOk = bpm => typeof bpm === "number" && Number.isFinite(bpm) && bpm >= 45 && bpm <= 220;

export function cleanTimed(value) {
  const out = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [id, bpm] of Object.entries(value)) if (RECORDING_ID.test(id) && tempoOk(bpm)) out[id] = bpm;
  return out;
}

export function withTimed(map, id, bpm, limit = MAX_TIMED) {
  if (!RECORDING_ID.test(id)) throw new Error("Not a recording id.");
  if (!tempoOk(bpm)) throw new Error("A take's tempo lies inside 45..220 bpm.");
  const entries = Object.entries(cleanTimed(map)).filter(([k]) => k !== id);
  entries.push([id, bpm]);
  return Object.fromEntries(entries.slice(-limit));
}

// The tempo a comp was sung to: its takes' tempos when they are all known and the same, else null.
export function compTempo(tempos) {
  return tempos.length && tempos.every(t => tempoOk(t) && t === tempos[0]) ? tempos[0] : null;
}
