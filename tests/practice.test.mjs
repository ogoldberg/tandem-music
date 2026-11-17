import { test } from "node:test";
import assert from "node:assert/strict";
import {
  trackPass, scorePass, passSummary, passText, noteScoreText, practiceSpan, foldCents, createPassSplitter,
  IN_TUNE, MIN_SPAN, MAX_SPAN,
  heldNotes, trackInSlices, phraseKey, phraseLabel, dayOf, cleanPracticeRecord, withPass, withTake, vocalRange, rangeText,
  phraseHistory, progressText, createPracticeStore, PRACTICE_KEY, HOLD, RANGE_MIN, MAX_PHRASES, MAX_DAYS,
} from "../practice.js";
import { memoryKV } from "./memory-kv.mjs";

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
  assert.equal(Math.round(foldCents(72.3, 60).cents), 30);
  assert.equal(foldCents(72.3, 60).octave, 1);
  assert.deepEqual(foldCents(60.2, 60).octave, 0);
  assert.equal(Math.round(foldCents(47.6, 60).cents), -40);
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


// PRACTICE.2: the range and the progress.
const DAY = 24 * 3600 * 1000, NOON = new Date(2026, 10, 10, 12).getTime();
const readingsOf = (seconds, parts) => trackPass(sing(seconds, parts), RATE, 0);

test("a steady note held long enough is one held note at its nearest semitone; a slide or a blip is not", () => {
  // A2 for 0.8 s, a quick slide, E4 25 cents sharp for 0.5 s, then a 0.15 s blip at C6.
  const parts = [{ m: 45, from: 0, to: 0.8 }, ...Array.from({ length: 8 }, (_, k) => ({ m: 46 + 2 * k, from: 0.8 + k * 0.02, to: 0.82 + k * 0.02 })),
    { m: 64, from: 1.0, to: 1.5, cents: 25 }, { m: 84, from: 1.7, to: 1.85 }];
  const held = heldNotes(readingsOf(2, parts));
  assert.deepEqual(held.map(h => h.m), [45, 64]);
  assert.ok(Math.abs(held[0].seconds - 0.8) < 0.06, `${held[0].seconds} s`);
  assert.ok(Math.abs(held[1].seconds - 0.5) < 0.06, `${held[1].seconds} s`);
  // Vibrato of 40 cents around a note is still one held note.
  assert.deepEqual(heldNotes(readingsOf(1, [{ m: 57, from: 0, to: 1, vibrato: 40 }])).map(h => h.m), [57]);
  // Shorter than HOLD: nothing.
  assert.deepEqual(heldNotes(readingsOf(1, [{ m: 57, from: 0, to: HOLD - 0.08 }])), []);
  assert.deepEqual(heldNotes([]), []);
});

test("one missed reading inside a held note does not cut it, but a breath does", () => {
  const steady = (from, to) => Array.from({ length: Math.round((to - from) / 0.01) }, (_, k) => ({ t: from + k * 0.01, m: 60.1 }));
  const gap = (from, n) => Array.from({ length: n }, (_, k) => ({ t: from + k * 0.01, m: null }));
  assert.deepEqual(heldNotes([...steady(0, 0.2), ...gap(0.2, 2), ...steady(0.22, 0.4)]).map(h => h.m), [60]);
  assert.deepEqual(heldNotes([...steady(0, 0.2), ...gap(0.2, 10), ...steady(0.3, 0.5)]), []);
});

test("the range is the lowest and highest notes held long enough over passes and takes", () => {
  let rec = cleanPracticeRecord(undefined);
  assert.equal(vocalRange(rec), null);
  assert.match(rangeText(null), /not known yet/);
  const key = phraseKey(MELODY, SPAN), summary = { notes: 4, sung: 4, inTune: 3, missed: 0, onTime: 4, worst: null };
  rec = withPass(rec, { key, summary, held: heldNotes(readingsOf(2, [{ m: 48, from: 0, to: 0.7 }, { m: 67, from: 1, to: 1.4 }])) }, NOON);
  // G4 held 0.4 s is not yet enough on its own; C3 held 0.7 s is.
  assert.deepEqual(vocalRange(rec), { low: 48, high: 48, passes: 1, takes: 0 });
  assert.equal(rangeText(vocalRange(rec)), "Your range: C3 only, held steadily over 1 pass.");
  rec = withTake(rec, heldNotes(readingsOf(1, [{ m: 67, from: 0, to: 0.5 }])));
  assert.deepEqual(vocalRange(rec), { low: 48, high: 67, passes: 1, takes: 1 });
  assert.equal(rangeText(vocalRange(rec)), "Your range: C3 to G4, held steadily over 1 pass and 1 take.");
  assert.ok(rec.range.held[67] >= RANGE_MIN);
});

