import test from "node:test";
import assert from "node:assert/strict";
import {
  frameTime, pitchContour, noteCentre, scalePitchClasses, snapToScale, stepInScale, snapNotesToScale,
  previewCorrection, contourRange, resizeNote, mergeFragments, sungNotes, SCALES, KEY_NAMES, CONTOUR_BINS, MIN_TARGET_SECONDS,
} from "../contour.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);

// One Basic Pitch contour frame (264 bins, 3 per semitone; bin 1 is MIDI 21) peaking at `midi`.
function frame(midi, peak = 0.9) {
  const f = new Array(CONTOUR_BINS).fill(0);
  if (midi == null) return f;
  const bin = (midi - 21) * 3 + 1, lo = Math.floor(bin), frac = bin - lo;
  // Split the peak between two neighbouring bins so the sub-bin position is recoverable.
  f[lo] = peak * (1 - frac); f[lo + 1] = peak * frac;
  if (lo - 1 >= 0) f[lo - 1] = 0.05;
  return f;
}

test("frame times follow Basic Pitch's own frame-to-time mapping", () => {
  close(frameTime(0), 0);
  close(frameTime(86), 86 * 256 / 22050);
  // Every 172 frames (one 2 s model window) the bundle subtracts its window-overlap correction.
  const hop = 256 / 22050, correction = hop * (172 - (22050 * 2 - 256) / 256) + 0.0018;
  close(frameTime(172), 172 * hop - correction);
  close(frameTime(400), 400 * hop - 2 * correction);
});

test("pitch contour follows the salience peak with sub-semitone precision and marks quiet frames unvoiced", () => {
  const c = pitchContour([frame(60), frame(60.5), frame(null), frame(69.25, 0.2), frame(72)], { duration: 10 });
  assert.equal(c.t.length, 5);
  close(c.m[0], 60, 0.05);
  close(c.m[1], 60.5, 0.05);
  assert.ok(Number.isNaN(c.m[2]), "silent frame is unvoiced");
  assert.ok(Number.isNaN(c.m[3]), "frame below the salience threshold is unvoiced");
  close(c.m[4], 72, 0.05);
  close(c.t[1], frameTime(1));
});

test("pitch contour drops frames past the end of the recording", () => {
  const frames = Array.from({ length: 100 }, () => frame(60));
  const c = pitchContour(frames, { duration: 0.5 });
  assert.ok(c.t.length < 100 && c.t.at(-1) <= 0.5);
});

test("note centre is the mean of frames near the median, ignoring octave errors and unvoiced frames", () => {
  const t = Float32Array.from({ length: 10 }, (_, i) => i * 0.01);
  const m = Float32Array.from([60.2, 60.4, NaN, 60.2, 72.2, 60.4, 60.2, 60.4, 60.2, 60.4]);
  close(noteCentre({ t, m }, { t: 0, d: 0.1 }), 60.3, 1e-5);
  assert.equal(noteCentre({ t, m }, { t: 0.5, d: 0.2 }), null);
  assert.equal(noteCentre(null, { t: 0, d: 1 }), null);
});

