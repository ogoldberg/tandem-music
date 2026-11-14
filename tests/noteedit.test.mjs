import test from "node:test";
import assert from "node:assert/strict";
import {
  keyPitchClasses, notesInBox, allIndices, toggleIndex, snapTime, moveNotes, resizeNote, lengthenNotes,
  drawNote, deleteNotes, shiftOctave, nextInScale, stepInKey, MIN_DURATION,
  shiftSemitones, shiftInKey, duplicateToVoice, VOICE_INTERVALS,
} from "../noteedit.js";

const n = (m, t, d = 0.5) => ({ m, t, d });
const MELODY = [n(60, 0), n(64, 0.5), n(67, 1), n(61, 1.5)];
const C_MAJOR = { tonic: 0, mode: "major" }, A_MINOR = { tonic: 9, mode: "minor" };

test("keyPitchClasses gives the major and natural minor scales", () => {
  assert.deepEqual(keyPitchClasses(C_MAJOR), [0, 2, 4, 5, 7, 9, 11]);
  assert.deepEqual(keyPitchClasses(A_MINOR), [0, 2, 4, 5, 7, 9, 11]);
  assert.deepEqual(keyPitchClasses({ tonic: 2, mode: "minor" }), [0, 2, 4, 5, 7, 9, 10]);
  assert.throws(() => keyPitchClasses(null), /Choose a key/);
  assert.throws(() => keyPitchClasses({ tonic: 12, mode: "major" }), /Choose a key/);
});

test("notesInBox picks notes overlapping the time range within the pitch range, either corner first", () => {
  assert.deepEqual(notesInBox(MELODY, { t0: 0.4, t1: 1.1, m0: 62, m1: 70 }), [1, 2]);
  assert.deepEqual(notesInBox(MELODY, { t0: 1.1, t1: 0.4, m0: 70, m1: 62 }), [1, 2]);
  assert.deepEqual(notesInBox(MELODY, { t0: 3, t1: 4, m0: 0, m1: 127 }), []);
});

test("allIndices and toggleIndex", () => {
  assert.deepEqual(allIndices(MELODY), [0, 1, 2, 3]);
  assert.deepEqual(toggleIndex([2, 0], 1), [0, 1, 2]);
  assert.deepEqual(toggleIndex([0, 1, 2], 1), [0, 2]);
});

test("snapTime rounds to the sixteenth grid at the tempo and never below zero", () => {
  assert.equal(snapTime(0.13, 120), 0.125);
  assert.equal(snapTime(0.2, 120), 0.25);
  assert.equal(snapTime(-0.3, 120), 0);
  assert.equal(snapTime(0.7, 120, 1), 0.5);
});

test("moveNotes shifts only the selection, in time and pitch, without changing the input", () => {
  const before = JSON.stringify(MELODY);
  const out = moveNotes(MELODY, [1, 2], { dt: 0.25, dm: 2 });
  assert.deepEqual(out, [n(60, 0), n(66, 0.75), n(69, 1.25), n(61, 1.5)]);
  assert.equal(JSON.stringify(MELODY), before);
});

test("moveNotes stops at zero and at the MIDI range, keeping the notes' spacing", () => {
  assert.deepEqual(moveNotes(MELODY, [1, 2], { dt: -2 }).slice(1, 3), [n(64, 0), n(67, 0.5)]);
  assert.deepEqual(moveNotes([n(120, 0), n(125, 1)], [0, 1], { dm: 9 }), [n(122, 0), n(127, 1)]);
  assert.deepEqual(moveNotes([n(3, 0)], [0], { dm: -9 }), [n(0, 0)]);
});

test("resizeNote moves one edge and keeps the other", () => {
  assert.deepEqual(resizeNote(MELODY, 1, "end", 1.25)[1], n(64, 0.5, 0.75));
  assert.deepEqual(resizeNote(MELODY, 1, "start", 0.25)[1], n(64, 0.25, 0.75));
  assert.deepEqual(resizeNote(MELODY, 1, "end", 0.1)[1], n(64, 0.5, MIN_DURATION));
  assert.deepEqual(resizeNote(MELODY, 1, "start", 5)[1], n(64, 0.95, MIN_DURATION));
  assert.deepEqual(resizeNote(MELODY, 1, "start", -1)[1], n(64, 0, 1));
  // A note shorter than MIN_DURATION at zero (the MIDI recorder keeps 20 ms notes) never starts before zero.
  for (const d of [0.02, 0.03]) for (const at of [0, -1, 0.01]) {
    const out = resizeNote([n(60, 0, d)], 0, "start", at)[0];
    assert.deepEqual(out, n(60, 0, MIN_DURATION));
  }
  assert.throws(() => resizeNote(MELODY, 9, "end", 1), /out of date/);
});

