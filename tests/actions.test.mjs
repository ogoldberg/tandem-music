// AI.7: actions.json declares each chat action once; actions.js runs them and tandem_backend.py validates
// them. These tests check the browser side agrees with the registry and the server's name tables.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { HANDLERS, applyActions, songSummary, MAX_SUMMARY_CHORDS, chatBody, CHAT_BODY_MAX_BYTES } from "../actions.js";
import { CHORD_QUALITIES, generateHarmony, readChords, chordName } from "../harmony.js";
import { KEY_NAMES } from "../contour.js";

const registry = JSON.parse(readFileSync(new URL("../actions.json", import.meta.url), "utf8"));
const backend = readFileSync(new URL("../tandem_backend.py", import.meta.url), "utf8");
const pyString = s => JSON.parse('"' + s + '"');

test("actions.js runs exactly the actions actions.json declares", () => {
  assert.deepEqual(Object.keys(HANDLERS), registry.actions.map(a => a.name));
  for (const a of registry.actions) {
    assert.ok(a.summary.startsWith(a.name + " "), a.name);
    assert.ok(a.description && a.params && a.parts, a.name);
  }
});

test("each handler changes the project as the chat always has", () => {
  const p = () => ({ bpm: 100, instrument: "piano", notes: [{ m: 60, t: 0, d: 1 }, { m: 95, t: 1, d: 1 }], drums: [{ k: "kick", t: 0 }] });
  const run = action => { const q = p(); assert.equal(applyActions(q, [action]), 1); return q; };
  assert.equal(run({ type: "set_tempo", bpm: 120 }).bpm, 120);
  assert.equal(run({ type: "set_instrument", instrument: "marimba" }).instrument, "marimba");
  assert.deepEqual(run({ type: "transpose", semitones: 3 }).notes.map(n => n.m), [63, 96]);
  assert.deepEqual(run({ type: "transpose", semitones: -30 }).notes.map(n => n.m), [36, 65]);
  assert.deepEqual(run({ type: "add_note", pitch: 72, start: 2, duration: 0.5 }).notes.at(-1), { m: 72, t: 2, d: 0.5 });
  assert.deepEqual(run({ type: "add_hit", drum: "hat", start: 0.5 }).drums.at(-1), { k: "hat", t: 0.5 });
  assert.deepEqual(run({ type: "remove_track", track: "melody" }).notes, []);
  const rhythm = run({ type: "remove_track", track: "rhythm" });
  assert.deepEqual([rhythm.drums, rhythm.notes.length], [[], 2]);
  assert.deepEqual(run({ type: "replace_notes", notes: [{ m: 70, t: 0, d: 1 }] }).notes, [{ m: 70, t: 0, d: 1 }]);
  assert.deepEqual(run({ type: "replace_drums", drums: [{ k: "snare", t: 1 }] }).drums, [{ k: "snare", t: 1 }]);
});

test("applyActions skips what the studio does not know, in order, and counts what ran", () => {
  const q = { bpm: 100, instrument: "piano", notes: [], drums: [] };
  assert.equal(applyActions(q, [{ type: "set_tempo", bpm: 90 }, { type: "execute_python" }, null, { type: "toString" }, { type: "set_tempo", bpm: 80 }]), 2);
  assert.equal(q.bpm, 80);
  assert.equal(applyActions(q, undefined), 0);
});

test("the server names keys and chords as the studio does", () => {
  const keys = backend.match(/^KEY_NAMES=\(([^)]*)\)/m);
  assert.ok(keys, "KEY_NAMES found in tandem_backend.py");
  assert.deepEqual([...keys[1].matchAll(/"([^"]*)"/g)].map(m => pyString(m[1])), KEY_NAMES);
  const suffixes = backend.match(/^CHORD_SUFFIXES=\{([^}]*)\}/m);
  assert.ok(suffixes, "CHORD_SUFFIXES found in tandem_backend.py");
  const pairs = [...suffixes[1].matchAll(/"([^"]*)":"([^"]*)"/g)].map(m => [m[1], pyString(m[2])]);
  assert.deepEqual(pairs, CHORD_QUALITIES.map(q => [q.id, q.suffix]));
});