test("scales give pitch classes from the chosen key", () => {
  assert.deepEqual(scalePitchClasses(0, "major"), [0, 2, 4, 5, 7, 9, 11]);
  assert.deepEqual(scalePitchClasses(2, "major"), [1, 2, 4, 6, 7, 9, 11]);
  assert.deepEqual(scalePitchClasses(9, "minor"), [0, 2, 4, 5, 7, 9, 11]);
  assert.deepEqual(scalePitchClasses(5, "chromatic"), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
  assert.equal(KEY_NAMES.length, 12);
  for (const name of Object.keys(SCALES)) assert.ok(scalePitchClasses(0, name).includes(0));
  assert.throws(() => scalePitchClasses(0, "lydian-dominant"), /Unknown scale/);
  assert.throws(() => scalePitchClasses(12, "major"), /key/);
});

test("snapping picks the nearest in-scale pitch and breaks ties towards the sung pitch", () => {
  const cMajor = scalePitchClasses(0, "major");
  assert.equal(snapToScale(64, cMajor), 64);
  assert.equal(snapToScale(66, cMajor), 65); // F# -> F or G: tie, no sung pitch -> lower
  assert.equal(snapToScale(66, cMajor, 66.3), 67); // sung sharp of F# -> G
  assert.equal(snapToScale(66, cMajor, 65.8), 65);
  assert.equal(snapToScale(97, cMajor), 96);
  assert.equal(snapToScale(35, cMajor), 36);
});

test("stepping moves by scale degree and stays in range", () => {
  const cMajor = scalePitchClasses(0, "major");
  assert.equal(stepInScale(64, cMajor, 1), 65);
  assert.equal(stepInScale(65, cMajor, 1), 67);
  assert.equal(stepInScale(66, cMajor, -1), 65); // off-scale start goes to the next scale note down
  assert.equal(stepInScale(66, cMajor, 1), 67);
  assert.equal(stepInScale(96, cMajor, 1), 96);
  assert.equal(stepInScale(36, cMajor, -1), 36);
  assert.equal(stepInScale(60, scalePitchClasses(0, "chromatic"), 1), 61);
});

test("snapping every note to a key reports only the notes that moved", () => {
  const notes = [{ m: 61, t: 0, d: 0.5 }, { m: 62, t: 0.5, d: 0.5 }, { m: 66, t: 1, d: 0.5, c: 0.4 }];
  const t = Float32Array.from({ length: 150 }, (_, i) => i * 0.01);
  const m = Float32Array.from(t, x => (x >= 1 ? 66.4 : x < 0.5 ? 60.9 : 62));
  const { notes: out, moved } = snapNotesToScale(notes, scalePitchClasses(0, "major"), { t, m });
  assert.deepEqual(out.map(n => n.m), [60, 62, 67]);
  assert.equal(moved, 2);
  assert.equal(out[2].c, 0.4, "other fields are kept");
  assert.equal(notes[0].m, 61, "input is not mutated");
});

test("correction preview matches the server formula: note shift, scaled residual, strength", () => {
  const t = Float32Array.from({ length: 200 }, (_, i) => i * 0.01);
  const wobble = i => 0.25 * Math.sin(2 * Math.PI * 5.5 * i * 0.01);
  const m = Float32Array.from(t, (_, i) => (i < 100 ? 69.4 + wobble(i) : NaN));
  const notes = [{ m: 69, t: 0, d: 1 }];
  const centre = noteCentre({ t, m }, notes[0]);
  const flat = previewCorrection({ t, m }, notes, { strength: 1, vibrato: 0 });
  for (let i = 0; i < 100; i++) close(flat[i], 69, 1e-5);
  assert.ok(Number.isNaN(flat[150]), "unvoiced stays unvoiced");
  const kept = previewCorrection({ t, m }, notes, { strength: 1, vibrato: 1 });
  for (let i = 0; i < 100; i++) close(kept[i], 69 + (m[i] - centre), 1e-5);
  const half = previewCorrection({ t, m }, notes, { strength: 0.5, vibrato: 1 });
  for (let i = 0; i < 100; i++) close(half[i], m[i] + 0.5 * (69 - centre), 1e-5);
  // Outside every note the sung pitch is unchanged.
  const outside = previewCorrection({ t, m }, [{ m: 69, t: 0.5, d: 0.2 }], { strength: 1, vibrato: 0 });
  close(outside[10], m[10]);
});

test("correction preview limits stray frames to 2.5 semitones and the note shift to an octave", () => {
  const t = Float32Array.from({ length: 10 }, (_, i) => i * 0.01);
  const m = Float32Array.from(t, (_, i) => (i === 4 ? 81 : 69));
  const out = previewCorrection({ t, m }, [{ m: 69, t: 0, d: 0.1 }], { strength: 1, vibrato: 0 });
  close(out[4], 78.5);
  const far = previewCorrection({ t, m: new Float32Array(10).fill(60) }, [{ m: 90, t: 0, d: 0.1 }], { strength: 1, vibrato: 0 });
  close(far[0], 72);
});

test("display range spans targets and sung pitch with a margin, inside 36..96", () => {
  const t = Float32Array.from([0, 0.1]), m = Float32Array.from([58.6, NaN]);
  assert.deepEqual(contourRange([{ m: 62, t: 0, d: 1 }, { m: 67, t: 1, d: 1 }], { t, m }), { lo: 56, hi: 69 });
  assert.deepEqual(contourRange([{ m: 37, t: 0, d: 1 }], null), { lo: 36, hi: 39 });
  const wide = contourRange([{ m: 62, t: 0, d: 1 }], { t, m: Float32Array.from([20, 110]) });
  assert.ok(wide.lo >= 36 && wide.hi <= 96);
});

test("resizing a note edge keeps a minimum length, stays in the recording and off its neighbours", () => {
  const notes = [{ m: 60, t: 0, d: 1 }, { m: 62, t: 1.2, d: 1 }, { m: 64, t: 2.4, d: 0.5 }];
  assert.deepEqual(resizeNote(notes, 1, "start", 0.9, 5), { t: 1, d: 1.2 }); // stops at the previous note's end
  assert.deepEqual(resizeNote(notes, 1, "start", 2.5, 5), { t: +(2.2 - MIN_TARGET_SECONDS).toFixed(3), d: MIN_TARGET_SECONDS });
  assert.deepEqual(resizeNote(notes, 1, "end", 3, 5), { t: 1.2, d: 1.2 }); // stops at the next note's start
  assert.deepEqual(resizeNote(notes, 2, "end", 9, 5), { t: 2.4, d: 2.6 }); // stops at the end of the take
  assert.deepEqual(resizeNote(notes, 0, "start", -1, 5), { t: 0, d: 1 });
  // Notes the detector already overlapped are not forced apart.
  const overlapping = [{ m: 60, t: 0, d: 1.5 }, { m: 62, t: 1, d: 1 }];
  assert.deepEqual(resizeNote(overlapping, 1, "start", 0.8, 5), { t: 0.8, d: 1.2 });
});

test("correction preview reproduces the server's _target_notes on the shared fixture", async () => {
  const { readFile } = await import("node:fs/promises");
  const fx = JSON.parse(await readFile(new URL("./fixtures/target-correction.json", import.meta.url), "utf8"));
  const contour = { t: Float64Array.from(fx.t), m: Float32Array.from(fx.m, v => (v === null ? NaN : v)) };
  assert.equal(fx.cases.length, 4);
  for (const c of fx.cases) {
    const out = previewCorrection(contour, fx.notes, { strength: c.strength, vibrato: c.vibrato });
    c.corrected.forEach((want, i) => {
      if (want === null) assert.ok(Number.isNaN(out[i]), `frame ${i} should be unvoiced`);
      else assert.ok(Math.abs(out[i] - want) < 1e-4, `strength ${c.strength} vibrato ${c.vibrato} frame ${i}: ${out[i]} != ${want}`);
    });
  }
});

test("vibrato fragments merge back into one target per sung note; distinct notes stay apart", () => {
  // A sharp C4 with vibrato that the detector split into C4/C#4/C4 pieces, then a real E4.
  const t = Float64Array.from({ length: 200 }, (_, i) => i * 0.01);
  const m = Float32Array.from(t, x => (x < 0.95 ? 60.35 + 0.25 * Math.sin(2 * Math.PI * 5.5 * x) : x >= 1.0 ? 64.1 : NaN));
  const notes = [
    { m: 60, t: 0, d: 0.3, c: 0.8 }, { m: 61, t: 0.32, d: 0.1, c: 0.4 }, { m: 60, t: 0.45, d: 0.5, c: 0.9 },
    { m: 64, t: 1.0, d: 0.5, c: 0.7 },
  ];
  const out = mergeFragments(notes, { t, m });
  assert.equal(out.length, 2);
  assert.deepEqual({ m: out[0].m, t: out[0].t, d: out[0].d }, { m: 60, t: 0, d: 0.95 });
  close(out[0].c, (0.8 * 0.3 + 0.4 * 0.1 + 0.9 * 0.5) / 0.9, 0.006);
  assert.deepEqual(out[1], notes[3]);
  // A semitone step is a new note, and so is a same-pitch note after a real breath.
  const step = [{ m: 60, t: 0, d: 0.4 }, { m: 61, t: 0.42, d: 0.4 }];
  const steps = Float32Array.from(t, x => (x < 0.41 ? 60 : 61));
  assert.equal(mergeFragments(step, { t, m: steps }).length, 2);
  assert.equal(mergeFragments([{ m: 60, t: 0, d: 0.3 }, { m: 60, t: 0.5, d: 0.3 }], { t, m: new Float32Array(200).fill(60) }).length, 2);
  // Without a contour, only same-pitch neighbours merge.
  assert.equal(mergeFragments([{ m: 60, t: 0, d: 0.3 }, { m: 60, t: 0.33, d: 0.3 }, { m: 61, t: 0.65, d: 0.3 }], null).length, 2);
  assert.equal(notes.length, 4, "input is not mutated");
});

test("a hummed note with wide vibrato and drift merges whole, though its pieces' centres span more than `within`", () => {
  // TRANS.1: what Basic Pitch made of a 1.4 s hummed A3 with 40-cent vibrato at 5.5 Hz and 25 cents
  // of slow drift: pieces about half a vibrato cycle long, each centred where its half-cycle sat
  // (56.6..57.3, a 0.77 semitone spread), then a C4.
  const t = Float64Array.from({ length: 300 }, (_, i) => i * 0.01);
  const m = Float32Array.from(t, x => (x < 1.4 ? 57 + 0.4 * Math.sin(2 * Math.PI * 5.5 * x) + 0.25 * Math.sin(2 * Math.PI * 0.7 * x) : x < 1.52 ? NaN : 60));
  const pieces = [];
  for (let s = 0; s + 0.09 <= 1.4; s += 0.09) pieces.push({ m: 57, t: Math.round(s * 1000) / 1000, d: 0.09 });
  for (const p of pieces) p.m = Math.round(m[Math.round((p.t + 0.045) * 100)]);
  assert.ok(new Set(pieces.map(p => p.m)).size > 1, "the pieces are split across neighbouring pitches");
  const out = mergeFragments([...pieces, { m: 60, t: 1.52, d: 1 }], { t, m });
  assert.deepEqual(out.map(n => n.m), [57, 60]);
  assert.deepEqual([out[0].t, out[0].d], [0, pieces.at(-1).t + 0.09]);
});

test("a wider `gap` joins pieces across a short dropout of the sung line, not across a breath", () => {
  // TRANS.1: room noise drops a held C4's contour for 90 ms; a real breath before the repeat is 250 ms.
  const t = Float64Array.from({ length: 300 }, (_, i) => i * 0.01);
  const m = Float32Array.from(t, x => ((x >= 0.5 && x < 0.59) || (x >= 1.2 && x < 1.45) ? NaN : 60));
  const notes = [{ m: 60, t: 0, d: 0.52 }, { m: 60, t: 0.58, d: 0.62 }, { m: 60, t: 1.45, d: 0.5 }];
  assert.equal(mergeFragments(notes, { t, m }).length, 3, "by default an 80 ms dropout separates notes");
  assert.deepEqual(mergeFragments(notes, { t, m }, { gap: 0.15 }).map(n => [n.t, n.d]), [[0, 1.2], [1.45, 0.5]]);
});

test("merging tolerates the detector's millisecond overlaps and absorbs contained ghost notes", () => {
  const t = Float64Array.from({ length: 200 }, (_, i) => i * 0.01);
  const m = new Float32Array(200).fill(67.2);
  const out = mergeFragments([{ m: 67, t: 0, d: 0.5 }, { m: 68, t: 0.499, d: 0.4 }, { m: 67, t: 0.6, d: 0.1 }, { m: 67, t: 0.9, d: 0.3 }], { t, m });
  assert.deepEqual(out.map(n => [n.m, n.t, n.d]), [[67, 0, 1.2]]);
});

test("merging never bridges a silence, even when the detector carried a note across it", () => {
  // F4 sung 35 cents flat, 100 ms of silence, then E4 sung 10 cents sharp: centres only 55 cents apart.
  const t = Float64Array.from({ length: 200 }, (_, i) => i * 0.01);
  const m = Float32Array.from(t, x => (x < 0.8 ? 64.65 : x < 0.9 ? NaN : 64.1));
  const out = mergeFragments([{ m: 65, t: 0, d: 0.9 }, { m: 64, t: 0.9, d: 0.8 }], { t, m });
  assert.deepEqual(out.map(n => n.m), [65, 64]);
});


// TRANS.2: a sung line sampled on the model's frames for `seconds`, its pitch from `pitchAt(t)`
// (NaN when nothing is sung), and the note activation it would carry (`actAt(t)`).
function sung(seconds, pitchAt) {
  const t = [], m = [];
  for (let r = 0; frameTime(r) < seconds; r++) { t.push(frameTime(r)); m.push(pitchAt(frameTime(r))); }
  return { t: Float64Array.from(t), m: Float32Array.from(m) };
}
const vibrato = (t, cents = 40) => cents / 100 * Math.sin(2 * Math.PI * 5.5 * t);
const loud = () => 0.6;

test("a held note with vibrato and drift is one note as long as it is held (TRANS.2)", () => {
  const line = sung(2.5, t => (t >= 0.2 && t < 2.2 ? 57 + vibrato(t) + 0.25 * Math.sin(2 * Math.PI * 0.7 * t) : NaN));
  const notes = sungNotes(line, loud);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].m, 57);
  close(notes[0].t, 0.2, 0.02);
  close(notes[0].t + notes[0].d, 2.2, 0.02);
});

