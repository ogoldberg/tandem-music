// AI.7: actions.json declares each chat action once; actions.js runs them and tandem_backend.py validates
// them. These tests check the browser side agrees with the registry and the server's name tables.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { HANDLERS, applyActions, songSummary, MAX_SUMMARY_CHORDS, chatBody, CHAT_BODY_MAX_BYTES, CHAT_LIMITS } from "../actions.js";
import { CHORD_QUALITIES, generateHarmony, readChords, chordName } from "../harmony.js";
import { KEY_NAMES } from "../contour.js";
import { GROOVES, grooveHits } from "../beats.js";
import { GENRE_IDS, genreChanges, harmonyStyle } from "../genre.js";

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
  // Without a summary or a history the body is the plain JSON, whatever its size.
  const plain = { message: "x".repeat(CHAT_BODY_MAX_BYTES), project: {} };
  assert.equal(chatBody(plain), JSON.stringify(plain));
  // Still over without the summary: the oldest turns of the history go, one by one, until it fits.
  const turn = i => ({ role: i % 2 ? "assistant" : "user", content: String(i).repeat(3000) });
  const big = { message: "m", project: { lyrics: "x".repeat(CHAT_BODY_MAX_BYTES - 20_000) }, history: Array.from({ length: 10 }, (_, i) => turn(i)), song };
  const sent = JSON.parse(chatBody(big));
  assert.ok(bytes(chatBody(big)) <= CHAT_BODY_MAX_BYTES);
  assert.equal(sent.song, undefined);
  assert.deepEqual(sent.history, big.history.slice(-sent.history.length));
  assert.ok(sent.history.length >= 5 && sent.history.length < 10, String(sent.history.length));
  // One turn fewer would not have fitted: only as many go as must.
  assert.ok(bytes(JSON.stringify({ ...sent, history: big.history.slice(-(sent.history.length + 1)) })) > CHAT_BODY_MAX_BYTES);
});

// AI.6: the three actions that run the studio's own generators.
const melody = [60, 64, 67, 69, 67, 64, 62, 60].map((m, i) => ({ m, t: i * 0.45, d: 0.4 }));
const song = () => ({ bpm: 100, instrument: "piano", notes: melody.map(n => ({ ...n })), drums: [{ k: "kick", t: 0 }], harmony: [], harmony_instrument: "piano" });

test("the server's groove and genre choices are the studio's", () => {
  const grooves = backend.match(/^GROOVES=\(([^)]*)\)/m);
  assert.ok(grooves, "GROOVES found in tandem_backend.py");
  assert.deepEqual([...grooves[1].matchAll(/"([^"]*)"/g)].map(m => m[1]), GROOVES.map(g => g.id));
  assert.match(backend, /"\$GENRE_CHOICES":\("none",\)\+GENRE_IDS/);
  assert.ok(!GENRE_IDS.includes("none"));
});

test("generate_harmony writes what Generate writes, in the key given or the melody's, in the genre's feel", () => {
  for (const style of ["chords", "bass"]) for (const genre of [null, "jazz"]) for (const key of [null, { tonic: 7, mode: "major" }]) {
    const p = { ...song(), genre };
    const want = generateHarmony(p, { style, key, feel: harmonyStyle(genre) }).notes;
    assert.equal(applyActions(p, [{ type: "generate_harmony", style }], { key }), 1);
    assert.deepEqual(p.harmony, want, `${style} ${genre} ${key && key.tonic}`);
    assert.ok(want.length > 0);
  }
  // A bass line into an empty chords part on the default piano plays on bass, as Generate does; chords stay on piano.
  const b = song(); applyActions(b, [{ type: "generate_harmony", style: "bass" }]);
  assert.equal(b.harmony_instrument, "bass");
  const c = song(); applyActions(c, [{ type: "generate_harmony", style: "chords" }]);
  assert.equal(c.harmony_instrument, "piano");
  // Read after the reply's earlier actions: a transpose first moves the key the chords are in.
  const t = song(), up = song();
  applyActions(t, [{ type: "transpose", semitones: 2 }, { type: "generate_harmony", style: "chords" }]);
  up.notes = up.notes.map(n => ({ ...n, m: n.m + 2 }));
  assert.deepEqual(t.harmony, generateHarmony(up, { style: "chords" }).notes);
});

test("add_beat replaces the drums with the starter beat from the song's bar grid", () => {
  for (const g of GROOVES) {
    const p = song();
    applyActions(p, [{ type: "add_beat", groove: g.id, bars: 4 }]);
    assert.deepEqual(p.drums, grooveHits(g.id, { bpm: 100, bars: 4, from: 0 }), g.id);
  }
  // Sung in free time, the melody's first bar line is the grid, as Starter beat uses (groove.js barOrigin).
  const free = song(); free.notes = free.notes.map(n => ({ ...n, t: n.t + 0.7 }));
  applyActions(free, [{ type: "add_beat", groove: "straight", bars: 2 }]);
  assert.ok(free.drums[0].t > 0 && free.drums[0].t < 2.4, free.drums[0].t);
});

