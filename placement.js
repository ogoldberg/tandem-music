// GROW.3 (ADR-018): where each recording plays in the song. A recording is never copied, cut or rewritten; the
// project's optional `placed` field says which stretches of it play where, by channel (keyed like the mixer's
// `mix`: "voice", "band", "timbre", "voice2_sung", "layer-<id>"): a list of clips {from, to, at}, the stretch
// from..to of the recording (seconds) playing from song time `at`. A channel with no entry plays the whole
// recording from zero, as before, so a project nobody rearranged has no `placed` and plays, saves and exports
// byte for byte as before. The voice is one channel: the take and what clean-up, pitch fixing and Separate make
// from it (the original, polished, tuned, vocal and accompaniment recordings) share `placed.voice`.
// Section edits (sections.js) carry the clips with the notes in the same edit: repeatClips, moveClips and
// deleteClips. Everything that plays or exports a recording lays it out with placeSamples, so Play, Export WAV,
// the stems, Hear how it grew and the DAWproject tracks cannot disagree; placeNotes carries notes read from a
// recording (Transcribe) to every place it plays.
// DOM-free so Node tests import it directly; tandem_backend.py's ProjectPlaced mirrors cleanPlaced.

export const MAX_CLIPS = 64;
export const MAX_TIME = 600;
// Each join between two clips crosses over this long, centred on the join (the maths of takes.js renderComp).
export const PLACE_FADE = 0.02;
export const PLACED_PARTS = Object.freeze(["voice", "band", "timbre", "voice2_sung"]);
const LAYER_KEY = /^layer-[a-z0-9]{1,24}$/;
// The recording slots that are the voice: the take, and what is made from it in its own time.
export const VOICE_SLOTS = Object.freeze(["original", "polished", "tuned", "vocal", "accompaniment", "voice"]);
const EPS = 1e-3;
const round3 = x => Math.round(x * 1000) / 1000;
const isObject = x => !!x && typeof x === "object" && !Array.isArray(x);
const isTime = x => typeof x === "number" && Number.isFinite(x);

export const isPlacedKey = key => PLACED_PARTS.includes(key) || (typeof key === "string" && LAYER_KEY.test(key));
// The channel a recording slot plays on: every voice slot is "voice", the others are their own.
export const placeKey = slot => (VOICE_SLOTS.includes(slot) ? "voice" : slot);
const NAMES = { voice: "Your voice", band: "The band", timbre: "The voice as instrument", voice2_sung: "The sung harmony" };
const nameOf = key => NAMES[key] || "A layer";
const lengthOf = c => c.to - c.from;

// One channel's clips with every value checked: in song order, not overlapping in the song, within 600 s.
export function cleanClips(clips) {
  if (!Array.isArray(clips) || clips.length > MAX_CLIPS) throw Error("Invalid placed clips");
  let end = 0;
  return clips.map(c => {
    if (!isObject(c)) throw Error("Invalid placed clip");
    for (const k of Object.keys(c)) if (!["from", "to", "at"].includes(k)) throw Error("Invalid placed clip");
    if (!isTime(c.from) || !isTime(c.to) || !isTime(c.at) || c.from < 0 || c.to <= c.from || c.to > MAX_TIME || c.at < 0) throw Error("Invalid placed clip times");
    if (c.at + c.to - c.from > MAX_TIME + EPS) throw Error("A placed clip goes past 600 seconds");
    if (c.at < end - EPS) throw Error("Placed clips must be in order and not overlap");
    end = c.at + c.to - c.from;
    return { from: c.from, to: c.to, at: c.at };
  });
}

// The placement with every value checked, or null when nothing is placed. Throws on anything else, like the other
// project checks, so a bad file is refused rather than half read.
export function cleanPlaced(placed) {
  if (placed == null) return null;
  if (!isObject(placed)) throw Error("Invalid placed");
  const out = {};
  for (const [key, clips] of Object.entries(placed)) {
    if (!isPlacedKey(key)) throw Error("Invalid placed channel: " + key);
    out[key] = cleanClips(clips);
  }
  return Object.keys(out).length ? out : null;
}

