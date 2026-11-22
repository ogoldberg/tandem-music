// SONG.1: song sections. Named stretches of the song, and repeating, moving and deleting one across every
// note part at once (melody, chords, harmony voice, drums); recordings are not touched.
import test from "node:test";
import assert from "node:assert/strict";
import {
  cleanSections, markSection, unmarkSection, repeatSection, deleteSection, moveSection, sectionAt, snapToBeat,
  SECTION_NAMES, SECTION_PARTS, MAX_SECTIONS, MIN_SECTION_SECONDS,
} from "../sections.js";
import { projectFromState } from "../versions.js";
import { timelineEnd } from "../playhead.js";

// At 120 bpm a beat is 0.5 s and a bar 2 s. Verse 0-4 s, chorus 4-8 s, outro 8-10 s.
const SECTIONS = [{ name: "Verse", from: 0, to: 4 }, { name: "Chorus", from: 4, to: 8 }, { name: "Outro", from: 8, to: 10 }];
const song = () => ({
  bpm: 120,
  notes: [{ m: 60, t: 0, d: 1 }, { m: 62, t: 2, d: 1 }, { m: 64, t: 4, d: 1 }, { m: 65, t: 6, d: 1 }, { m: 67, t: 8, d: 2 }],
  harmony: [{ m: 48, t: 0, d: 4 }, { m: 53, t: 4, d: 4 }, { m: 55, t: 8, d: 2 }],
  voice2: [{ m: 64, t: 4, d: 1 }, { m: 69, t: 6, d: 1 }],
  drums: [{ k: "kick", t: 0 }, { k: "snare", t: 5 }, { k: "kick", t: 9 }],
  sections: SECTIONS.map(s => ({ ...s })),
});
const starts = part => part.map(n => n.t);

test("a section list is checked like the rest of the project", () => {
  assert.deepEqual(cleanSections(undefined), []);
  assert.deepEqual(cleanSections(null), []);
  assert.deepEqual(cleanSections(SECTIONS), SECTIONS);
  assert.deepEqual(cleanSections([{ name: "  Chorus  ", from: 1, to: 3 }]), [{ name: "Chorus", from: 1, to: 3 }]);
  for (const bad of [
    {}, "x", [{ name: "", from: 0, to: 1 }], [{ name: "A", from: 1, to: 1 }], [{ name: "A", from: -1, to: 1 }],
    [{ name: "A", from: 0, to: 601 }], [{ name: "A", from: 0, to: 1, extra: 1 }], [{ name: "x".repeat(41), from: 0, to: 1 }],
    [{ name: "A", from: 2, to: 4 }, { name: "B", from: 0, to: 2 }], // out of order
    [{ name: "A", from: 0, to: 3 }, { name: "B", from: 2, to: 4 }], // overlapping
    [{ name: "A", from: Number.NaN, to: 1 }], [{ name: 3, from: 0, to: 1 }],
    Array.from({ length: MAX_SECTIONS + 1 }, (_, i) => ({ name: "A", from: i, to: i + 1 })),
  ]) assert.throws(() => cleanSections(bad), Error, JSON.stringify(bad).slice(0, 60));
  assert.ok(SECTION_NAMES.includes("Verse") && SECTION_NAMES.includes("Chorus"));
  assert.deepEqual(SECTION_PARTS, ["notes", "harmony", "voice2", "drums"]);
});

test("a section is marked in time order and cannot overlap another", () => {
  const one = markSection([], { name: "Chorus", from: 4, to: 8 });
  assert.deepEqual(one, [{ name: "Chorus", from: 4, to: 8 }]);
  const two = markSection(one, { name: "Verse", from: 0, to: 4 });
  assert.deepEqual(two.map(s => s.name), ["Verse", "Chorus"]);
  assert.throws(() => markSection(two, { name: "Bridge", from: 7, to: 9 }), /overlaps Chorus/);
  assert.throws(() => markSection(two, { name: " ", from: 9, to: 10 }), /name/);
  assert.throws(() => markSection(two, { name: "Bridge", from: 9, to: 9 + MIN_SECTION_SECONDS / 2 }), /too short/);
  assert.deepEqual(unmarkSection(two, 0), [{ name: "Chorus", from: 4, to: 8 }]);
  assert.throws(() => unmarkSection(two, 5), /Choose a section/);
  assert.equal(sectionAt(two, 5), 1);
  assert.equal(sectionAt(two, 8), -1);
  assert.equal(sectionAt(two, 0), 0);
});

test("a marked range snaps to the nearest beat at the project tempo", () => {
  assert.equal(snapToBeat(3.9, 120), 4);
  assert.equal(snapToBeat(4.26, 120), 4.5);
  assert.equal(snapToBeat(0.1, 120), 0);
  assert.throws(() => snapToBeat(1, 0), /tempo/);
});

