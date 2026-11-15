// TAKE.1: every take kept, picked or comped: the takes in the project, the comp edit list, rendering the comp,
// the take recordings' links, Tandem files and versions, and older projects opening unchanged.
import test from "node:test";
import assert from "node:assert/strict";
import {
  cleanTakes, addTake, pickTake, compSection, removeTake, newTakeId, nextTakeName, takeKey, takeFile, takeIdOf,
  isTakeKey, isExtraKey, usedTakes, wholeTake, compSig, compSeconds, compText, renderComp, dropCompVocal, MAX_TAKES, MAX_SECTIONS,
} from "../takes.js";
import { cleanLinks, linkedIds } from "../recordings.js";
import { projectFromState } from "../versions.js";
import { writeBundle, readBundle, encodeWav, ideaProject } from "../bundle.js";

const HEX = "a".repeat(64), HEX2 = "b".repeat(64), HEX3 = "c".repeat(64);
const wav = (n = 100, rate = 8000, v = 0.5) => encodeWav(Float32Array.from({ length: n }, (_, i) => Math.sin(i / 3) * v), rate);
const two = () => addTake(null, { id: "second", seconds: 6, first: { id: "first", seconds: 5 } });

test("a second take starts the list: the first recording is Take 1 and the new one is the take in use", () => {
  const t = two();
  assert.deepEqual(t, {
    list: [{ id: "first", name: "Take 1", seconds: 5 }, { id: "second", name: "Take 2", seconds: 6 }],
    comp: [{ take: "second", from: 0, to: 6 }],
  });
  assert.equal(wholeTake(t), "second");
  assert.throws(() => addTake(null, { id: "x", seconds: 1 }), /first take/);
  const three = addTake(t, { id: "third", seconds: 4.12345 });
  assert.equal(three.list.length, 3);
  assert.deepEqual(three.list[2], { id: "third", name: "Take 3", seconds: 4.123 });
  assert.deepEqual(three.comp, [{ take: "third", from: 0, to: 4.123 }]);
});

test("takes are checked like the rest of the project; a missing field is no takes", () => {
  assert.equal(cleanTakes(undefined), null);
  assert.equal(cleanTakes(null), null);
  const t = two();
  assert.deepEqual(cleanTakes(t), t);
  assert.deepEqual(cleanTakes({ ...t, list: [{ ...t.list[0], name: "  Keeper " }, t.list[1]] }).list[0].name, "Keeper");
  for (const bad of [
    "x", [], {}, { list: [], comp: [] }, { ...t, extra: 1 },
    { ...t, list: [...t.list, t.list[0]] },
    { ...t, list: [{ id: "A", name: "x", seconds: 1 }], comp: [{ take: "A", from: 0, to: 1 }] },
    { ...t, list: [{ ...t.list[0], name: " " }, t.list[1]] },
    { ...t, list: [{ ...t.list[0], seconds: 0 }, t.list[1]] },
    { ...t, list: [{ ...t.list[0], seconds: 601 }, t.list[1]] },
    { ...t, list: [{ ...t.list[0], extra: 1 }, t.list[1]] },
    { ...t, comp: [] },
    { ...t, comp: [{ take: "nope", from: 0, to: 1 }] },
    { ...t, comp: [{ take: "first", from: 0, to: 5.5 }] },
    { ...t, comp: [{ take: "first", from: 2, to: 2 }] },
    { ...t, comp: [{ take: "first", from: -1, to: 2 }] },
    { ...t, comp: [{ take: "first", from: 2, to: 4 }, { take: "second", from: 1, to: 3 }] },
    { ...t, comp: [{ take: "first", from: 0, to: 2, extra: true }] },
    { list: Array.from({ length: MAX_TAKES + 1 }, (_, i) => ({ id: "t" + i, name: "T" + i, seconds: 1 })), comp: [{ take: "t0", from: 0, to: 1 }] },
  ]) assert.throws(() => cleanTakes(bad), undefined, JSON.stringify(bad));
  let full = two();
  for (let i = 3; i <= MAX_TAKES; i++) full = addTake(full, { id: "t" + i, seconds: 2 });
  assert.equal(full.list.length, MAX_TAKES);
  assert.throws(() => addTake(full, { id: "more", seconds: 2 }), /at most 8 takes/);
});

test("Use picks the whole of a take", () => {
  const t = pickTake(two(), "first");
  assert.deepEqual(t.comp, [{ take: "first", from: 0, to: 5 }]);
  assert.equal(wholeTake(t), "first");
  assert.throws(() => pickTake(t, "nope"), /No such take/);
});

