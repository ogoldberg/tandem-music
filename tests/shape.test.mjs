// GROW.4: Song shape. The idea as one block of whole bars (a pickup kept before it, "as sung" when the tune is shorter
// than the beat), written with the bar grid pinned, and the tile's state line.
import test from "node:test";
import assert from "node:assert/strict";
import { IDEA_NAME, blockLength, clock, ideaBlock, shapeLine, withIdea } from "../shape.js";
import { repeatSection, renameSection } from "../sections.js";
import { barOrigin } from "../bars.js";

// 100 bpm: a beat is 0.6 s, a bar 2.4 s.
const hum = (extra = {}) => ({
  bpm: 100,
  notes: [{ m: 60, t: 0, d: 0.5 }, { m: 62, t: 0.6, d: 0.5 }, { m: 64, t: 1.2, d: 1 }, { m: 65, t: 3.0, d: 1.5 }, { m: 67, t: 5.4, d: 0.5 }],
  drums: [], harmony: [], voice2: [], ...extra,
});

test("the idea is whole bars from the first bar to the bar line at or after the end of everything", () => {
  // The tune ends at 5.9 s: three bars (7.2 s).
  const b = ideaBlock(hum(), { end: 5.9, tune: 5.9 });
  assert.deepEqual(b, { name: IDEA_NAME, from: 0, to: 7.2, bars: 3, pickup: 0, sung: null });
  // A recording running on to 7.3 s makes it four bars, never a bar cut short.
  assert.equal(ideaBlock(hum(), { end: 7.3, tune: 7.3 }).bars, 4);
  // Exactly on a bar line is that bar, not one more.
  assert.equal(ideaBlock(hum(), { end: 7.2, tune: 7.2 }).to, 7.2);
  // With nothing in the song there is no block.
  assert.throws(() => ideaBlock(hum({ notes: [] }), { end: 0 }), /nothing to shape/);
});

test("a pickup stays before the idea as its lead-in", () => {
  // Notes on the beat from 2.4 s (the zero grid, so a bar starts there) with a pickup half a beat (0.3 s) before it.
  const p = { bpm: 100, notes: [{ m: 60, t: 2.1, d: 0.3 }, ...[2.4, 3.0, 3.6, 4.2, 4.8, 5.4].map(t => ({ m: 62, t, d: 0.5 }))], drums: [], harmony: [], voice2: [] };
  const b = ideaBlock(p, { end: 5.9, tune: 5.9 });
  assert.equal(b.pickup, 0.3);
  assert.equal(b.from, 2.4);
  assert.equal(b.to, 7.2);
  assert.equal(b.bars, 2);
});

test("a tune shorter than the beat offers the block as sung", () => {
  // The tune is three bars; a starter beat runs four (9.6 s).
  const drums = Array.from({ length: 16 }, (_, i) => ({ k: i % 2 ? "snare" : "kick", t: Math.round(i * 0.6 * 1000) / 1000 }));
  const p = hum({ drums });
  const b = ideaBlock(p, { end: 9.6, tune: 5.9 });
  assert.equal(b.bars, 4);
  assert.equal(b.to, 9.6);
  assert.deepEqual(b.sung, { from: 0, to: 7.2, bars: 3 });
  const sung = ideaBlock(p, { end: 9.6, tune: 5.9, asSung: true });
  assert.equal(sung.bars, 3);
  assert.equal(sung.to, 7.2);
  // A tune as long as the beat offers nothing, and asSung then changes nothing.
  assert.equal(ideaBlock(p, { end: 9.6, tune: 9.6 }).sung, null);
  assert.equal(ideaBlock(p, { end: 9.6, tune: 9.6, asSung: true }).bars, 4);
});

test("the idea is written with the bar grid pinned where it is, and a repeat then copies whole bars", () => {
  // A free-time hum: onsets on a beat grid from 0.25 s, so the guessed origin is not zero.
  const p = { bpm: 100, notes: [0.25, 0.85, 1.45, 2.05, 2.65, 3.25].map(t => ({ m: 60, t, d: 0.5 })), drums: [], harmony: [], voice2: [] };
  const origin = barOrigin(p);
  assert.ok(origin > 0.2 && origin < 0.3, String(origin));
  const block = ideaBlock(p, { end: 3.75, tune: 3.75 });
  assert.equal(block.from, Math.round(origin * 1000) / 1000);
  const w = withIdea(p, block);
  assert.deepEqual(w.grid, { origin });
  assert.deepEqual(w.sections, [{ name: IDEA_NAME, from: block.from, to: block.to }]);
  const r = repeatSection({ ...p, ...w }, 0);
  assert.equal(r.notes.length, 12);
  assert.deepEqual(r.sections.map(s => s.name), [IDEA_NAME, IDEA_NAME]);
  assert.equal(r.sections[1].from, block.to);
  // A grid already pinned is kept; a song with blocks is refused.
  assert.deepEqual(withIdea({ ...p, grid: { origin: 0.1 } }, block).grid, { origin: 0.1 });
  assert.throws(() => withIdea({ ...p, sections: w.sections }, block), /blocks already/);
});

test("a block is named from the menu, and its length is said in bars", () => {
  const list = [{ name: IDEA_NAME, from: 0, to: 7.2 }, { name: IDEA_NAME, from: 7.2, to: 14.4 }];
  assert.deepEqual(renameSection(list, 1, "Chorus"), [list[0], { ...list[1], name: "Chorus" }]);
  assert.throws(() => renameSection(list, 2, "Chorus"), /Choose a section/);
  assert.throws(() => renameSection(list, 0, " "), /name/);
  assert.equal(blockLength(hum(), list[0]), "3 bars");
  assert.equal(blockLength(hum(), { from: 0, to: 2.4 }), "1 bar");
  assert.equal(blockLength(hum(), { from: 1.2, to: 2.4 }), "1.2 s");
});

test("the Song shape state line", () => {
  assert.equal(clock(10.4), "0:10");
  assert.equal(clock(72), "1:12");
  assert.equal(shapeLine([], 10.4), "One part, 0:10");
  assert.equal(shapeLine(undefined, 0), "Nothing yet");
  assert.equal(shapeLine([{ name: "Verse", from: 0, to: 24 }, { name: "Verse", from: 24, to: 48 }, { name: "Chorus", from: 48, to: 72 }], 72),
    "Verse, Verse, Chorus, 1:12");
  const eight = Array.from({ length: 8 }, (_, i) => ({ name: "Verse", from: i, to: i + 1 }));
  assert.equal(shapeLine(eight, 8), "Verse, Verse, Verse, Verse, Verse, Verse, and 2 more, 0:08");
});