test("a stretch is named by its notes, wherever it is in the song", () => {
  const key = phraseKey(MELODY, SPAN);
  assert.match(key, /^p[0-9a-f]{16}$/);
  const later = MELODY.map(n => ({ ...n, t: n.t + 10 }));
  assert.equal(phraseKey(later, { from: 11, to: 13 }), key);
  assert.equal(phraseKey([...MELODY].reverse(), SPAN), key);
  assert.notEqual(phraseKey(MELODY.map((n, k) => (k === 2 ? { ...n, m: 63 } : n)), SPAN), key);
  assert.notEqual(phraseKey(MELODY, { from: 1, to: 2.5 }), key);
  assert.throws(() => phraseKey(MELODY, { from: 5, to: 6 }), /No melody note/);
  assert.equal(phraseLabel(MELODY, SPAN), "C4 D4 E4 F4 (4 notes)");
  assert.equal(phraseLabel([...MELODY, { m: 67, t: 2.9, d: 0.1 }], SPAN), "C4 D4 E4 F4 … (5 notes)");
});

test("a stretch's history keeps one summary a day, and the text compares the first day with the latest", () => {
  const key = phraseKey(MELODY, SPAN), pass = inTune => ({ key, label: "C4 D4 E4 F4 (4 notes)", song: "Song", summary: { notes: 4, sung: 4, inTune, missed: 0, onTime: 3, worst: null } });
  // The day's best pass is kept, not its last.
  let rec = withPass(undefined, pass(2), NOON);
  rec = withPass(rec, pass(1), NOON + 60_000);
  assert.equal(progressText(phraseHistory(rec, key), NOON), "Best pass today: 2 of 4 in tune (2 passes).");
  rec = withPass(rec, pass(3), NOON + 2 * DAY);
  rec = withPass(rec, pass(4), NOON + 2 * DAY + 60_000);
  const h = phraseHistory(rec, key);
  assert.deepEqual(h.days, [
    { day: dayOf(NOON), passes: 2, notes: 8, inTune: 3, onTime: 6, sung: 8, best: 2 },
    { day: dayOf(NOON + 2 * DAY), passes: 2, notes: 8, inTune: 7, onTime: 6, sung: 8, best: 4 },
  ]);
  assert.equal(h.song, "Song");
  assert.equal(progressText(h, NOON + 2 * DAY), "Best pass 10 Nov: 2 of 4 in tune; today: 4 of 4 in tune (4 passes on 2 days).");
  assert.equal(progressText(h, NOON + 400 * DAY), "Best pass 10 Nov 2026: 2 of 4 in tune; 12 Nov 2026: 4 of 4 in tune (4 passes on 2 days).");
  assert.equal(progressText(null, NOON), "First time practising this stretch.");
  assert.equal(phraseHistory(rec, phraseKey(MELODY, { from: 1, to: 2.5 })), null);
});

test("the history keeps the latest stretches and days only", () => {
  const summary = { notes: 2, sung: 2, inTune: 1, missed: 0, onTime: 2, worst: null };
  let rec;
  for (let k = 0; k < MAX_PHRASES + 5; k++) rec = withPass(rec, { key: "p" + k.toString(16).padStart(16, "0"), summary }, NOON + k);
  assert.equal(rec.phrases.length, MAX_PHRASES);
  assert.equal(rec.phrases[0].key, "p" + (MAX_PHRASES + 4).toString(16).padStart(16, "0"));
  assert.equal(phraseHistory(rec, "p" + "0".repeat(16)), null);
  const key = "p" + "a".repeat(16);
  for (let d = 0; d < MAX_DAYS + 3; d++) rec = withPass(rec, { key, summary }, NOON + d * DAY);
  const days = phraseHistory(rec, key).days;
  assert.equal(days.length, MAX_DAYS);
  assert.equal(days[0].day, dayOf(NOON + 3 * DAY));
});