// A channel's clips: its entry, else the whole recording (`seconds` long) from zero, else none.
export function clipsOf(placed, key, seconds = 0) {
  const own = isObject(placed) ? placed[key] : undefined;
  if (Array.isArray(own)) return own.map(c => ({ ...c }));
  return seconds > 0 ? [{ from: 0, to: round3(Math.min(seconds, MAX_TIME)), at: 0 }] : [];
}

// Whether clips are the whole recording (`seconds` long) from zero, which is what no entry means.
export const isWhole = (clips, seconds) => Array.isArray(clips) && clips.length === 1 && seconds > 0
  && Math.abs(clips[0].from) < EPS && Math.abs(clips[0].at) < EPS && Math.abs(clips[0].to - Math.min(seconds, MAX_TIME)) < EPS;

// The placement with channel `key` set to `clips`; the whole recording from zero is no entry. Null when empty.
export function withClips(placed, key, clips, seconds = 0) {
  if (!isPlacedKey(key)) throw Error("Invalid placed channel: " + key);
  const out = { ...(isObject(placed) ? placed : {}) };
  if (clips == null || isWhole(clips, seconds)) delete out[key];
  else out[key] = cleanClips(clips);
  return Object.keys(out).length ? out : null;
}

export function withoutClips(placed, key) {
  const out = { ...(isObject(placed) ? placed : {}) };
  delete out[key];
  return Object.keys(out).length ? out : null;
}

// When a channel stops playing in the song: the end of its last clip, else the recording's own length.
export function placedSeconds(placed, key, seconds = 0) {
  const own = isObject(placed) ? placed[key] : undefined;
  if (!Array.isArray(own)) return seconds;
  return own.reduce((end, c) => Math.max(end, c.at + c.to - c.from), 0);
}

// The clips laid along `regions` of the song: [{from, to, shifts}] in song time, not overlapping (`to` may be
// Infinity). Each stretch of a clip inside a region plays once per shift, moved by it, and not at all
// when the region has none. Pieces that join up in both the recording and the song are one clip again.
function mapClips(clips, regions, key) {
  const pieces = [];
  for (const c of clips) {
    const end = c.at + lengthOf(c);
    for (const r of regions) {
      const a = Math.max(c.at, r.from), b = Math.min(end, r.to);
      if (b - a < EPS / 2) continue;
      for (const shift of r.shifts) pieces.push({ from: c.from + (a - c.at), to: c.from + (b - c.at), at: a + shift });
    }
  }
  pieces.sort((x, y) => x.at - y.at);
  const out = [];
  for (const p of pieces) {
    const last = out.at(-1);
    if (last && Math.abs(last.at + lengthOf(last) - p.at) < EPS && Math.abs(last.to - p.from) < EPS) last.to = p.to;
    else out.push({ ...p });
  }
  const clean = out.map(p => ({ from: round3(p.from), to: round3(p.to), at: round3(p.at) })).filter(p => p.to - p.from >= EPS);
  if (clean.length > MAX_CLIPS) throw Error(`${nameOf(key)} would play in more than ${MAX_CLIPS} pieces.`);
  if (clean.some(p => p.at + lengthOf(p) > MAX_TIME + EPS)) throw Error(`${nameOf(key)} would go past ${MAX_TIME} seconds.`);
  return cleanClips(clean);
}

// Section s ({from, to} in song time) played twice, the copy right after it, and what was after it later by its length.
export function repeatClips(clips, s, key = "voice") {
  const len = s.to - s.from;
  return mapClips(clips, [{ from: s.from, to: s.to, shifts: [0, len] }, { from: s.to, to: Infinity, shifts: [len] }, { from: 0, to: s.from, shifts: [0] }], key);
}

// Section s taken out, and what was after it earlier by its length.
export function deleteClips(clips, s, key = "voice") {
  const len = s.to - s.from;
  return mapClips(clips, [{ from: s.from, to: s.to, shifts: [] }, { from: s.to, to: Infinity, shifts: [-len] }, { from: 0, to: s.from, shifts: [0] }], key);
}

