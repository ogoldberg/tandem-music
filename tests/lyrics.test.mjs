import test from "node:test";
import assert from "node:assert/strict";
import { syllables, assignLyrics, cleanLyrics, onsets, shown, lyricsSummary, sixteenth, MAX_LYRICS } from "../lyrics.js";
import { musicXml } from "../notation.js";

// 120 bpm: a beat is 0.5 s, a sixteenth 0.125 s.
const line = (...ms) => ms.map((m, i) => ({ m, t: i * 0.5, d: 0.45 }));
const texts = (notes, lyrics, bpm = 120) => assignLyrics(notes, lyrics, bpm).byNote.map(e => (e ? (e.held ? "_" : e.text) : null));

test("words split into syllables by spaces and hyphens, with their MusicXML syllabic", () => {
  assert.deepEqual(syllables("Twin-kle star  beau-ti-ful\nnight"), [
    { text: "Twin", syllabic: "begin" }, { text: "kle", syllabic: "end" },
    { text: "star", syllabic: "single" },
    { text: "beau", syllabic: "begin" }, { text: "ti", syllabic: "middle" }, { text: "ful", syllabic: "end" },
    { text: "night", syllabic: "single" },
  ]);
  // A hyphen typed with a space on either side, as notation apps type it, still joins the word.
  assert.deepEqual(syllables("slow- ly so -ft"), syllables("slow-ly so-ft"));
  // Punctuation stays on its syllable.
  assert.deepEqual(syllables("Oh, yeah!").map(s => s.text), ["Oh,", "yeah!"]);
});

test("an underscore holds the syllable before it, alone or stuck to a word", () => {
  const hold = { hold: true };
  assert.deepEqual(syllables("it _ low"), [{ text: "it", syllabic: "single" }, hold, { text: "low", syllabic: "single" }]);
  assert.deepEqual(syllables("it_ low"), syllables("it _ low"));
  assert.deepEqual(syllables("it__"), [{ text: "it", syllabic: "single" }, hold, hold]);
  assert.deepEqual(syllables("_ it"), [hold, { text: "it", syllabic: "single" }]);
});

test("syllables land on the melody notes in time order, not in array order", () => {
  const notes = [{ m: 64, t: 1, d: 0.4 }, { m: 60, t: 0, d: 0.4 }, { m: 62, t: 0.5, d: 0.4 }];
  assert.deepEqual(texts(notes, "one two three"), ["three", "one", "two"]);
});

test("notes starting on the same sixteenth are one chord and take one syllable, on the highest note", () => {
  // 0.51 s and 0.53 s both round to sixteenth 4 at 120 bpm.
  const notes = [{ m: 60, t: 0, d: 0.4 }, { m: 62, t: 0.51, d: 0.4 }, { m: 67, t: 0.53, d: 0.4 }, { m: 64, t: 1, d: 0.4 }];
  assert.equal(sixteenth(0.51, 120), sixteenth(0.53, 120));
  assert.deepEqual(onsets(notes, 120).map(o => [o.at, o.note]), [[0, 0], [4, 2], [8, 3]]);
  assert.deepEqual(texts(notes, "a b c"), ["a", null, "b", "c"]);
});

test("a hold puts no word on the note and marks the syllable it holds; the last held note ends the line", () => {
  const { byNote } = assignLyrics(line(60, 62, 64, 65, 67), "sing it _ _ low", 120);
  assert.deepEqual(byNote, [
    { text: "sing", syllabic: "single", extend: false },
    { text: "it", syllabic: "single", extend: true },
    { held: true, last: false },
    { held: true, last: true },
    { text: "low", syllabic: "single", extend: false },
  ]);
  // A hold before any syllable leaves the note bare: a pickup note with no word.
  assert.deepEqual(texts(line(60, 62, 64), "_ la la"), [null, "la", "la"]);
});

test("syllables past the last note and notes past the last syllable are counted", () => {
  const few = assignLyrics(line(60, 62), "one two three four", 120);
  assert.deepEqual([few.words, few.left, few.bare], [2, 2, 0]);
  const many = assignLyrics(line(60, 62, 64, 65), "one two", 120);
  assert.deepEqual([many.words, many.left, many.bare], [2, 0, 2]);
  assert.equal(lyricsSummary(line(60, 62), "one two three", 120), "2 syllables on the notes; 1 more has no note yet.");
  assert.equal(lyricsSummary(line(60, 62, 64), "one", 120), "1 syllable on the notes; 2 notes have no word.");
  assert.equal(lyricsSummary(line(60), "  ", 120), "");
});

