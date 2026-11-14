import test from "node:test";
import assert from "node:assert/strict";
import { MIN_LOOP, loopRegion, createPlan, songTime, clipNotes, clipHits, clipProject, timelineEnd } from "../playhead.js";

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("loopRegion orders the ends, keeps them inside the song and refuses a loop too short to hear", () => {
  assert.deepEqual(loopRegion(3, 1, 10), { start: 1, end: 3 });
  assert.deepEqual(loopRegion(-2, 4, 10), { start: 0, end: 4 });
  assert.deepEqual(loopRegion(8, 14, 10), { start: 8, end: 10 });
  assert.equal(loopRegion(2, 2 + MIN_LOOP / 2, 10), null);
  assert.equal(loopRegion(NaN, 2, 10), null);
});

test("without a loop the plan is one segment from the start to the end of the song", () => {
  const plan = createPlan({ from: 2.5 });
  assert.deepEqual(plan.next(), { at: 0, from: 2.5, to: Infinity });
  assert.equal(plan.next(), null);
});

test("a loop plays from the start point to the loop's end, then the loop again and again", () => {
  const plan = createPlan({ from: 0.5, loop: { start: 1, end: 3 } });
  assert.deepEqual(plan.next(), { at: 0, from: 0.5, to: 3 });
  assert.deepEqual(plan.next(), { at: 2.5, from: 1, to: 3 });
  assert.deepEqual(plan.next(), { at: 4.5, from: 1, to: 3 });
  assert.deepEqual(plan.next(), { at: 6.5, from: 1, to: 3 });
});

test("starting inside the loop plays to its end before wrapping; starting after it ignores it", () => {
  const inside = createPlan({ from: 2, loop: { start: 1, end: 3 } });
  assert.deepEqual(inside.next(), { at: 0, from: 2, to: 3 });
  assert.deepEqual(inside.next(), { at: 1, from: 1, to: 3 });
  const after = createPlan({ from: 4, loop: { start: 1, end: 3 } });
  assert.deepEqual(after.next(), { at: 0, from: 4, to: Infinity });
  assert.equal(after.next(), null);
});

test("songTime follows the plan: the start point plus the time played, wrapping inside the loop", () => {
  assert.equal(songTime(-0.1, { from: 0 }), null);
  near(songTime(1.25, { from: 2 }), 3.25);
  const loop = { start: 1, end: 3 };
  near(songTime(0.4, { from: 0.5, loop }), 0.9);
  near(songTime(2.5, { from: 0.5, loop }), 1);
  near(songTime(3.7, { from: 0.5, loop }), 2.2);
  near(songTime(6.6, { from: 0.5, loop }), 1.1);
  near(songTime(9, { from: 4, loop }), 13);
});

test("songTime agrees with the plan's segments at every point", () => {
  const options = { from: 0.3, loop: { start: 0.75, end: 2 } }, plan = createPlan(options), segs = [];
  for (let i = 0; i < 6; i++) segs.push(plan.next());
  for (let i = 0; i < 700; i++) {
    const e = i / 100 + 0.003;
    const s = segs.findLast(x => x.at <= e + 1e-12);
    near(songTime(e, options), s.from + (e - s.at), 1e-9);
  }
});

test("clipNotes keeps the part of each note inside the window, timed from the window's start", () => {
  const notes = [{ m: 60, t: 0, d: 1 }, { m: 62, t: 1, d: 1 }, { m: 64, t: 2.5, d: 2 }, { m: 65, t: 5, d: 1 }];
  assert.deepEqual(clipNotes(notes, 1.5, 3), [{ m: 62, t: 0, d: 0.5 }, { m: 64, t: 1, d: 0.5 }]);
  assert.deepEqual(clipNotes(notes, 4, Infinity), [{ m: 64, t: 0, d: 0.5 }, { m: 65, t: 1, d: 1 }]);
  // A note that ends where the window begins, or one that would keep a sliver, is left out.
  assert.deepEqual(clipNotes([{ m: 60, t: 0, d: 1 }, { m: 61, t: 0.9995, d: 0.0006 }], 1, 2), []);
  assert.deepEqual(clipNotes([], 0, Infinity), []);
});

test("clipHits keeps the drum hits that fall inside the window", () => {
  const hits = [{ k: "kick", t: 0 }, { k: "snare", t: 1 }, { k: "hat", t: 2 }];
  assert.deepEqual(clipHits(hits, 1, 2), [{ k: "snare", t: 0 }]);
  assert.deepEqual(clipHits(hits, 0.5, Infinity), [{ k: "snare", t: 0.5 }, { k: "hat", t: 1.5 }]);
});

test("clipProject clips every part and keeps the rest of the project", () => {
  const p = { bpm: 90, instrument: "piano", notes: [{ m: 60, t: 1, d: 1 }], harmony: [{ m: 48, t: 0, d: 4 }], voice2: [{ m: 64, t: 1, d: 1 }], drums: [{ k: "kick", t: 2 }] };
  const c = clipProject(p, 1.5, 3);
  assert.equal(c.bpm, 90);
  assert.equal(c.instrument, "piano");
  assert.deepEqual(c.notes, [{ m: 60, t: 0, d: 0.5 }]);
  assert.deepEqual(c.harmony, [{ m: 48, t: 0, d: 1.5 }]);
  assert.deepEqual(c.voice2, [{ m: 64, t: 0, d: 0.5 }]);
  assert.deepEqual(c.drums, [{ k: "kick", t: 0.5 }]);
  assert.deepEqual(p.notes, [{ m: 60, t: 1, d: 1 }], "the project is not changed");
  assert.deepEqual(clipProject({ notes: [], drums: [] }, 0, 1).harmony, []);
});

test("timelineEnd is the end of the longest part, at least eight seconds", () => {
  assert.equal(timelineEnd({ notes: [], drums: [] }), 8);
  assert.equal(timelineEnd({ notes: [{ m: 60, t: 9, d: 1 }], drums: [], harmony: [{ m: 48, t: 0, d: 12 }] }), 12);
  near(timelineEnd({ notes: [], drums: [{ k: "kick", t: 11 }] }), 11.3);
  assert.equal(timelineEnd({ notes: [], drums: [], voice2: [{ m: 60, t: 14, d: 1 }] }), 15);
  assert.equal(timelineEnd({ notes: [], drums: [], band: { seconds: 20 } }), 20);
  assert.equal(timelineEnd({ notes: [], drums: [], band: { seconds: 20, muted: true } }), 8);
  assert.equal(timelineEnd({ notes: [], drums: [] }, [{ m: 60, t: 30, d: 1 }]), 31, "extra events, such as a harmony line being tried");
});
