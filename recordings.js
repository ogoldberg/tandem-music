// Recordings on the device (STORE.2a, ADR-011): the original, polished and tuned audio is kept in
// the Origin Private File System, one file per recording, named by the SHA-256 of its bytes, so the
// same audio is stored once however many versions link to it. The draft and each named version keep
// small links ({id, type}) to these files; the project itself never carries audio.
// DOM-free so Node tests import it directly: the directory handle and Web Locks are passed in.

import { storageError } from "./storage.js";

export const RECORDINGS_DIR = "recordings";
// The draft's recordings, kept next to the draft in the IndexedDB key-value store.
export const DRAFT_AUDIO_KEY = "draft-audio";
export const AUDIO_SLOTS = ["original", "polished", "tuned", "vocal", "accompaniment", "band", "timbre"];
const LOCK = "tandem-recordings";
const ID = /^[0-9a-f]{64}$/;

export async function recordingId(blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

// The well-formed links among AUDIO_SLOTS (original, polished, tuned, SEP.1's separated vocal and
// accompaniment, GEN.2's generated band and TIMBRE.1's voice played as an instrument); anything else is dropped.
export function cleanLinks(value) {
  const out = {};
  if (!value || typeof value !== "object") return out;
  for (const slot of AUDIO_SLOTS) {
    const link = value[slot];
    if (link && typeof link === "object" && typeof link.id === "string" && ID.test(link.id)) {
      out[slot] = { id: link.id, type: typeof link.type === "string" ? link.type : "" };
    }
  }
  return out;
}

// Every recording id linked from a list of link objects (the draft's and each version's).
export function linkedIds(linkSets) {
  const ids = new Set();
  for (const links of linkSets) for (const link of Object.values(cleanLinks(links))) ids.add(link.id);
  return ids;
}

const notFound = err => err?.name === "NotFoundError" || err?.name === "TypeMismatchError";

export async function openRecordings(storage, options = {}) {
  if (typeof storage?.getDirectory !== "function") {
    throw Error("Recordings cannot be kept on this device in this browser, so a recording lasts only until the page is closed.");
  }
  const root = await storage.getDirectory();
  return createRecordingStore(await root.getDirectoryHandle(RECORDINGS_DIR, { create: true }), options);
}

// `locks` is navigator.locks (Web Locks). Saving holds a shared lock from storing a file until it is
// linked (hold), and garbage collection an exclusive one, so a file another tab has just stored but
// not yet linked is never collected. Without Web Locks, garbage collection is skipped.
export function createRecordingStore(dir, { locks = null } = {}) {
  const known = new WeakMap(); // blob -> id, so a blob is hashed once
  const lock = (mode, fn) => (locks ? locks.request(LOCK, { mode }, fn) : fn());

  async function exists(id, size) {
    try { return (await (await dir.getFileHandle(id)).getFile()).size === size; } catch (err) { if (notFound(err)) return false; throw err; }
  }

  return {
    // Store a recording and return its link. Call it inside hold() with the write that links it.
    async put(blob) {
      let id = known.get(blob);
      if (!id) { id = await recordingId(blob); known.set(blob, id); }
      if (!(await exists(id, blob.size))) {
        const writable = await (await dir.getFileHandle(id, { create: true })).createWritable();
        try {
          await writable.write(blob);
          await writable.close();
        } catch (err) {
          await writable.abort?.().catch(() => {});
          // A file created empty for this write is not a recording; leave nothing behind.
          if (!(await exists(id, blob.size))) await dir.removeEntry(id).catch(() => {});
          throw storageError(err);
        }
      }
      return { id, type: blob.type || "" };
    },

    // The recording a link points to, or null if it is no longer on the device.
    async get(link) {
      if (!link || typeof link.id !== "string" || !ID.test(link.id)) throw Error("That link is not a recording.");
      try {
        const file = await (await dir.getFileHandle(link.id)).getFile();
        return new Blob([file], { type: link.type || "" });
      } catch (err) {
        if (notFound(err)) return null;
        throw err;
      }
    },

    hold(fn) { return lock("shared", fn); },

    // Delete every recording not in the set that referenced() resolves to (read under the lock).
    async gc(referenced) {
      if (!locks) return 0;
      return lock("exclusive", async () => {
        const keep = await referenced();
        const doomed = [];
        for await (const entry of dir.values()) {
          if (entry.kind === "file" && ID.test(entry.name) && !keep.has(entry.name)) doomed.push(entry.name);
        }
        for (const name of doomed) await dir.removeEntry(name).catch(err => { if (!notFound(err)) throw err; });
        return doomed.length;
      });
    },
  };
}