test("lengthenNotes changes the selected lengths, never below the minimum", () => {
  assert.deepEqual(lengthenNotes(MELODY, [0, 3], 0.125).map(x => x.d), [0.625, 0.5, 0.5, 0.625]);
  assert.deepEqual(lengthenNotes(MELODY, [0], -1)[0].d, MIN_DURATION);
});

test("drawNote appends a note where it is placed; deleteNotes removes the selection", () => {
  const drawn = drawNote(MELODY, { m: 72, t: 0.25, d: 0.5 });
  assert.equal(drawn.length, 5);
  assert.deepEqual(drawn[4], n(72, 0.25));
  assert.throws(() => drawNote(MELODY, { m: 128, t: 0, d: 1 }), /MIDI range/);
  assert.deepEqual(deleteNotes(MELODY, [0, 2]), [n(64, 0.5), n(61, 1.5)]);
  assert.throws(() => deleteNotes(MELODY, []), /Select a note/);
});

test("shiftOctave moves the selection by 12 and refuses to leave the MIDI range", () => {
  assert.deepEqual(shiftOctave(MELODY, [0, 2], 1).map(x => x.m), [72, 64, 79, 61]);
  assert.deepEqual(shiftOctave(MELODY, allIndices(MELODY), -1).map(x => x.m), [48, 52, 55, 49]);
  assert.throws(() => shiftOctave([n(120, 0)], [0], 1), /outside the MIDI range/);
});

test("nextInScale finds the next scale pitch in either direction", () => {
  const pcs = keyPitchClasses(C_MAJOR);
  assert.equal(nextInScale(60, pcs, 1), 62);
  assert.equal(nextInScale(64, pcs, 1), 65);
  assert.equal(nextInScale(61, pcs, -1), 60);
  assert.equal(nextInScale(127, pcs, 1), null);
});

test("stepInKey keeps every shifted note in the scale, in both directions and every key", () => {
  const chromatic = Array.from({ length: 24 }, (_, i) => n(48 + i, i * 0.5));
  for (const mode of ["major", "minor"]) {
    for (let tonic = 0; tonic < 12; tonic++) {
      const key = { tonic, mode }, pcs = keyPitchClasses(key);
      for (const dir of [1, -1]) {
        const out = stepInKey(chromatic, allIndices(chromatic), key, dir);
        out.forEach((x, i) => {
          assert.ok(pcs.includes(x.m % 12), `${x.m} not in ${tonic} ${mode}`);
          assert.ok(dir > 0 ? x.m > chromatic[i].m && x.m - chromatic[i].m <= 2 : x.m < chromatic[i].m && chromatic[i].m - x.m <= 2);
        });
      }
    }
  }
});

test("stepInKey moves a scale note to the next scale note and leaves the rest alone", () => {
  assert.deepEqual(stepInKey(MELODY, [0, 1, 2], C_MAJOR, 1).map(x => x.m), [62, 65, 69, 61]);
  assert.deepEqual(stepInKey(MELODY, [3], C_MAJOR, 1).map(x => x.m), [60, 64, 67, 62]);
  assert.deepEqual(stepInKey(MELODY, [3], C_MAJOR, -1).map(x => x.m), [60, 64, 67, 60]);
  assert.throws(() => stepInKey([n(127, 0)], [0], C_MAJOR, 1), /outside the MIDI range/);
  assert.throws(() => stepInKey(MELODY, [0], null, 1), /Choose a key/);
});

// HARM.1: the harmony voice.
test("shiftSemitones moves the selection by any number of semitones and refuses to leave the MIDI range", () => {
  const out = shiftSemitones(MELODY, [0, 2], 3);
  assert.deepEqual(out.map(x => x.m), [63, 64, 70, 61]);
  assert.deepEqual(MELODY.map(x => x.m), [60, 64, 67, 61]);
  assert.deepEqual(shiftSemitones(MELODY, [1], -1).map(x => x.m), [60, 63, 67, 61]);
  assert.throws(() => shiftSemitones([n(126, 0)], [0], 2), /MIDI range/);
  assert.throws(() => shiftSemitones([n(1, 0)], [0], -2), /MIDI range/);
  assert.throws(() => shiftSemitones(MELODY, [], 1), /Select a note/);
});

