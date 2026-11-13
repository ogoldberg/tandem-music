import test from "node:test";
import assert from "node:assert/strict";
import {
  midiSupported, listPorts, partChannels, readMessage, createKeyRecorder, addTake, songEvents, silence, createSender,
  DRUM_CHANNEL, VELOCITY,
} from "../midi.js";
import { PROGRAMS, DRUM_NOTES, DRUM_SECONDS } from "../daw.js";

test("Web MIDI is offered only where the browser has requestMIDIAccess", () => {
  assert.equal(midiSupported({ requestMIDIAccess() {} }), true);
  assert.equal(midiSupported({}), false);
  assert.equal(midiSupported(undefined), false);
});

test("listPorts names the connected ports and leaves out disconnected ones", () => {
  const map = new Map([
    ["a", { id: "a", name: "Keystation 49", state: "connected" }],
    ["b", { id: "b", name: "Gone", state: "disconnected" }],
    ["c", { id: "c", name: "", manufacturer: "Roland", state: "connected" }],
  ]);
  assert.deepEqual(listPorts(map), [{ id: "a", name: "Keystation 49" }, { id: "c", name: "Roland" }]);
  assert.deepEqual(listPorts(null), []);
});

test("the harmony goes on the channel after the melody's, skipping the drum channel", () => {
  assert.deepEqual(partChannels(0), { melody: 0, harmony: 1, drums: 9 });
  assert.deepEqual(partChannels(8), { melody: 8, harmony: 10, drums: 9 });
  assert.deepEqual(partChannels(15), { melody: 15, harmony: 0, drums: 9 });
  assert.throws(() => partChannels(DRUM_CHANNEL), /other than 10/);
  assert.throws(() => partChannels(16));
});

test("readMessage reads note on, note off (also as velocity 0) and the sustain pedal on any channel", () => {
  assert.deepEqual(readMessage([0x93, 60, 100]), { type: "on", m: 60, v: 100 });
  assert.deepEqual(readMessage([0x90, 60, 0]), { type: "off", m: 60 });
  assert.deepEqual(readMessage([0x85, 61, 64]), { type: "off", m: 61 });
  assert.deepEqual(readMessage([0xb0, 64, 127]), { type: "pedal", down: true });
  assert.deepEqual(readMessage([0xb2, 64, 0]), { type: "pedal", down: false });
  assert.equal(readMessage([0xb0, 7, 100]), null);
  assert.equal(readMessage([0xf8]), null);
  assert.equal(readMessage([0xe0, 0, 64]), null);
});

test("the recorder turns key presses into notes from the take's zero", () => {
  const r = createKeyRecorder();
  r.message([0x90, 60, 100], 0.5);
  r.message([0x90, 64, 90], 1);
  r.message([0x80, 60, 0], 1.25);
  r.message([0x90, 64, 0], 1.5);
  r.message([0x90, 67, 80], 2);
  assert.deepEqual(r.finish(2.4), [{ m: 60, t: 0.5, d: 0.75 }, { m: 64, t: 1, d: 0.5 }, { m: 67, t: 2, d: 0.4 }]);
});

test("a note held over the count-in starts at zero; one that ended in the count-in is dropped", () => {
  const r = createKeyRecorder();
  r.message([0x90, 50, 100], -1);
  r.message([0x80, 50, 0], -0.5);
  r.message([0x90, 52, 100], -0.25);
  r.message([0x80, 52, 0], 0.5);
  assert.deepEqual(r.finish(1), [{ m: 52, t: 0, d: 0.5 }]);
});

test("the sustain pedal holds released keys until it comes up", () => {
  const r = createKeyRecorder();
  r.message([0xb0, 64, 127], 0);
  r.message([0x90, 60, 100], 0.1);
  r.message([0x80, 60, 0], 0.3);
  r.message([0x90, 62, 100], 0.5);
  r.message([0x80, 62, 0], 0.6);
  r.message([0xb0, 64, 0], 1.1);
  r.message([0x90, 64, 100], 1.2);
  r.message([0x80, 64, 0], 1.4);
  assert.deepEqual(r.finish(2), [{ m: 60, t: 0.1, d: 1 }, { m: 62, t: 0.5, d: 0.6 }, { m: 64, t: 1.2, d: 0.2 }]);
});

