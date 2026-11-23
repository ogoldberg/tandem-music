import test from "node:test";
import assert from "node:assert/strict";
import { MIX_PARTS, OWN_MUTE, LEVEL_MIN, LEVEL_MAX, cleanMix, channel, dbToGain, mixGains, setChannel, levelText, scaled } from "../mixer.js";

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("a project with no mix plays every part at full level, the voice left out", () => {
  const g = mixGains({});
  for (const p of MIX_PARTS) assert.equal(g[p], p === "voice" ? 0 : 1, p);
});

test("level in dB becomes a gain factor", () => {
  close(dbToGain(0), 1);
  close(dbToGain(-6), 0.501187233627, 1e-9);
  close(dbToGain(6), 1.995262314969, 1e-9);
  close(dbToGain(-20), 0.1);
  const g = mixGains({ mix: { melody: { level: -6 }, drums: { level: 3 } } });
  close(g.melody, dbToGain(-6));
  close(g.drums, dbToGain(3));
  close(g.harmony, 1);
});

test("mute silences a part; an unmuted voice is heard at its level", () => {
  const g = mixGains({ mix: { harmony: { mute: true }, voice: { mute: false, level: -3 } } });
  assert.equal(g.harmony, 0);
  close(g.voice, dbToGain(-3));
  assert.equal(g.melody, 1);
});

test("the band, instrument and sung harmony mute through their own field", () => {
  const project = { band: { muted: true }, timbre: { muted: false }, voice2_sung: { muted: true }, mix: { band: { level: -2 } } };
  const g = mixGains(project);
  assert.equal(g.band, 0);
  assert.equal(g.timbre, 1);
  assert.equal(g.voice2_sung, 0);
  assert.equal(channel(project, "band").level, -2);
  assert.deepEqual(OWN_MUTE, ["band", "timbre", "voice2_sung"]);
  assert.throws(() => cleanMix({ band: { mute: true } }), /Invalid mix/);
  assert.throws(() => setChannel({}, "timbre", { mute: true }), /own mute/);
});

test("a solo silences every other part, keeps levels, and several solos add up", () => {
  let g = mixGains({ mix: { drums: { solo: true, level: -4 } } });
  close(g.drums, dbToGain(-4));
  for (const p of MIX_PARTS) if (p !== "drums") assert.equal(g[p], 0, p);
  g = mixGains({ mix: { drums: { solo: true }, melody: { solo: true } } });
  assert.equal(g.drums, 1);
  assert.equal(g.melody, 1);
  assert.equal(g.harmony, 0);
});

test("a muted part stays silent when soloed, and its solo does not silence the rest", () => {
  const g = mixGains({ mix: { melody: { solo: true, mute: true } } });
  assert.equal(g.melody, 0);
  assert.equal(g.drums, 1);
  // The voice is muted by default, so a solo on it alone is no solo.
  const v = mixGains({ mix: { voice: { solo: true } } });
  assert.equal(v.voice, 0);
  assert.equal(v.melody, 1);
});

test("a solo on a part that is not there does not silence the song", () => {
  const project = { mix: { band: { solo: true } } };
  assert.equal(mixGains(project, ["melody", "drums"]).melody, 1);
  assert.equal(mixGains(project, ["melody", "drums", "band"]).melody, 0);
});

test("cleanMix keeps only what differs from the defaults and rounds to half a dB", () => {
  assert.deepEqual(cleanMix(undefined), {});
  assert.deepEqual(cleanMix(null), {});
  assert.deepEqual(cleanMix({ melody: { level: 0, mute: false, solo: false }, voice: { mute: true } }), {});
  assert.deepEqual(cleanMix({ melody: { level: -6.2 }, voice: { mute: false }, drums: { solo: true } }),
    { melody: { level: -6 }, voice: { mute: false }, drums: { solo: true } });
  assert.deepEqual(cleanMix({ melody: { level: LEVEL_MIN }, harmony: { level: LEVEL_MAX } }),
    { melody: { level: LEVEL_MIN }, harmony: { level: LEVEL_MAX } });
});

test("cleanMix refuses anything it does not know", () => {
  for (const bad of [[], "loud", { piano: { level: 0 } }, { melody: [] }, { melody: { level: "3" } }, { melody: { level: LEVEL_MAX + 1 } },
    { melody: { level: LEVEL_MIN - 1 } }, { melody: { level: NaN } }, { melody: { mute: "yes" } }, { melody: { solo: 1 } }, { melody: { pan: 0 } }]) {
    assert.throws(() => cleanMix(bad), /Invalid mix/, JSON.stringify(bad));
  }
});

