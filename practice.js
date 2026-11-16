// Practice (PRACTICE.1): sing a stretch of the song over and over, and see how each melody note in it went. A pass is
// recorded through the take's capture path but kept only when asked; its pitch is read with the live guide's tracker
// (pitch.js: YIN at about 16 kHz) and every melody note starting in the stretch is scored: how many cents off it was
// once settled, how long it took to settle, how steady it was held, and how early or late it came in. Pitch and timing
// only: nothing here judges breath, strain or tone. Pure functions; the studio does the recording and the drawing.

import { createPitchTracker, hzToMidi } from "./pitch.js";
import { noteName } from "./contour.js";

export const IN_TUNE = 25;        // cents: a settled note within this reads as in tune
export const SETTLED = 50;        // cents: the voice has settled on the note once it stays this close...
export const SETTLE_RUN = 3;      // ...for this many readings in a row (about 50 ms)
export const ONSET_CENTS = 50;    // cents: the note has come in at the first reading this close to it (nearer it than
                                  // any other semitone, so the note a step below or above is never taken for its onset)
export const ONSET_EARLY = 0.25;  // seconds before a note's start a reading can still be its onset
export const ON_TIME = 0.1;       // seconds: an onset within this of the note's start is on time
export const MIN_SUNG = 0.25;     // a note is sung when voiced readings cover at least this share of it...
export const MIN_READINGS = 3;    // ...and there are at least this many of them
export const MIN_SPAN = 0.5;      // seconds: the shortest stretch that can be practised
export const MAX_SPAN = 60;       // seconds: the longest

// Every reading of a mono pass `samples` at `rate`, fed to the guide's tracker in 128-frame blocks as the worklet is:
// [{t, m}] with t in seconds from the pass's first frame plus `t0`, and m the MIDI pitch (fractional) or null.
export function trackPass(samples, rate, t0 = 0) {
  if (!(rate > 0)) throw Error("The pass needs a sample rate above zero");
  const tr = createPitchTracker(rate), out = [];
  for (let i = 0; i < samples.length; i += 128) {
    for (const r of tr.push(samples.subarray(i, Math.min(samples.length, i + 128)), t0 + i / rate)) {
      out.push({ t: r.t, m: r.hz ? hzToMidi(r.hz) : null });
    }
  }
  return out;
}

// The stretch to practise: the Timeline's marked section when there is one, else the chosen phrase, else the whole
// melody. {from, to, what} in seconds of the song; throws when there is nothing to sing.
export function practiceSpan(notes, { loop = null, phrase = null } = {}) {
  if (!notes?.length) throw Error("Practice needs a melody: record or write one first.");
  let from, to, what;
  if (loop) { from = loop.start; to = loop.end; what = "the marked section"; }
  else if (phrase) { from = phrase.start; to = phrase.end; what = "the chosen phrase"; }
  else { from = Math.min(...notes.map(n => n.t)); to = Math.max(...notes.map(n => n.t + n.d)); what = "the melody"; }
  from = Math.max(0, from);
  if (!notes.some(n => n.t >= from && n.t < to)) throw Error("No melody note starts in " + what + ": choose another stretch.");
  if (to - from < MIN_SPAN) throw Error("Choose a stretch of at least " + MIN_SPAN + " s to practise.");
  if (to - from > MAX_SPAN) throw Error("Choose a stretch of at most " + MAX_SPAN + " s to practise: mark a section on the Timeline.");
  return { from: round3(from), to: round3(to), what };
}

const round3 = x => Math.round(x * 1000) / 1000;
const quantile = (sorted, q) => {
  if (!sorted.length) return null;
  const at = (sorted.length - 1) * q, lo = Math.floor(at), hi = Math.ceil(at);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
};

// Cents from `target` to the reading `m`, taken in the nearest octave of the target: a melody hummed an octave away
// from where it is written is scored on its own octave. {cents, octave} with octave the whole octaves between them.
export function foldCents(m, target) {
  const raw = (m - target) * 100, octave = Math.round(raw / 1200);
  return { cents: raw - octave * 1200, octave };
}

