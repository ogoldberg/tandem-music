"""EXP.4: Web MIDI in a real Chromium, with a mocked MIDIAccess standing in for a keyboard and a synth.

The mock is installed before the page loads: one input ("Test Keys") whose onmidimessage handler the
test calls with real MIDI bytes, and one output ("Test Synth") that keeps every message it is sent.
Like a real output it delivers a timed message at its timestamp, and clear() drops what is still
queued; window.__midiSounding() replays what has been delivered and lists the notes still sounding.
Setting window.__midiNoClear first gives an output without clear(), as some browsers have.
"""
import time

import pytest
from playwright.sync_api import expect

MOCK_MIDI = """(() => {
  window.__midiSent = [];
  window.__midiRequests = 0;
  const input = {id: 'in-1', name: 'Test Keys', manufacturer: 'Tandem', state: 'connected', type: 'input', onmidimessage: null};
  const output = {id: 'out-1', name: 'Test Synth', manufacturer: 'Tandem', state: 'connected', type: 'output',
    send(data, ts) { const at = performance.now(); window.__midiSent.push({data: Array.from(data), ts: ts == null ? null : ts, at, due: ts == null || ts < at ? at : ts}); }};
  if (!window.__midiNoClear) output.clear = () => { const now = performance.now(); for (const e of window.__midiSent) if (e.due > now) e.cleared = true; };
  window.__midiSounding = () => {
    const now = performance.now(), on = new Set();
    const due = window.__midiSent.map((e, i) => ({...e, i})).filter(e => !e.cleared && e.due <= now).sort((a, b) => a.due - b.due || a.i - b.i);
    for (const {data: [s, a, b]} of due) {
      const type = s & 0xf0, c = s & 15;
      if (type === 0x90 && b > 0) on.add(c + ':' + a);
      else if (type === 0x80 || type === 0x90) on.delete(c + ':' + a);
      else if (type === 0xb0 && (a === 120 || a === 123)) for (const k of [...on]) if (k.startsWith(c + ':')) on.delete(k);
    }
    return [...on];
  };
  window.__midiKey = bytes => input.onmidimessage && input.onmidimessage({data: new Uint8Array(bytes), timeStamp: performance.now()});
  const access = {inputs: new Map([[input.id, input]]), outputs: new Map([[output.id, output]]), onstatechange: null, sysexEnabled: false};
  Object.defineProperty(Navigator.prototype, 'requestMIDIAccess', {configurable: true, value: async () => { window.__midiRequests++; return access; }});
})()"""

NO_MIDI = "delete Navigator.prototype.requestMIDIAccess"


