import test from "node:test";
import assert from "node:assert/strict";
import { createIdeaStore, IDEAS_KEY, MAX_IDEA_NAME, ideaTitle, formatDuration } from "../ideas.js";
import { memoryKV } from "./memory-kv.mjs";

const link = (c = "a") => ({ id: c.repeat(64), type: "audio/webm" });

function clock(start = 1_700_000_000_000) {
  let t = start;
  return () => (t += 1000);
}

test("ideas are kept under the IndexedDB key 'ideas'", () => {
  assert.equal(IDEAS_KEY, "ideas");
});

test("needs a key-value store", () => {
  assert.throws(() => createIdeaStore(null), TypeError);
});

test("starts empty", async () => {
  assert.deepEqual(await createIdeaStore(memoryKV()).list(), []);
});

test("adds ideas newest first with their time, length and recording", async () => {
  const kv = memoryKV(), ideas = createIdeaStore(kv, { now: clock() });
  const first = await ideas.add({ duration: 7.25, audio: link("a") });
  const second = await ideas.add({ duration: 3, audio: link("b") });
  assert.equal(first.name, "");
  assert.notEqual(first.id, second.id);
  assert.deepEqual((await ideas.list()).map(i => i.id), [second.id, first.id]);
  const got = await ideas.get(first.id);
  assert.equal(got.duration, 7.25);
  assert.deepEqual(got.audio, link("a"));
  assert.equal(got.savedAt, first.savedAt);
});

test("two ideas saved in the same millisecond get different ids", async () => {
  const ideas = createIdeaStore(memoryKV(), { now: () => 5 });
  const a = await ideas.add({ duration: 1, audio: link("a") });
  const b = await ideas.add({ duration: 1, audio: link("b") });
  assert.notEqual(a.id, b.id);
});

test("an idea needs a recording link and a sane length", async () => {
  const ideas = createIdeaStore(memoryKV());
  await assert.rejects(ideas.add({ duration: 2, audio: { id: "nope" } }), /recording/);
  await assert.rejects(ideas.add({ duration: 2 }), /recording/);
  await assert.rejects(ideas.add({ duration: -1, audio: link() }), /length/);
  await assert.rejects(ideas.add({ duration: NaN, audio: link() }), /length/);
  assert.deepEqual(await ideas.list(), []);
});

test("rename trims, limits the length and can clear the name", async () => {
  const ideas = createIdeaStore(memoryKV(), { now: clock() });
  const { id } = await ideas.add({ duration: 1, audio: link() });
  assert.equal(await ideas.rename(id, "  chorus hook  "), true);
  assert.equal((await ideas.get(id)).name, "chorus hook");
  await ideas.rename(id, "x".repeat(200));
  assert.equal((await ideas.get(id)).name.length, MAX_IDEA_NAME);
  await ideas.rename(id, "   ");
  assert.equal((await ideas.get(id)).name, "");
  assert.equal(await ideas.rename("missing", "y"), false);
});

test("remove deletes only that idea", async () => {
  const ideas = createIdeaStore(memoryKV(), { now: clock() });
  const a = await ideas.add({ duration: 1, audio: link("a") });
  const b = await ideas.add({ duration: 1, audio: link("b") });
  assert.equal(await ideas.remove(a.id), true);
  assert.equal(await ideas.remove(a.id), false);
  assert.deepEqual((await ideas.list()).map(i => i.id), [b.id]);
  assert.equal(await ideas.get(a.id), null);
});

test("audioIds lists every idea's recording, so recording clean-up keeps them", async () => {
  const kv = memoryKV(), ideas = createIdeaStore(kv, { now: clock() });
  await ideas.add({ duration: 1, audio: link("a") });
  await ideas.add({ duration: 1, audio: link("b") });
  // An entry this version does not recognise still keeps its recording.
  await kv.update(IDEAS_KEY, v => [[...v, { future: true, audio: link("c") }], null]);
  assert.deepEqual([...(await ideas.audioIds())].sort(), [link("a").id, link("b").id, link("c").id]);
});

test("entries this version does not recognise are hidden but kept", async () => {
  const kv = memoryKV(), ideas = createIdeaStore(kv, { now: clock() });
  await kv.set(IDEAS_KEY, [{ future: "format" }]);
  const { id } = await ideas.add({ duration: 1, audio: link() });
  assert.deepEqual((await ideas.list()).map(i => i.id), [id]);
  await ideas.remove(id);
  assert.deepEqual(await kv.get(IDEAS_KEY), [{ future: "format" }]);
});

test("unreadable stored ideas are an error, never overwritten", async () => {
  const kv = memoryKV(), ideas = createIdeaStore(kv);
  await kv.set(IDEAS_KEY, "garbage");
  await assert.rejects(ideas.list(), /unreadable/);
  await assert.rejects(ideas.add({ duration: 1, audio: link() }), /unreadable/);
  assert.equal(await kv.get(IDEAS_KEY), "garbage");
});

test("ideaTitle uses the name, else the time it was recorded", () => {
  const fmt = ms => "T" + ms;
  assert.equal(ideaTitle({ name: "hook", savedAt: 1 }, fmt), "hook");
  assert.equal(ideaTitle({ name: "", savedAt: 5 }, fmt), "Idea · T5");
});

test("formatDuration shows minutes and seconds", () => {
  assert.equal(formatDuration(0), "0:00");
  assert.equal(formatDuration(7.6), "0:08");
  assert.equal(formatDuration(65), "1:05");
  assert.equal(formatDuration(3600), "60:00");
  assert.equal(formatDuration(NaN), "0:00");
});
