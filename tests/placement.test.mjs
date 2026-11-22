// GROW.3: placement.js, where each recording plays in the song: clips {from, to, at}, the section edits on them,
// laying samples out with equal-power joins, and carrying notes read from a recording to every place it plays.
import test from "node:test";
import assert from "node:assert/strict";
import {
  cleanPlaced, cleanClips, clipsOf, withClips, withoutClips, placedSeconds, repeatClips, deleteClips, moveClips,
  placeSamples, placeNotes, edgeGain, placeKey, isWhole, MAX_CLIPS, PLACE_FADE,
} from "../placement.js";
import { repeatSection, deleteSection, moveSection } from "../sections.js";

const whole = s => [{ from: 0, to: s, at: 0 }];

test("no entry is the whole recording from zero, and that is no entry again", () => {
  assert.equal(cleanPlaced(null), null);
  assert.equal(cleanPlaced({}), null);
  assert.deepEqual(clipsOf(null, "voice", 6), whole(6));
  assert.deepEqual(clipsOf(null, "voice", 0), []);
  assert.equal(withClips(null, "voice", whole(6), 6), null);
  assert.ok(isWhole(whole(6), 6));
  assert.deepEqual(withClips(null, "voice", [{ from: 0, to: 3, at: 0 }], 6), { voice: [{ from: 0, to: 3, at: 0 }] });
  assert.equal(withoutClips({ voice: [{ from: 0, to: 3, at: 0 }] }, "voice"), null);
  assert.equal(placedSeconds(null, "voice", 6), 6);
  assert.equal(placedSeconds({ voice: [{ from: 0, to: 2, at: 0 }, { from: 0, to: 2, at: 5 }] }, "voice", 6), 7);
});

test("cleanPlaced refuses what a file must not hold", () => {
  for (const bad of [[], 1, { melody: [] }, { "layer-UP": [] }, { voice: {} }, { voice: [{ from: 0, to: 1 }] },
    { voice: [{ from: 1, to: 1, at: 0 }] }, { voice: [{ from: 0, to: 2, at: 0, x: 1 }] }, { voice: [{ from: 0, to: 2, at: 1 }, { from: 0, to: 2, at: 2 }] },
    { voice: [{ from: 0, to: 2, at: 599 }] }, { voice: Array.from({ length: MAX_CLIPS + 1 }, (_, i) => ({ from: 0, to: 1, at: i })) }])
    assert.throws(() => cleanPlaced(bad), undefined, JSON.stringify(bad));
  const ok = { voice: [{ from: 0, to: 2, at: 0 }, { from: 0, to: 2, at: 2 }], "layer-abc123": [], band: [{ from: 1, to: 3, at: 4 }] };
  assert.deepEqual(cleanPlaced(ok), ok);
  assert.equal(placeKey("tuned"), "voice");
  assert.equal(placeKey("accompaniment"), "voice");
  assert.equal(placeKey("band"), "band");
});

test("repeat plays the section twice and moves what follows later; joined stretches stay one clip", () => {
  // A 6 s take, the section 2..4 repeated: 0..4 at 0, then 2..6 at 4.
  assert.deepEqual(repeatClips(whole(6), { from: 2, to: 4 }), [{ from: 0, to: 4, at: 0 }, { from: 2, to: 6, at: 4 }]);
  // A section past the recording's end leaves it whole.
  assert.deepEqual(repeatClips(whole(6), { from: 7, to: 9 }), whole(6));
  // A section that holds the start of the recording only.
  assert.deepEqual(repeatClips(whole(6), { from: 0, to: 2 }), [{ from: 0, to: 2, at: 0 }, { from: 0, to: 6, at: 2 }]);
});

test("delete takes the section's stretch out and closes the gap", () => {
  assert.deepEqual(deleteClips(whole(6), { from: 2, to: 4 }), [{ from: 0, to: 2, at: 0 }, { from: 4, to: 6, at: 2 }]);
  assert.deepEqual(deleteClips(whole(6), { from: 0, to: 6 }), []);
  // Repeat then delete the copy is the whole recording again.
  assert.deepEqual(deleteClips(repeatClips(whole(6), { from: 2, to: 4 }), { from: 4, to: 6 }), whole(6));
});

test("move swaps two sections and keeps the stretch between them between them", () => {
  // A 0..2, gap 2..3, B 3..4: B now at 0..1, the gap at 1..2, A at 2..4; the rest stays.
  assert.deepEqual(moveClips(whole(6), { from: 0, to: 2 }, { from: 3, to: 4 }),
    [{ from: 3, to: 4, at: 0 }, { from: 2, to: 3, at: 1 }, { from: 0, to: 2, at: 2 }, { from: 4, to: 6, at: 4 }]);
  // Moving back is the whole recording again.
  const there = moveClips(whole(6), { from: 0, to: 2 }, { from: 2, to: 4 });
  assert.deepEqual(moveClips(there, { from: 0, to: 2 }, { from: 2, to: 4 }), whole(6));
});

test("too many pieces, or a song past 600 s, is refused in words", () => {
  let clips = whole(10);
  assert.throws(() => { for (let i = 0; i < 80; i++) clips = repeatClips(clips, { from: 0, to: 0.5 + (i % 2) * 0.25 }, "voice") }, /more than 64 pieces|past 600/);
  assert.throws(() => repeatClips([{ from: 0, to: 400, at: 0 }], { from: 0, to: 300 }, "band"), /The band would go past 600 seconds/);
});

