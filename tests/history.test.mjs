import test from "node:test";
import assert from "node:assert/strict";
import { createHistory, DEFAULT_LIMIT, markHistory, editsSince } from "../history.js";

// Drive the history the way the studio does: `state` is the live snapshot, edit() records a change.
function studio(opts) {
  const h = createHistory(opts);
  let state = "s0";
  return {
    h,
    get state() { return state; },
    edit(next, label) { const recorded = h.record(state, next, label); state = next; return recorded; },
    undo() { const e = h.undo(state); if (e) state = e.snapshot; return e; },
    redo() { const e = h.redo(state); if (e) state = e.snapshot; return e; },
  };
}

test("starts empty with nothing to undo or redo", () => {
  const h = createHistory();
  assert.equal(h.canUndo, false);
  assert.equal(h.canRedo, false);
  assert.equal(h.undoLabel, null);
  assert.equal(h.redoLabel, null);
  assert.equal(h.undo("x"), null);
  assert.equal(h.redo("x"), null);
  assert.equal(h.limit, DEFAULT_LIMIT);
});

test("undo and redo walk the edits in order and restore each snapshot", () => {
  const s = studio();
  s.edit("s1", "Add note");
  s.edit("s2", "AI edit");
  s.edit("s3", "Change tempo");
  assert.deepEqual(s.undo(), { snapshot: "s2", label: "Change tempo" });
  assert.deepEqual(s.undo(), { snapshot: "s1", label: "AI edit" });
  assert.deepEqual(s.undo(), { snapshot: "s0", label: "Add note" });
  assert.equal(s.undo(), null);
  assert.equal(s.state, "s0");
  assert.equal(s.h.canUndo, false);
  assert.equal(s.h.canRedo, true);
  assert.deepEqual(s.redo(), { snapshot: "s1", label: "Add note" });
  assert.deepEqual(s.redo(), { snapshot: "s2", label: "AI edit" });
  assert.deepEqual(s.redo(), { snapshot: "s3", label: "Change tempo" });
  assert.equal(s.redo(), null);
  assert.equal(s.state, "s3");
  assert.equal(s.h.canRedo, false);
});

test("labels name the same edit on both sides", () => {
  const s = studio();
  s.edit("s1", "Open project");
  s.edit("s2", "Raise vocal target 2");
  assert.equal(s.h.undoLabel, "Raise vocal target 2");
  s.undo();
  assert.equal(s.h.undoLabel, "Open project");
  assert.equal(s.h.redoLabel, "Raise vocal target 2");
  assert.equal(createHistory().record("a", "b", undefined), true);
  const long = createHistory();
  long.record("a", "b", "x".repeat(500));
  assert.equal(long.undoLabel.length, 80);
});

test("a new edit clears the redo stack", () => {
  const s = studio();
  s.edit("s1", "Add note");
  s.edit("s2", "Add note");
  s.undo();
  assert.equal(s.h.canRedo, true);
  s.edit("s2b", "Clear drums");
  assert.equal(s.h.canRedo, false);
  assert.equal(s.redo(), null);
  assert.deepEqual(s.undo(), { snapshot: "s1", label: "Clear drums" });
  assert.deepEqual(s.undo(), { snapshot: "s0", label: "Add note" });
});

test("an edit that changed nothing is not recorded and keeps redo available", () => {
  const s = studio();
  s.edit("s1", "Add note");
  s.undo();
  assert.equal(s.edit("s0", "Change tempo"), false);
  assert.equal(s.h.canUndo, false);
  assert.equal(s.h.canRedo, true);
  assert.deepEqual(s.h.size, { undo: 0, redo: 1 });
});

test("the undo stack is capped, dropping the oldest edits", () => {
  const s = studio({ limit: 5 });
  for (let i = 1; i <= 12; i++) s.edit("s" + i, "Edit " + i);
  assert.deepEqual(s.h.size, { undo: 5, redo: 0 });
  const labels = [];
  while (s.h.canUndo) labels.push(s.undo().label);
  assert.deepEqual(labels, ["Edit 12", "Edit 11", "Edit 10", "Edit 9", "Edit 8"]);
  assert.equal(s.state, "s7");
  // Redo is bounded by what undo held, so it is capped too.
  assert.deepEqual(s.h.size, { undo: 0, redo: 5 });
  const big = studio();
  for (let i = 1; i <= DEFAULT_LIMIT * 3; i++) big.edit("s" + i, "Edit");
  assert.equal(big.h.size.undo, DEFAULT_LIMIT);
});

test("rejects an invalid limit", () => {
  for (const limit of [0, -1, 1.5, NaN, "10"]) assert.throws(() => createHistory({ limit }), /positive integer/);
});

