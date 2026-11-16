import { test } from "node:test";
import assert from "node:assert/strict";
import {
  trackPass, scorePass, passSummary, passText, noteScoreText, practiceSpan, foldCents, createPassSplitter,
  IN_TUNE, MIN_SPAN, MAX_SPAN,
} from "../practice.js";

const RATE = 48000;
const midiHz = m => 440 * 2 ** ((m - 69) / 12);

// A sung pass: each part {m, from, to, cents = 0, vibrato = 0 (cents depth, 5.5 Hz)} is a voice-like tone at that
// pitch over [from, to) seconds of the pass, with silence between. The phase runs on, so a pitch change has no click.
function sing(seconds, parts) {
  const x = new Float32Array(Math.round(seconds * RATE));
  let phase = 0;
  for (let i = 0; i < x.length; i++) {
    const t = i / RATE, p = parts.find(q => t >= q.from && t < q.to);
    if (!p) continue;
    const c = (p.cents ?? 0) + (p.vibrato ?? 0) * Math.sin(2 * Math.PI * 5.5 * t);
    phase += 2 * Math.PI * midiHz(p.m + c / 100) / RATE;
    x[i] = 0.3 * Math.sin(phase) + 0.15 * Math.sin(2 * phase) + 0.07 * Math.sin(3 * phase);
  }
  return x;
}

// Four half-second notes from 1 s of the song: C4 D4 E4 F4.
const MELODY = [{ m: 60, t: 1, d: 0.5 }, { m: 62, t: 1.5, d: 0.5 }, { m: 64, t: 2, d: 0.5 }, { m: 65, t: 2.5, d: 0.5 }];
const SPAN = { from: 1, to: 3 };
// The pass covers the span: pass time 0 is song time 1.
const at = (m, songFrom, songTo, extra = {}) => ({ m, from: songFrom - 1, to: songTo - 1, ...extra });
const scoreOf = parts => scorePass(trackPass(sing(2, parts), RATE, SPAN.from), MELODY, SPAN);

test("a pass sung in tune and on time scores every note in tune and on time", () => {
  const s = scoreOf(MELODY.map(n => at(n.m, n.t, n.t + n.d)));
  assert.equal(s.length, 4);
  for (const n of s) {
    assert.equal(n.sung, true);
    assert.equal(n.pitch, "in", noteScoreText(n));
    assert.ok(Math.abs(n.cents) <= 5, `${n.cents} cents`);
    assert.equal(n.timing, "on", noteScoreText(n));
    assert.equal(n.octave, 0);
    assert.ok(n.spread <= 5, `spread ${n.spread}`);
  }
  assert.deepEqual(s.map(n => n.i), [0, 1, 2, 3]);
  const sum = passSummary(s);
  assert.deepEqual({ ...sum, worst: undefined }, { notes: 4, sung: 4, inTune: 4, missed: 0, onTime: 4, worst: undefined });
  assert.equal(passText(sum, 1), "Pass 1: 4 of 4 notes in tune");
});

test("a note held 40 cents sharp reads 40 cents sharp, and is the worst note", () => {
  const s = scoreOf(MELODY.map((n, k) => at(n.m, n.t, n.t + n.d, k === 2 ? { cents: 40 } : {})));
  assert.equal(s[2].pitch, "sharp");
  assert.ok(Math.abs(s[2].cents - 40) <= 4, `${s[2].cents} cents`);
  assert.equal(s[2].sung, true);
  // A steady 40 cents is within the onset window, so the note still comes in on time.
  assert.equal(s[2].timing, "on");
  for (const k of [0, 1, 3]) assert.equal(s[k].pitch, "in");
  const sum = passSummary(s);
  assert.equal(sum.inTune, 3);
  assert.deepEqual({ i: sum.worst.i, m: sum.worst.m }, { i: 2, m: 64 });
  assert.match(passText(sum, 2), /^Pass 2: 3 of 4 notes in tune; furthest off: E4, 4\d cents sharp$/);
  assert.match(noteScoreText(s[2]), /^E4: 4\d cents sharp, on time$/);
});

test("a note held flat reads flat", () => {
  const s = scoreOf(MELODY.map((n, k) => at(n.m, n.t, n.t + n.d, k === 1 ? { cents: -60 } : {})));
  assert.equal(s[1].pitch, "flat");
  assert.ok(Math.abs(s[1].cents + 60) <= 5, `${s[1].cents} cents`);
});