def open_studio(page, server_url, script):
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.add_init_script(script)
    page.goto(server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    return problems


@pytest.fixture
def midi_studio(page, server_url):
    problems = open_studio(page, server_url, MOCK_MIDI)
    yield page
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def connect(page):
    page.click("#midiconnect")
    expect(page.locator("#midiports")).to_be_visible()
    expect(page.locator("#midiinfo")).to_have_text("1 input, 1 output")


def melody(page):
    return page.locator("#melodyroll .note").evaluate_all(
        "els => els.map(e => { const m = e.title.match(/MIDI (\\d+) at ([\\d.]+)s/); return [Number(m[1]), Number(m[2])]; })")


def sent(page):
    return page.evaluate("window.__midiSent")


def test_midi_is_hidden_where_the_browser_has_no_web_midi(page, server_url):
    problems = open_studio(page, server_url, NO_MIDI)
    expect(page.locator("#miditrack")).to_be_hidden()
    assert not problems, problems


def test_devices_are_asked_for_only_when_connect_is_pressed(midi_studio):
    page = midi_studio
    expect(page.locator("#miditrack")).to_be_visible()
    expect(page.locator("#midiports")).to_be_hidden()
    assert page.evaluate("window.__midiRequests") == 0
    connect(page)
    assert page.evaluate("window.__midiRequests") == 1
    assert page.locator("#midiinput").input_value() == "in-1"
    assert page.locator("#midioutput").input_value() == ""
    channels = page.locator("#midichannel option").evaluate_all("els => els.map(e => e.textContent)")
    assert channels == [str(c) for c in range(1, 17) if c != 10]


def test_a_take_from_the_keyboard_is_added_to_the_melody_as_one_undoable_edit(midi_studio):
    page = midi_studio
    page.click("#demo")
    before = melody(page)
    assert len(before) == 8
    page.fill("#bpm", "150")
    page.locator("#bpm").dispatch_event("change")
    connect(page)
    page.click("#midirecord")
    expect(page.locator("#status")).to_contain_text("Recording from Test Keys")
    expect(page.locator("#midirecord")).to_contain_text("Stop recording")
    # A key pressed and let go during the count-in (one bar at 150 BPM: 1.6 s) is not part of the take.
    page.evaluate("window.__midiKey([0x90, 50, 100])")
    time.sleep(0.2)
    page.evaluate("window.__midiKey([0x80, 50, 0])")
    time.sleep(1.4 + 0.5)  # zero of the take, then half a second
    page.evaluate("window.__midiKey([0x90, 72, 100])")
    time.sleep(0.4)
    page.evaluate("window.__midiKey([0x90, 72, 0])")  # note off as a note on with velocity 0
    page.evaluate("window.__midiKey([0x91, 76, 80])")  # another channel: still the keyboard
    time.sleep(0.3)
    page.click("#midirecord")
    expect(page.locator("#status")).to_have_text("Recorded 2 notes from the MIDI keyboard into the melody")
    expect(page.locator("#notecount")).to_have_text("10 notes")
    after = melody(page)
    added = [n for n in after if n[0] in (72, 76)]
    assert [m for m, _ in added] == [72, 76]
    assert all(m != 50 for m, _ in after)
    # Played half a second after the count-in, give or take the browser's timer and audio latency.
    assert 0.25 < added[0][1] < 0.9, added
    assert 0.3 < added[1][1] - added[0][1] < 0.6, added
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Record from MIDI keyboard")
    page.click("#undo")
    assert melody(page) == before
    page.click("#redo")
    assert melody(page) == after


def test_stopping_a_take_with_nothing_played_leaves_the_melody_alone(midi_studio):
    page = midi_studio
    page.click("#demo")
    connect(page)
    page.click("#midirecord")
    expect(page.locator("#status")).to_contain_text("Recording from Test Keys")
    page.click("#stop")
    expect(page.locator("#status")).to_have_text("Nothing was played, so the melody is unchanged")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#midirecord")).to_contain_text("Record from keyboard")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Load example")


def test_play_sends_melody_harmony_and_drums_to_the_chosen_output_and_channel(midi_studio):
    page = midi_studio
    page.click("#demo")
    page.click("#genharmony")
    expect(page.locator("#harmonycount")).not_to_have_text("0 notes")
    connect(page)
    page.select_option("#midioutput", "out-1")
    page.select_option("#midichannel", label="3")  # channel 3: the harmony goes on 4, the drums on 10
    page.click("#play")
    expect(page.locator("#status")).to_have_text("Playing to Test Synth")
    page.wait_for_function("window.__midiSent.filter(e => (e.data[0] & 0xf0) === 0x90).length >= 6")
    time.sleep(0.5)
    page.click("#stop")
    messages = sent(page)
    datas = [e["data"] for e in messages]
    programs = [d for d in datas if d[0] & 0xF0 == 0xC0]
    assert [0xC2, 12] in programs  # marimba melody on channel 3
    assert [0xC3, 0] in programs   # piano harmony on channel 4
    ons = [d for d in datas if d[0] & 0xF0 == 0x90]
    assert {d[0] for d in ons} >= {0x92, 0x93, 0x99}
    assert [0x92, 60, 90] in ons
    assert [0x99, 36, 90] in ons
    # Each message is timed ahead on the MIDI clock, in song order, and the song starts after Play.
    timed = [e for e in messages if e["ts"] is not None and e["data"][0] & 0xF0 in (0x80, 0x90)]
    assert all(b["ts"] >= a["ts"] - 1 for a, b in zip(timed, timed[1:]))
    assert all(e["ts"] >= e["at"] - 30 for e in timed)
    # Stop silences every channel the song used, and nothing more is sent after it.
    # HARM.1: that includes the harmony voice's channel, the one after the harmony's.
    tail = datas[-12:]
    for c in (2, 3, 4, 9):
        assert [0xB0 | c, 123, 0] in tail and [0xB0 | c, 120, 0] in tail
    count = len(messages)
    time.sleep(0.4)
    assert len(sent(page)) == count


def test_keys_play_through_to_the_chosen_output(midi_studio):
    page = midi_studio
    connect(page)
    page.select_option("#midioutput", "out-1")
    page.select_option("#midichannel", label="5")
    page.evaluate("window.__midiKey([0x90, 61, 99])")
    page.evaluate("window.__midiKey([0xb0, 64, 127])")
    page.evaluate("window.__midiKey([0x80, 61, 0])")
    assert [e["data"] for e in sent(page)] == [[0xC4, 0], [0x94, 61, 99], [0xB4, 64, 127], [0x84, 61, 0]]


def test_keys_sound_on_the_melody_instrument_without_an_output(midi_studio):
    page = midi_studio
    connect(page)
    page.evaluate("window.__midiKey([0x90, 60, 100])")
    time.sleep(0.2)
    page.evaluate("window.__midiKey([0x80, 60, 0])")
    assert sent(page) == []
    expect(page.locator("#notecount")).to_have_text("0 notes")


@pytest.mark.parametrize("clearable", [True, False], ids=["output-with-clear", "output-without-clear"])
def test_stop_leaves_no_note_sounding_on_the_synth(page, server_url, clearable):
    # Play queues timed messages up to 200 ms ahead; Stop right after the first are queued must still
    # leave the synth silent once everything queued has been delivered, whether or not clear() exists.
    problems = open_studio(page, server_url, ("" if clearable else "window.__midiNoClear = true;") + MOCK_MIDI)
    page.click("#demo")
    connect(page)
    page.select_option("#midioutput", "out-1")
    page.click("#play")
    # Press Stop in the page the moment a note-on is queued but not yet due, so the test does not race it.
    page.evaluate("""new Promise(done => { const look = () => {
      if (window.__midiSent.some(e => (e.data[0] & 0xf0) === 0x90 && e.due > performance.now())) { document.getElementById('stop').click(); done(); }
      else setTimeout(look, 1); }; look(); })""")
    time.sleep(0.5)
    assert page.evaluate("window.__midiSounding()") == []
    # What Stop does to the stopped song must not touch what comes after it: a key played at once keeps sounding,
    # even one on the pitch and channel of a melody note the stopped song still had queued.
    pitch = page.evaluate("""new Promise(done => { document.getElementById('play').click(); const look = () => {
      const queued = window.__midiSent.find(e => e.data[0] === 0x90 && e.data[2] > 0 && e.due > performance.now());
      if (queued) { document.getElementById('stop').click(); window.__midiKey([0x90, queued.data[1], 100]); done(queued.data[1]); }
      else setTimeout(look, 1); }; look(); })""")
    time.sleep(0.5)
    assert page.evaluate("window.__midiSounding()") == [f"0:{pitch}"]
    # Nor a key on the pitch of a melody note that was already sounding with its note-off still queued.
    page.evaluate("window.__midiKey([0x80, %d, 0])" % pitch)
    pitch = page.evaluate("""new Promise(done => { document.getElementById('play').click(); const look = () => {
      const now = performance.now(), sent = window.__midiSent;
      const off = sent.find(e => (e.data[0] === 0x80 || (e.data[0] === 0x90 && e.data[2] === 0)) && e.due > now
        && sent.some(o => o.data[0] === 0x90 && o.data[2] > 0 && o.data[1] === e.data[1] && o.due <= now && o.at < e.at));
      if (off) { document.getElementById('stop').click(); window.__midiKey([0x90, off.data[1], 100]); done(off.data[1]); }
      else setTimeout(look, 1); }; look(); })""")
    time.sleep(0.5)
    assert page.evaluate("window.__midiSounding()") == [f"0:{pitch}"]
    assert not problems, problems


def test_changing_output_or_channel_while_keys_are_held_releases_them_where_they_sound(midi_studio):
    page = midi_studio
    connect(page)
    page.select_option("#midioutput", "out-1")
    page.select_option("#midichannel", label="5")
    page.evaluate("window.__midiKey([0x90, 61, 99])")
    page.evaluate("window.__midiKey([0xb0, 64, 127])")
    page.select_option("#midichannel", label="6")  # the held key and pedal were on channel 5
    assert [0xB4, 123, 0] in [e["data"] for e in sent(page)]
    assert [0xB4, 64, 0] in [e["data"] for e in sent(page)]
    page.evaluate("window.__midiKey([0x90, 62, 99])")
    assert page.evaluate("window.__midiSounding()") == ["5:62"]
    page.select_option("#midioutput", "")  # This device: the note on channel 6 of Test Synth is released
    assert [0xB5, 123, 0] in [e["data"] for e in sent(page)]
    assert page.evaluate("window.__midiSounding()") == []