test("setChannel changes one part and drops it when back at the defaults", () => {
  let mix = setChannel({}, "melody", { level: -6 });
  assert.deepEqual(mix, { melody: { level: -6 } });
  mix = setChannel(mix, "melody", { solo: true });
  assert.deepEqual(mix, { melody: { level: -6, solo: true } });
  mix = setChannel(mix, "voice", { mute: false });
  assert.deepEqual(mix, { melody: { level: -6, solo: true }, voice: { mute: false } });
  mix = setChannel(mix, "melody", { level: 0, solo: false });
  assert.deepEqual(mix, { voice: { mute: false } });
  assert.throws(() => setChannel({}, "kazoo", { level: 1 }), /Unknown mix part/);
});

test("levelText and scaled", () => {
  assert.equal(levelText(0), "0 dB");
  assert.equal(levelText(-6), "−6 dB");
  assert.equal(levelText(3.5), "+3.5 dB");
  assert.deepEqual([...scaled(Float32Array.from([1, -0.5, 0.25]), 0.5)], [0.5, -0.25, 0.125]);
});

// FX.1: a little room on the voice.
import { ROOM_SECONDS, ROOM_PREDELAY, ROOM_WET, roomGains, roomImpulse, roomText, roundRoom } from "../mixer.js";

test("the voice's room is kept in the mix on a 5 % grid, zero left out, and only the voice has one", () => {
  assert.deepEqual(cleanMix({ voice: { room: 0.3 } }), { voice: { room: 0.3 } });
  assert.deepEqual(cleanMix({ voice: { room: 0.149 } }), { voice: { room: 0.15 } });
  assert.deepEqual(cleanMix({ voice: { room: 0, mute: true } }), {});
  assert.equal(channel({}, "voice").room, 0);
  assert.equal(channel({ mix: { voice: { room: 0.45 } } }, "voice").room, 0.45);
  assert.equal("room" in channel({}, "melody"), false);
  for (const bad of [-0.05, 1.05, NaN, "0.3", null]) assert.throws(() => cleanMix({ voice: { room: bad } }), /Invalid mix/, String(bad));
  assert.throws(() => cleanMix({ melody: { room: 0.3 } }), /Invalid mix/);
  assert.throws(() => setChannel({}, "drums", { room: 0.3 }), /Only your voice has a room/);
  assert.deepEqual(setChannel({ voice: { level: -3 } }, "voice", { room: 0.2 }), { voice: { level: -3, room: 0.2 } });
  assert.deepEqual(setChannel({ voice: { room: 0.2 } }, "voice", { room: 0 }), {});
  assert.equal(roundRoom(0.15), 0.15);
  assert.equal(roomText(0), "Dry");
  assert.equal(roomText(0.3), "30 %");
});

test("zero room is the dry voice alone; the dry voice is never turned down", () => {
  assert.deepEqual(roomGains(0), { dry: 1, wet: 0 });
  assert.deepEqual(roomGains(undefined), { dry: 1, wet: 0 });
  assert.deepEqual(roomGains(1), { dry: 1, wet: ROOM_WET });
  close(roomGains(0.5).wet, ROOM_WET / 2);
  assert.deepEqual(roomGains(4), { dry: 1, wet: ROOM_WET });
  assert.ok(ROOM_WET <= 0.5, "a little room: the wet voice at most 6 dB under the dry one");
});

test("the room's impulse is a short gap, then a tail that falls 60 dB over ROOM_SECONDS, at unit energy", () => {
  for (const rate of [44100, 48000, 22050]) {
    const ir = roomImpulse(rate), gap = Math.round(ROOM_PREDELAY * rate), tail = Math.round(ROOM_SECONDS * rate);
    assert.equal(ir.length, gap + tail, String(rate));
    assert.ok(ir.subarray(0, gap).every(v => v === 0), "silent before the tail");
    assert.notEqual(ir[gap + 1], 0);
    let energy = 0;
    for (const v of ir) energy += v * v;
    close(energy, 1, 1e-4);
    // The envelope in 20 ms windows: it falls steadily, about 60 dB from the start of the tail to its end.
    const win = Math.round(0.02 * rate), rms = from => Math.sqrt(ir.subarray(from, from + win).reduce((a, v) => a + v * v, 0) / win);
    const first = rms(gap + win), last = rms(ir.length - win);
    const drop = 20 * Math.log10(first / last);
    assert.ok(drop > 50 && drop < 70, `${rate}: fell ${drop.toFixed(1)} dB`);
    const half = 20 * Math.log10(first / rms(gap + Math.round(tail / 2)));
    assert.ok(half > 22 && half < 36, `${rate}: half way fell ${half.toFixed(1)} dB`);
  }
  assert.deepEqual(roomImpulse(44100), roomImpulse(44100), "the same tail every time");
  assert.throws(() => roomImpulse(0), /Invalid sample rate/);
});