test("Comp in puts a section of a take in place of what the comp held there", () => {
  const t = pickTake(two(), "first");
  // A section in the middle splits the comp in three.
  const mid = compSection(t, "second", 1.5, 3);
  assert.deepEqual(mid.comp, [{ take: "first", from: 0, to: 1.5 }, { take: "second", from: 1.5, to: 3 }, { take: "first", from: 3, to: 5 }]);
  assert.equal(wholeTake(mid), null);
  assert.equal(compText(mid), "Take 1 0:00.0-0:01.5, Take 2 0:01.5-0:03.0, Take 1 0:03.0-0:05.0");
  // A section over a join replaces the parts of both it covers; one of the same take as its neighbour merges with it.
  const over = compSection(mid, "first", 2, 4);
  assert.deepEqual(over.comp, [{ take: "first", from: 0, to: 1.5 }, { take: "second", from: 1.5, to: 2 }, { take: "first", from: 2, to: 5 }]);
  const back = compSection(mid, "first", 1.5, 3);
  assert.deepEqual(back.comp, [{ take: "first", from: 0, to: 5 }]);
  assert.equal(wholeTake(back), "first");
  // Past the end of the comp it grows (Take 2 is 6 s long); past the end of the take it is cut there.
  const longer = compSection(t, "second", 4, 9);
  assert.deepEqual(longer.comp, [{ take: "first", from: 0, to: 4 }, { take: "second", from: 4, to: 6 }]);
  assert.equal(compSeconds(longer), 6);
  // A section after a gap leaves silence before it.
  const short = compSection(pickTake(addTake(two(), { id: "tiny", seconds: 1 }), "tiny"), "second", 3, 4);
  assert.deepEqual(short.comp, [{ take: "tiny", from: 0, to: 1 }, { take: "second", from: 3, to: 4 }]);
  // The whole span covered by one take.
  assert.deepEqual(compSection(mid, "second", 0, 10).comp, [{ take: "second", from: 0, to: 6 }]);
  assert.throws(() => compSection(t, "second", 2, 2.05), /at least 0.1 s/);
  assert.throws(() => compSection(t, "second", 7, 8), /at least 0.1 s/);
  assert.throws(() => compSection(t, "nope", 0, 1), /No such take/);
  // Times are kept to the millisecond.
  assert.deepEqual(compSection(t, "second", 1.23456, 2.34567).comp[1], { take: "second", from: 1.235, to: 2.346 });
});

test("a comp holds at most MAX_SECTIONS sections", () => {
  let t = cleanTakes({ list: [{ id: "a", name: "A", seconds: 600 }, { id: "b", name: "B", seconds: 600 }], comp: [{ take: "a", from: 0, to: 600 }] });
  let n = 0;
  assert.throws(() => { for (; n < 100; n++) t = compSection(t, "b", 1 + n * 0.2, 1.1 + n * 0.2); }, /at most 64 sections/);
  assert.ok(t.comp.length <= MAX_SECTIONS && t.comp.length > MAX_SECTIONS - 3);
});

test("Remove keeps a take the comp uses and the only take", () => {
  const t = two();
  assert.throws(() => removeTake(t, "second"), /Take 2 is in the take the song uses/);
  const one = removeTake(t, "first");
  assert.deepEqual(one.list, [{ id: "second", name: "Take 2", seconds: 6 }]);
  assert.throws(() => removeTake(one, "second"), /in the take the song uses/);
  // The next new take takes the lowest free number.
  assert.equal(addTake(one, { id: "again", seconds: 1 }).list[1].name, "Take 1");
  assert.equal(nextTakeName([{ name: "Take 1" }, { name: "Take 3" }]), "Take 2");
});

test("the comp's key changes only when the recording it makes does", () => {
  const t = two();
  assert.equal(compSig(null), "");
  assert.notEqual(compSig(t), compSig(pickTake(t, "first")));
  assert.equal(compSig(t), compSig(removeTake(t, "first")));
  assert.deepEqual([...usedTakes(compSection(pickTake(t, "first"), "second", 1, 2))].sort(), ["first", "second"]);
  assert.equal(usedTakes(null).size, 0);
});

