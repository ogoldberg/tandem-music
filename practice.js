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
  const out = [];
  for (const slice of tracking(samples, rate, t0)) out.push(...slice);
  return out;
}

// The same readings for a long recording, a slice at a time with `pause()` awaited between slices (PRACTICE.2 tracks a
// whole take for the range without holding the page up).
export async function trackInSlices(samples, rate, { pause = () => new Promise(r => setTimeout(r, 0)) } = {}) {
  const out = [];
  for (const slice of tracking(samples, rate, 0)) { out.push(...slice); await pause(); }
  return out;
}

function* tracking(samples, rate, t0, sliceFrames = 1 << 17) {
  if (!(rate > 0)) throw Error("The pass needs a sample rate above zero");
  const tr = createPitchTracker(rate);
  for (let s = 0; s < samples.length; s += sliceFrames) {
    const out = [];
    for (let i = s; i < Math.min(samples.length, s + sliceFrames); i += 128) {
      for (const r of tr.push(samples.subarray(i, Math.min(samples.length, i + 128)), t0 + i / rate)) {
        out.push({ t: r.t, m: r.hz ? hzToMidi(r.hz) : null });
      }
    }
    yield out;
  }
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

// PRACTICE.2: your range and your progress, kept on this device beside the draft (one IndexedDB key, never in the
// project). The range is built from held notes: a run of readings that stays within HOLD_CENTS of its own average for
// at least HOLD seconds is one held note at the nearest semitone to its median, so a passing slide or a reading an octave
// out is never counted. Seconds held add up per semitone over every pass and recorded take; the range is the lowest and
// highest semitones held for RANGE_MIN seconds in all. Progress is kept per stretch, named by its notes (phraseKey), as
// one summary a day: passes, notes scored, in tune, on time, sung and the best pass's in-tune count.
export const PRACTICE_KEY = "practice";
export const HOLD = 0.3;          // seconds: the shortest steady run that counts as a held note
export const HOLD_CENTS = 50;     // cents: how far a reading may be from the run's average and still be the same note
export const HOLD_GAP = 2;        // unvoiced readings a held note may have inside it (a missed reading, not a breath)
export const RANGE_MIN = 0.6;     // seconds: a semitone is in the range once it has been held this long in all
export const MAX_PHRASES = 200;   // stretches kept; the one practised longest ago goes first
export const MAX_DAYS = 366;      // days kept per stretch; the oldest goes first
const MIDI_LOW = 21, MIDI_HIGH = 108;

// The held notes in `readings` ([{t, m}], m null when unvoiced): [{m, from, seconds}] in time order.
export function heldNotes(readings) {
  const out = [];
  if (!readings?.length) return out;
  const step = readings.length > 1 ? Math.max(1e-3, (readings.at(-1).t - readings[0].t) / (readings.length - 1)) : 0.016;
  let run = null, gap = 0;
  const end = () => {
    if (run && run.last - run.first + step >= HOLD) {
      const ms = run.ms.sort((a, b) => a - b), m = Math.round(quantile(ms, 0.5));
      if (m >= MIDI_LOW && m <= MIDI_HIGH) out.push({ m, from: round3(run.first), seconds: round3(run.last - run.first + step) });
    }
    run = null; gap = 0;
  };
  for (const r of readings) {
    if (r.m === null || !Number.isFinite(r.m)) { if (run && ++gap > HOLD_GAP) end(); continue; }
    if (run && Math.abs(r.m - run.sum / run.ms.length) * 100 > HOLD_CENTS) end();
    if (!run) run = { first: r.t, last: r.t, ms: [], sum: 0 };
    run.ms.push(r.m); run.sum += r.m; run.last = r.t; gap = 0;
  }
  end();
  return out;
}

// A stretch's name for its history: its melody notes (pitch, start from the stretch's start, length, to the ms), hashed.
// The same notes anywhere in any song are the same stretch; a stretch whose notes change starts a history of its own.
export function phraseKey(notes, { from, to }) {
  const inside = (notes ?? []).filter(n => n.t >= from && n.t < to)
    .map(n => [n.m, Math.round((n.t - from) * 1000), Math.round(n.d * 1000)])
    .sort((a, b) => a[1] - b[1] || a[0] - b[0] || a[2] - b[2]);
  if (!inside.length) throw Error("No melody note starts in that stretch.");
  const text = inside.map(x => x.join(":")).join(",");
  return "p" + fnv(text, 0x811c9dc5) + fnv(text, 0x01000193 ^ 0x9e3779b9);
}

function fnv(text, seed) {
  let h = seed >>> 0;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, "0");
}

