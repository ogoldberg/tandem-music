import test from "node:test";
import assert from "node:assert/strict";
import { createVersionStore, projectFromState, VERSIONS_KEY, MAX_VERSIONS, MAX_NAME_LENGTH } from "../versions.js";

// In-memory stand-in for window.localStorage (same getItem/setItem contract).
function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: k => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { data.set(k, String(v)); },
  };
}

const project = (bpm = 100, notes = [{ m: 60, t: 0, d: 0.4 }]) =>
  ({ bpm, instrument: "piano", melody_locked: true, notes, drums: [{ k: "kick", t: 0 }] });

function clock(start = 1_700_000_000_000) {
  let t = start;
  return () => (t += 1000);
}

test("projectFromState keeps only the portable project fields", () => {
  const p = projectFromState({ ...project(120), extra: "x", melody_locked: false });
  assert.deepEqual(p, { format: "tandem-project", version: 1, bpm: 120, instrument: "piano", melody_locked: false, notes: [{ m: 60, t: 0, d: 0.4 }], drums: [{ k: "kick", t: 0 }] });
});

test("starts empty", () => {
  assert.deepEqual(createVersionStore(memoryStorage()).list(), []);
});

test("saves, lists newest first and restores a deep copy", () => {
  const storage = memoryStorage();
  const store = createVersionStore(storage, { now: clock() });
  const a = store.save("Verse idea", project(90));
  const b = store.save("  Chorus  ", project(130));
  assert.equal(b.name, "Chorus");
  assert.deepEqual(store.list().map(v => v.name), ["Chorus", "Verse idea"]);
  assert.ok(store.list()[0].savedAt > store.list()[1].savedAt);
  assert.notEqual(a.id, b.id);

  const restored = store.get(a.id);
  assert.equal(restored.bpm, 90);
  restored.notes.push({ m: 72, t: 1, d: 0.2 });
  assert.equal(store.get(a.id).notes.length, 1, "get returns a copy, not the stored object");
});

test("versions survive a new store over the same storage (reload)", () => {
  const storage = memoryStorage();
  const first = createVersionStore(storage, { now: clock() });
  const v = first.save("Keep me", project(111));
  const reloaded = createVersionStore(storage);
  assert.deepEqual(reloaded.list().map(x => x.name), ["Keep me"]);
  assert.equal(reloaded.get(v.id).bpm, 111);
  assert.ok(JSON.parse(storage.data.get(VERSIONS_KEY)).length === 1);
});

test("saving copies the project, so later edits don't change the version", () => {
  const store = createVersionStore(memoryStorage(), { now: clock() });
  const p = project();
  const v = store.save("Snapshot", p);
  p.notes.push({ m: 64, t: 1, d: 0.3 });
  p.bpm = 200;
  assert.equal(store.get(v.id).notes.length, 1);
  assert.equal(store.get(v.id).bpm, 100);
});

test("ids stay unique when two versions are saved in the same millisecond", () => {
  const store = createVersionStore(memoryStorage(), { now: () => 5 });
  const ids = [store.save("a", project()), store.save("b", project()), store.save("c", project())].map(v => v.id);
  assert.equal(new Set(ids).size, 3);
});

test("rejects empty names and trims long ones", () => {
  const store = createVersionStore(memoryStorage(), { now: clock() });
  assert.throws(() => store.save("   ", project()), /name/i);
  assert.throws(() => store.save(undefined, project()), /name/i);
  assert.equal(store.save("x".repeat(200), project()).name.length, MAX_NAME_LENGTH);
});

test("rejects a project without note and drum lists", () => {
  const store = createVersionStore(memoryStorage(), { now: clock() });
  assert.throws(() => store.save("bad", { bpm: 100 }), /project/i);
  assert.deepEqual(store.list(), []);
});

test("keeps at most the limit, dropping the oldest", () => {
  const store = createVersionStore(memoryStorage(), { now: clock(), limit: 3 });
  for (const n of ["v1", "v2", "v3", "v4"]) store.save(n, project());
  assert.deepEqual(store.list().map(v => v.name), ["v4", "v3", "v2"]);
  assert.equal(MAX_VERSIONS, 50);
});

test("remove deletes one version and reports whether it existed", () => {
  const store = createVersionStore(memoryStorage(), { now: clock() });
  const a = store.save("a", project()), b = store.save("b", project());
  assert.equal(store.remove(a.id), true);
  assert.equal(store.remove(a.id), false);
  assert.equal(store.get(a.id), null);
  assert.deepEqual(store.list().map(v => v.id), [b.id]);
});

test("a full storage leaves existing versions intact and explains the failure", () => {
  const storage = memoryStorage();
  const store = createVersionStore(storage, { now: clock() });
  store.save("first", project());
  const before = storage.data.get(VERSIONS_KEY);
  storage.setItem = () => { throw Object.assign(new Error("quota"), { name: "QuotaExceededError" }); };
  assert.throws(() => store.save("second", project()), /storage is full/i);
  assert.equal(storage.data.get(VERSIONS_KEY), before);
  assert.deepEqual(store.list().map(v => v.name), ["first"]);
});

test("unreadable saved data is reported, not silently replaced", () => {
  const storage = memoryStorage({ [VERSIONS_KEY]: "{not json" });
  const store = createVersionStore(storage, { now: clock() });
  assert.throws(() => store.list(), /unreadable/i);
  assert.throws(() => store.save("x", project()), /unreadable/i);
  assert.equal(storage.data.get(VERSIONS_KEY), "{not json");
});

test("malformed entries are skipped when listing", () => {
  const good = { id: "g", name: "good", savedAt: 2, project: projectFromState(project()) };
  const storage = memoryStorage({ [VERSIONS_KEY]: JSON.stringify([good, { id: "x" }, null, "junk"]) });
  assert.deepEqual(createVersionStore(storage).list().map(v => v.id), ["g"]);
});