// Scores one pass. `readings` are [{t, m}] in song time; `notes` the melody; {from, to} the stretch. Every note that
// starts in the stretch gets a score, in time order:
//   {i, m, t, d, sung, cents, settle, spread, onset, octave, pitch, timing}
// i the note's index in `notes`; sung false when too little of it was voiced (then the rest is null and pitch is
// "missed"); cents the median cents off over the settled part (or the whole note when it never settled), rounded;
// settle seconds from the onset to settling within SETTLED cents (null if it never did); spread the interquartile
// range in cents over the settled part (how steady); onset seconds from the note's start to the first reading within
// ONSET_CENTS (negative is early; null if none, or if the voice was already there before, as in a legato repeated
// note); pitch "in", "sharp" or "flat"; timing "on", "early", "late" or null.
export function scorePass(readings, notes, { from, to }) {
  const scored = [];
  notes.forEach((n, i) => { if (n.t >= from && n.t < to) scored.push({ n, i }); });
  scored.sort((a, b) => a.n.t - b.n.t || a.i - b.i);
  return scored.map(({ n, i }) => scoreNote(readings, n, i, to));
}

function scoreNote(readings, n, i, to) {
  const end = Math.min(n.t + n.d, to), base = { i, m: n.m, t: n.t, d: n.d };
  const inside = readings.filter(r => r.t >= n.t && r.t < end), voiced = inside.filter(r => r.m !== null);
  const step = readings.length > 1 ? Math.max(1e-3, (readings.at(-1).t - readings[0].t) / (readings.length - 1)) : 0.016;
  if (voiced.length < MIN_READINGS || voiced.length * step < MIN_SUNG * (end - n.t)) {
    return { ...base, sung: false, cents: null, settle: null, spread: null, onset: null, octave: null, pitch: "missed", timing: null };
  }
  // The octave the note was sung in: the one most of its readings fall in.
  const octaves = new Map();
  for (const r of voiced) { const o = foldCents(r.m, n.m).octave; octaves.set(o, (octaves.get(o) ?? 0) + 1); }
  const octave = [...octaves].sort((a, b) => b[1] - a[1] || Math.abs(a[0]) - Math.abs(b[0]))[0][0];
  const off = r => (r.m - n.m) * 100 - octave * 1200;
  // Onset: the first reading near the note, from a little before it starts to the end of its first half second.
  // When the voice was already on this pitch before that window (a note tied over from one before at the same pitch,
  // sung legato), the pitch cannot tell when it came in, so the onset is unknown.
  const near = r => r.m !== null && Math.abs(off(r)) <= ONSET_CENTS;
  const k0 = readings.findIndex(r => near(r) && r.t >= n.t - ONSET_EARLY && r.t < Math.min(end, n.t + 0.5));
  let k = k0;
  while (k > 0 && near(readings[k - 1])) k--;
  const onsetR = k0 >= 0 && readings[k].t >= n.t - ONSET_EARLY ? readings[k0] : null;
  const onset = onsetR ? round3(onsetR.t - n.t) : null;
  // Settled: the first run of SETTLE_RUN voiced readings in a row within SETTLED cents, inside the note.
  let settledAt = -1;
  for (let k = 0, run = 0; k < inside.length; k++) {
    const r = inside[k];
    run = r.m !== null && Math.abs(off(r)) <= SETTLED ? run + 1 : 0;
    if (run === SETTLE_RUN) { settledAt = k - SETTLE_RUN + 1; break; }
  }
  const held = (settledAt >= 0 ? inside.slice(settledAt) : inside).filter(r => r.m !== null).map(off).sort((a, b) => a - b);
  const cents = Math.round(quantile(held, 0.5));
  const spread = Math.round(quantile(held, 0.75) - quantile(held, 0.25));
  const settle = settledAt >= 0 ? round3(Math.max(0, inside[settledAt].t - (onsetR ? onsetR.t : n.t))) : null;
  const pitch = Math.abs(cents) <= IN_TUNE ? "in" : cents > 0 ? "sharp" : "flat";
  const timing = onset === null ? null : Math.abs(onset) <= ON_TIME ? "on" : onset < 0 ? "early" : "late";
  return { ...base, sung: true, cents, settle, spread, onset, octave, pitch, timing };
}