test("a legato line splits where its pitch steps to a new note, not on vibrato", () => {
  const line = sung(1.7, t => (t < 1.5 ? [60, 62, 64][Math.floor(t / 0.5)] + vibrato(t) : NaN));
  const notes = sungNotes(line, loud);
  assert.deepEqual(notes.map(n => n.m), [60, 62, 64]);
  close(notes[1].t, 0.5, 0.06);
  close(notes[2].t, 1.0, 0.06);
});

test("a slide joins the note it settles on, whatever its length", () => {
  for (const glide of [0.12, 0.25]) {
    // 44 held, then a slide of `glide` s up to 49, held.
    const line = sung(1.6, t => (t < 0.6 ? 44 : t < 0.6 + glide ? 44 + 5 * (t - 0.6) / glide : t < 1.4 ? 49 : NaN) + vibrato(t, 20));
    const notes = sungNotes(line, loud);
    assert.deepEqual(notes.map(n => n.m), [44, 49], `slide of ${glide} s`);
    assert.ok(notes[1].t < 0.6 + glide / 2, `the slide is part of the note it reaches (${notes[1].t})`);
    close(notes[1].t + notes[1].d, 1.4, 0.02);
  }
  // A fall at the end of a phrase stays with the note it falls from.
  const fall = sungNotes(sung(1.2, t => (t < 0.7 ? 60 : t < 0.9 ? 60 - 6 * (t - 0.7) / 0.2 : NaN)), loud);
  assert.deepEqual(fall.map(n => n.m), [60]);
  close(fall[0].t + fall[0].d, 0.9, 0.02);
});

