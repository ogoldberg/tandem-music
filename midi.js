// Web MIDI (EXP.4): play and record from a MIDI keyboard, and play the song to a MIDI output.
// The studio (index.html) owns the MIDIAccess, the audio and the timer; this module turns MIDI
// messages into project notes and the project into timed MIDI messages, so Node tests import it.

import { PROGRAMS, DRUM_NOTES, DRUM_SECONDS } from "./daw.js";

export const DRUM_CHANNEL = 9;
// The same velocities the MIDI file uses (daw.js): the harmony a little under the melody.
export const VELOCITY = Object.freeze({ melody: 90, harmony: 70, voice2: 80, drums: 90 });
// A count-in of one 4/4 bar before recording starts.
export const COUNT_IN_BEATS = 4;
// Shorter notes are key bounce or a slip, not a note.
export const MIN_NOTE_SECONDS = 0.02;

const finite = x => typeof x === "number" && Number.isFinite(x);
const round3 = x => Math.round(x * 1000) / 1000;

// Web MIDI exists in Chromium and Firefox on desktop; Safari and the Mac app's WKWebView have none.
export function midiSupported(nav) {
  return !!nav && typeof nav.requestMIDIAccess === "function";
}

// The ports of a MIDIInputMap or MIDIOutputMap that are connected, as {id, name}.
export function listPorts(map) {
  const out = [];
  if (!map) return out;
  map.forEach(port => {
    if (port.state === "disconnected") return;
    out.push({ id: port.id, name: port.name || port.manufacturer || "MIDI device " + (out.length + 1) });
  });
  return out;
}

// The channels (0-based) the song is sent on: the melody on the chosen one, the harmony on the next
// that is not the General MIDI drum channel, the harmony voice (HARM.1) on the one after that, the
// drums on channel 10.
export function partChannels(channel) {
  if (!Number.isInteger(channel) || channel < 0 || channel > 15 || channel === DRUM_CHANNEL) throw Error("Choose a MIDI channel from 1 to 16 other than 10");
  const after = c => (c + 1) % 16 === DRUM_CHANNEL ? (c + 2) % 16 : (c + 1) % 16;
  const harmony = after(channel);
  return { melody: channel, harmony, voice2: after(harmony), drums: DRUM_CHANNEL };
}

// What one MIDI message means for recording: a note starting or ending, or the sustain pedal.
export function readMessage(data) {
  if (!data || data.length < 2) return null;
  const kind = data[0] & 0xf0, a = data[1], b = data.length > 2 ? data[2] : 0;
  if (kind === 0x90 && b > 0) return { type: "on", m: a, v: b };
  if (kind === 0x80 || kind === 0x90) return { type: "off", m: a };
  if (kind === 0xb0 && a === 64) return { type: "pedal", down: b >= 64 };
  return null;
}

// Collects the notes of a take. Times are seconds from the take's zero (the end of the count-in):
// a note held across zero starts at zero, a note that ended before it is dropped. With the sustain
// pedal down a released key holds until the pedal comes up, as it sounds.
export function createKeyRecorder() {
  const open = new Map(), held = new Map(), notes = [];
  let pedal = false;
  function close(m, t) {
    const start = open.get(m);
    open.delete(m);
    held.delete(m);
    if (start == null) return;
    const s = Math.max(0, start), d = t - s;
    if (t > 0 && d >= MIN_NOTE_SECONDS) notes.push({ m, t: round3(s), d: round3(d) });
  }
  return {
    message(data, t) {
      const e = readMessage(data);
      if (!e || !finite(t)) return e;
      if (e.type === "on") {
        if (open.has(e.m)) close(e.m, t);
        open.set(e.m, t);
      } else if (e.type === "off") {
        if (pedal && open.has(e.m)) held.set(e.m, true);
        else close(e.m, t);
      } else {
        pedal = e.down;
        if (!pedal) for (const m of [...held.keys()]) close(m, t);
      }
      return e;
    },
    // Closes every note still sounding at t and returns the take, in time order.
    finish(t) {
      for (const m of [...open.keys()]) close(m, t);
      return notes.slice().sort((x, y) => x.t - y.t || x.m - y.m);
    },
  };
}

// The recorded take added to the melody, in time order.
export function addTake(melody, take) {
  return [...melody, ...take].sort((x, y) => x.t - y.t || x.m - y.m);
}

// The song as timed MIDI messages ({t seconds, data}), in the order they are sent: each part's
// program first, and at one time a note's end before the next start, so a repeated pitch sounds again.
export function songEvents(project, channel) {
  const ch = partChannels(channel), events = [];
  const add = (t, order, data) => events.push({ t, order, data });
  for (const [part, key, instrument] of [["melody", "notes", "instrument"], ["harmony", "harmony", "harmony_instrument"], ["voice2", "voice2", "voice2_instrument"]]) {
    const notes = (project[key] || []).filter(n => n && finite(n.m) && finite(n.t) && finite(n.d) && n.d > 0);
    if (!notes.length) continue;
    const c = ch[part], program = PROGRAMS[project[instrument]];
    if (program != null) add(0, 0, [0xc0 | c, program]);
    for (const n of notes) {
      const m = Math.min(127, Math.max(0, Math.round(n.m))), t = Math.max(0, n.t);
      add(t, 2, [0x90 | c, m, VELOCITY[part]]);
      add(t + n.d, 1, [0x80 | c, m, 0]);
    }
  }
  for (const h of project.drums || []) {
    if (!h || !finite(h.t) || DRUM_NOTES[h.k] == null) continue;
    const t = Math.max(0, h.t), note = DRUM_NOTES[h.k];
    add(t, 2, [0x90 | DRUM_CHANNEL, note, VELOCITY.drums]);
    add(t + DRUM_SECONDS, 1, [0x80 | DRUM_CHANNEL, note, 0]);
  }
  return events
    .map((e, i) => ({ ...e, i }))
    .sort((a, b) => a.t - b.t || a.order - b.order || a.i - b.i)
    .map(({ t, data }) => ({ t, data }));
}

// Silences a device: All Sound Off, All Notes Off and the sustain pedal up on each channel.
export function silence(channels) {
  return [...new Set(channels)].flatMap(c => [[0xb0 | c, 120, 0], [0xb0 | c, 123, 0], [0xb0 | c, 64, 0]]);
}

// Sends timed events a little ahead of time. now() is the song's clock in seconds (the song starts at
// zero); each call of pump() sends, through send(data, t), what falls before now() + lookahead.
// The studio calls pump() from a timer, so at Stop the browser's MIDI output holds at most lookahead seconds
// of messages: the studio drops them with clear(), or, where there is none, ends each queued note at its own time.
export function createSender(events, { lookahead = 0.2 } = {}) {
  let next = 0;
  return {
    pump(now, send) {
      while (next < events.length && events[next].t <= now + lookahead) {
        send(events[next].data, events[next].t);
        next++;
      }
      return next < events.length;
    },
    get sent() { return next; },
  };
}
