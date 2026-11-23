import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { songSheet, sheetText, CHORD_LINE_BARS } from "../sheet.js";
import { lyricLines, syllables } from "../lyrics.js";

// At 120 bpm a beat is 0.5 s and a bar 2 s.
const chord = (ms, t, d) => ms.map(m => ({ m, t, d }));
const C = [48, 52, 55], F = [53, 57, 60], G = [55, 59, 62], Am = [57, 60, 64];
const tune = beats => beats.map(([m, beat, len = 1]) => ({ m, t: beat * 0.5, d: len * 0.5 * 0.9 }));
const words = sheet => sheet.blocks.map(b => [b.section, b.lines.map(l => l.kind === "chords"
  ? "| " + l.segments.map(s => s.chords.join(" ")).join(" ")
  : l.segments.map(s => (s.chords.length ? "[" + s.chords.join(" ") + "]" : "") + s.text + (s.joined ? "" : " ")).join("").trim())]);

test("SHEET.1: the notation fixture as a sheet: each chord over the syllable sung when it starts, sections as blocks", async () => {
  const { project, key } = JSON.parse(await readFile(new URL("./fixtures/notation-project.json", import.meta.url), "utf8"));
  // Its chords are F, C, B♭, F, one a bar (2.5 s at 96 bpm) from 0.013 s; the words on two lines.
  const song = { ...project, lyrics: "Sing it slow-ly, sing it _ low,\nand let the morn-ing come", sections: [{ name: "Verse", from: 0, to: 5 }, { name: "Chorus", from: 5, to: 11 }] };
  const sheet = songSheet(song, { key, title: "  Morning  " });
  assert.equal(sheet.title, "Morning");
  assert.equal(sheet.key, "F major");
  assert.equal(sheet.bpm, 96);
  // C starts at 2.513 s while "sing" (1.875 s) is held; B♭ at 5.013 s, in the rest before "and" (5.625 s), leads into the
  // second line; F at 7.513 s is struck on "come" (7.5 s, within half a sixteenth).
  assert.deepEqual(words(sheet), [
    ["Verse", ["[F]Sing it slowly, [C]sing it low,"]],
    ["Chorus", ["[B♭] and let the morning [F]come"]],
  ]);
  assert.equal(sheetText(sheet), [
    "Morning", "F major, 96 bpm", "", "[Verse]",
    "F               C",
    "Sing it slowly, sing it low,", "", "[Chorus]",
    "B♭                     F",
    "   and let the morning come", "",
  ].join("\n"));
});

test("SHEET.1: chords with no words under them: an intro line, a lead into the line, a break and an ending", () => {
  // Bars 1-5 chords alone (C F G Am C), words from 10.5 s ("three" held over the bar line at 12 s), a break, two more
  // words from 17 s ("five" held over 18 s), then two bars alone.
  const notes = tune([[60, 21], [62, 22], [64, 23, 2], [65, 34], [67, 35, 2]]);
  const harmony = [C, F, G, Am, C, F, G, Am, C, F, G, Am].flatMap((c, i) => chord(c, i * 2, 2));
  const sheet = songSheet({ bpm: 120, notes, harmony, lyrics: "one two three\nfour five" });
  assert.deepEqual(words(sheet), [[null, [
    // Bars 1-4 and bar 5: a chord line holds at most four bars. Bar 6's F (10 s) is a bar before "one" (10.5 s): a lead.
    "| C F G Am", "| C",
    "[F] one two [G]three",
    // Am (14 s) in the break; C (16 s) is a bar before "four" (17 s): it leads into the line. F (18 s) is on the held "five".
    "| Am",
    "[C] four [F]five",
    // After the last word: G, Am.
    "| G Am",
  ]]]);
  assert.equal(CHORD_LINE_BARS, 4);
});

test("SHEET.1: a chord over a held syllable, two chords on one syllable, and a chord only after silence is written again", () => {
  // "hold" is sung for two bars: C then F under it; "on" for a beat over G, G again after a bar of silence.
  const notes = tune([[60, 0, 8], [62, 8], [64, 16]]);
  const harmony = [...chord(C, 0, 2), ...chord(F, 2, 2), ...chord(G, 4, 2), ...chord(G, 6, 2), ...chord(G, 8.5, 1.5)];
  const sheet = songSheet({ bpm: 120, notes, harmony, lyrics: "hold on _ now" });
  // G at 4 s is held into the next bar (6 s): written once. The G at 8.5 s comes after 0.5 s of silence: written again,
  // after the words, since "on" (held over the note at 8 s by "_") has ended by then.
  assert.deepEqual(words(sheet), [[null, ["[C F]hold [G]on now", "| G"]]]);
});