test("set_genre changes what the Genre menu changes; none clears the genre and keeps the instruments", () => {
  const p = song();
  applyActions(p, [{ type: "set_genre", genre: "jazz" }]);
  assert.deepEqual({ genre: p.genre, instrument: p.instrument, harmony_instrument: p.harmony_instrument }, genreChanges("jazz"));
  applyActions(p, [{ type: "set_genre", genre: "none" }]);
  assert.equal(p.genre, null);
  assert.equal(p.instrument, genreChanges("jazz").instrument);
  // The song's own genre again changes nothing, as in the Genre menu: instruments chosen since are kept.
  const own = { ...song(), genre: "jazz", instrument: "flute", harmony_instrument: "guitar" };
  assert.equal(applyActions(own, [{ type: "set_genre", genre: "jazz" }]), 1);
  assert.deepEqual([own.genre, own.instrument, own.harmony_instrument], ["jazz", "flute", "guitar"]);
  const none = { ...song(), instrument: "flute" };
  applyActions(none, [{ type: "set_genre", genre: "none" }]);
  assert.equal(none.instrument, "flute");
  assert.ok(!("genre" in none) || none.genre == null);
});

test("the chat limits are the server's ProjectNote and part limits", () => {
  assert.match(backend, /class ProjectNote\(BaseModel\):[^]*?t: float = Field\(ge=0,le=600,/);
  assert.match(backend, /class ProjectNote\(BaseModel\):[^]*?d: float = Field\(gt=0,le=600,/);
  assert.match(backend, /class ProjectHit\(BaseModel\):[^]*?t: float = Field\(ge=0,le=600,/);
  for (const part of ["notes", "drums", "harmony"]) assert.match(backend, new RegExp(`\\n    ${part}: list\\[Project(Note|Hit)\\] = Field\\(default_factory=list,max_length=1024\\)`), part);
  assert.deepEqual({ ...CHAT_LIMITS }, { seconds: 600, items: 1024 });
});

test("a generated part the next chat request could not carry is refused, not kept", () => {
  // A melody near the 10-minute end: the chords run past it (the reviewer's case).
  const late = { bpm: 220, genre: "rock", notes: [{ m: 60, t: 597, d: 0.5 }, { m: 64, t: 598, d: 0.5 }, { m: 67, t: 599, d: 4 }], drums: [], harmony: [] };
  assert.ok(generateHarmony(late, { style: "chords", feel: harmonyStyle("rock") }).notes.some(n => n.t > 600), "the generator does run past");
  const problems = [];
  assert.equal(applyActions(late, [{ type: "generate_harmony", style: "chords" }], { problems }), 0);
  assert.deepEqual(late.harmony, []);
  assert.match(problems[0].message, /past 10 minutes/);
  // A beat stays inside 10 minutes (64 bars at the slowest 45 BPM is 341 s from the first bar line), but no groove
  // may give one part more hits than the chat can carry: 64 bars of every groove fit, and a longer list is refused.
  for (const g of GROOVES) {
    const p = song();
    assert.equal(applyActions(p, [{ type: "add_beat", groove: g.id, bars: 64 }], { problems }), 1, g.id);
    assert.ok(p.drums.length <= CHAT_LIMITS.items && p.drums.at(-1).t < CHAT_LIMITS.seconds, g.id);
  }
  assert.equal(problems.length, 1);
});

test("after a generated beat the next chat request still fits: the oldest history goes", () => {
  // The reviewer's case: a request near the cap, then a 64-bar shuffle that adds about 16 KB to the project.
  const notes = Array.from({ length: 1024 }, (_, i) => ({ m: 60 + i % 8, t: i * Math.PI / 20, d: Math.SQRT2 / 10 }));
  const project = { notes, voice2: notes, drums: [], harmony: [], bpm: 100, lyrics: "\u{1F3B5}".repeat(3900), melody_locked: true };
  const history = Array.from({ length: 10 }, (_, i) => ({ role: i % 2 ? "assistant" : "user", content: "\u{1F3B5}".repeat(i % 2 ? 2700 : 2990) }));
  const message = "\u{1F3B5}".repeat(2980) + " add a beat";
  const send = () => JSON.parse(chatBody({ project, history, message, song: songSummary(project) }));
  const bytes = () => new TextEncoder().encode(chatBody({ project, history, message, song: songSummary(project) })).length;
  assert.ok(bytes() <= CHAT_BODY_MAX_BYTES);
  assert.equal(send().history.length, 10);
  const problems = [];
  assert.equal(applyActions(project, [{ type: "add_beat", groove: "shuffle", bars: 64 }], { problems }), 1);
  assert.deepEqual(problems, []);
  assert.ok(bytes() <= CHAT_BODY_MAX_BYTES, String(bytes()));
  const sent = send();
  assert.equal(sent.message, message);
  assert.deepEqual(sent.project, JSON.parse(JSON.stringify(project)));
  assert.ok(sent.history.length < 10 && sent.history.length > 0, String(sent.history.length));
  assert.deepEqual(sent.history, history.slice(-sent.history.length));
});

test("an action that cannot run on this song is skipped with its reason and changes nothing", () => {
  const p = song(); p.notes = [];
  const before = structuredClone(p), problems = [];
  assert.equal(applyActions(p, [{ type: "generate_harmony", style: "chords" }, { type: "set_tempo", bpm: 90 }], { problems }), 1);
  assert.deepEqual(problems, [{ type: "generate_harmony", message: "Add or transcribe a melody before generating harmony." }]);
  assert.deepEqual({ ...p, bpm: 100 }, before);
  const q = song(); q.bpm = 0;
  applyActions(q, [{ type: "add_beat", groove: "straight", bars: 4 }], { problems });
  assert.equal(problems.length, 2);
  assert.deepEqual(q.drums, [{ k: "kick", t: 0 }]);
});
