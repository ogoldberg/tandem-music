import test from "node:test";
import assert from "node:assert/strict";
import {
  openRecordings, createRecordingStore, recordingId, cleanLinks, linkedIds, RECORDINGS_DIR, AUDIO_SLOTS,
  liveChannels, monoSamples,
} from "../recordings.js";

// In-memory stand-in for an OPFS directory handle: getFileHandle, removeEntry, values() and
// FileSystemFileHandle.getFile/createWritable. A writable only replaces the file on close(), like
// the real swap-file behaviour. Set `failWrites` to make every write throw.
function memoryDir() {
  const files = new Map();
  const dir = {
    files, failWrites: null, writes: 0,
    async getFileHandle(name, { create = false } = {}) {
      if (!files.has(name)) {
        if (!create) throw Object.assign(new Error("not found"), { name: "NotFoundError" });
        files.set(name, new Uint8Array(0));
      }
      return fileHandle(name);
    },
    async removeEntry(name) {
      if (!files.delete(name)) throw Object.assign(new Error("not found"), { name: "NotFoundError" });
    },
    async *values() { for (const name of [...files.keys()]) yield { kind: "file", name }; },
  };
  const fileHandle = name => ({
    kind: "file", name,
    async getFile() { return new Blob([files.get(name)]); },
    async createWritable() {
      const parts = [];
      return {
        async write(data) { if (dir.failWrites) throw dir.failWrites; parts.push(new Uint8Array(await new Blob([data]).arrayBuffer())); },
        async close() { files.set(name, new Uint8Array(await new Blob(parts).arrayBuffer())); dir.writes++; },
        async abort() {},
      };
    },
  });
  return dir;
}

// A Web Locks stand-in: shared holders run together, an exclusive holder waits for every holder
// before it and blocks the ones after it. Records the order holders start in.
function memoryLocks() {
  const log = [], active = new Set();
  let exclusiveTail = Promise.resolve();
  return {
    log,
    request(name, opts, fn) {
      if (opts?.mode === "shared") {
        const run = exclusiveTail.then(async () => { log.push("shared"); return fn(); });
        active.add(run);
        run.finally(() => active.delete(run)).catch(() => {});
        return run;
      }
      const run = Promise.allSettled([exclusiveTail, ...active]).then(async () => { log.push("exclusive"); return fn(); });
      exclusiveTail = run.catch(() => {});
      return run;
    },
  };
}

const blob = (text, type = "audio/wav") => new Blob([text], { type });

test("a recording is stored under its SHA-256 and read back with its type", async () => {
  const dir = memoryDir(), store = createRecordingStore(dir);
  const a = blob("take one");
  const link = await store.put(a);
  assert.equal(link.id, await recordingId(a));
  assert.match(link.id, /^[0-9a-f]{64}$/);
  assert.equal(link.type, "audio/wav");
  const back = await store.get(link);
  assert.equal(back.type, "audio/wav");
  assert.equal(await back.text(), "take one");
});

test("storing the same recording twice writes it once", async () => {
  const dir = memoryDir(), store = createRecordingStore(dir);
  const first = await store.put(blob("same"));
  const second = await store.put(blob("same", "audio/webm"));
  assert.equal(first.id, second.id);
  assert.equal(second.type, "audio/webm");
  assert.equal(dir.writes, 1);
});

test("a stored file of the wrong size (an interrupted write) is written again", async () => {
  const dir = memoryDir(), store = createRecordingStore(dir);
  const b = blob("complete take");
  dir.files.set(await recordingId(b), new Uint8Array(0));
  await store.put(b);
  assert.equal(await (await store.get({ id: await recordingId(b), type: "" })).text(), "complete take");
});

test("a missing recording reads as null; a malformed link is refused", async () => {
  const store = createRecordingStore(memoryDir());
  assert.equal(await store.get({ id: "a".repeat(64), type: "audio/wav" }), null);
  await assert.rejects(store.get({ id: "../draft", type: "" }), /not a recording/i);
});

test("a full device is reported as a storage-full error and nothing is kept", async () => {
  const dir = memoryDir(), store = createRecordingStore(dir);
  dir.failWrites = Object.assign(new Error("quota"), { name: "QuotaExceededError" });
  await assert.rejects(store.put(blob("big take")), /storage is full/i);
  const b = blob("big take");
  assert.ok(!dir.files.has(await recordingId(b)), "the file created for the failed write is removed");
});