// What a pass comes to: {notes, sung, inTune, missed, worst, onTime} with worst the sung note furthest off ({i, m,
// cents}, null when none was sung) and onTime the sung notes whose onset was on time.
export function passSummary(scores) {
  const sung = scores.filter(s => s.sung);
  const worst = sung.reduce((w, s) => (!w || Math.abs(s.cents) > Math.abs(w.cents) ? s : w), null);
  return {
    notes: scores.length, sung: sung.length, inTune: sung.filter(s => s.pitch === "in").length,
    missed: scores.length - sung.length, onTime: sung.filter(s => s.timing === "on").length,
    worst: worst ? { i: worst.i, m: worst.m, cents: worst.cents } : null,
  };
}

// One line for the status: "Pass 2: 5 of 7 notes in tune; furthest off: E4, 38 cents flat; 1 missed".
export function passText(summary, pass) {
  const s = summary, parts = [s.inTune + " of " + s.notes + " note" + (s.notes === 1 ? "" : "s") + " in tune"];
  if (s.worst && s.worst.cents !== 0 && s.inTune < s.sung) {
    parts.push("furthest off: " + noteName(s.worst.m) + ", " + Math.abs(s.worst.cents) + " cents " + (s.worst.cents > 0 ? "sharp" : "flat"));
  }
  if (s.missed) parts.push(s.missed + " not heard");
  return "Pass " + pass + ": " + parts.join("; ");
}

// The words for one note's score, for its title on the roll.
export function noteScoreText(s) {
  if (!s.sung) return noteName(s.m) + ": not heard";
  const pitch = s.pitch === "in" ? "in tune (" + (s.cents > 0 ? "+" : "") + s.cents + " cents)" : Math.abs(s.cents) + " cents " + s.pitch;
  const timing = s.timing === null ? "" : s.timing === "on" ? ", on time" : ", " + Math.round(Math.abs(s.onset) * 1000) + " ms " + s.timing;
  const octave = s.octave ? ", sung " + Math.abs(s.octave) + " octave" + (Math.abs(s.octave) === 1 ? "" : "s") + (s.octave > 0 ? " up" : " down") : "";
  return noteName(s.m) + ": " + pitch + timing + octave;
}

// Splits the capture into passes. Passes follow one another from `zero` (context time of the first pass's song start,
// already moved by the round trip), each `length` seconds long. add(t, channels) takes a capture batch ({t: context time
// of its first frame}); it returns the passes the batch completed, in order, as [{index, channels}]: each pass `length`
// seconds at `rate` in every channel the capture has (the studio makes it mono with recordings.js monoSamples, which
// leaves out a dead side). Batches may arrive in any order; frames before `zero` are dropped.
export function createPassSplitter({ zero, length, rate }) {
  if (!(rate > 0) || !(length > 0)) throw Error("Passes need a length and a sample rate above zero");
  const frames = Math.round(length * rate), first = Math.round(zero * rate);
  const open = new Map(); // pass index -> {channels, filled}
  let done = -1;
  return {
    frames,
    add(t, channels) {
      if (!channels?.length || !channels[0].length) return [];
      const at = Math.round(t * rate) - first, n = channels[0].length, out = [];
      for (let k = Math.max(0, Math.floor(at / frames)); k * frames < at + n; k++) {
        if (k <= done) continue;
        let p = open.get(k);
        if (!p) { p = { channels: channels.map(() => new Float32Array(frames)), filled: 0 }; open.set(k, p); }
        const from = Math.max(0, k * frames - at), to = Math.min(n, (k + 1) * frames - at);
        if (to <= from) continue;
        channels.forEach((c, j) => { if (p.channels[j]) p.channels[j].set(c.subarray(from, to), at + from - k * frames); });
        p.filled += to - from;
      }
      for (const k of [...open.keys()].sort((a, b) => a - b)) {
        const p = open.get(k);
        if (k !== done + 1 || p.filled < frames) break;
        open.delete(k); done = k; out.push({ index: k, channels: p.channels });
      }
      return out;
    },
  };
}
