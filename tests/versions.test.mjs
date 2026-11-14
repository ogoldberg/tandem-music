import test from "node:test";
import assert from "node:assert/strict";
import { createVersionStore, projectFromState, VERSIONS_KEY, MAX_VERSIONS, MAX_NAME_LENGTH } from "../versions.js";
import { memoryKV } from "./memory-kv.mjs";

const project = (bpm = 100, notes = [{ m: 60, t: 0, d: 0.4 }]) =>
  ({ bpm, instrument: "piano", melody_locked: true, notes, drums: [{ k: "kick", t: 0 }] });

function clock(start = 1_700_000_000_000) {
  let t = start;
  return () => (t += 1000);
}

const names = async store => (await store.list()).map(v => v.name);

test("projectFromState keeps the harmony part, and defaults it for projects without one", () => {
  const harmony = [{ m: 48, t: 0, d: 1.9 }, { m: 52, t: 0, d: 1.9 }];
  const p = projectFromState({ ...project(120), harmony, harmony_instrument: "organ" });
  assert.deepEqual(p.harmony, harmony);
  assert.equal(p.harmony_instrument, "organ");
  assert.deepEqual(projectFromState({ ...project(120), harmony: "junk" }).harmony, []);
});

test("projectFromState keeps the generated band only when there is one (GEN.2)", () => {
  const band = { id: "b-1", style: "rock", follows: "recording", seconds: 9, muted: true, model: "musicgen-melody" };
  assert.deepEqual(projectFromState({ ...project(), band }).band, band);
  assert.equal("band" in projectFromState({ ...project(), band: null }), false);
  assert.equal("band" in projectFromState(project()), false);
});

test("projectFromState keeps the voice played as an instrument only when there is one (TIMBRE.1)", () => {
  const timbre = { id: "t-1", instrument: "organ", source: "take", seconds: 7, muted: false, model: "rave" };
  assert.deepEqual(projectFromState({ ...project(), timbre }).timbre, timbre);
  assert.equal("timbre" in projectFromState({ ...project(), timbre: null }), false);
});

test("projectFromState keeps the sung harmony only when there is one (HARM.3)", () => {
  const voice2_sung = { id: "s-1", seconds: 9.5, muted: true, line: "89abcdef" };
  assert.deepEqual(projectFromState({ ...project(), voice2_sung }).voice2_sung, voice2_sung);
  assert.equal("voice2_sung" in projectFromState({ ...project(), voice2_sung: null }), false);
  assert.equal("voice2_sung" in projectFromState(project()), false);
});

test("projectFromState keeps the harmony voice and its instrument only when it has notes (HARM.1)", () => {
  const voice2 = [{ m: 64, t: 0, d: 0.4 }];
  const p = projectFromState({ ...project(), voice2, voice2_instrument: "strings" });
  assert.deepEqual(p.voice2, voice2);
  assert.equal(p.voice2_instrument, "strings");
  assert.equal(projectFromState({ ...project(), voice2 }).voice2_instrument, "piano");
  for (const empty of [[], undefined, "junk"]) {
    const q = projectFromState({ ...project(), voice2: empty, voice2_instrument: "organ" });
    assert.equal("voice2" in q || "voice2_instrument" in q, false);
  }
});

test("projectFromState keeps only the portable project fields", () => {
  const p = projectFromState({ ...project(120), extra: "x", melody_locked: false });
  assert.deepEqual(p, { format: "tandem-project", version: 1, bpm: 120, instrument: "piano", melody_locked: false, notes: [{ m: 60, t: 0, d: 0.4 }], drums: [{ k: "kick", t: 0 }], harmony: [], harmony_instrument: "piano" });
});

test("versions are kept under the IndexedDB key 'versions'", () => {
  assert.equal(VERSIONS_KEY, "versions");
});

test("needs a key-value store", () => {
  assert.throws(() => createVersionStore(null), TypeError);
  assert.throws(() => createVersionStore({ getItem() {}, setItem() {} }), TypeError, "a localStorage is no longer accepted");
});

test("starts empty", async () => {
  assert.deepEqual(await createVersionStore(memoryKV()).list(), []);
});