test("a note that comes in 120 ms late reads late by about 120 ms", () => {
  const s = scoreOf(MELODY.map((n, k) => at(n.m, n.t + (k === 1 ? 0.12 : 0), n.t + n.d)));
  assert.equal(s[1].timing, "late", noteScoreText(s[1]));
  assert.ok(Math.abs(s[1].onset - 0.12) <= 0.03, `onset ${s[1].onset}`);
  assert.equal(s[1].pitch, "in");
  for (const k of [0, 2, 3]) assert.equal(s[k].timing, "on", noteScoreText(s[k]));
  assert.match(noteScoreText(s[1]), /^D4: in tune \([+-]?\d+ cents\), 1\d\d ms late$/);
});

test("a note that comes in early, sung over the end of the note before, reads early", () => {
  // E4 starts 150 ms before its time, in place of the end of D4.
  const parts = [at(60, 1, 1.5), at(62, 1.5, 1.85), at(64, 1.85, 2.5), at(65, 2.5, 3)];
  const s = scoreOf(parts);
  assert.equal(s[2].timing, "early", noteScoreText(s[2]));
  assert.ok(Math.abs(s[2].onset + 0.15) <= 0.03, `onset ${s[2].onset}`);
});

test("a repeated note sung legato has no onset to time, but is still scored", () => {
  const notes = [{ m: 62, t: 1, d: 0.5 }, { m: 62, t: 1.5, d: 0.5 }];
  const s = scorePass(trackPass(sing(1, [at(62, 1, 2)]), RATE, 1), notes, { from: 1, to: 2 });
  assert.equal(s[0].timing, "on");
  assert.equal(s[1].onset, null);
  assert.equal(s[1].timing, null);
  assert.equal(s[1].pitch, "in");
  assert.equal(noteScoreText(s[1]).startsWith("D4: in tune"), true);
});

test("a note not sung is missed, and the rest are still scored", () => {
  const s = scoreOf(MELODY.filter((_, k) => k !== 3).map(n => at(n.m, n.t, n.t + n.d)));
  assert.equal(s[3].sung, false);
  assert.equal(s[3].pitch, "missed");
  assert.equal(s[3].cents, null);
  assert.equal(s[3].timing, null);
  const sum = passSummary(s);
  assert.equal(sum.missed, 1);
  assert.equal(sum.sung, 3);
  assert.equal(passText(sum, 3), "Pass 3: 3 of 4 notes in tune; 1 not heard");
  assert.equal(noteScoreText(s[3]), "F4: not heard");
});

test("vibrato around the right pitch counts as in tune, and shows as a wider spread", () => {
  const steady = scoreOf(MELODY.map(n => at(n.m, n.t, n.t + n.d)));
  const wide = scoreOf(MELODY.map(n => at(n.m, n.t, n.t + n.d, { vibrato: 60 })));
  for (let k = 0; k < 4; k++) {
    assert.equal(wide[k].pitch, "in", noteScoreText(wide[k]));
    assert.ok(Math.abs(wide[k].cents) <= IN_TUNE, `${wide[k].cents} cents`);
    assert.ok(wide[k].spread > steady[k].spread + 20, `spread ${wide[k].spread} against ${steady[k].spread}`);
  }
});

test("a scoop up to the note is timed from where it comes near and settles after it", () => {
  // D4 starts 300 cents low and slides up to the note over 150 ms.
  const x = new Float32Array(2 * RATE);
  let phase = 0;
  for (let i = 0; i < x.length; i++) {
    const t = i / RATE, songT = t + 1;
    let m = null;
    for (const n of MELODY) if (songT >= n.t && songT < n.t + n.d) m = n.m;
    if (m === null) continue;
    if (m === 62 && songT < 1.65) m = 59 + 3 * (songT - 1.5) / 0.15;
    phase += 2 * Math.PI * midiHz(m) / RATE;
    x[i] = 0.3 * Math.sin(phase) + 0.15 * Math.sin(2 * phase);
  }
  const s = scorePass(trackPass(x, RATE, 1), MELODY, SPAN);
  assert.equal(s[1].pitch, "in");
  assert.ok(s[1].onset > 0.05 && s[1].onset < 0.16, `onset ${s[1].onset}`);
  assert.ok(s[1].settle !== null && s[1].settle < 0.15, `settle ${s[1].settle}`);
});