test("SHEET.1: sections: lines go to the section their first word or chord is in, an empty section still shows", () => {
  const notes = tune([[60, 0], [62, 1], [64, 8], [65, 9], [67, 16]]);
  const harmony = [...chord(C, 0, 2), ...chord(G, 4, 2), ...chord(Am, 8, 2)];
  const sections = [{ name: "Verse", from: 0, to: 4 }, { name: "Chorus", from: 4, to: 8 }, { name: "Solo", from: 8, to: 10 }, { name: "Outro", from: 12, to: 14 }];
  const sheet = songSheet({ bpm: 120, notes, harmony, sections, lyrics: "la la\nhey ho\nend\nmore words here" });
  assert.deepEqual(words(sheet), [
    ["Verse", ["[C]la la"]],
    ["Chorus", ["[G]hey ho"]],
    // Am at 8 s is struck on "end" (8 s), in the Solo; the words with no note left stay in the block before them.
    ["Solo", ["[Am]end", "more words here"]],
    ["Outro", []],
  ]);
});

test("SHEET.1: a blank line in the words starts a stanza; words with no note yet are still on the sheet", () => {
  const notes = tune([[60, 0], [62, 1]]);
  const sheet = songSheet({ bpm: 120, notes, harmony: chord(C, 0, 2), lyrics: "one two\n\n  \nthree four" });
  assert.deepEqual(sheet.blocks[0].lines.map(l => [l.stanza, l.segments.map(s => s.text).join(" ")]), [[false, "one two"], [true, "three four"]]);
  assert.match(sheetText(sheet), /one two\n\nthree four\n$/);
  // No notes at all: the chords first, then the words.
  const bare = songSheet({ bpm: 120, notes: [], harmony: chord(C, 0, 2), lyrics: "just words" });
  assert.deepEqual(words(bare), [[null, ["| C", "just words"]]]);
});

test("SHEET.1: only words, only chords, and nothing", () => {
  assert.deepEqual(words(songSheet({ bpm: 120, notes: tune([[60, 0]]), lyrics: "hi" })), [[null, ["hi"]]]);
  assert.deepEqual(words(songSheet({ bpm: 120, notes: [], harmony: [C, F].flatMap((c, i) => chord(c, i * 2, 2)) })), [[null, ["| C F"]]]);
  assert.throws(() => songSheet({ bpm: 120, notes: tune([[60, 0]]), lyrics: "  " }), /Nothing for a song sheet yet/);
  assert.throws(() => songSheet({ bpm: 0, notes: [], lyrics: "hi" }), /Set a tempo/);
  assert.equal(songSheet({ bpm: 120, lyrics: "hi" }).title, "Untitled song");
  assert.equal(songSheet({ bpm: 120, lyrics: "hi" }).key, null);
});

test("SHEET.1: lyricLines keeps each typed line's syllables, and syllables is them in order", () => {
  const text = "Twin-kle twin-kle\nlit-tle _ star\n\nhow I won-\nder";
  assert.deepEqual(lyricLines(text).map(l => [l.stanza, l.tokens.map(t => t.hold ? "_" : t.text)]), [
    [false, ["Twin", "kle", "twin", "kle"]], [false, ["lit", "tle", "_", "star"]], [true, ["how", "I", "won", "der"]],
  ]);
  assert.deepEqual(lyricLines(text).flatMap(l => l.tokens), syllables(text));
  assert.deepEqual(lyricLines(""), []);
});

test("SHEET.1: a word sung a little late still takes the chord struck just before it, up to half a sixteenth", () => {
  // At 120 bpm half a sixteenth is 62.5 ms. G is struck at 2 s; "two" is sung 30 ms late, then 100 ms late.
  const at = late => songSheet({ bpm: 120, notes: [{ m: 60, t: 0, d: 1.8 }, { m: 62, t: 2 + late, d: 0.9 }],
    harmony: [...chord(C, 0, 2), ...chord(G, 2, 2)], lyrics: "one two" });
  assert.deepEqual(words(at(0.03)), [[null, ["[C]one [G]two"]]]);
  assert.deepEqual(words(at(0.1)), [[null, ["[C G]one two"]]]);
});