test("room noise in a breath is not a note, and does not stretch the notes around it", () => {
  // Two hummed notes 120 ms apart; in the breath the line reads the fan noise at 45 with little activation.
  const pitchAt = t => (t < 0.8 ? 57 + vibrato(t) : t < 0.92 ? 45 : t < 1.8 ? 60 + vibrato(t) : NaN);
  const line = sung(2, pitchAt);
  const activation = r => (line.t[r] >= 0.8 && line.t[r] < 0.92 ? 0.15 : 0.6);
  const notes = sungNotes(line, activation);
  assert.deepEqual(notes.map(n => n.m), [57, 60]);
  close(notes[0].t + notes[0].d, 0.8, 0.02);
  close(notes[1].t, 0.92, 0.02);
  // Noise alone gives no notes.
  assert.deepEqual(sungNotes(sung(1, () => 45), () => 0.15), []);
});

test("a breath separates two notes of one pitch; a dropout shorter than `gap` does not", () => {
  const twice = breath => sung(1.6, t => (t < 0.5 || (t >= 0.5 + breath && t < 1 + breath) ? 60 + vibrato(t) : NaN));
  assert.equal(sungNotes(twice(0.25), loud).length, 2);
  const joined = sungNotes(twice(0.1), loud);
  assert.equal(joined.length, 1);
  close(joined[0].d, 1.1, 0.02);
});

