import test from "node:test";
import assert from "node:assert/strict";
import {
  migrateLegacy, persistence, storageError, openKV, PERSISTENCE_TEXT,
  DRAFT_KEY, VERSIONS_KEY, LEGACY_DRAFT_KEY, LEGACY_VERSIONS_KEY,
} from "../storage.js";
import { memoryKV, memoryStorage } from "./memory-kv.mjs";

const entry = (id, savedAt, name = id) =>
  ({ id, name, savedAt, project: { format: "tandem-project", version: 1, bpm: 100, instrument: "piano", notes: [], drums: [] } });
const draft = { bpm: 120, instrument: "organ", melody_locked: true, notes: [{ m: 60, t: 0, d: 0.5 }], drums: [] };

test("the legacy draft and versions move to IndexedDB and leave localStorage", async () => {
  const kv = memoryKV();
  const local = memoryStorage({
    [LEGACY_DRAFT_KEY]: JSON.stringify(draft),
    [LEGACY_VERSIONS_KEY]: JSON.stringify([entry("b", 2), entry("a", 1)]),
    "tandem-api": "https://example.test",
  });
  const report = await migrateLegacy(kv, local);
  assert.deepEqual(report, { draft: true, versions: 2, problems: [] });
  assert.deepEqual(kv.data.get(DRAFT_KEY), draft);
  assert.deepEqual(kv.data.get(VERSIONS_KEY).map(e => e.id), ["b", "a"]);
  assert.equal(local.getItem(LEGACY_DRAFT_KEY), null);
  assert.equal(local.getItem(LEGACY_VERSIONS_KEY), null);
  assert.equal(local.getItem("tandem-api"), "https://example.test", "settings stay in localStorage");
});

test("nothing to migrate writes nothing", async () => {
  const kv = memoryKV();
  assert.deepEqual(await migrateLegacy(kv, memoryStorage()), { draft: false, versions: 0, problems: [] });
  assert.equal(kv.writes, 0);
});

test("running again is harmless, and later legacy data is merged by id", async () => {
  const kv = memoryKV({ [VERSIONS_KEY]: [entry("c", 3, "kept here"), entry("a", 1, "kept here")] });
  const local = memoryStorage({ [LEGACY_VERSIONS_KEY]: JSON.stringify([entry("b", 2), entry("a", 1, "older copy")]) });
  const report = await migrateLegacy(kv, local);
  assert.equal(report.versions, 1, "only the version not already here is added");
  const stored = kv.data.get(VERSIONS_KEY);
  assert.deepEqual(stored.map(e => e.id), ["c", "b", "a"], "newest first");
  assert.equal(stored.find(e => e.id === "a").name, "kept here", "the IndexedDB copy wins");
  assert.deepEqual(await migrateLegacy(kv, local), { draft: false, versions: 0, problems: [] });
});

test("a legacy draft replaces the stored draft", async () => {
  const kv = memoryKV({ [DRAFT_KEY]: { ...draft, bpm: 90 } });
  await migrateLegacy(kv, memoryStorage({ [LEGACY_DRAFT_KEY]: JSON.stringify(draft) }));
  assert.equal(kv.data.get(DRAFT_KEY).bpm, 120);
});

test("unrecognised legacy version entries are carried over untouched", async () => {
  const future = { id: "f", name: "future", savedAt: 9, project: { version: 2 } };
  const kv = memoryKV();
  await migrateLegacy(kv, memoryStorage({ [LEGACY_VERSIONS_KEY]: JSON.stringify([future, "junk"]) }));
  assert.deepEqual(kv.data.get(VERSIONS_KEY), [future, "junk"]);
});

test("unreadable legacy versions are reported and left in localStorage", async () => {
  const kv = memoryKV();
  const local = memoryStorage({ [LEGACY_VERSIONS_KEY]: "{oops", [LEGACY_DRAFT_KEY]: JSON.stringify(draft) });
  const report = await migrateLegacy(kv, local);
  assert.equal(report.problems.length, 1);
  assert.match(report.problems[0], /could not be read/);
  assert.equal(local.getItem(LEGACY_VERSIONS_KEY), "{oops");
  assert.equal(kv.data.has(VERSIONS_KEY), false);
  assert.equal(report.draft, true, "the draft still moves");
});