test("repeating a section puts a copy of every note part right after it and moves the rest later", () => {
  const p = song(), r = repeatSection(p, 1);
  // The chorus is 4 s: its notes are copied 4 s later and everything from 8 s on moves 4 s later.
  assert.deepEqual(starts(r.notes), [0, 2, 4, 6, 12, 8, 10]);
  assert.deepEqual(r.notes.slice(-2), [{ m: 64, t: 8, d: 1 }, { m: 65, t: 10, d: 1 }]);
  assert.deepEqual(starts(r.harmony), [0, 4, 12, 8]);
  assert.deepEqual(starts(r.voice2), [4, 6, 8, 10]);
  assert.deepEqual(r.drums, [{ k: "kick", t: 0 }, { k: "snare", t: 5 }, { k: "kick", t: 13 }, { k: "snare", t: 9 }]);
  assert.deepEqual(r.sections, [
    { name: "Verse", from: 0, to: 4 }, { name: "Chorus", from: 4, to: 8 }, { name: "Chorus", from: 8, to: 12 }, { name: "Outro", from: 12, to: 14 },
  ]);
  assert.equal(r.index, 2);
  // The project passed in is unchanged.
  assert.deepEqual(p, song());
});

test("deleting a section removes its notes, pulls the rest earlier and cuts a note held into it", () => {
  const p = song();
  p.notes.push({ m: 59, t: 3, d: 2 }); // held from the verse over the start of the chorus
  const r = deleteSection(p, 1);
  assert.deepEqual(r.notes, [{ m: 60, t: 0, d: 1 }, { m: 62, t: 2, d: 1 }, { m: 67, t: 4, d: 2 }, { m: 59, t: 3, d: 1 }]);
  assert.deepEqual(r.harmony, [{ m: 48, t: 0, d: 4 }, { m: 55, t: 4, d: 2 }]);
  assert.deepEqual(r.voice2, []);
  assert.deepEqual(r.drums, [{ k: "kick", t: 0 }, { k: "kick", t: 5 }]);
  assert.deepEqual(r.sections, [{ name: "Verse", from: 0, to: 4 }, { name: "Outro", from: 4, to: 6 }]);
});

test("moving a section swaps it with its neighbour, keeping the gap between them", () => {
  const p = song();
  // A gap of one bar between the chorus and the outro.
  p.sections[2] = { name: "Outro", from: 10, to: 12 };
  p.notes.push({ m: 70, t: 8.5, d: 0.5 }, { m: 72, t: 10, d: 1 });
  const later = moveSection(p, 1, 1);
  // Outro (10-12) goes to 4-6, the gap (8-10) to 6-8, the chorus (4-8) to 8-12.
  assert.deepEqual(later.sections, [{ name: "Verse", from: 0, to: 4 }, { name: "Outro", from: 4, to: 6 }, { name: "Chorus", from: 8, to: 12 }]);
  assert.deepEqual(later.notes.map(n => [n.m, n.t]), [[60, 0], [62, 2], [64, 8], [65, 10], [67, 6], [70, 6.5], [72, 4]]);
  assert.deepEqual(later.drums, [{ k: "kick", t: 0 }, { k: "snare", t: 9 }, { k: "kick", t: 7 }]);
  assert.equal(later.index, 2);
  // Moving it back gives the song it came from.
  const back = moveSection({ ...p, ...later }, 2, -1);
  assert.deepEqual(back.sections, p.sections);
  assert.deepEqual([...back.notes].sort((a, b) => a.t - b.t || a.m - b.m), [...p.notes].sort((a, b) => a.t - b.t || a.m - b.m));
  assert.equal(back.index, 1);
  assert.throws(() => moveSection(p, 0, -1), /already the first/);
  assert.throws(() => moveSection(p, 2, 1), /already the last/);
});

test("a section edit is refused when the song would grow past its limits", () => {
  const p = { bpm: 120, notes: [{ m: 60, t: 0, d: 1 }, { m: 62, t: 590, d: 1 }], harmony: [], voice2: [], drums: [], sections: [{ name: "Verse", from: 0, to: 20 }] };
  assert.throws(() => repeatSection(p, 0), /600 seconds/);
  // GROW.2: a part holds 4,096 notes, so 1,000 notes repeated is room enough and 3,000 is not.
  const many = n => ({ bpm: 120, notes: Array.from({ length: n }, (_, i) => ({ m: 60, t: Math.round(i * 9000 / n) / 1000, d: 0.001 })), harmony: [], voice2: [], drums: [], sections: [{ name: "Verse", from: 0, to: 10 }] });
  assert.equal(repeatSection(many(1000), 0).project.notes.length, 2000);
  assert.throws(() => repeatSection(many(3000), 0), /more than 4096/);
  assert.throws(() => repeatSection(song(), 7), /Choose a section/);
});

test("a project keeps its sections only when it has some, so older projects save unchanged", () => {
  const base = { bpm: 100, instrument: "piano", notes: [], drums: [] };
  assert.equal("sections" in projectFromState(base), false);
  assert.equal("sections" in projectFromState({ ...base, sections: [] }), false);
  assert.deepEqual(projectFromState({ ...base, sections: SECTIONS }).sections, SECTIONS);
});

test("the Timeline is long enough to show every section, even one past the last note", () => {
  assert.equal(timelineEnd({ notes: [{ m: 60, t: 0, d: 1 }], drums: [], sections: [{ name: "Outro", from: 10, to: 20 }] }), 20);
  assert.equal(timelineEnd({ notes: [{ m: 60, t: 0, d: 1 }], drums: [] }), 8);
});
