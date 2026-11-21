// Edit history for the studio (EDIT.1): bounded undo/redo over whole-project snapshots.
// Pure and DOM-free so Node tests import it directly. Snapshots are opaque values compared with
// `===`; the studio passes JSON strings, which are immutable and cheap to compare.
//
// Model: the undo stack holds the states *before* each edit, the redo stack the states *after*
// each undone edit. Each entry carries the label of the edit that separates it from its neighbour,
// so "Undo: Add note" and "Redo: Add note" name the same edit.

export const DEFAULT_LIMIT = 100;

export function createHistory({ limit = DEFAULT_LIMIT } = {}) {
  if (!(Number.isInteger(limit) && limit > 0)) throw Error("History limit must be a positive integer");
  // floor is the position of undoStack[0]: the number of edits done since the history began, net of undos, that can no
  // longer be undone (trimmed past the limit or cleared). position = floor + undoStack.length (UX.6).
  let undoStack = [], redoStack = [], floor = 0;
  const clean = label => String(label ?? "Edit").slice(0, 80) || "Edit";

  return {
    get limit() { return limit; },
    get canUndo() { return undoStack.length > 0; },
    get canRedo() { return redoStack.length > 0; },
    get undoLabel() { return undoStack.at(-1)?.label ?? null; },
    get redoLabel() { return redoStack.at(-1)?.label ?? null; },
    get size() { return { undo: undoStack.length, redo: redoStack.length }; },
    get position() { return floor + undoStack.length; },

    // The snapshot Undo would reach at `position` (a position below the current one), or null when it is out of reach.
    snapshotAt(position) {
      const i = position - floor;
      return Number.isInteger(i) && i >= 0 && i < undoStack.length ? undoStack[i].snapshot : null;
    },

    // Record an edit that turned `before` into `after`. An edit that changed nothing is not
    // recorded and leaves the redo stack intact. Returns whether the edit was recorded.
    record(before, after, label) {
      if (before === after) return false;
      undoStack.push({ snapshot: before, label: clean(label) });
      if (undoStack.length > limit) floor += undoStack.splice(0, undoStack.length - limit).length;
      redoStack = [];
      return true;
    },

    // Step back from `current`. Returns {snapshot, label} to restore, or null when there is nothing
    // to undo. `current` becomes the redo target for the same edit.
    undo(current) {
      const entry = undoStack.pop();
      if (!entry) return null;
      redoStack.push({ snapshot: current, label: entry.label });
      return { snapshot: entry.snapshot, label: entry.label };
    },

    redo(current) {
      const entry = redoStack.pop();
      if (!entry) return null;
      undoStack.push({ snapshot: current, label: entry.label });
      return { snapshot: entry.snapshot, label: entry.label };
    },

    // Rewrite every stored snapshot with `map` (for example to drop data that no longer applies,
    // such as vocal targets of a replaced recording), then discard edits that became no-ops.
    // `current` must already be in its mapped form.
    rewrite(map, current) {
      const undoMapped = undoStack.map(e => ({ ...e, snapshot: map(e.snapshot) }));
      const redoMapped = redoStack.map(e => ({ ...e, snapshot: map(e.snapshot) }));
      // Undo entry i is the state before the edit leading to entry i+1 (or to `current`).
      const before = undoStack.length;
      undoStack = undoMapped.filter((e, i) => e.snapshot !== (i + 1 < undoMapped.length ? undoMapped[i + 1].snapshot : current));
      // Redo entries run from the bottom (furthest future) to the top (next state after `current`).
      redoStack = redoMapped.filter((e, i) => e.snapshot !== (i + 1 < redoMapped.length ? redoMapped[i + 1].snapshot : current));
      floor += before - undoStack.length;
      return this.size;
    },

    clear() { floor += undoStack.length; undoStack = []; redoStack = []; },
  };
}

// UX.6: where the history stands when a change view opens, with the state it opened with.
export const markHistory = (history, current) => ({ position: history.position, snapshot: current });

// The Undo steps that lead back to `mark`: the edits made since it, while Undo can still reach the state it noted
// (not undone past and edited from, trimmed, cleared or rewritten). Zero when there is nothing of the view's to put back.
export function editsSince(history, mark) {
  if (!mark) return 0;
  const steps = history.position - mark.position;
  return steps > 0 && history.snapshotAt(mark.position) === mark.snapshot ? steps : 0;
}