test("the comp renders each section from its take, crossing over at constant power", () => {
  const rate = 1000, a = new Float32Array(5000).fill(1), b = new Float32Array(6000).fill(-1);
  const sources = { first: a, second: b };
  // The whole of one take is that take.
  assert.deepEqual(renderComp(two(), sources, rate), b);
  const t = compSection(pickTake(two(), "first"), "second", 2, 3);
  const out = renderComp(t, sources, rate);
  assert.equal(out.length, 5000);
  // Away from the joins each stretch is its own take.
  for (const i of [0, 1000, 1989, 3011, 4999]) assert.equal(out[i], 1, "at " + i);
  for (const i of [2011, 2500, 2989]) assert.equal(out[i], -1, "at " + i);
  // Across a join the two gains have unit power: with takes of +1 and -1 the output is gA - gB.
  const ga = renderComp(t, { first: a, second: new Float32Array(6000) }, rate);
  const gb = renderComp(t, { first: new Float32Array(5000), second: b }, rate);
  for (let i = 1985; i < 2015; i++) assert.ok(Math.abs(ga[i] ** 2 + gb[i] ** 2 - 1) < 1e-6, "power at " + i);
  assert.ok(ga[1995] < 1 && ga[1995] > 0 && gb[1995] < 0, "both takes sound in the crossfade");
  for (let i = 0; i < out.length; i++) assert.ok(Math.abs(out[i] - (ga[i] + gb[i])) < 1e-6);
  // A take shorter than its section is silence past its end, and a gap is silence.
  const gap = compSection(pickTake(addTake(two(), { id: "tiny", seconds: 1 }), "tiny"), "second", 3, 4);
  const g = renderComp(gap, { ...sources, tiny: new Float32Array(500).fill(0.5) }, rate);
  assert.equal(g.length, 4000);
  assert.equal(g[100], 0.5);
  assert.equal(g[700], 0);
  assert.equal(g[2000], 0);
  assert.equal(g[3500], -1);
  assert.throws(() => renderComp(t, { first: a }, rate), /Take 2 is not on this device/);
  assert.throws(() => renderComp(null, sources, rate), /no takes/);
});

test("each take's recording is linked from the draft and versions under its key", () => {
  assert.equal(takeKey("abc"), "take-abc");
  assert.equal(takeFile("abc"), "take-abc.wav");
  assert.equal(takeIdOf("take-abc"), "abc");
  assert.equal(takeIdOf("layer-abc"), null);
  assert.ok(isTakeKey("take-abc") && !isTakeKey("take-ABC") && !isTakeKey("takeabc"));
  assert.ok(isExtraKey("take-abc") && isExtraKey("layer-abc") && !isExtraKey("original"));
  assert.throws(() => takeKey("Bad"), /Invalid take id/);
  const links = cleanLinks({ original: { id: HEX, type: "audio/wav" }, "take-first": { id: HEX2, type: "audio/wav" }, "take-Bad": { id: HEX3 }, "layer-x": { id: HEX3, type: "" } });
  assert.deepEqual(Object.keys(links).sort(), ["layer-x", "original", "take-first"]);
  assert.deepEqual([...linkedIds([links])].sort(), [HEX, HEX2, HEX3]);
  assert.match(newTakeId(), /^[a-z0-9]{12}$/);
  assert.equal(newTakeId(n => new Uint8Array(n)), "aaaaaaaaaaaa");
});

test("versions and Tandem files keep the takes and their recordings; older ones open unchanged", async () => {
  const takes = compSection(pickTake(two(), "first"), "second", 1, 2);
  const state = { ...ideaProject(), notes: [], drums: [], takes };
  assert.deepEqual(projectFromState(state).takes, takes);
  assert.ok(!("takes" in projectFromState({ ...state, takes: null })));
  const project = projectFromState(state);
  const bytes = writeBundle({ name: "Comped", project, recordings: { original: wav(), "take-first": wav(80), "take-second": wav(90) } });
  const back = await readBundle(bytes);
  assert.deepEqual(back.project.takes, takes);
  assert.deepEqual(Object.keys(back.recordings).sort(), ["original", "take-first", "take-second"]);
  assert.deepEqual(back.recordings["take-first"], wav(80));
  assert.throws(() => writeBundle({ project, recordings: { original: wav(), "take-first": new Uint8Array([1, 2, 3]) } }), /must be WAV/);
  // A file from before takes: one recording, no takes field.
  const old = await readBundle(writeBundle({ project: projectFromState({ ...ideaProject(), notes: [], drums: [] }), recordings: { original: wav() } }));
  assert.equal(cleanTakes(old.project.takes), null);
  assert.deepEqual(Object.keys(old.recordings), ["original"]);
});

test("Separate drops the vocal targets only from the snapshots of the comp in use", () => {
  const t = addTake(null, { id: "second", seconds: 4, first: { id: "first", seconds: 3 } });
  const other = pickTake(t, "first");
  const vocal = { notes: [{ m: 60, t: 0, d: 1 }], original: [{ m: 60, t: 0, d: 1 }] };
  const snapOf = (takes, v) => JSON.stringify({ project: { bpm: 120, takes }, vocal: v, key: null });
  const drop = dropCompVocal(compSig(t));
  assert.equal(JSON.parse(drop(snapOf(t, vocal))).vocal, null);
  const kept = snapOf(other, vocal);
  assert.equal(drop(kept), kept);
  // A snapshot from before the takes list (one recording, no takes) is a different comp too.
  const before = snapOf(null, vocal);
  assert.equal(drop(before), before);
  // With no takes, the one recording is the comp: its snapshots lose their targets.
  assert.equal(JSON.parse(dropCompVocal(compSig(null))(before)).vocal, null);
});
