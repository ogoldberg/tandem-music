import { test } from "node:test";
import assert from "node:assert/strict";
import { GROOVES, grooveById, grooveHits, barSeconds, barsToCover, withBeat, grooveWindow, MAX_BARS } from "../beats.js";
import { quantizeProject } from "../groove.js";
import { midiFile, DRUM_NOTES } from "../daw.js";

const WANT = {
  // hits per bar: kick, snare, hat
  straight: [2, 2, 8],
  halftime: [2, 1, 8],
  shuffle: [2, 2, 8],
  four: [4, 2, 4],
};

test("each groove has the right hits in every bar, at any tempo", () => {
  assert.deepEqual(GROOVES.map(g => g.id), Object.keys(WANT));
  for (const g of GROOVES) for (const bpm of [45, 100, 137, 220]) {
    const bars = 3, hits = grooveHits(g.id, { bpm, bars }), bar = 240 / bpm;
    assert.equal(hits.length, bars * WANT[g.id].reduce((a, b) => a + b, 0), `${g.id} at ${bpm}`);
    for (let b = 0; b < bars; b++) {
      const inBar = hits.filter(h => h.t >= b * bar - 1e-5 && h.t < (b + 1) * bar - 1e-5);
      assert.deepEqual(["kick", "snare", "hat"].map(k => inBar.filter(h => h.k === k).length), WANT[g.id], `${g.id} bar ${b} at ${bpm}`);
      // Every bar is the first bar moved on by whole bars.
      const first = hits.filter(h => h.t < bar - 1e-5);
      assert.deepEqual(inBar.map(h => h.k), first.map(h => h.k));
      assert.ok(inBar.every((h, i) => Math.abs(h.t - b * bar - first[i].t) < 1e-5));
    }
    // In time order, kick before snare before hi-hat when together; every hit inside its bars.
    for (let i = 1; i < hits.length; i++) assert.ok(hits[i].t >= hits[i - 1].t);
    assert.ok(hits.every(h => h.t >= 0 && h.t < bars * bar));
  }
});

test("the beat falls where it should: the backbeat, the half-time snare, the swung hi-hat, a kick on every beat", () => {
  const beat = 0.5; // 120 bpm
  const at = (id, k) => grooveHits(id, { bpm: 120, bars: 1 }).filter(h => h.k === k).map(h => h.t / beat);
  assert.deepEqual(at("straight", "snare"), [1, 3]);
  assert.deepEqual(at("halftime", "snare"), [2]);
  assert.deepEqual(at("halftime", "kick"), [0, 2.5]);
  assert.deepEqual(at("straight", "kick"), [0, 2]);
  assert.deepEqual(at("four", "kick"), [0, 1, 2, 3]);
  assert.deepEqual(at("four", "hat"), [0.5, 1.5, 2.5, 3.5]);
  const swung = at("shuffle", "hat").map(x => +(x % 1).toFixed(4));
  assert.deepEqual(swung, [0, 0.6667, 0, 0.6667, 0, 0.6667, 0, 0.6667]);
  // From a start time.
  assert.equal(grooveHits("straight", { bpm: 120, bars: 1, from: 1.25 })[0].t, 1.25);
});

test("the grooves are all different", () => {
  const keys = GROOVES.map(g => JSON.stringify(grooveHits(g.id, { bpm: 100, bars: 1 })));
  assert.equal(new Set(keys).size, GROOVES.length);
});

test("a groove quantizes to itself and exports to the MIDI file's drum keys", () => {
  for (const g of GROOVES) {
    const drums = grooveHits(g.id, { bpm: 96, bars: 2 });
    const q = quantizeProject({ bpm: 96, notes: [], drums }, { division: g.id === "shuffle" ? 2 : 4, swing: g.id === "shuffle" ? 1 : 0 });
    assert.deepEqual(q.drums.map(h => [h.k, +h.t.toFixed(4)]), drums.map(h => [h.k, +h.t.toFixed(4)]), g.id);
  }
  const bytes = midiFile({ bpm: 120, instrument: "piano", notes: [], drums: grooveHits("four", { bpm: 120, bars: 1 }) });
  // Note-ons on channel 10 (0x99): four kicks, two snares, four hats.
  const ons = [];
  for (let i = 0; i < bytes.length - 2; i++) if (bytes[i] === 0x99 && bytes[i + 2] > 0) ons.push(bytes[i + 1]);
  assert.deepEqual([DRUM_NOTES.kick, DRUM_NOTES.snare, DRUM_NOTES.hat].map(n => ons.filter(x => x === n).length), [4, 2, 4]);
});