test("songSummary gives the key shown and the chords readChords names in it", () => {
  const notes = [60, 64, 67, 69, 67, 64, 62, 60].map((m, i) => ({ m, t: i * 0.45, d: 0.4 }));
  const key = { tonic: 0, mode: "major" };
  const project = { bpm: 100, notes, drums: [], harmony: generateHarmony({ bpm: 100, notes }, { key }).notes };
  const s = songSummary(project, { key });
  const read = readChords(project.harmony, { bpm: 100, key });
  assert.ok(read.length >= 2);
  assert.deepEqual(s.key, key);
  assert.deepEqual(s.chords.map(c => KEY_NAMES[c.root] + CHORD_QUALITIES.find(q => q.id === c.quality).suffix), read.map(c => c.name));
  assert.deepEqual(s.chords.map(c => [c.t, c.d]), read.map(c => [Math.round(c.t * 1000) / 1000, Math.round(c.d * 1000) / 1000]));
  assert.deepEqual(s.chords.map(c => chordName(c)), read.map(c => c.name));
  // No key passed: the melody's detected key; none chosen and too few notes: no key, and no chords part, no chords.
  assert.deepEqual(songSummary(project).key, key);
  assert.deepEqual(songSummary({ bpm: 100, notes: notes.slice(0, 2), drums: [] }), { key: null, chords: [] });
  assert.deepEqual(songSummary({ bpm: 100, notes, drums: [] }, { key: null }), { key: null, chords: [] });
});

test("songSummary keeps at most MAX_SUMMARY_CHORDS chords and refuses a project without a tempo", () => {
  const harmony = [];
  for (let b = 0; b < MAX_SUMMARY_CHORDS + 10; b++) for (const x of [0, 4, 7]) harmony.push({ m: 60 + x + (b % 2 ? 2 : 0), t: b * 2.4, d: 2.3 });
  assert.equal(songSummary({ bpm: 100, notes: [], harmony }, { key: null }).chords.length, MAX_SUMMARY_CHORDS);
  assert.throws(() => songSummary({ bpm: 0, notes: [], harmony }, { key: null }), /tempo/);
});

test("chatBody sends the summary only when the request fits the server's limit", () => {
  const guards = readFileSync(new URL("../request_guards.py", import.meta.url), "utf8");
  assert.equal(CHAT_BODY_MAX_BYTES, Number(guards.match(/^CHAT_BODY_MAX_BYTES = ([\d_]+)$/m)[1].replaceAll("_", "")));
  const song = { key: { tonic: 0, mode: "major" }, chords: [{ t: 0, d: 2.4, root: 0, quality: "major" }] };
  const bytes = x => new TextEncoder().encode(x).length;
  // A message of multi-byte characters: the limit is in UTF-8 bytes, not characters.
  const body = n => ({ message: "\u00e9".repeat(n), project: {}, history: [], song });
  const withSong = bytes(JSON.stringify(body(0)));
  const fits = (CHAT_BODY_MAX_BYTES - withSong) / 2;   // each e-acute is 2 bytes
  assert.equal(bytes(chatBody(body(fits))), CHAT_BODY_MAX_BYTES);
  assert.deepEqual(JSON.parse(chatBody(body(fits))).song, song);
  const over = JSON.parse(chatBody(body(fits + 1)));
  assert.equal(over.song, undefined);
  assert.equal(over.message.length, fits + 1);
  // Without a summary the body is the plain JSON, whatever its size.
  const plain = { message: "x".repeat(CHAT_BODY_MAX_BYTES), project: {} };
  assert.equal(chatBody(plain), JSON.stringify(plain));
});