test("placeSamples: null clips are the recording itself, and a whole clip is the samples unchanged", () => {
  const src = Float32Array.from({ length: 1000 }, (_, i) => Math.sin(i / 7));
  assert.equal(placeSamples(null, src, 100), src);
  assert.deepEqual([...placeSamples(whole(10), src, 100)], [...src]);
});

test("placeSamples lays stretches out where they play, crossing over at joins with unit power", () => {
  const rate = 1000, half = (PLACE_FADE * rate) / 2;
  // Equal power at every sample of a join.
  for (let i = 90; i < 112; i++) assert.ok(Math.abs(edgeGain(i, 100, half, true) ** 2 + edgeGain(i, 100, half, false) ** 2 - 1) < 1e-12);
  // A ramp, so where each sample came from is its value.
  const src = Float32Array.from({ length: 6 * rate }, (_, i) => i);
  const out = placeSamples(repeatClips(whole(6), { from: 2, to: 4 }), src, rate);
  assert.equal(out.length, 8 * rate);
  assert.equal(out[1000], 1000);
  assert.equal(out[3000], 3000);
  // After the join at 4 s the recording plays again from 2 s.
  assert.equal(out[5000], 3000);
  assert.equal(out[7999], 5999);
  // At the join both sides are heard at equal power: (4000 + 2000) * cos(pi/4).
  assert.ok(Math.abs(out[4000] - 6000 * Math.SQRT1_2) < 1);
  // A gap is silence, and an edge cut out of the recording beside it fades in from nothing.
  const gapped = placeSamples([{ from: 0, to: 1, at: 0 }, { from: 2, to: 3, at: 2 }], src, rate);
  assert.equal(gapped[1500], 0);
  assert.equal(gapped[2000], 0);
  assert.equal(gapped[2500], 2500);
});

test("placeNotes carries notes read from a recording to every clip, cut at its end", () => {
  const notes = [{ m: 60, t: 0.5, d: 0.4 }, { m: 62, t: 2.5, d: 2 }, { m: 64, t: 4.5, d: 0.3 }];
  assert.equal(placeNotes(null, notes), notes);
  const clips = repeatClips(whole(6), { from: 2, to: 4 });
  assert.deepEqual(placeNotes(clips, notes), [
    { m: 60, t: 0.5, d: 0.4 }, { m: 62, t: 2.5, d: 1.5 }, { m: 62, t: 4.5, d: 2 }, { m: 64, t: 6.5, d: 0.3 },
  ]);
  assert.deepEqual(placeNotes(clips, [{ k: "kick", t: 3 }]), [{ k: "kick", t: 3 }, { k: "kick", t: 5 }]);
  assert.throws(() => placeNotes(clips, notes, { max: 3 }), /more than 3/);
});

test("a section edit changes the notes and the clips alike, and leaves no entry where nothing moved", () => {
  const project = { notes: [{ m: 60, t: 2.5, d: 0.5 }], harmony: [], voice2: [], drums: [], sections: [{ name: "Verse", from: 2, to: 4 }] };
  const lengths = { voice: 6, band: 1.5, "layer-abc": 3 };
  const r = repeatSection(project, 0, { lengths });
  assert.deepEqual(r.notes, [{ m: 60, t: 2.5, d: 0.5 }, { m: 60, t: 4.5, d: 0.5 }]);
  // The voice plays the verse twice, a layer too; the band ends before the verse, so it is still whole from zero.
  assert.deepEqual(r.placed, { voice: [{ from: 0, to: 4, at: 0 }, { from: 2, to: 6, at: 4 }], "layer-abc": [{ from: 0, to: 3, at: 0 }, { from: 2, to: 3, at: 4 }] });
  // No recordings: no placement.
  assert.equal(repeatSection(project, 0).placed, null);
  // Delete the copy: back to the start, with no entry.
  const back = deleteSection({ ...project, ...r }, 1, { lengths });
  assert.deepEqual(back.notes, project.notes);
  assert.equal(back.placed, null);
  // Move the copy earlier: the voice follows the notes.
  // Intro 0..2 swapped with the first Verse 2..4: the song plays the recording's 2..4, then 0..6, which joins up.
  const moved = moveSection({ ...project, notes: r.notes, placed: r.placed, sections: [{ name: "Intro", from: 0, to: 2 }, ...r.sections] }, 0, 1, { lengths: { voice: 6 } });
  assert.deepEqual(moved.notes, [{ m: 60, t: 0.5, d: 0.5 }, { m: 60, t: 4.5, d: 0.5 }]);
  assert.deepEqual(moved.placed.voice, [{ from: 2, to: 4, at: 0 }, { from: 0, to: 6, at: 2 }]);
  // A placement already there is carried without a length.
  const again = repeatSection({ ...project, placed: r.placed, sections: r.sections }, 1);
  assert.deepEqual(again.placed.voice, [{ from: 0, to: 4, at: 0 }, { from: 2, to: 4, at: 4 }, { from: 2, to: 6, at: 6 }]);
  assert.deepEqual(cleanClips(again.placed.voice), again.placed.voice);
});