test("rewrite maps stored snapshots and drops edits that became no-ops", () => {
  // Snapshots carry a project part and a vocal-target part; a new recording drops vocal targets.
  const snap = (project, vocal) => JSON.stringify({ project, vocal });
  const dropVocal = s => { const x = JSON.parse(s); x.vocal = null; return JSON.stringify(x); };
  const h = createHistory();
  let state = snap("0", null);
  for (const [next, label] of [
    [snap("A", null), "Open project"],
    [snap("A", [60]), "Detect sung notes"],
    [snap("A", [61]), "Raise vocal target 1"],
    [snap("B", [61]), "Add note"],
    [snap("B", [62]), "Raise vocal target 1"],
    [snap("C", [62]), "AI edit"],
  ]) { h.record(state, next, label); state = next; }
  state = h.undo(state).snapshot; // back to B/[62], with "AI edit" on the redo stack
  state = dropVocal(state);
  h.rewrite(dropVocal, state);
  // Only the project edits survive.
  assert.deepEqual(h.size, { undo: 2, redo: 1 });
  const undone = [];
  for (let e; (e = h.undo(state)); state = e.snapshot) undone.push([e.label, JSON.parse(e.snapshot).project]);
  assert.deepEqual(undone, [["Add note", "A"], ["Open project", "0"]]);
  const redone = [];
  for (let e; (e = h.redo(state)); state = e.snapshot) redone.push([e.label, JSON.parse(e.snapshot)]);
  assert.deepEqual(redone, [["Open project", { project: "A", vocal: null }], ["Add note", { project: "B", vocal: null }], ["AI edit", { project: "C", vocal: null }]]);
});

test("rewrite also prunes redo entries that no longer change anything", () => {
  const h = createHistory();
  h.record("a1", "a2", "vocal only");
  const e = h.undo("a2");
  assert.equal(e.snapshot, "a1");
  // After mapping both to "a", redoing would be a no-op, so the entry is dropped.
  h.rewrite(s => s.replace(/\d$/, ""), "a");
  assert.equal(h.canRedo, false);
  assert.equal(h.canUndo, false);
});

test("clear empties both stacks", () => {
  const s = studio();
  s.edit("s1", "Add note");
  s.edit("s2", "Add note");
  s.undo();
  s.h.clear();
  assert.deepEqual(s.h.size, { undo: 0, redo: 0 });
});

// UX.6: a change view notes where the history stands when it opens (markHistory); editsSince counts the Undo steps
// back to that point, which is what Put it back takes and what enables Before.
test("a view counts its edits and Undo and Redo move the count", () => {
  const s = studio();
  s.edit("s1", "Before the view");
  const mark = markHistory(s.h, s.state);
  assert.deepEqual(mark, { position: 1, snapshot: "s1" });
  assert.equal(editsSince(s.h, mark), 0);
  s.edit("s2", "Line up");
  s.edit("s3", "Speed");
  assert.equal(editsSince(s.h, mark), 2);
  s.undo();
  assert.equal(editsSince(s.h, mark), 1);
  s.redo();
  assert.equal(editsSince(s.h, mark), 2);
  // Undoing past the point the view opened at leaves nothing of this view's to put back.
  s.undo(); s.undo(); s.undo();
  assert.equal(s.state, "s0");
  assert.equal(editsSince(s.h, mark), 0);
  s.redo();
  assert.equal(editsSince(s.h, mark), 0);
  s.redo();
  assert.equal(editsSince(s.h, mark), 1);
});

test("an edit the chat makes while the view is open is one of the view's edits", () => {
  const s = studio();
  const mark = markHistory(s.h, s.state);
  s.edit("s1", "Line up");
  s.edit("s2", "AI edit");
  assert.equal(editsSince(s.h, mark), 2);
  // Put it back: as many Undo steps as the view made bring back the state it opened with, and Redo brings them back.
  for (let n = editsSince(s.h, mark); n > 0; n--) s.undo();
  assert.equal(s.state, mark.snapshot);
  assert.equal(editsSince(s.h, mark), 0);
  s.redo(); s.redo();
  assert.equal(s.state, "s2");
  assert.equal(editsSince(s.h, mark), 2);
});

test("a new edit after undoing past the mark leaves the view nothing to put back", () => {
  const s = studio();
  s.edit("s1", "Before the view");
  const mark = markHistory(s.h, s.state);
  s.edit("s2", "Line up");
  s.undo(); s.undo();
  // A different edit from the state before the view: position 1 is now "x1", not the state the view opened with.
  s.edit("x1", "Other");
  s.edit("x2", "Other again");
  assert.equal(s.h.position, 2);
  assert.equal(editsSince(s.h, mark), 0);
});

test("clearing the history or trimming it past the mark leaves the view nothing to put back", () => {
  const s = studio({ limit: 3 });
  const mark = markHistory(s.h, s.state);
  s.edit("s1", "a"); s.edit("s2", "b"); s.edit("s3", "c");
  assert.equal(editsSince(s.h, mark), 3);
  // The fourth edit drops the oldest state, the one the view opened with: Undo can no longer reach it.
  s.edit("s4", "d");
  assert.equal(s.h.position, 4);
  assert.equal(editsSince(s.h, mark), 0);
  const later = markHistory(s.h, s.state);
  s.edit("s5", "e");
  assert.equal(editsSince(s.h, later), 1);
  s.h.clear();
  assert.equal(editsSince(s.h, later), 0);
  assert.equal(s.h.position, 5);
  assert.equal(editsSince(s.h, null), 0);
});

test("a rewrite that changes the snapshots leaves the view nothing to put back", () => {
  const s = studio();
  const mark = markHistory(s.h, s.state);
  s.edit("s1", "a");
  s.h.rewrite(x => x + "!", "s1!");
  assert.equal(editsSince(s.h, mark), 0);
});