test("a stored record that cannot be read is an error, never overwritten; bad entries in it are dropped", async () => {
  assert.throws(() => cleanPracticeRecord("junk"), /unreadable/);
  assert.throws(() => cleanPracticeRecord({ version: 2 }), /newer version/);
  const rec = cleanPracticeRecord({ version: 1, range: { held: { 60: 1, 5: 1, 70: -1, x: 2 }, passes: 3, takes: "2" },
    phrases: [{ key: "p" + "1".repeat(16), last: 5, days: [{ day: "2026-11-10", passes: 1, notes: 4, inTune: 2, onTime: 1, sung: 4, best: 2, extra: 1 }, { day: "soon" }] },
      { key: "bad", last: 1, days: [] }] });
  assert.deepEqual(rec.range, { held: { 60: 1 }, passes: 3, takes: 0 });
  assert.equal(rec.phrases.length, 1);
  assert.deepEqual(rec.phrases[0].days, [{ day: "2026-11-10", passes: 1, notes: 4, inTune: 2, onTime: 1, sung: 4, best: 2 }]);
  const kv = memoryKV(), store = createPracticeStore(kv);
  await kv.set(PRACTICE_KEY, "junk");
  await assert.rejects(store.addTake([{ m: 60, seconds: 1 }]), /unreadable/);
  assert.equal(await kv.get(PRACTICE_KEY), "junk");
  assert.throws(() => withPass(undefined, { key: "nope", summary: { notes: 1 } }, NOON), /key/);
});

test("a pass whose summary is missing a count is refused, so no day is saved that the next read would drop", () => {
  const key = "p" + "0".repeat(16), full = { notes: 4, sung: 3, inTune: 2, onTime: 1 };
  for (const k of ["sung", "inTune", "onTime"]) {
    const summary = { ...full };
    delete summary[k];
    assert.throws(() => withPass(undefined, { key, summary }, NOON), /scores/, k);
    assert.throws(() => withPass(undefined, { key, summary: { ...full, [k]: -1 } }, NOON), /scores/, k);
    assert.throws(() => withPass(undefined, { key, summary: { ...full, [k]: 1.5 } }, NOON), /scores/, k);
  }
  assert.throws(() => withPass(undefined, { key, summary: { ...full, inTune: 4 } }, NOON), /scores/);
  const rec = withPass(undefined, { key, summary: full }, NOON);
  assert.deepEqual(cleanPracticeRecord(JSON.parse(JSON.stringify(rec))), rec);
});

test("the store keeps passes and takes under the 'practice' key, and forgets them on request", async () => {
  assert.equal(PRACTICE_KEY, "practice");
  assert.throws(() => createPracticeStore(null), TypeError);
  let t = NOON;
  const kv = memoryKV(), store = createPracticeStore(kv, { now: () => t });
  const key = phraseKey(MELODY, SPAN), summary = { notes: 4, sung: 4, inTune: 2, missed: 0, onTime: 4, worst: null };
  await store.addPass({ key, label: phraseLabel(MELODY, SPAN), summary, held: [{ m: 50, from: 0, seconds: 0.7 }] });
  t += DAY;
  await store.addPass({ key, summary: { ...summary, inTune: 4 }, held: [{ m: 62, from: 0, seconds: 0.9 }] });
  await store.addTake([{ m: 45, from: 0, seconds: 2 }]);
  // A second store over the same storage (another tab, or after a reload) sees all of it.
  const again = await createPracticeStore(kv).get();
  assert.deepEqual(vocalRange(again), { low: 45, high: 62, passes: 2, takes: 1 });
  assert.equal(phraseHistory(again, key).days.length, 2);
  assert.equal(phraseHistory(again, key).label, "C4 D4 E4 F4 (4 notes)");
  await store.forget();
  assert.equal(vocalRange(await store.get()), null);
  assert.equal(phraseHistory(await store.get(), key), null);
});

test("a long recording is tracked in slices with the same readings as in one go", async () => {
  const x = sing(6, [{ m: 57, from: 0.5, to: 3 }, { m: 64, from: 3.5, to: 5.5 }]);
  let pauses = 0;
  const slices = await trackInSlices(x, RATE, { pause: async () => { pauses++; } });
  assert.deepEqual(slices, trackPass(x, RATE, 0));
  assert.ok(pauses >= 2, `${pauses} pauses`);
  assert.deepEqual(heldNotes(slices).map(h => h.m), [57, 64]);
});
