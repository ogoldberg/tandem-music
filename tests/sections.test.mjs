// SONG.1: song sections. Named stretches of the song, and repeating, moving and deleting one across every
// note part at once (melody, chords, harmony voice, drums); given no recording lengths, nothing is placed (GROW.3's
// clips are tested in tests/placement.test.mjs).
import test from "node:test";
import assert from "node:assert/strict";
import {
  cleanSections, markSection, unmarkSection, repeatSection, deleteSection, moveSection, sectionAt, snapToBeat,
  SECTION_NAMES, SECTION_PARTS, MAX_SECTIONS, MIN_SECTION_SECONDS, addIntro, addEnding,
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
  assert.equal(repeatSection(many(1000), 0).notes.length, 2000);
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

// SONG.3: an intro and an ending.
// A 120 bpm song (2 s bars) on the grid from zero: a melody from bar 1, C major chords a bar each, a beat.
const C = { tonic: 0, mode: "major" };
function arranged() {
  const notes = [
    { m: 64, t: 0, d: 0.5 }, { m: 62, t: 0.5, d: 0.5 }, { m: 60, t: 1, d: 1 },
    { m: 67, t: 2, d: 1 }, { m: 65, t: 3, d: 1 }, { m: 64, t: 4, d: 1 }, { m: 62, t: 5, d: 1 }, { m: 67, t: 6.5, d: 0.5 },
  ];
  const chord = (pcs, t) => pcs.map(m => ({ m, t, d: 1.88 }));
  const harmony = [...chord([48, 52, 55], 0), ...chord([53, 57, 60], 2), ...chord([48, 52, 55], 4), ...chord([55, 59, 62], 6)];
  const drums = [];
  for (let b = 0; b < 4; b++) for (let q = 0; q < 4; q++) drums.push({ k: q % 2 ? "snare" : "kick", t: b * 2 + q * 0.5 });
  return { bpm: 120, notes, harmony, voice2: [{ m: 72, t: 2, d: 1 }], drums };
}
const byTime = xs => [...xs].sort((a, b) => a.t - b.t || (a.m ?? 0) - (b.m ?? 0) || String(a.k).localeCompare(String(b.k)));

test("SONG.3: Add intro puts the first bars of chords and drums before the tune and moves the song later by whole bars", () => {
  const p = arranged();
  for (const bars of [1, 2]) {
    const D = bars * 2, r = addIntro(p, { bars });
    // The melody and the harmony voice are the song's, later by the intro; nothing of them is copied.
    assert.deepEqual(r.notes, p.notes.map(n => ({ ...n, t: n.t + D })));
    assert.deepEqual(r.voice2, p.voice2.map(n => ({ ...n, t: n.t + D })));
    // The chords and drums of the first bars play in the intro, then the song's own, later by the intro.
    const first = xs => xs.filter(e => e.t < D - 1e-9);
    assert.deepEqual(byTime(first(r.harmony)), byTime(first(p.harmony)));
    assert.deepEqual(byTime(first(r.drums)), byTime(first(p.drums)));
    assert.deepEqual(byTime(r.harmony.filter(e => e.t >= D)), byTime(p.harmony.map(e => ({ ...e, t: e.t + D }))));
    assert.deepEqual(byTime(r.drums.filter(e => e.t >= D)), byTime(p.drums.map(e => ({ ...e, t: e.t + D }))));
    assert.deepEqual(r.sections, [{ name: "Intro", from: 0, to: D }]);
    assert.equal(r.index, 0);
    assert.equal(r.placed, null);
  }
  // A second intro is refused.
  const once = addIntro(p, { bars: 1 });
  assert.throws(() => addIntro({ ...p, ...once }, { bars: 1 }), /intro already/);
  assert.throws(() => addIntro(p, { bars: 3 }), /one or two bars/);
});

test("SONG.3: the intro needs chords or a beat, keeps the sections after it, and moves the recordings with the song", () => {
  const p = arranged();
  assert.throws(() => addIntro({ ...p, harmony: [], drums: [] }), /chords or a beat/);
  // Only a beat: the intro is the beat.
  const beat = addIntro({ ...p, harmony: [] }, { bars: 1 });
  assert.deepEqual(beat.harmony, []);
  assert.equal(beat.drums.filter(h => h.t < 2 - 1e-9).length, 4);
  // A pickup a beat before the song's first bar line lands in the intro's last beat; the intro copies from the first bar.
  const lift = { bpm: 120, grid: { origin: 0 }, notes: [{ m: 60, t: 1.75, d: 0.25 }, { m: 64, t: 2, d: 1 }], harmony: [{ m: 48, t: 2, d: 1.9 }], voice2: [], drums: [] };
  const li = addIntro(lift, { bars: 1 });
  assert.deepEqual(li.notes, [{ m: 60, t: 3.75, d: 0.25 }, { m: 64, t: 4, d: 1 }]);
  assert.deepEqual(li.harmony, [{ m: 48, t: 2, d: 1.9 }, { m: 48, t: 4, d: 1.9 }]);
  assert.deepEqual(li.sections, [{ name: "Intro", from: 2, to: 4 }]);
  // A chord held past the intro is cut at its end, so it does not sound over the song's first chord.
  const held = addIntro({ ...p, harmony: [{ m: 48, t: 0, d: 4 }] }, { bars: 1 });
  assert.deepEqual(held.harmony, [{ m: 48, t: 0, d: 2 }, { m: 48, t: 2, d: 4 }]);
  // The song's sections move with it.
  const marked = addIntro({ ...p, sections: [{ name: "Verse", from: 0, to: 4 }, { name: "Chorus", from: 4, to: 8 }] }, { bars: 2 });
  assert.deepEqual(marked.sections, [{ name: "Intro", from: 0, to: 4 }, { name: "Verse", from: 4, to: 8 }, { name: "Chorus", from: 8, to: 12 }]);
  // GROW.3: the voice is placed later by the intro; no recording is cut.
  const voiced = addIntro(p, { bars: 2, lengths: { voice: 7.5 } });
  assert.deepEqual(voiced.placed, { voice: [{ from: 0, to: 7.5, at: 4 }] });
  // The limits hold.
  assert.throws(() => addIntro({ ...p, notes: [...p.notes, { m: 60, t: 598, d: 1 }] }, { bars: 2 }), /600 seconds/);
});

test("SONG.3: Add ending holds the tonic chord under the last note, ends the beat on one hit, and marks an Outro", () => {
  const p = arranged();
  const r = addEnding(p, { key: C });
  // The last note starts at 6.5 s in the bar from 6 s and ends at 7 s, so the ending is that bar, 6 to 8 s.
  assert.deepEqual(r.sections, [{ name: "Outro", from: 6, to: 8 }]);
  assert.equal(r.index, 0);
  // The chords before the ending are the song's; in it, one C major chord held to the bar line, under the last note (G4).
  assert.deepEqual(r.harmony.filter(n => n.t < 6), p.harmony.filter(n => n.t < 6));
  const end = r.harmony.filter(n => n.t >= 6);
  assert.ok(end.length >= 3);
  assert.deepEqual([...new Set(end.map(n => n.m % 12))].sort((a, b) => a - b), [0, 4, 7]);
  for (const n of end) { assert.equal(n.t, 6); assert.equal(n.d, 2); assert.ok(n.m <= 67); }
  // The beat plays up to the ending and ends on a kick and snare together on its first beat.
  assert.deepEqual(r.drums.filter(h => h.t < 6), p.drums.filter(h => h.t < 6));
  assert.deepEqual(r.drums.filter(h => h.t >= 6), [{ k: "kick", t: 6 }, { k: "snare", t: 6 }]);
  // The melody and the harmony voice are untouched, and nothing is placed.
  assert.deepEqual(r.notes, p.notes);
  assert.deepEqual(r.voice2, p.voice2);
  assert.equal(r.placed, null);
  // Adding it again changes nothing.
  const again = addEnding({ ...p, ...r }, { key: C });
  for (const k of ["notes", "harmony", "voice2", "drums", "sections"]) assert.deepEqual(again[k], r[k], k);
  // Under a low last note (G3) the chord stays at or below it, though the chord before it is high (C5 E5 G5)
  // and voicing near that alone would put it there.
  const high = [...p.harmony.filter(n => n.t < 4), ...[72, 76, 79].map(m => ({ m, t: 4, d: 1.88 }))];
  const without = addEnding({ ...p, harmony: high }, { key: C }).harmony.filter(n => n.t >= 6);
  assert.ok(Math.max(...without.map(n => n.m)) > 55);
  const low = addEnding({ ...p, harmony: high, notes: [...p.notes.slice(0, -1), { m: 55, t: 6.5, d: 0.5 }] }, { key: C }).harmony.filter(n => n.t >= 6);
  assert.ok(low.length >= 2);
  for (const n of low) assert.ok(n.m <= 55, n.m);
  assert.ok(low.every(n => [0, 4, 7].includes(n.m % 12)));
  // In A minor the chord is A minor.
  const am = addEnding(p, { key: { tonic: 9, mode: "minor" } }).harmony.filter(n => n.t >= 6);
  assert.deepEqual([...new Set(am.map(n => n.m % 12))].sort((a, b) => a - b), [0, 4, 9]);
});

test("SONG.3: the ending is at least a bar, needs a tune and a key, leaves a song without drums without a hit, and keeps the sections before it", () => {
  const p = arranged();
  assert.throws(() => addEnding({ ...p, notes: [] }, { key: C }), /melody first/);
  assert.throws(() => addEnding(p, {}), /key/);
  // No drums: no hit is added.
  assert.deepEqual(addEnding({ ...p, drums: [] }, { key: C }).drums, []);
  // A last note held over the bar line takes the ending to the next one.
  const long = { ...p, notes: [...p.notes.slice(0, -1), { m: 67, t: 6.5, d: 2 }] };
  assert.deepEqual(addEnding(long, { key: C }).sections, [{ name: "Outro", from: 6, to: 10 }]);
  // A section that runs into the ending stops where it starts; one inside it gives way to the Outro.
  const marked = addEnding({ ...p, sections: [{ name: "Verse", from: 0, to: 7 }] }, { key: C });
  assert.deepEqual(marked.sections, [{ name: "Verse", from: 0, to: 6 }, { name: "Outro", from: 6, to: 8 }]);
  assert.equal(marked.index, 1);
  const inside = addEnding({ ...p, sections: [{ name: "Verse", from: 0, to: 6 }, { name: "Chorus", from: 6, to: 8 }] }, { key: C });
  assert.deepEqual(inside.sections, [{ name: "Verse", from: 0, to: 6 }, { name: "Outro", from: 6, to: 8 }]);
  // A chord held into the ending stops where it starts.
  const into = addEnding({ ...p, harmony: [{ m: 48, t: 4, d: 4 }] }, { key: C });
  assert.deepEqual(into.harmony.filter(n => n.t < 6), [{ m: 48, t: 4, d: 2 }]);
  // Nothing after the ending is there: `later` is null.
  assert.equal(addEnding(p, { key: C }).later, null);
});

test("SONG.3: Add ending changes only its own bar: the chords, drums, harmony voice and sections after it stay and are reported", () => {
  const p = arranged();
  // An instrumental Solo after the tune, 8 to 12 s: chords, a beat and a harmony voice note, and a Verse running across the ending.
  const solo = {
    ...p,
    harmony: [...p.harmony, { m: 53, t: 8, d: 2 }, { m: 55, t: 10, d: 2 }],
    drums: [...p.drums, { k: "kick", t: 8 }, { k: "snare", t: 9 }, { k: "hat", t: 11.5 }],
    voice2: [...p.voice2, { m: 72, t: 9, d: 1 }],
    sections: [{ name: "Verse", from: 4, to: 9 }, { name: "Solo", from: 9, to: 12 }],
  };
  const r = addEnding(solo, { key: C });
  assert.deepEqual(r.harmony.filter(n => n.t >= 8), [{ m: 53, t: 8, d: 2 }, { m: 55, t: 10, d: 2 }]);
  assert.deepEqual(r.drums.filter(h => h.t >= 8), [{ k: "kick", t: 8 }, { k: "snare", t: 9 }, { k: "hat", t: 11.5 }]);
  assert.deepEqual(r.drums.filter(h => h.t >= 6 && h.t < 8), [{ k: "kick", t: 6 }, { k: "snare", t: 6 }]);
  assert.deepEqual(r.voice2, solo.voice2);
  // The Verse keeps its parts on both sides of the Outro; the Solo stays.
  assert.deepEqual(r.sections, [
    { name: "Verse", from: 4, to: 6 }, { name: "Outro", from: 6, to: 8 }, { name: "Verse", from: 8, to: 9 }, { name: "Solo", from: 9, to: 12 },
  ]);
  assert.equal(r.index, 1);
  // The music after the ending runs to 12 s, which the studio tells the person.
  assert.equal(r.later, 12);
  // A section after the ending that runs on past every note and hit counts too.
  assert.equal(addEnding({ ...solo, sections: [{ name: "Solo", from: 9, to: 14 }] }, { key: C }).later, 14);
  // A harmony voice note held past everything else after the ending counts too.
  assert.equal(addEnding({ ...solo, voice2: [...solo.voice2, { m: 72, t: 10, d: 5 }] }, { key: C }).later, 15);
  // A section alone after the ending, with no notes there, is reported as well.
  assert.equal(addEnding({ ...p, sections: [{ name: "Solo", from: 8, to: 10 }] }, { key: C }).later, 10);
  // Again: nothing changes.
  const again = addEnding({ ...solo, ...r }, { key: C });
  for (const k of ["notes", "harmony", "voice2", "drums", "sections"]) assert.deepEqual(again[k], r[k], k);
});