// What a stretch is called in the history: its first notes' names ("A4 C5 E5 …") and how many notes it has.
export function phraseLabel(notes, { from, to }) {
  const inside = (notes ?? []).filter(n => n.t >= from && n.t < to).sort((a, b) => a.t - b.t || a.m - b.m);
  return inside.slice(0, 4).map(n => noteName(n.m)).join(" ") + (inside.length > 4 ? " …" : "") + " (" + inside.length + " note" + (inside.length === 1 ? "" : "s") + ")";
}

// The local calendar day of a time in ms, "YYYY-MM-DD".
export function dayOf(ms) {
  const d = new Date(ms);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

const isDay = s => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);
const count = x => Number.isInteger(x) && x >= 0;
const EMPTY = () => ({ version: 1, range: { held: {}, passes: 0, takes: 0 }, phrases: [] });

// The stored record, checked: undefined is an empty record; anything else that is not one this version can read is an
// error, so it is never overwritten. Entries inside it that do not check out are dropped.
export function cleanPracticeRecord(value) {
  if (value === undefined || value === null) return EMPTY();
  if (typeof value !== "object" || Array.isArray(value)) throw Error("Your saved range and progress are unreadable in this browser's storage.");
  if (value.version !== 1) throw Error("Your range and progress were saved by a newer version of Tandem: reload to update.");
  const out = EMPTY(), held = value.range?.held;
  if (held && typeof held === "object") {
    for (const [k, s] of Object.entries(held)) {
      const m = Number(k);
      if (Number.isInteger(m) && m >= MIDI_LOW && m <= MIDI_HIGH && Number.isFinite(s) && s > 0) out.range.held[m] = s;
    }
  }
  if (count(value.range?.passes)) out.range.passes = value.range.passes;
  if (count(value.range?.takes)) out.range.takes = value.range.takes;
  for (const p of Array.isArray(value.phrases) ? value.phrases : []) {
    if (!p || typeof p.key !== "string" || !/^p[0-9a-f]{16}$/.test(p.key) || !Number.isFinite(p.last)) continue;
    const days = (Array.isArray(p.days) ? p.days : []).filter(d => d && isDay(d.day)
      && ["passes", "notes", "inTune", "onTime", "sung", "best"].every(k => count(d[k])))
      .map(({ day, passes, notes, inTune, onTime, sung, best }) => ({ day, passes, notes, inTune, onTime, sung, best }));
    if (!days.length || out.phrases.some(q => q.key === p.key)) continue;
    out.phrases.push({ key: p.key, label: String(p.label ?? "").slice(0, 80), song: String(p.song ?? "").slice(0, 80), last: p.last,
      days: days.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0)).slice(-MAX_DAYS) });
  }
  out.phrases.sort((a, b) => b.last - a.last);
  out.phrases = out.phrases.slice(0, MAX_PHRASES);
  return out;
}

function addHeld(range, held) {
  const next = { ...range.held };
  for (const h of held ?? []) {
    if (Number.isInteger(h.m) && h.m >= MIDI_LOW && h.m <= MIDI_HIGH && Number.isFinite(h.seconds) && h.seconds > 0) {
      next[h.m] = round3((next[h.m] ?? 0) + h.seconds);
    }
  }
  return next;
}