// Sections a and b (a before b) swapped; the stretch between them keeps its length and stays between them.
export function moveClips(clips, a, b, key = "voice") {
  const lenA = a.to - a.from, lenB = b.to - b.from;
  return mapClips(clips, [
    { from: a.from, to: a.to, shifts: [lenB + (b.from - a.to)] },
    { from: b.from, to: b.to, shifts: [a.from - b.from] },
    { from: a.to, to: b.from, shifts: [lenB - lenA] },
    { from: 0, to: a.from, shifts: [0] },
    { from: b.to, to: Infinity, shifts: [0] },
  ], key);
}

// Equal-power gains at sample i for an edge at sample `edge`, over `half` samples either side: sin rising, cos
// falling, so a rise and a fall at the same edge sum to unit power.
export function edgeGain(i, edge, half, rising) {
  if (half <= 0) return (rising ? i >= edge : i < edge) ? 1 : 0;
  const x = Math.min(1, Math.max(0, (i - (edge - half)) / (2 * half)));
  return rising ? Math.sin((x * Math.PI) / 2) : Math.cos((x * Math.PI) / 2);
}

// The recording's samples (`samples` at `rate`) laid along the song by `clips`; null clips are the recording as it
// is (the same array). Where one clip ends as the next begins, the two cross over with equal-power curves over
// `fade` seconds centred on the join, each reading its recording on past its edge; any other edge cut out of the
// recording fades over `fade` inside the clip, so nothing clicks. A clip starting at the recording's start or ending
// at its end keeps that edge as it is.
export function placeSamples(clips, samples, rate, fade = PLACE_FADE) {
  if (clips == null) return samples;
  if (!(rate > 0)) throw Error("Invalid sample rate");
  const list = cleanClips(clips), srcEnd = samples.length;
  const total = Math.round(list.reduce((e, c) => Math.max(e, c.at + lengthOf(c)), 0) * rate);
  const out = new Float32Array(total), half = (fade * rate) / 2, span = fade * rate;
  list.forEach((c, n) => {
    const a = c.at * rate, b = (c.at + lengthOf(c)) * rate, offset = Math.round((c.from - c.at) * rate);
    const prev = list[n - 1], next = list[n + 1];
    const joinIn = !!prev && Math.abs(prev.at + lengthOf(prev) - c.at) < EPS, joinOut = !!next && Math.abs(c.at + lengthOf(c) - next.at) < EPS;
    const cutIn = !joinIn && c.from > EPS && c.at > EPS, cutOut = !joinOut && c.to * rate < srcEnd - EPS * rate;
    const lo = Math.max(0, Math.floor(joinIn ? a - half : a)), hi = Math.min(total, Math.ceil(joinOut ? b + half : b));
    for (let i = lo; i < hi; i++) {
      const j = i + offset;
      if (j < 0 || j >= srcEnd) continue;
      let g = 1;
      if (joinIn) g *= edgeGain(i, a, half, true);
      else if (cutIn && i < a + span) g *= (i - a) / span;
      if (joinOut) g *= edgeGain(i, b, half, false);
      else if (cutOut && i > b - span) g *= (b - i) / span;
      out[i] += samples[j] * g;
    }
  });
  return out;
}

// Notes or hits read from a recording, in the recording's time, carried to every place it plays: each event in a
// clip is moved with it, and a note is cut at its clip's end. Null clips leave them as they are.
export function placeNotes(clips, events, { max = 4096 } = {}) {
  if (clips == null) return events;
  const out = [];
  for (const c of cleanClips(clips)) {
    for (const e of events) {
      if (!(e.t >= c.from - EPS && e.t < c.to - EPS)) continue;
      const moved = { ...e, t: round3(Math.max(0, e.t - c.from + c.at)) };
      if ("d" in e) moved.d = round3(Math.max(0.01, Math.min(e.d, c.to - e.t)));
      out.push(moved);
    }
  }
  if (out.length > max) throw Error(`The recording plays in so many places that its notes would be more than ${max}.`);
  return out.sort((x, y) => x.t - y.t);
}
