// GROW.4: Song shape, the song as a row of blocks (SONG.1's sections, in whole bars). A song with no sections is one
// block, the idea, which is not written into the project until the first thing done to it (Play it again, Earlier,
// Later, Remove, a new name): that edit marks it (`ideaBlock`) and pins the bar grid (GROW.1) at the same time
// (`withIdea`), so the bars a repeat copies stay where they were heard.
// Pure, DOM-free: index.html and the Node tests import it.

import { barGrid, barsBetween, pickup, songBars } from "./bars.js";
import { MAX_TIME, cleanSections } from "./sections.js";

export const IDEA_NAME = "Your idea";
const EPS = 1e-3;
const round3 = x => Math.round(x * 1000) / 1000;

// The idea as one block of whole bars: from the bar the song's first bar starts on (bars.js songBars: the bar after a
// pickup, which stays before the block as its lead-in) to the bar line at or after `end`, the end of everything the song
// has (every part and recording). `tune` is where the tune (the melody and the voice) ends: when its whole bars are fewer
// than the song's (a short hum over a starter beat), `sung` offers the block to the end of the tune instead, and
// `asSung` takes it. Returns {name, from, to, bars, pickup, sung}: sung is {from, to, bars} or null. Throws when the song
// has nothing in it.
export function ideaBlock(project, { end = 0, tune = 0, asSung = false } = {}) {
  if (!(Number(end) > EPS)) throw Error("Sing or add something first: the song has nothing to shape yet.");
  const { bar } = barGrid(project);
  const whole = songBars(project, end), from = whole.start;
  let sung = null;
  if (Number(tune) > EPS) {
    const bars = songBars(project, tune).bars;
    if (bars < whole.bars) sung = { from: round3(from), to: round3(from + bars * bar), bars };
  }
  const bars = asSung && sung ? sung.bars : whole.bars;
  const to = round3(from + bars * bar);
  if (to > MAX_TIME + EPS) throw Error(`The song is longer than ${MAX_TIME} seconds.`);
  return { name: IDEA_NAME, from: round3(from), to, bars, pickup: pickup(project), sung };
}

// The project's fields once the idea is written: {sections, grid}, the one block and the bar grid pinned where it is
// now (a grid already pinned is kept). Refused when the song has sections already.
export function withIdea(project, block) {
  if (cleanSections(project.sections).length) throw Error("The song has its blocks already.");
  const { origin } = barGrid(project);
  return {
    sections: cleanSections([{ name: block.name, from: block.from, to: block.to }]),
    grid: project.grid != null ? { ...project.grid } : { origin },
  };
}

// A block's length in words: whole bars on the song's grid ("4 bars"), else seconds ("1.2 s") for a block marked by the
// beat on the Timeline that is not a whole number of bars.
export function blockLength(project, block) {
  const grid = barGrid(project), n = barsBetween(block.from, block.to, grid);
  if (n > 0 && Math.abs(n * grid.bar - (block.to - block.from)) < 2 * EPS) return n === 1 ? "1 bar" : n + " bars";
  return (block.to - block.from).toFixed(1) + " s";
}

// m:ss for a length in seconds.
export function clock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

// The Song shape tile's state line: "One part, 0:10" for a song with no sections, else the blocks' names and the
// length ("Verse, Verse, Chorus, 1:12"); a long list is cut after six names. "Nothing yet" for an empty song.
export function shapeLine(sections, seconds) {
  if (!(Number(seconds) > 0.5)) return "Nothing yet";
  const list = cleanSections(sections);
  if (!list.length) return "One part, " + clock(seconds);
  const names = list.map(s => s.name), shown = names.length > 6 ? [...names.slice(0, 6), "and " + (names.length - 6) + " more"] : names;
  return shown.join(", ") + ", " + clock(seconds);
}