// The record with one more scored pass: its held notes added to the range and its summary to the stretch's day.
export function withPass(record, { key, label = "", song = "", summary, held = [] }, now) {
  const rec = cleanPracticeRecord(record);
  if (typeof key !== "string" || !/^p[0-9a-f]{16}$/.test(key)) throw Error("A pass needs its stretch's key.");
  // every count the day keeps, or the day would be saved with a bad value and dropped by the next read
  const s = summary;
  if (!s || !["notes", "sung", "inTune", "onTime"].every(k => count(s[k])) || !s.notes || s.sung > s.notes
    || s.inTune > s.sung || s.onTime > s.sung) throw Error("A pass needs its scores.");
  const day = dayOf(now), old = rec.phrases.find(p => p.key === key);
  const days = old ? old.days.map(d => ({ ...d })) : [];
  let today = days.find(d => d.day === day);
  if (!today) { today = { day, passes: 0, notes: 0, inTune: 0, onTime: 0, sung: 0, best: 0 }; days.push(today); }
  today.passes++; today.notes += summary.notes; today.inTune += summary.inTune; today.onTime += summary.onTime;
  today.sung += summary.sung; today.best = Math.max(today.best, summary.inTune);
  const phrase = { key, label: String(label || old?.label || "").slice(0, 80), song: String(song || old?.song || "").slice(0, 80), last: now, days: days.slice(-MAX_DAYS) };
  return {
    version: 1,
    range: { held: addHeld(rec.range, held), passes: rec.range.passes + 1, takes: rec.range.takes },
    phrases: [phrase, ...rec.phrases.filter(p => p.key !== key)].slice(0, MAX_PHRASES),
  };
}

// The record with one more recorded take's held notes in the range.
export function withTake(record, held) {
  const rec = cleanPracticeRecord(record);
  return { ...rec, range: { held: addHeld(rec.range, held), passes: rec.range.passes, takes: rec.range.takes + 1 } };
}

// The range: {low, high} MIDI notes held RANGE_MIN seconds or more in all, with the passes and takes it came from, or
// null when no note has been held that long yet.
export function vocalRange(record) {
  const rec = cleanPracticeRecord(record);
  const ms = Object.entries(rec.range.held).filter(([, s]) => s >= RANGE_MIN).map(([m]) => Number(m));
  if (!ms.length) return null;
  return { low: Math.min(...ms), high: Math.max(...ms), passes: rec.range.passes, takes: rec.range.takes };
}

export function rangeText(range) {
  if (!range) return "Your range: not known yet. Hold a few notes while practising or recording.";
  const from = [range.passes && range.passes + " pass" + (range.passes === 1 ? "" : "es"), range.takes && range.takes + " take" + (range.takes === 1 ? "" : "s")].filter(Boolean).join(" and ");
  return "Your range: " + noteName(range.low) + (range.high > range.low ? " to " + noteName(range.high) : " only") + ", held steadily" + (from ? " over " + from : "") + ".";
}

// A stretch's history, oldest day first, or null when it has never been practised.
export function phraseHistory(record, key) {
  const p = cleanPracticeRecord(record).phrases.find(q => q.key === key);
  return p ? { key: p.key, label: p.label, song: p.song, last: p.last, days: p.days } : null;
}

const shortDay = (day, today) => {
  if (day === today) return "today";
  const [y, m, d] = day.split("-").map(Number);
  return d + " " + ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1] + (day.slice(0, 4) === today.slice(0, 4) ? "" : " " + y);
};

// One line on how a stretch has gone: the first day's best pass beside the latest day's, so the person sees whether it is
// getting better. "First time practising this stretch." when there is no history.
export function progressText(history, now) {
  if (!history?.days.length) return "First time practising this stretch.";
  const today = dayOf(now), days = history.days, passes = days.reduce((n, d) => n + d.passes, 0);
  const notes = d => Math.round(d.notes / d.passes), best = d => d.best + " of " + notes(d) + " in tune";
  const first = days[0], last = days.at(-1);
  const total = " (" + passes + " pass" + (passes === 1 ? "" : "es") + (days.length > 1 ? " on " + days.length + " days" : "") + ")";
  if (days.length === 1) return "Best pass " + shortDay(first.day, today) + ": " + best(first) + total + ".";
  return "Best pass " + shortDay(first.day, today) + ": " + best(first) + "; " + shortDay(last.day, today) + ": " + best(last) + total + ".";
}

// The store over storage.js's key-value store: every change is one read-change-write transaction, so two tabs cannot
// lose each other's passes.
export function createPracticeStore(kv, { now = () => Date.now() } = {}) {
  if (!kv || typeof kv.get !== "function" || typeof kv.update !== "function") throw TypeError("Expected a key-value store with get and update");
  const change = fn => kv.update(PRACTICE_KEY, value => { const next = fn(value); return [next, next]; });
  return {
    async get() { return cleanPracticeRecord(await kv.get(PRACTICE_KEY)); },
    addPass(pass) { return change(v => withPass(v, pass, now())); },
    addTake(held) { return change(v => withTake(v, held)); },
    forget() { return change(() => EMPTY()); },
  };
}
