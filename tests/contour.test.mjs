import test from "node:test";
import assert from "node:assert/strict";
import {
  frameTime, pitchContour, noteCentre, scalePitchClasses, snapToScale, stepInScale, snapNotesToScale,
  previewCorrection, contourRange, resizeNote, mergeFragments, SCALES, KEY_NAMES, CONTOUR_BINS, MIN_TARGET_SECONDS,
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