test("a legacy draft the app could never open is dropped, as before", async () => {
  const kv = memoryKV();
  const local = memoryStorage({ [LEGACY_DRAFT_KEY]: "not json" });
  assert.equal((await migrateLegacy(kv, local)).draft, false);
  assert.equal(local.getItem(LEGACY_DRAFT_KEY), null);
  assert.equal(kv.data.has(DRAFT_KEY), false);
});

test("when IndexedDB cannot be written, localStorage keeps everything", async () => {
  const kv = memoryKV();
  kv.failWrites = Object.assign(new Error("quota"), { name: "QuotaExceededError" });
  const local = memoryStorage({ [LEGACY_DRAFT_KEY]: JSON.stringify(draft), [LEGACY_VERSIONS_KEY]: JSON.stringify([entry("a", 1)]) });
  await assert.rejects(migrateLegacy(kv, local), /storage is full/i);
  assert.notEqual(local.getItem(LEGACY_DRAFT_KEY), null);
  assert.notEqual(local.getItem(LEGACY_VERSIONS_KEY), null);
});

test("unreadable versions already in IndexedDB skip the versions merge, keep both copies and still move the draft", async () => {
  const kv = memoryKV({ [VERSIONS_KEY]: "broken" });
  const local = memoryStorage({ [LEGACY_DRAFT_KEY]: JSON.stringify(draft), [LEGACY_VERSIONS_KEY]: JSON.stringify([entry("a", 1)]) });
  const report = await migrateLegacy(kv, local);
  assert.equal(report.draft, true);
  assert.equal(report.versions, 0);
  assert.equal(report.problems.length, 1);
  assert.match(report.problems[0], /unreadable/i);
  assert.equal(kv.data.get(VERSIONS_KEY), "broken");
  assert.notEqual(local.getItem(LEGACY_VERSIONS_KEY), null);
  assert.deepEqual(kv.data.get(DRAFT_KEY), draft);
  assert.equal(local.getItem(LEGACY_DRAFT_KEY), null);
});

test("an unavailable localStorage is skipped", async () => {
  const throwing = { getItem() { throw new Error("SecurityError"); } };
  assert.deepEqual(await migrateLegacy(memoryKV(), throwing), { draft: false, versions: 0, problems: [] });
  assert.deepEqual(await migrateLegacy(memoryKV(), undefined), { draft: false, versions: 0, problems: [] });
});

test("persistence reports what the browser promised, asking only when told to", async () => {
  let asked = 0;
  const manager = (persisted, grant) => ({ persisted: async () => persisted, persist: async () => { asked++; return grant; } });
  assert.equal(await persistence(undefined), "unsupported");
  assert.equal(await persistence({}), "unsupported");
  assert.equal(await persistence(manager(true, false)), "persisted");
  assert.equal(await persistence(manager(false, true)), "best-effort");
  assert.equal(asked, 0, "checking never prompts");
  assert.equal(await persistence(manager(false, true), { request: true }), "persisted");
  assert.equal(await persistence(manager(false, false), { request: true }), "best-effort");
  assert.equal(asked, 2);
  for (const k of ["persisted", "best-effort", "unsupported"]) assert.ok(PERSISTENCE_TEXT[k]);
});

test("storage errors explain a full quota and pass others through", () => {
  assert.match(storageError(Object.assign(new Error("x"), { name: "QuotaExceededError" })).message, /storage is full/i);
  const other = new Error("other");
  assert.equal(storageError(other), other);
});

test("openKV explains a browser without IndexedDB", async () => {
  await assert.rejects(openKV(undefined), /no IndexedDB/);
});

// Issue #40: an IndexedDB factory whose open request is blocked by another tab holding an older
// version of the database. `release()` lets the open finish, as when that tab finally closes.
function blockedFactory() {
  const db = { closed: false, close() { this.closed = true; }, objectStoreNames: { contains: () => true } };
  let req;
  return {
    db,
    open() {
      req = { result: undefined };
      setTimeout(() => req.onblocked?.({ type: "blocked" }), 0);
      return req;
    },
    release() { req.result = db; req.onsuccess?.({ target: req }); },
  };
}

test("openKV refuses a blocked open with a message instead of waiting forever (#40)", { timeout: 5000 }, async () => {
  const factory = blockedFactory();
  await assert.rejects(openKV(factory), /Close other Tandem tabs/);
});

test("openKV closes a connection that opens after it gave up on a blocked open (#40)", { timeout: 5000 }, async () => {
  const factory = blockedFactory();
  await assert.rejects(openKV(factory), /Close other Tandem tabs/);
  factory.release();
  assert.equal(factory.db.closed, true);
});
