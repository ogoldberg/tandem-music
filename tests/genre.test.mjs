// GENRE.1: the optional genre. No genre gives exactly what Tandem made before genres (the fixture was written by
// the harmony.js and groove.js of the commit before GENRE.1); each genre's choices are applied as its table says.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GENRES, GENRE_IDS, VOICINGS, RHYTHMS, BASS_PATTERNS, genreById, cleanGenre, harmonyStyle, tempoRange, beatFor, genreChanges, checkGenres } from "../genre.js";
import { generateHarmony, readChords, detectKey } from "../harmony.js";
import { estimateTempo, quantizeProject, TEMPO_RANGE } from "../groove.js";
import { GROOVES } from "../beats.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/genre-none.json", import.meta.url)));
const NOTES = [60, 64, 67, 69, 67, 64, 62, 60, 65, 69, 72, 69, 67, 64, 62, 60, 57, 60, 64, 62].map((m, i) => ({ m, t: Math.round(i * 0.55 * 1000) / 1000, d: 0.45 }));
const pcOf = m => ((m % 12) + 12) % 12;

test("no genre gives today's harmony and tempo byte for byte", () => {
  for (const feel of [undefined, null, harmonyStyle(null), harmonyStyle(""), harmonyStyle(undefined)]) {
    const out = {
      chords: generateHarmony({ bpm: 96, notes: NOTES }, { style: "chords", feel }),
      bass: generateHarmony({ bpm: 96, notes: NOTES }, { style: "bass", feel }),
      minor: generateHarmony({ bpm: 120, notes: NOTES.map(n => ({ ...n, m: n.m - 3 })) }, { style: "chords", key: { tonic: 9, mode: "minor" }, feel }),
      tempo: [estimateTempo(NOTES.map(n => n.t), { prefer: tempoRange(null) }), estimateTempo(Array.from({ length: 16 }, (_, i) => i * 0.4), { prefer: tempoRange(null) })],
    };
    assert.equal(JSON.stringify(out), JSON.stringify(fixture));
  }
  assert.deepEqual(tempoRange(null), TEMPO_RANGE);
  assert.equal(beatFor(null), null);
  assert.deepEqual(genreChanges(null), { genre: null });
});

test("the genre table only names things the studio has, and matches the backend's genres", () => {
  assert.equal(checkGenres(), true);
  assert.deepEqual(GENRE_IDS, ["pop", "rock", "folk", "jazz", "hiphop", "electronic"]);
  const src = readFileSync(new URL("../tandem_backend.py", import.meta.url), "utf8");
  const block = src.match(/^GENRES=\{([\s\S]*?)^\}/m);
  assert.ok(block, "GENRES found in tandem_backend.py");
  assert.deepEqual([...block[1].matchAll(/^\s*"([a-z]+)":/gm)].map(m => m[1]), [...GENRE_IDS]);
  for (const g of GENRES) {
    assert.ok(VOICINGS.includes(g.harmony.voicing) && g.harmony.rhythm in RHYTHMS && BASS_PATTERNS.includes(g.harmony.bass));
    assert.ok(GROOVES.some(x => x.id === g.groove));
  }
});

test("a genre id is cleaned, and an unknown one is refused", () => {
  assert.equal(cleanGenre("jazz"), "jazz");
  assert.equal(cleanGenre(null), null);
  assert.equal(cleanGenre(undefined), null);
  assert.throws(() => cleanGenre("polka"), /no genre called polka/);
  assert.throws(() => cleanGenre(3), /no genre/);
  assert.equal(genreById("rock").name, "Rock");
});

test("choosing a genre sets the genre and its instruments in one change", () => {
  assert.deepEqual(genreChanges("jazz"), { genre: "jazz", instrument: "piano", harmony_instrument: "organ" });
  assert.deepEqual(genreChanges("electronic"), { genre: "electronic", instrument: "chip", harmony_instrument: "strings" });
});