test("saves, lists newest first and restores a deep copy", async () => {
  const store = createVersionStore(memoryKV(), { now: clock() });
  const a = await store.save("Verse idea", project(90));
  const b = await store.save("  Chorus  ", project(130));
  assert.equal(b.name, "Chorus");
  assert.deepEqual(await names(store), ["Chorus", "Verse idea"]);
  const list = await store.list();
  assert.ok(list[0].savedAt > list[1].savedAt);
  assert.notEqual(a.id, b.id);

  const restored = await store.get(a.id);
  assert.equal(restored.bpm, 90);
  restored.notes.push({ m: 72, t: 1, d: 0.2 });
  assert.equal((await store.get(a.id)).notes.length, 1, "get returns a copy, not the stored object");
});

test("versions survive a new store over the same database (reload)", async () => {
  const kv = memoryKV();
  const first = createVersionStore(kv, { now: clock() });
  const v = await first.save("Keep me", project(111));
  const reloaded = createVersionStore(kv);
  assert.deepEqual(await names(reloaded), ["Keep me"]);
  assert.equal((await reloaded.get(v.id)).bpm, 111);
  assert.equal(kv.data.get(VERSIONS_KEY).length, 1);
});

test("saving copies the project, so later edits don't change the version", async () => {
  const store = createVersionStore(memoryKV(), { now: clock() });
  const p = project();
  const pending = store.save("Snapshot", p);
  // Even an edit made before the write finishes does not reach the stored version.
  p.notes.push({ m: 64, t: 1, d: 0.3 });
  p.bpm = 200;
  const v = await pending;
  assert.equal((await store.get(v.id)).notes.length, 1);
  assert.equal((await store.get(v.id)).bpm, 100);
});

test("ids stay unique when two versions are saved in the same millisecond", async () => {
  const store = createVersionStore(memoryKV(), { now: () => 5 });
  const ids = [];
  for (const n of ["a", "b", "c"]) ids.push((await store.save(n, project())).id);
  assert.equal(new Set(ids).size, 3);
});

test("saves started together are all kept", async () => {
  const store = createVersionStore(memoryKV(), { now: clock() });
  await Promise.all(["a", "b", "c"].map(n => store.save(n, project())));
  assert.deepEqual((await names(store)).sort(), ["a", "b", "c"]);
});

test("rejects empty names and trims long ones", async () => {
  const store = createVersionStore(memoryKV(), { now: clock() });
  await assert.rejects(store.save("   ", project()), /name/i);
  await assert.rejects(store.save(undefined, project()), /name/i);
  assert.equal((await store.save("x".repeat(200), project())).name.length, MAX_NAME_LENGTH);
});

test("rejects a project without note and drum lists", async () => {
  const store = createVersionStore(memoryKV(), { now: clock() });
  await assert.rejects(store.save("bad", { bpm: 100 }), /project/i);
  assert.deepEqual(await store.list(), []);
});

test("keeps at most the limit, dropping the oldest", async () => {
  const store = createVersionStore(memoryKV(), { now: clock(), limit: 3 });
  for (const n of ["v1", "v2", "v3", "v4"]) await store.save(n, project());
  assert.deepEqual(await names(store), ["v4", "v3", "v2"]);
  assert.equal(MAX_VERSIONS, 50);
});

test("remove deletes one version and reports whether it existed", async () => {
  const store = createVersionStore(memoryKV(), { now: clock() });
  const a = await store.save("a", project()), b = await store.save("b", project());
  assert.equal(await store.remove(a.id), true);
  assert.equal(await store.remove(a.id), false);
  assert.equal(await store.get(a.id), null);
  assert.deepEqual((await store.list()).map(v => v.id), [b.id]);
});

test("a full storage leaves existing versions intact and explains the failure", async () => {
  const kv = memoryKV();
  const store = createVersionStore(kv, { now: clock() });
  await store.save("first", project());
  const before = structuredClone(kv.data.get(VERSIONS_KEY));
  kv.failWrites = Object.assign(new Error("quota"), { name: "QuotaExceededError" });
  await assert.rejects(store.save("second", project()), /storage is full/i);
  assert.deepEqual(kv.data.get(VERSIONS_KEY), before);
  assert.deepEqual(await names(store), ["first"]);
});

test("unreadable saved data is reported, not silently replaced", async () => {
  const kv = memoryKV({ [VERSIONS_KEY]: "{not a list" });
  const store = createVersionStore(kv, { now: clock() });
  await assert.rejects(store.list(), /unreadable/i);
  await assert.rejects(store.save("x", project()), /unreadable/i);
  await assert.rejects(store.remove("x"), /unreadable/i);
  assert.equal(kv.data.get(VERSIONS_KEY), "{not a list");
  assert.equal(kv.writes, 0);
});