test("garbage collection removes only unreferenced recordings", async () => {
  const dir = memoryDir(), store = createRecordingStore(dir, { locks: memoryLocks() });
  const keep = await store.put(blob("kept"));
  const drop = await store.put(blob("dropped"));
  dir.files.set("notes.txt", new Uint8Array(1)); // not a recording name: left alone
  const removed = await store.gc(async () => new Set([keep.id]));
  assert.equal(removed, 1);
  assert.ok(dir.files.has(keep.id));
  assert.ok(!dir.files.has(drop.id));
  assert.ok(dir.files.has("notes.txt"));
});

test("without Web Locks nothing is collected, because another tab could be about to link a file", async () => {
  const dir = memoryDir(), store = createRecordingStore(dir);
  await store.put(blob("orphan"));
  assert.equal(await store.gc(async () => new Set()), 0);
  assert.equal(dir.files.size, 1);
});

test("saving holds a shared lock and garbage collection an exclusive one, so a just-stored file is linked before it can be collected", async () => {
  const locks = memoryLocks();
  const dir = memoryDir(), store = createRecordingStore(dir, { locks });
  let linked = new Set();
  const saving = store.hold(async () => {
    const link = await store.put(blob("fresh"));
    await new Promise(r => setTimeout(r, 5));
    linked = new Set([link.id]);
  });
  const collecting = store.gc(async () => linked);
  await Promise.all([saving, collecting]);
  assert.deepEqual(locks.log, ["shared", "exclusive"]);
  assert.equal(dir.files.size, 1, "the fresh recording survived the collection");
});

test("the recording slots, in order, include the separated stems, the generated band, the instrument voice and the sung harmony", () => {
  assert.deepEqual(AUDIO_SLOTS, ["original", "polished", "tuned", "vocal", "accompaniment", "band", "timbre", "voice2_sung"]);
});

test("cleanLinks keeps only well-formed slot links; linkedIds collects their ids", () => {
  const id = "b".repeat(64);
  assert.deepEqual(cleanLinks({ original: { id, type: "audio/wav" }, polished: { id: "x" }, tuned: null, other: { id, type: "" } }),
    { original: { id, type: "audio/wav" } });
  assert.deepEqual(cleanLinks("junk"), {});
  assert.deepEqual([...linkedIds([{ original: { id, type: "" } }, null, { tuned: { id: "c".repeat(64), type: 3 } }])], [id, "c".repeat(64)]);
});

test("openRecordings uses the recordings folder of the origin-private file system and reports when there is none", async () => {
  const root = memoryRootDir();
  const store = await openRecordings({ getDirectory: async () => root });
  await store.put(blob("x"));
  assert.ok(root.dirs.has(RECORDINGS_DIR));
  await assert.rejects(openRecordings({}), /recordings cannot be kept/i);
  await assert.rejects(openRecordings(undefined), /recordings cannot be kept/i);
});

function memoryRootDir() {
  const dirs = new Map();
  return { dirs, async getDirectoryHandle(name, { create } = {}) { if (!dirs.has(name)) { if (!create) throw new Error("NotFoundError"); dirs.set(name, memoryDir()); } return dirs.get(name); } };
}

const decodedOf = (...channels) => ({ numberOfChannels: channels.length, length: channels[0].length, getChannelData: c => channels[c] });

test("a microphone that fills one side of a stereo take: the silent side is not part of the recording", () => {
  // The Mac app's WebKit recorder writes 2-channel audio with the voice on the left and the right all zero.
  const voice = Float32Array.from({ length: 400 }, (_, i) => 0.3 * Math.sin(i / 7));
  const silent = new Float32Array(400);
  assert.deepEqual(liveChannels(decodedOf(voice, silent)), [voice]);
  assert.deepEqual(liveChannels(decodedOf(silent, voice)), [voice]);
  // Mono is the voice itself, at full level, not averaged with the silence.
  assert.deepEqual([...monoSamples(decodedOf(voice, silent))], [...voice]);
});

test("a side 60 dB or more below the other counts as silent; real stereo and quiet takes keep every channel", () => {
  const voice = Float32Array.from({ length: 400 }, (_, i) => 0.3 * Math.sin(i / 7));
  const hiss = voice.map(x => x / 1000), quieter = voice.map(x => x / 100);
  assert.deepEqual(liveChannels(decodedOf(voice, hiss)), [voice]);
  assert.deepEqual(liveChannels(decodedOf(voice, quieter)), [voice, quieter]);
  const left = Float32Array.of(1, 0.5), right = Float32Array.of(0, 0.5);
  assert.deepEqual([...monoSamples(decodedOf(left, right))], [0.5, 0.5]);
  const nothing = new Float32Array(4);
  assert.deepEqual(liveChannels(decodedOf(nothing, nothing)), [nothing, nothing]);
  assert.deepEqual(liveChannels(decodedOf(voice)), [voice]);
});