test("replace or keep the drums already there", () => {
  const hits = grooveHits("straight", { bpm: 120, bars: 1 });
  const mine = [{ k: "snare", t: 0.51 }, { k: "kick", t: 0.25 }];
  assert.deepEqual(withBeat(mine, hits), hits);
  const kept = withBeat(mine, hits, { keep: true });
  // My snare at 0.51 stands in for the beat's snare at 0.5; my off-beat kick stays.
  assert.equal(kept.length, hits.length + 1);
  assert.ok(kept.some(h => h.k === "snare" && h.t === 0.51) && !kept.some(h => h.k === "snare" && h.t === 0.5));
  assert.ok(kept.some(h => h.k === "kick" && h.t === 0.25));
  for (let i = 1; i < kept.length; i++) assert.ok(kept[i].t >= kept[i - 1].t);
  // The inputs are not changed.
  assert.deepEqual(mine, [{ k: "snare", t: 0.51 }, { k: "kick", t: 0.25 }]);
});

test("bars to cover a song, and what is refused", () => {
  assert.equal(barSeconds(120), 2);
  assert.equal(barsToCover(0, 120), 4);
  assert.equal(barsToCover(9, 120), 5);
  assert.equal(barsToCover(10, 120), 5);
  assert.equal(barsToCover(10000, 120), MAX_BARS);
  assert.throws(() => grooveById("polka"), /no starter beat called polka/);
  assert.throws(() => grooveHits("straight", { bpm: 0, bars: 4 }), /tempo/);
  assert.throws(() => grooveHits("straight", { bpm: 100, bars: 0 }), /1 to 256 bars/);
  assert.throws(() => grooveHits("straight", { bpm: 100, bars: 2.5 }), /1 to 256 bars/);
  assert.throws(() => grooveHits("straight", { bpm: 100, bars: 257 }), /1 to 256 bars/);
});

test("GROW.2: a beat as long as a whole song, and never past the project's 10 minutes", () => {
  assert.equal(MAX_BARS, 256);
  assert.equal(barsToCover(180, 120), 90);
  // 90 bars of the straight beat: 12 hits a bar, more than the 1,024 a part the chat carries.
  const song = grooveHits("straight", { bpm: 120, bars: 90 });
  assert.equal(song.length, 1080);
  assert.equal(song.at(-1).t, 179.75);
  // 256 bars at 100 bpm would run to 614 s: the hits after 600 s are left out, the rest are kept. 250 bars end
  // at 600 s exactly, so what is kept is those 250 bars and the next bar's downbeat at 600 s (the schema's last time).
  const long = grooveHits("straight", { bpm: 100, bars: 256 });
  const at600 = grooveHits("straight", { bpm: 100, bars: 251 }).filter(h => h.t === 600);
  assert.equal(long.at(-1).t, 600);
  assert.ok(at600.length > 0);
  assert.deepEqual(long, [...grooveHits("straight", { bpm: 100, bars: 250 }), ...at600]);
  assert.equal(grooveHits("four", { bpm: 220, bars: 256 }).length, 2560);
});

test("the capture page's beat: the hits due in each window, from the take's zero, none twice and none missed", () => {
  // 100 bpm: a bar is 2.4 s. The beat starts at zero = 3.1 (the end of a count-in) and runs until stopped.
  const zero = 3.1, bpm = 100, all = grooveHits("straight", { bpm, bars: 5, from: zero });
  const ticks = [];
  for (let from = 0; from < 14.99; from += 0.2) ticks.push(...grooveWindow("straight", { bpm, zero, from: Math.round(from * 10) / 10, to: Math.round((from + 0.2) * 10) / 10 }));
  assert.deepEqual(ticks.map(h => [h.k, h.t]), all.map(h => [h.k, h.t]));
  // Each hit also says where it is in the song (seconds from zero), the same as the drum part opened in the studio.
  assert.deepEqual(ticks.map(h => [h.k, h.s]), grooveHits("straight", { bpm, bars: 5 }).map(h => [h.k, h.t]));
  // Nothing before zero, and a window inside one bar.
  assert.deepEqual(grooveWindow("four", { bpm: 120, zero: 10, from: 0, to: 10 }), []);
  // 120 bpm, a beat is 0.5 s: from 2.4 to 3.1 s into the song are bar 2's second beat (kick and snare), the hi-hat
  // after it and the third beat (kick).
  assert.deepEqual(grooveWindow("four", { bpm: 120, zero: 10, from: 12.4, to: 13.1 }).map(h => [h.k, h.s]),
    [["kick", 2.5], ["snare", 2.5], ["hat", 2.75], ["kick", 3]]);
  assert.throws(() => grooveWindow("waltz", { bpm: 120, zero: 0, from: 0, to: 1 }), /no starter beat/);
});
