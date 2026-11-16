import test from "node:test";
import assert from "node:assert/strict";
import { linePoints, sampleLine, lineNotes, withLine } from "../drawline.js";

const C_MAJOR = { tonic: 0, mode: "major" };
const A_MINOR = { tonic: 9, mode: "minor" };

// A hand-drawn stroke: points every `dt` s through (t, m) corners, with a small wobble on the pitch.
function stroke(corners, { dt = 1 / 60, wobble = 0.3 } = {}) {
  const out = [];
  let k = 0;
  for (let i = 0; i < corners.length - 1; i++) {
    const [ta, ma] = corners[i], [tb, mb] = corners[i + 1];
    for (let t = ta; t < tb - 1e-9; t += dt) {
      const f = (t - ta) / (tb - ta);
      out.push({ t, m: ma + (mb - ma) * f + wobble * Math.sin(k++ * 1.7) });
    }
  }
  const [t, m] = corners.at(-1);
  out.push({ t, m });
  return out;
}
// A staircase: each [m, from, to] held flat, stepping straight to the next.
const stairs = steps => stroke(steps.flatMap(([m, a, b]) => [[a, m], [b - 0.001, m]]));

test("a drawn staircase gives those scale notes on the grid", () => {
  const notes = lineNotes(stairs([[60, 0, 1], [62, 1, 2], [64, 2, 2.5], [65, 2.5, 3.5]]), { bpm: 120, division: 4, key: C_MAJOR });
  assert.deepEqual(notes, [{ m: 60, t: 0, d: 1 }, { m: 62, t: 1, d: 1 }, { m: 64, t: 2, d: 0.5 }, { m: 65, t: 2.5, d: 1 }]);
});

test("every note is in the key and on the grid", () => {
  // Drawn between scale notes: 61.3 is nearer D than C sharp in C major, 66.4 nearer G than F sharp.
  const notes = lineNotes(stairs([[61.3, 0.03, 0.98], [66.4, 0.98, 2.04]]), { bpm: 100, division: 2, key: C_MAJOR });
  assert.deepEqual(notes.map(n => n.m), [62, 67]);
  const step = 60 / 100 / 2;
  for (const n of notes) {
    assert.ok(Math.abs(n.t / step - Math.round(n.t / step)) < 0.01, `start ${n.t} on the grid`);
    assert.ok(Math.abs((n.t + n.d) / step - Math.round((n.t + n.d) / step)) < 0.01, `end ${n.t + n.d} on the grid`);
  }
  // The same line in A minor: G sharp is not in the scale, so 68.4 reads as A.
  assert.deepEqual(lineNotes(stairs([[68.4, 0, 1]]), { bpm: 120, key: A_MINOR }).map(n => n.m), [69]);
});

test("a slide joins the note it settles on", () => {
  // Held on C, a quick slide up to G (through D, E and F), held on G.
  const notes = lineNotes(stroke([[0, 60], [1, 60], [1.2, 67], [2.5, 67]]), { bpm: 120, division: 4, key: C_MAJOR });
  assert.deepEqual(notes, [{ m: 60, t: 0, d: 1 }, { m: 67, t: 1, d: 1.5 }]);
});

test("a slow climb is a note for each step it holds", () => {
  // The same rise drawn slowly holds each scale note long enough to be a note of its own.
  const notes = lineNotes(stroke([[0, 60], [2, 67]], { wobble: 0 }), { bpm: 120, division: 4, key: C_MAJOR });
  assert.deepEqual(notes.map(n => n.m), [60, 62, 64, 65, 67]);
  for (let i = 1; i < notes.length; i++) assert.ok(Math.abs(notes[i - 1].t + notes[i - 1].d - notes[i].t) < 1e-6, "the notes touch");
});

test("a pitch held with a wobble stays one note", () => {
  const notes = lineNotes(stroke([[0.5, 64], [2.5, 64]], { wobble: 0.6 }), { bpm: 90, division: 4, key: C_MAJOR });
  assert.deepEqual(notes, [{ m: 64, t: 0.5, d: 2 }]);
});

test("drawing back over the line does not fold it", () => {
  const pts = [{ t: 0, m: 60 }, { t: 0.5, m: 60 }, { t: 0.3, m: 72 }, { t: 1, m: 60 }, { t: NaN, m: 60 }];
  assert.deepEqual(linePoints(pts), [{ t: 0, m: 60 }, { t: 0.5, m: 60 }, { t: 1, m: 60 }]);
  const s = sampleLine(pts, 0.25);
  assert.deepEqual([...s.t], [0, 0.25, 0.5, 0.75, 1]);
  assert.deepEqual([...s.m], [60, 60, 60, 60, 60]);
  assert.deepEqual(lineNotes(pts, { bpm: 120, key: C_MAJOR }), [{ m: 60, t: 0, d: 1 }]);
});

test("a line too short, no tempo or no key is refused", () => {
  assert.throws(() => lineNotes([{ t: 1, m: 60 }, { t: 1.02, m: 60 }], { bpm: 120, key: C_MAJOR }), /longer line/);
  assert.throws(() => lineNotes(stairs([[60, 0, 1]]), { bpm: 0, key: C_MAJOR }), /tempo/);
  assert.throws(() => lineNotes(stairs([[60, 0, 1]]), { bpm: 120, key: null }), /key/);
  assert.throws(() => lineNotes(stairs([[60, 0, 1]]), { bpm: 120, division: 3, key: C_MAJOR }), /grid/);
});

test("the drawn notes replace the notes in their span", () => {
  const melody = [{ m: 55, t: 0, d: 1.5 }, { m: 57, t: 1.5, d: 0.5 }, { m: 59, t: 2, d: 0.5 }, { m: 60, t: 3, d: 1 }];
  const drawn = [{ m: 64, t: 1, d: 1 }, { m: 65, t: 2, d: 0.5 }];
  const r = withLine(melody, drawn);
  assert.deepEqual(r.notes, [{ m: 55, t: 0, d: 1 }, { m: 64, t: 1, d: 1 }, { m: 65, t: 2, d: 0.5 }, { m: 60, t: 3, d: 1 }]);
  assert.deepEqual(r.indices, [1, 2]);
  assert.equal(r.replaced, 3);
  assert.equal(melody[0].d, 1.5, "the melody passed in is not changed");
  // Into an empty melody the line is the whole melody.
  assert.deepEqual(withLine([], drawn), { notes: drawn, indices: [0, 1], replaced: 0 });
  assert.throws(() => withLine(melody, []), /no notes/);
});