test("a key struck again while held by the pedal ends the first note and starts another", () => {
  const r = createKeyRecorder();
  r.message([0xb0, 64, 127], 0);
  r.message([0x90, 60, 100], 0);
  r.message([0x80, 60, 0], 0.2);
  r.message([0x90, 60, 100], 0.5);
  r.message([0xb0, 64, 0], 0.9);
  assert.deepEqual(r.finish(1.5), [{ m: 60, t: 0, d: 0.5 }, { m: 60, t: 0.5, d: 1 }]);
});

test("key bounce shorter than 20 ms is not a note, and notes still down at the end are closed", () => {
  const r = createKeyRecorder();
  r.message([0x90, 60, 100], 1);
  r.message([0x80, 60, 0], 1.01);
  r.message([0x90, 72, 100], 1.5);
  assert.deepEqual(r.finish(2.25), [{ m: 72, t: 1.5, d: 0.75 }]);
});

test("addTake merges the take into the melody in time order", () => {
  const melody = [{ m: 60, t: 0, d: 0.5 }, { m: 62, t: 2, d: 0.5 }];
  assert.deepEqual(addTake(melody, [{ m: 64, t: 1, d: 0.5 }]).map(n => n.m), [60, 64, 62]);
  assert.equal(melody.length, 2);
});

const project = {
  bpm: 120, instrument: "flute", harmony_instrument: "strings",
  notes: [{ m: 60, t: 0, d: 0.5 }, { m: 60, t: 0.5, d: 0.5 }],
  harmony: [{ m: 48, t: 0, d: 1 }],
  drums: [{ k: "kick", t: 0 }, { k: "hat", t: 0.5 }, { k: "cowbell", t: 0.7 }],
};

test("songEvents sends each part on its channel with its General MIDI program and the drums on channel 10", () => {
  const events = songEvents(project, 2);
  const ch = partChannels(2);
  assert.deepEqual(events.slice(0, 2).map(e => e.data), [[0xc0 | ch.melody, PROGRAMS.flute], [0xc0 | ch.harmony, PROGRAMS.strings]]);
  const ons = events.filter(e => (e.data[0] & 0xf0) === 0x90);
  assert.deepEqual(ons.map(e => [e.t, ...e.data]), [
    [0, 0x92, 60, VELOCITY.melody], [0, 0x93, 48, VELOCITY.harmony], [0, 0x99, DRUM_NOTES.kick, VELOCITY.drums],
    [0.5, 0x92, 60, VELOCITY.melody], [0.5, 0x99, DRUM_NOTES.hat, VELOCITY.drums],
  ]);
  const offs = events.filter(e => (e.data[0] & 0xf0) === 0x80);
  assert.equal(offs.length, ons.length);
  assert.ok(offs.some(e => e.t === DRUM_SECONDS && e.data[1] === DRUM_NOTES.kick));
  for (let i = 1; i < events.length; i++) assert.ok(events[i - 1].t <= events[i].t);
});

test("at one time a repeated pitch's end is sent before its next start", () => {
  const events = songEvents(project, 0).filter(e => e.t === 0.5 && (e.data[0] & 0x0f) === 0);
  assert.deepEqual(events.map(e => e.data), [[0x80, 60, 0], [0x90, 60, VELOCITY.melody]]);
});

test("songEvents leaves out empty parts and invalid notes", () => {
  const events = songEvents({ instrument: "piano", notes: [{ m: 60, t: 0, d: 0 }, { m: 61, t: NaN, d: 1 }], harmony: [], drums: [] }, 0);
  assert.deepEqual(events, []);
});

test("silence turns off every sound, note and the pedal on each channel once", () => {
  assert.deepEqual(silence([0, 9, 0]), [
    [0xb0, 120, 0], [0xb0, 123, 0], [0xb0, 64, 0], [0xb9, 120, 0], [0xb9, 123, 0], [0xb9, 64, 0],
  ]);
});

test("the sender sends only what is due within the lookahead, each event once", () => {
  const events = [{ t: 0, data: [1] }, { t: 0.15, data: [2] }, { t: 0.5, data: [3] }, { t: 2, data: [4] }];
  const s = createSender(events, { lookahead: 0.2 }), sent = [];
  const send = (data, t) => sent.push([data[0], t]);
  assert.equal(s.pump(0, send), true);
  assert.deepEqual(sent, [[1, 0], [2, 0.15]]);
  s.pump(0.1, send);
  assert.equal(sent.length, 2);
  s.pump(0.35, send);
  assert.deepEqual(sent.at(-1), [3, 0.5]);
  assert.equal(s.pump(5, send), false);
  assert.equal(s.sent, 4);
});