const chordsBy = notes => { const m = new Map(); for (const n of notes) m.set(n.t, [...(m.get(n.t) || []), n.m]); return m; };

test("each genre voices and strikes the chords its own way, and they still read as the key's chords", () => {
  const plain = generateHarmony({ bpm: 96, notes: NOTES }, { style: "chords" });
  const bars = plain.chords.length;
  for (const g of GENRES) {
    const h = generateHarmony({ bpm: 96, notes: NOTES }, { style: "chords", feel: g.harmony });
    assert.notDeepEqual(h.notes, plain.notes, g.id);
    const strikes = chordsBy(h.notes);
    assert.equal(strikes.size, bars * RHYTHMS[g.harmony.rhythm], `${g.id} strikes`);
    const size = { triad: 3, seventh: 4, power: 3, open: 3 }[g.harmony.voicing];
    for (const ms of strikes.values()) assert.equal(ms.length, size, g.id);
    // Every chord tone is in the chord the bar was given.
    const read = readChords(h.notes, { bpm: 96, key: h.key });
    assert.ok(read.length >= bars && read.length <= bars * RHYTHMS[g.harmony.rhythm]);
    h.chords.forEach((c, b) => {
      const said = read.find(r => Math.abs(r.t - c.t) < 1e-3);
      assert.ok(said, `${g.id} bar ${b} is read`);
      assert.ok(said.name.startsWith(c.name.replace(/m$/, "")), `${g.id} bar ${b}: ${said.name} for ${c.name}`);
    });
  }
});

test("voicings: sevenths add the key's seventh, power chords are root fifth octave, open chords are a tenth wide", () => {
  const feel = v => ({ ...genreById("pop").harmony, voicing: v, rhythm: "bar" });
  const key = { tonic: 0, mode: "major" };
  const first = v => [...chordsBy(generateHarmony({ bpm: 96, notes: NOTES }, { style: "chords", key, feel: feel(v) }).notes).values()][0].sort((a, b) => a - b);
  assert.deepEqual(first("seventh").map(pcOf).sort((a, b) => a - b), [0, 4, 7, 11]);
  const p = first("power");
  assert.deepEqual([p[1] - p[0], p[2] - p[0], pcOf(p[0])], [7, 12, 0]);
  const o = first("open");
  assert.deepEqual([o[1] - o[0], o[2] - o[0], pcOf(o[0])], [7, 16, 0]);
  // In a minor key the seventh of V is the dominant seventh (harmonic minor's V, natural minor's seventh).
  const minor = generateHarmony({ bpm: 120, notes: [{ m: 64, t: 0, d: 1.8 }, { m: 68, t: 0.1, d: 1.5 }, { m: 71, t: 0.2, d: 1.5 }] }, { style: "chords", key: { tonic: 9, mode: "minor" }, feel: feel("seventh") });
  assert.equal(minor.chords[0].roman, "V");
  assert.deepEqual(minor.notes.map(n => pcOf(n.m)).sort((a, b) => a - b), [2, 4, 8, 11]);
});

test("bass patterns: roots on the beat, a walking line, octaves and a held root", () => {
  const key = { tonic: 0, mode: "major" }, beat = 60 / 96;
  const bass = b => generateHarmony({ bpm: 96, notes: NOTES }, { style: "bass", key, feel: { ...genreById("pop").harmony, bass: b } });
  const plain = generateHarmony({ bpm: 96, notes: NOTES }, { style: "bass", key });
  assert.deepEqual(bass("rootfifth").notes, plain.notes);
  const bars = plain.chords.length;
  assert.equal(bass("roots").notes.length, bars * 4);
  assert.equal(bass("octaves").notes.length, bars * 8);
  assert.equal(bass("held").notes.length, bars);
  const o = bass("octaves").notes;
  assert.equal(o[1].m - o[0].m, 12);
  const w = bass("walk"), roots = w.chords.map(c => c.name);
  for (let b = 0; b < bars; b++) {
    const bar = w.notes.slice(b * 4, b * 4 + 4), root = bar[0].m;
    assert.equal(pcOf(root), pcOf({ C: 0, F: 5, G: 7, Am: 9, Dm: 2, Em: 4 }[roots[b]]));
    assert.deepEqual(bar.map(n => Math.round((n.t - w.chords[b].t) / beat * 1000) / 1000), [0, 1, 2, 3]);
    assert.ok(bar.every(n => n.m >= root && n.m < root + 12));
    const next = roots[b + 1] ?? roots[0];
    if (next !== roots[b]) assert.equal(pcOf(bar[3].m + 1), pcOf({ C: 0, F: 5, G: 7, Am: 9, Dm: 2, Em: 4 }[next]), `bar ${b} leads into ${next}`);
  }
});