test("malformed entries are skipped when listing", async () => {
  const good = { id: "g", name: "good", savedAt: 2, project: projectFromState(project()) };
  const kv = memoryKV({ [VERSIONS_KEY]: [good, { id: "x" }, null, "junk"] });
  assert.deepEqual((await createVersionStore(kv).list()).map(v => v.id), ["g"]);
});

test("entries it does not recognise are kept on save and remove, only hidden from the list (issue #21)", async () => {
  const future = { id: "f", name: "from a newer Tandem", savedAt: 1, project: { format: "tandem-project", version: 2, tracks: [] } };
  const kv = memoryKV({ [VERSIONS_KEY]: [future, { id: "x" }, "junk"] });
  const store = createVersionStore(kv, { now: clock() });
  assert.deepEqual(await store.list(), []);
  assert.equal(await store.get("f"), null);
  const a = await store.save("a", project());
  assert.equal(await store.remove("f"), false, "an unrecognised entry is not removable through the store");
  const b = await store.save("b", project());
  assert.equal(await store.remove(a.id), true);
  const stored = kv.data.get(VERSIONS_KEY);
  assert.deepEqual(stored.map(e => e?.id ?? e), [b.id, "f", "x", "junk"]);
  assert.deepEqual(stored[1], future);
  assert.deepEqual(await names(store), ["b"]);
});

test("the version limit counts only recognised entries and never drops unrecognised ones", async () => {
  const future = { id: "f", name: "future", savedAt: 1, project: { version: 2 } };
  const kv = memoryKV({ [VERSIONS_KEY]: [future] });
  const store = createVersionStore(kv, { now: clock(), limit: 2 });
  for (const n of ["v1", "v2", "v3"]) await store.save(n, project());
  assert.deepEqual(await names(store), ["v3", "v2"]);
  assert.ok(kv.data.get(VERSIONS_KEY).some(e => e.id === "f"));
});

test("a new id never collides with an unrecognised entry's id", async () => {
  const savedAt = 1_700_000_001_000;
  const kv = memoryKV({ [VERSIONS_KEY]: [{ id: String(savedAt), name: "future", savedAt: 1, project: {} }] });
  const store = createVersionStore(kv, { now: () => savedAt });
  const v = await store.save("a", project());
  assert.notEqual(v.id, String(savedAt));
  assert.deepEqual((await store.get(v.id)).bpm, 100);
});

// STORE.2a: a version can link the recordings that were loaded when it was saved.
const A = "a".repeat(64), B = "b".repeat(64), C = "c".repeat(64);

test("a version keeps the recording links it was saved with; one without links has none", async () => {
  const kv = memoryKV(), store = createVersionStore(kv, { now: clock() });
  const withAudio = await store.save("Take", project(), { original: { id: A, type: "audio/wav" }, tuned: { id: B, type: "audio/wav" }, junk: { id: C } });
  const without = await store.save("Plain", project());
  assert.deepEqual(await store.audio(withAudio.id), { original: { id: A, type: "audio/wav" }, tuned: { id: B, type: "audio/wav" } });
  assert.equal(await store.audio(without.id), null);
  assert.equal(await store.audio("missing"), null);
  assert.equal("audio" in kv.data.get(VERSIONS_KEY).find(e => e.id === without.id), false, "no empty audio field is stored");
  assert.equal("audio" in (await store.get(withAudio.id)), false, "the project itself carries no audio");
});

test("audioIds lists every linked recording, including those of entries it does not recognise", async () => {
  const kv = memoryKV({ [VERSIONS_KEY]: [{ id: "future", format: 99, audio: { original: { id: C, type: "" } } }] });
  const store = createVersionStore(kv, { now: clock() });
  await store.save("Take", project(), { original: { id: A, type: "" }, polished: { id: B, type: "" } });
  assert.deepEqual([...(await store.audioIds())].sort(), [A, B, C]);
});

test("removing a version drops its links from audioIds", async () => {
  const kv = memoryKV(), store = createVersionStore(kv, { now: clock() });
  const v = await store.save("Take", project(), { original: { id: A, type: "" } });
  await store.remove(v.id);
  assert.deepEqual([...(await store.audioIds())], []);
});