test("shiftInKey moves scale notes by scale steps: two steps up is a third in the key", () => {
  const scale = [n(60, 0), n(62, 1), n(64, 2), n(65, 3), n(67, 4), n(69, 5), n(71, 6)];
  // C D E F G A B a third up in C major: E F G A B C D.
  assert.deepEqual(shiftInKey(scale, allIndices(scale), C_MAJOR, 2).map(x => x.m), [64, 65, 67, 69, 71, 72, 74]);
  // A third down: A B C D E F G.
  assert.deepEqual(shiftInKey(scale, allIndices(scale), C_MAJOR, -2).map(x => x.m), [57, 59, 60, 62, 64, 65, 67]);
  // A sixth down is five steps.
  assert.deepEqual(shiftInKey([n(64, 0)], [0], C_MAJOR, -5).map(x => x.m), [55]);
  assert.deepEqual(shiftInKey(scale, [0], C_MAJOR, 0), scale);
  for (const tonic of [0, 3, 7, 10]) for (const mode of ["major", "minor"]) {
    const key = { tonic, mode }, pcs = keyPitchClasses(key);
    const out = shiftInKey(MELODY, allIndices(MELODY), key, 2);
    assert.ok(out.every(x => pcs.includes(x.m % 12)), `every note in ${tonic} ${mode}`);
  }
  assert.throws(() => shiftInKey([n(126, 0)], [0], C_MAJOR, 2), /MIDI range/);
  assert.throws(() => shiftInKey(MELODY, [0], null, 2), /Choose a key/);
});

test("duplicateToVoice copies the selection, or the whole melody, into the voice, shifted, and selects the copies", () => {
  const melody = [n(60, 0), n(62, 0.5), n(64, 1), n(65, 1.5)];
  const all = duplicateToVoice(melody, [], [], VOICE_INTERVALS.third_up, C_MAJOR);
  assert.deepEqual(all.notes.map(x => x.m), [64, 65, 67, 69]);
  assert.deepEqual(all.notes.map(x => [x.t, x.d]), melody.map(x => [x.t, x.d]));
  assert.deepEqual(all.indices, [0, 1, 2, 3]);
  assert.deepEqual(melody.map(x => x.m), [60, 62, 64, 65], "the melody is not changed");
  // A selection appends to what the voice already holds, and the copies are the new selection.
  const some = duplicateToVoice(melody, [3, 1], all.notes, VOICE_INTERVALS.octave_down);
  assert.deepEqual(some.notes.slice(4).map(x => [x.m, x.t]), [[50, 0.5], [53, 1.5]]);
  assert.deepEqual(some.indices, [4, 5]);
  assert.equal(duplicateToVoice(melody, [0], [], VOICE_INTERVALS.same).notes[0].m, 60);
  assert.equal(duplicateToVoice(melody, [0], [], VOICE_INTERVALS.sixth_down, C_MAJOR).notes[0].m, 52);
  assert.equal(duplicateToVoice(melody, [0], [], VOICE_INTERVALS.octave_up).notes[0].m, 72);
});

test("duplicateToVoice does not add a note the voice already has, and says so when nothing is new", () => {
  const melody = [n(60, 0), n(62, 0.5)];
  const once = duplicateToVoice(melody, [], [], VOICE_INTERVALS.third_up, C_MAJOR);
  assert.throws(() => duplicateToVoice(melody, [], once.notes, VOICE_INTERVALS.third_up, C_MAJOR), /already has/);
  const more = duplicateToVoice([...melody, n(64, 1)], [], once.notes, VOICE_INTERVALS.third_up, C_MAJOR);
  assert.deepEqual(more.notes.map(x => x.m), [64, 65, 67]);
  assert.deepEqual(more.indices, [2]);
  assert.throws(() => duplicateToVoice([], [], [], VOICE_INTERVALS.same), /no notes/i);
  assert.throws(() => duplicateToVoice(melody, [], [], VOICE_INTERVALS.third_up, null), /Choose a key/);
  assert.throws(() => duplicateToVoice(melody, [], [], { steps: 1, semitones: 2 }), /Unknown interval/);
});