test("a genre's prior changes which chord a bar leans to", () => {
  // A bar of A and C held together fits F (IV) and Am (vi) exactly as well: Tandem's own prior and most genres
  // take IV, electronic leans to vi.
  const notes = [{ m: 69, t: 0, d: 2.4 }, { m: 72, t: 0, d: 2.4 }];
  const key = { tonic: 0, mode: "major" };
  const pick = id => generateHarmony({ bpm: 100, notes }, { style: "chords", key, feel: harmonyStyle(id) }).chords[0].name;
  assert.equal(pick(null), "F");
  assert.equal(pick("pop"), "F");
  assert.equal(pick("electronic"), "Am");
});

test("FIX.4: Detect tempo prefers the genre's range on a near tie, never over a clearly better fit", () => {
  // Notes every 0.4 s fit 150 and 75 bpm about as well: the genre's range picks between them.
  const eighths = Array.from({ length: 16 }, (_, i) => i * 0.4);
  assert.equal(estimateTempo(eighths), 150);
  assert.equal(estimateTempo(eighths, { prefer: tempoRange("hiphop") }), 75);
  assert.equal(estimateTempo(eighths, { prefer: tempoRange("electronic") }), 150, "neither in 110..140: the better fit");
  for (const g of GENRES) {
    const bpm = estimateTempo(eighths, { prefer: tempoRange(g.id) });
    assert.ok(bpm === 75 || bpm === 150, `${g.id}: ${bpm}`);
    if (bpm === 75) assert.ok(75 >= g.tempo[0] && 75 <= g.tempo[1], `${g.id} took 75 outside its range`);
  }
  // Quarters at 150 bpm: 150 fits clearly better than anything in pop's 80..140, so it stays 150.
  const quarters = [0, 1, 1.5, 2.5, 3, 4, 5, 6, 6.5, 7.5, 8].map(b => 0.3 + b * 0.4);
  assert.equal(estimateTempo(quarters, { prefer: tempoRange("pop") }), 150);
  assert.throws(() => estimateTempo(eighths, { prefer: [30, 100] }), /45\.\.220/);
});

test("a beat is lined up to the genre's grid and swing", () => {
  const played = [0, 0.27, 0.49, 0.77, 1.02, 1.26, 1.5, 1.74].map((t, i) => ({ k: i % 2 ? "hat" : "kick", t }));
  const jazz = quantizeProject({ bpm: 120, notes: [], drums: played }, beatFor("jazz"));
  const rock = quantizeProject({ bpm: 120, notes: [], drums: played }, beatFor("rock"));
  // Jazz: eighths swung to the triplet (the offbeat a third of a beat late), at 75%; rock: straight sixteenths, fully.
  assert.notDeepEqual(jazz.drums, rock.drums);
  assert.deepEqual(rock.drums.map(h => h.t), [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75]);
  assert.ok(jazz.drums[1].t > 0.3, "the jazz offbeat is pulled late: " + jazz.drums[1].t);
});

test("detectKey still finds the key of the fixture tune", () => {
  assert.deepEqual({ ...detectKey(NOTES), confidence: undefined }, { tonic: 0, mode: "major", confidence: undefined });
});