test("a breath whose noise reads at the sung pitch still separates two notes of that pitch", () => {
  // The line stays at 60 through a 500 ms breath; only the activation shows nothing is sung there.
  const line = sung(1.8, t => 60 + vibrato(t));
  const quietFrom = (a, b) => r => (line.t[r] >= a && line.t[r] < b ? 0.1 : 0.6);
  const notes = sungNotes(line, quietFrom(0.8, 1.3));
  assert.deepEqual(notes.map(n => n.m), [60, 60]);
  close(notes[0].t + notes[0].d, 0.8, 0.02);
  close(notes[1].t, 1.3, 0.02);
  // A dip in activation shorter than `gap` is not a breath.
  assert.equal(sungNotes(line, quietFrom(0.8, 0.9)).length, 1);
});

test("the melody options of pitchContour ignore the noise bins and prefer a strong subharmonic", () => {
  // Room noise peaks in the lowest bins; a soft hum at MIDI 50 is below it.
  const noisy = frame(50, 0.2); noisy[0] = 0.25;
  assert.ok(Number.isNaN(pitchContour([noisy]).m[0]), "below VOICED_SALIENCE the editor's line is unvoiced");
  assert.ok(pitchContour([noisy], { threshold: 0.15 }).m[0] < 22, "without `lowest` the noise bin wins");
  close(pitchContour([noisy], { threshold: 0.15, lowest: 36 }).m[0], 50, 0.1);
  // The 3rd harmonic of MIDI 42 (19 semitones up) reads loudest, its fundamental nearly as loud.
  const harmonic = frame(61, 0.24);
  const fundamental = frame(42, 0.2);
  const both = harmonic.map((v, b) => Math.max(v, fundamental[b]));
  close(pitchContour([both], { threshold: 0.15, lowest: 36, subharmonics: true }).m[0], 42, 0.1);
  close(pitchContour([both], { threshold: 0.15, lowest: 36 }).m[0], 61, 0.1);
  // A weak bin below a strong note is not taken for its fundamental.
  const clear = frame(61, 0.6).map((v, b) => Math.max(v, frame(42, 0.2)[b]));
  close(pitchContour([clear], { threshold: 0.15, lowest: 36, subharmonics: true }).m[0], 61, 0.1);
});
