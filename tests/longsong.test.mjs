// GROW.2: room for a whole song. The studio holds 4,096 notes or hits a part and a starter beat of 256 bars;
// the chat still carries 1,024 a part and refuses a longer song in words. A song at the new size goes through
// section repeat, quantize, every exporter and the project checks.
import test from "node:test";
import assert from "node:assert/strict";
import { MAX_EVENTS, repeatSection, cleanSections } from "../sections.js";
import { MAX_MELODY_NOTES, copyPhraseToEnd, detectPhrases } from "../phrases.js";
import { MAX_HARMONY_NOTES } from "../harmony.js";
import { MAX_BARS, grooveHits } from "../beats.js";
import { quantizeProject, GRID_DIVISIONS } from "../groove.js";
import { midiFile } from "../daw.js";
import { musicXml } from "../notation.js";
import { projectXml } from "../dawproject.js";
import { projectFromState, checkUses } from "../versions.js";
import { writeBundle, readBundle } from "../bundle.js";
import { CHAT_LIMITS, chatTooLong, applyActions } from "../actions.js";

const PARTS = ["notes", "harmony", "voice2", "drums"];
// `n` events a part over the first `seconds`, the drums on a 16th grid of their own.
function song(n, { seconds = 590, bpm = 120 } = {}) {
  const step = seconds / n;
  const note = i => ({ m: 55 + (i * 7) % 24, t: Math.round(i * step * 1000) / 1000, d: Math.round(step * 0.8 * 1000) / 1000 });
  const kinds = ["kick", "hat", "snare", "hat"];
  return {
    bpm, instrument: "piano", melody_locked: true,
    notes: Array.from({ length: n }, (_, i) => note(i)),
    harmony: Array.from({ length: n }, (_, i) => ({ ...note(i), m: 48 + (i * 5) % 19 })),
    voice2: Array.from({ length: n }, (_, i) => ({ ...note(i), m: 59 + (i * 7) % 24 })),
    drums: Array.from({ length: n }, (_, i) => ({ k: kinds[i % 4], t: Math.round(i * step * 1000) / 1000 })),
  };
}

test("every part's studio cap is 4,096 and a beat may be 256 bars", () => {
  assert.equal(MAX_EVENTS, 4096);
  assert.equal(MAX_MELODY_NOTES, MAX_EVENTS);
  assert.equal(MAX_HARMONY_NOTES, MAX_EVENTS);
  assert.equal(MAX_BARS, 256);
  // The chat keeps its own cap (ChatProject in tandem_backend.py; tests/actions.test.mjs checks the mirror).
  assert.equal(CHAT_LIMITS.items, 1024);
});

test("a section repeat fills a part up to 4,096 and no further", () => {
  const p = song(2048, { seconds: 290 });
  p.sections = [{ name: "Verse", from: 0, to: 290 }];
  const r = repeatSection(p, 0);
  for (const k of PARTS) assert.equal(r.project[k].length, 4096, k);
  assert.ok(r.project.notes.at(-1).t < 600);
  cleanSections(r.project.sections);
  const over = song(2049, { seconds: 290 });
  over.sections = [{ name: "Verse", from: 0, to: 290 }];
  assert.throws(() => repeatSection(over, 0), /more than 4096/);
});

test("a phrase copied onto a 4,095-note melody fills it, one more is refused", () => {
  const notes = Array.from({ length: 4095 }, (_, i) => ({ m: 60, t: Math.round(i * 0.1 * 1000) / 1000, d: 0.05 }));
  const ps = detectPhrases(notes, { bpm: 120 });
  assert.equal(copyPhraseToEnd(notes, { ...ps[0], indices: [0] }, { bpm: 120 }).notes.length, 4096);
  assert.throws(() => copyPhraseToEnd(notes, { ...ps[0], indices: [0, 1] }, { bpm: 120 }), /more than 4096/);
});

test("quantize keeps every one of 4,096 events a part", () => {
  const q = quantizeProject(song(4096), { division: GRID_DIVISIONS["1/16"] });
  for (const k of PARTS) assert.equal(q[k].length, 4096, k);
});

// Note-ons in a Standard MIDI File, by channel.
function noteOns(bytes) {
  const u32 = at => ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0;
  const count = (bytes[10] << 8) | bytes[11], ons = {};
  let at = 14;
  for (let n = 0; n < count; n++) {
    const end = at + 8 + u32(at + 4);
    let i = at + 8, running = 0, b;
    while (i < end) {
      do { b = bytes[i++]; } while (b & 128);
      let status = bytes[i];
      if (status & 128) i++; else status = running;
      if (status === 0xff) {
        i++;
        let len = 0;
        do { b = bytes[i++]; len = (len << 7) | (b & 127); } while (b & 128);
        i += len;
      } else {
        running = status;
        const kind = status >> 4, size = kind === 0xc || kind === 0xd ? 1 : 2;
        if (kind === 9 && bytes[i + 1] > 0) ons[status & 15] = (ons[status & 15] ?? 0) + 1;
        i += size;
      }
    }
    at = end;
  }
  return ons;
}

test("the MIDI file, MusicXML and DAWproject carry every one of 4,096 events a part", () => {
  const p = song(4096);
  const ons = noteOns(midiFile(p));
  assert.equal(Object.values(ons).reduce((a, b) => a + b, 0), 4 * 4096);
  assert.equal(ons[9], 4096, "drums on channel 10");
  const xml = musicXml(p);
  // Melody (P1) and harmony (P2) notes: each sounding note is at least one <note> with a pitch, ties split more.
  for (const id of ["P1", "P2"]) {
    const part = xml.match(new RegExp(`<part id="${id}">([\\s\\S]*?)</part>`))[1];
    const starts = (part.match(/<pitch>/g) || []).length - (part.match(/<tie type="stop"\/>/g) || []).length;
    assert.ok(starts >= 4096 * 0.9, `${id}: ${starts}`);
  }
  const daw = projectXml(p, { rate: 44100 });
  assert.equal((daw.match(/<Note /g) || []).length, 4 * 4096);
});

test("a 4,096-event song saves and opens as a Tandem file", async () => {
  const p = projectFromState(song(4096));
  checkUses(p.uses);
  const back = await readBundle(writeBundle({ name: "Long", project: p }));
  for (const k of PARTS) assert.equal(back.project[k].length, 4096, k);
});

test("the chat reads up to 1,024 a part and refuses a longer song in words, never cut short", () => {
  assert.equal(chatTooLong(song(1024)), "");
  assert.equal(chatTooLong({ notes: [], drums: [] }), "");
  const beat = { ...song(16), drums: grooveHits("straight", { bpm: 120, bars: 90 }) };
  assert.equal(beat.drums.length, 1080);
  assert.equal(chatTooLong(beat), "This song is too long for Ask Tandem to read yet: the drums have 1080 hits, and Ask Tandem reads up to 1024 a part. Nothing was sent.");
  const all = song(1025);
  assert.match(chatTooLong(all), /the melody has 1025 notes, the chords part has 1025 notes, the harmony voice has 1025 notes, the drums have 1025 hits/);
  // A chat action still may not make a part longer than the chat carries (64 bars of beat at most).
  const problems = [];
  assert.equal(applyActions(song(16), [{ type: "add_beat", groove: "straight", bars: 64 }], { problems }), 1);
  assert.deepEqual(problems, []);
});