test("editing the notes moves no word: the syllables flow onto the notes again in order", () => {
  const notes = line(60, 62, 64);
  assert.deepEqual(texts(notes, "a b c"), ["a", "b", "c"]);
  // Delete the first note: every word moves up one note.
  assert.deepEqual(texts(notes.slice(1), "a b c"), ["a", "b"]);
  // Notes with no length or broken values carry no word and take none.
  assert.deepEqual(texts([{ m: 60, t: 0, d: 0 }, ...notes], "a b c"), [null, "a", "b", "c"]);
});

test("the roll shows a hyphen after a syllable the word goes on from", () => {
  const { byNote } = assignLyrics(line(60, 62, 64, 65), "beau-ti-ful _", 120);
  assert.deepEqual(byNote.map(shown), ["beau-", "ti-", "ful", ""]);
});

test("cleanLyrics keeps the text as typed, refuses what is not text or too long", () => {
  assert.equal(cleanLyrics(undefined), "");
  assert.equal(cleanLyrics("   \n "), "");
  assert.equal(cleanLyrics("la\r\nla\rla"), "la\nla\nla");
  assert.equal(cleanLyrics(" la la "), " la la ");
  assert.throws(() => cleanLyrics(5), /text/);
  assert.throws(() => cleanLyrics("a".repeat(MAX_LYRICS + 1)), /too long/);
  assert.equal(cleanLyrics("a".repeat(MAX_LYRICS)).length, MAX_LYRICS);
});

test("MusicXML writes each syllable on the first note of its chord and only on the first piece of a tied note", () => {
  const project = {
    bpm: 120, drums: [], lyrics: "a <b> c-d _",
    // A chord on beat 1, a note tied across the barline, then two notes the last syllable is held over.
    notes: [{ m: 60, t: 0, d: 0.5 }, { m: 64, t: 0, d: 0.5 }, { m: 62, t: 1.5, d: 1 }, { m: 65, t: 2.5, d: 0.5 }, { m: 67, t: 3, d: 0.5 }, { m: 69, t: 3.5, d: 0.5 }],
  };
  const xml = musicXml(project);
  const notes = [...xml.matchAll(/<note>([\s\S]*?)<\/note>/g)].map(x => x[1]).filter(n => !n.includes("<rest"));
  const lyric = n => n.match(/<lyric number="1">([\s\S]*?)<\/lyric>/)?.[1] ?? null;
  assert.deepEqual(notes.map(lyric), [
    "<syllabic>single</syllabic><text>a</text>", null,
    // The tied note: its first piece has the word, the piece after the barline has none.
    "<syllabic>single</syllabic><text>&lt;b&gt;</text>", null,
    "<syllabic>begin</syllabic><text>c</text>",
    '<syllabic>end</syllabic><text>d</text><extend type="start"/>',
    // The note "d" is held over ends its extend line and has no word of its own.
    '<extend type="stop"/>',
  ]);
  // The harmony part never carries the words.
  const withHarmony = musicXml({ ...project, harmony: [{ m: 48, t: 0, d: 2 }] });
  const harmony = withHarmony.slice(withHarmony.indexOf('<part id="P2">'));
  assert.ok(!harmony.includes("<lyric"));
  // A project without lyrics writes the same score as before LYR.1.
  const { lyrics, ...plain } = project;
  assert.ok(!musicXml(plain).includes("<lyric"));
});

test("versions, drafts and Tandem files keep the lyrics, and leave the field out when there are none", async () => {
  const { projectFromState } = await import("../versions.js");
  const { writeBundle, readBundle } = await import("../bundle.js");
  const base = { bpm: 120, instrument: "piano", notes: line(60, 62), drums: [] };
  assert.equal("lyrics" in projectFromState(base), false);
  assert.equal("lyrics" in projectFromState({ ...base, lyrics: " \n " }), false);
  const project = projectFromState({ ...base, lyrics: "la-la\nla" });
  assert.equal(project.lyrics, "la-la\nla");
  const back = await readBundle(writeBundle({ project, recordings: {} }));
  assert.equal(back.project.lyrics, "la-la\nla");
});