test("a melody sung an octave down is scored in its own octave and says so", () => {
  const s = scoreOf(MELODY.map(n => at(n.m - 12, n.t, n.t + n.d)));
  for (const n of s) {
    assert.equal(n.pitch, "in", noteScoreText(n));
    assert.equal(n.octave, -1);
  }
  assert.match(noteScoreText(s[0]), /sung 1 octave down$/);
});

test("only notes starting in the stretch are scored", () => {
  const notes = [{ m: 57, t: 0.4, d: 0.8 }, ...MELODY, { m: 67, t: 3, d: 0.5 }];
  const s = scorePass(trackPass(sing(2, MELODY.map(n => at(n.m, n.t, n.t + n.d))), RATE, 1), notes, SPAN);
  assert.deepEqual(s.map(n => n.i), [1, 2, 3, 4]);
});

test("foldCents takes the nearest octave", () => {
  assert.deepEqual(foldCents(72.3, 60), { cents: 30.000000000000427, octave: 1 });
  assert.deepEqual(foldCents(60.2, 60).octave, 0);
  assert.equal(Math.round(foldCents(47.6, 60).cents), 160);
  assert.equal(foldCents(47.6, 60).octave, -1);
});

test("practiceSpan takes the marked section, else the chosen phrase, else the melody", () => {
  assert.deepEqual(practiceSpan(MELODY, { loop: { start: 1.4, end: 2.6 } }), { from: 1.4, to: 2.6, what: "the marked section" });
  assert.deepEqual(practiceSpan(MELODY, { phrase: { start: 1, end: 2 } }), { from: 1, to: 2, what: "the chosen phrase" });
  assert.deepEqual(practiceSpan(MELODY, { loop: { start: 1.4, end: 2.6 }, phrase: { start: 1, end: 2 } }).what, "the marked section");
  assert.deepEqual(practiceSpan(MELODY), { from: 1, to: 3, what: "the melody" });
  assert.throws(() => practiceSpan([]), /needs a melody/);
  assert.throws(() => practiceSpan(MELODY, { loop: { start: 3.2, end: 5 } }), /No melody note starts in the marked section/);
  assert.throws(() => practiceSpan(MELODY, { loop: { start: 1, end: 1 + MIN_SPAN / 2 } }), /at least/);
  assert.throws(() => practiceSpan([{ m: 60, t: 0, d: 1 }], { loop: { start: 0, end: MAX_SPAN + 1 } }), /at most/);
});

test("the splitter cuts the capture into passes of the stretch's length, whatever the batches' order", () => {
  const rate = 1000, zero = 10.0005, length = 0.5, frames = 500;
  // The capture: frame f of the context (from context time 9.8) holds f, in two channels (the second negated).
  const total = 1800, start = 9.8;
  const batches = [];
  for (let i = 0; i < total; i += 128) {
    const n = Math.min(128, total - i), a = new Float32Array(n), b = new Float32Array(n);
    for (let k = 0; k < n; k++) { a[k] = i + k; b[k] = -(i + k); }
    batches.push([start + i / rate, [a, b]]);
  }
  const sp = createPassSplitter({ zero, length, rate });
  assert.equal(sp.frames, frames);
  // Shuffle a few neighbours: the worklet's batches can arrive out of order.
  [batches[3], batches[4]] = [batches[4], batches[3]];
  const passes = batches.flatMap(([t, ch]) => sp.add(t, ch));
  assert.deepEqual(passes.map(p => p.index), [0, 1, 2]);
  const firstFrame = Math.round(zero * rate) - Math.round(start * rate);
  passes.forEach(p => {
    assert.equal(p.channels.length, 2);
    assert.equal(p.channels[0].length, frames);
    assert.equal(p.channels[0][0], firstFrame + p.index * frames);
    assert.equal(p.channels[0][frames - 1], firstFrame + (p.index + 1) * frames - 1);
    assert.equal(p.channels[1][7], -(firstFrame + p.index * frames + 7));
  });
  // Frames past the last whole pass stay open until it fills.
  assert.deepEqual(sp.add(start + total / rate, [new Float32Array(10), new Float32Array(10)]), []);
});
