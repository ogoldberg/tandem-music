"""SING.1: the live pitch guide. Chromium's fake microphone plays a known tone from a WAV file (A4 sung 25 cents sharp,
446.4 Hz): while recording, the studio draws the pitch over the melody roll and reads how far it is off its note, the
guided Sing step and the capture page show it too, and the recording is the same with the guide as without it."""
import json
import math
import os
import re
import struct
import tempfile
import wave
from pathlib import Path

import pytest
from playwright.sync_api import expect

from conftest import ALL_CONTROLS
from test_studio import wait_until

# Screenshots for the PR go where TANDEM_E2E_SHOTS points (the temporary directory by default).
SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())
TONE_HZ = 440 * 2 ** (25 / 1200)
RATE = 48000


def write_tone(path, hz=TONE_HZ, seconds=4.0):
    # A voice-like tone: a fundamental and three weaker harmonics, continuous, so the file loops without a gap.
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        frames = bytearray()
        for i in range(int(seconds * RATE)):
            p = 2 * math.pi * hz * i / RATE
            v = 0.4 * math.sin(p) + 0.2 * math.sin(2 * p) + 0.1 * math.sin(3 * p) + 0.05 * math.sin(4 * p)
            frames += struct.pack("<h", int(v * 32767))
        w.writeframes(bytes(frames))


@pytest.fixture(scope="module")
def tone_browser(playwright, tmp_path_factory):
    """A Chromium of its own whose fake microphone plays the tone file (the session's browser plays Chromium's beeps)."""
    wav = tmp_path_factory.mktemp("tone") / "tone.wav"
    write_tone(wav)
    browser = playwright.chromium.launch(args=[
        "--enable-unsafe-swiftshader", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        f"--use-file-for-fake-audio-capture={wav}"])
    yield browser
    browser.close()


def open_page(browser, url, *, all_controls=True):
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    if all_controls:
        context.add_init_script(ALL_CONTROLS)
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.goto(url)
    return page, problems


@pytest.fixture
def tone_studio(tone_browser, server_url):
    page, problems = open_page(tone_browser, server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    yield page
    page.context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def pitch_data(page, selector="#pitchnow"):
    return page.locator(selector).evaluate("e => ({...e.dataset, text: e.textContent})")


def wait_for_readings(page, n, selector="#pitchnow"):
    page.wait_for_function(f"(document.querySelector('{selector}')?.dataset.count | 0) >= {n} && !!document.querySelector('{selector}').dataset.hz",
                           timeout=10000)


def record(page, seconds, *, guide=True):
    page.set_checked("#pitchguide", guide)
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    if guide:
        wait_for_readings(page, 10)
        expect(page.locator("#pitchnow")).to_be_visible()
    page.wait_for_timeout(int(seconds * 1000))
    data = pitch_data(page) if guide else None
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    expect(page.locator("#status")).to_contain_text("Recorded")
    return json.loads(page.locator("#finish").get_attribute("data-take")), data


def test_the_studio_draws_the_sung_pitch_over_the_melody_roll_and_reads_it_sharp(tone_studio):
    page = tone_studio
    page.uncheck("#countin")
    expect(page.locator("#pitchguide")).to_be_checked()
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    wait_for_readings(page, 10)
    # The update rate, by the wall clock: readings counted over one second.
    before = int(pitch_data(page)["count"])
    page.wait_for_timeout(1000)
    data = pitch_data(page)
    per_second = int(data["count"]) - before
    assert per_second >= 20, f"{per_second} readings in a second"
    # ... and by the readings' own times.
    assert (int(data["count"]) - 1) / (float(data["to"]) - float(data["from"])) >= 20
    # A4 sung 25 cents sharp: measured against A4 (no melody, no key: the nearest note).
    assert abs(1200 * math.log2(float(data["hz"]) / TONE_HZ)) <= 10
    assert data["target"] == "69" and abs(int(data["cents"]) - 25) <= 5
    assert re.fullmatch(r"A4, 2\d cents sharp", data["text"]), data["text"]
    # The line is over the melody roll, on the row of MIDI 69.25 (an empty roll: rows from MIDI 48, 2.2% apart).
    line = page.evaluate("""() => { const roll = document.getElementById('melodyroll'), path = roll.querySelector('svg.pitchline path');
      const nums = (path.getAttribute('d').match(/-?[0-9.]+/g) || []).map(Number); return { ys: nums.filter((_, i) => i % 2), xs: nums.filter((_, i) => i % 2 === 0), h: roll.clientHeight }; }""")
    want = 85 - (69.25 - 48) * 2.2 + 6 / line["h"] * 100
    assert len(line["ys"]) >= 20 and all(abs(y - want) < 0.6 for y in line["ys"])
    assert line["xs"] == sorted(line["xs"]) and line["xs"][0] >= 0
    page.screenshot(path=str(SHOTS / "studio-pitch.png"))
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    # When the take ends the guide goes.
    expect(page.locator("#melodyroll svg.pitchline")).to_have_count(0)
    expect(page.locator("#pitchnow")).to_have_count(0)


def open_project(page, tmp_path, notes):
    project = tmp_path / "song.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano",
                                   "melody_locked": True, "notes": notes, "drums": []}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")


def test_in_the_studio_the_voice_is_measured_against_the_melody_note_sounding(tone_studio, tmp_path):
    page = tone_studio
    # G4 for the first 30 s: the sung A4 (+25 cents) is measured against it, 225 cents sharp, not against A4.
    open_project(page, tmp_path, [{"m": 67, "t": 0, "d": 30}])
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    wait_for_readings(page, 10)
    data = pitch_data(page)
    assert data["target"] == "67" and abs(int(data["cents"]) - 225) <= 5, data
    assert re.fullmatch(r"G4, 2\d\d cents sharp", data["text"]), data["text"]
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")


def test_a_take_past_the_songs_end_rescales_the_roll_and_rebuilds_the_pitch_line(tone_studio, tmp_path):
    """FIX.1 (review of #93): the roll shows at least 8 s; once the take runs past its end (less half a second) the
    roll's scale grows, and the pitch line drawn so far is rebuilt on the new scale (drawGuide in index.html)."""
    page = tone_studio
    open_project(page, tmp_path, [{"m": 69, "t": 0, "d": 1}])
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    wait_for_readings(page, 10)
    line = """() => { const n = document.getElementById('pitchnow'), path = document.querySelector('#melodyroll svg.pitchline path');
      const nums = (path.getAttribute('d').match(/-?[0-9.]+/g) || []).map(Number);
      return { from: +n.dataset.from, to: +n.dataset.to, count: +n.dataset.count, xs: nums.filter((_, i) => i % 2 === 0),
               moves: (path.getAttribute('d').match(/M/g) || []).length }; }"""
    before = page.evaluate(line)
    page.wait_for_function("+document.getElementById('pitchnow').dataset.to > 9", timeout=20000)
    after = page.evaluate(line)
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    # Before the end, the roll is 8 s wide: x is the reading's time over 8 s.
    assert abs(before["xs"][-1] - before["to"] / 8 * 97) < 0.3, before
    # After it, the scale is wider, and every point is on it: the line is one stroke, its points in time order and
    # evenly spread from the first reading to the last (a line kept on the old scale jumps back where it changed).
    end = after["to"] / after["xs"][-1] * 97
    assert end > 9.5, end
    xs = after["xs"]
    # (Readings before the take's zero, the round trip it was moved by, are not drawn.)
    assert after["moves"] == 1 and 0 <= after["count"] - len(xs) <= 10, after
    assert xs == sorted(xs)
    assert xs[0] < 0.1 / end * 97 + 0.2, (xs[0], end)
    mid = len(xs) // 2
    assert abs(xs[mid] - (xs[0] + xs[-1]) / 2) < 0.5, (xs[0], xs[mid], xs[-1])


def test_in_the_studio_between_melody_notes_the_voice_is_measured_against_the_key(tone_studio, tmp_path):
    page = tone_studio
    # The melody comes in only at 60 s; until then the chosen key, E♭ major, has B♭ nearest: 75 cents flat.
    open_project(page, tmp_path, [{"m": 63, "t": 60, "d": 1}])
    page.select_option("#harmonykey", "3:major")
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    wait_for_readings(page, 10)
    data = pitch_data(page)
    assert data["target"] == "70" and abs(int(data["cents"]) + 75) <= 5, data
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")


BROKEN_GUIDE = """(() => {
  const Node = window.AudioWorkletNode;
  window.AudioWorkletNode = function (ac, name, opts) {
    if (name === 'tandem-pitch') throw new Error('no pitch worklet here');
    return new Node(ac, name, opts);
  };
})()"""


def test_when_the_guide_cannot_start_the_take_records_and_says_so(tone_browser, server_url):
    page, problems = open_page(tone_browser, server_url + "/")
    page.add_init_script(BROKEN_GUIDE)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording… (without the pitch guide: no pitch worklet here)", timeout=8000)
    expect(page.locator("#pitchnow")).to_have_count(0)
    page.wait_for_timeout(800)
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    expect(page.locator("#status")).to_contain_text("Recorded")
    page.context.close()
    assert not problems, problems


# Keeps every batch the capture worklet posts (its context time and frames), so a test can check the take against what
# the microphone actually gave: Chromium's media stream source can itself give a few milliseconds of silence while it
# starts (seen about 70 ms after the take's zero with the count-in off), which is the input, not a frame lost by us.
CAPTURE_SPY = """(() => {
  const Node = window.AudioWorkletNode; window.__batches = [];
  window.AudioWorkletNode = function (ac, name, opts) {
    const node = new Node(ac, name, opts);
    if (name === 'tandem-capture') node.port.addEventListener('message', e => {
      if (e.data && e.data.channels) window.__batches.push({ t: e.data.t, rate: ac.sampleRate, channels: e.data.channels.map(c => Array.from(c)) });
    });
    return node;
  };
})()"""


def captured_take(page, info):
    """The newest stored take beside the capture's batches: whether the batches run without a gap from before the take's
    zero to Stop, how many 16-bit samples differ from those frames, and the take's length, level and pitch."""
    return page.evaluate("""async info => {
      const r = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
      let newest = null; for await (const e of r.values()) { const f = await e.getFile(); if (!newest || f.lastModified >= newest.lastModified) newest = f; }
      const v = new DataView(await newest.arrayBuffer()), rate = v.getUint32(24, true), n = v.getUint32(40, true) / 2;
      const x = new Float32Array(n); for (let i = 0; i < n; i++) x[i] = v.getInt16(44 + 2 * i, true) / 32767;
      const batches = window.__batches.splice(0), first = Math.ceil(Math.round(info.start * rate * 1e6) / 1e6);
      let gaps = 0, end = null;
      // Only a break that falls inside the take counts: frames before its zero are dropped by the studio anyway.
      for (const b of batches) { const at = Math.round(b.t * rate); if (end !== null && at !== end && at > first && end < first + n) gaps++; end = at + b.channels[0].length; }
      // The take's frames per channel, made mono as the studio does (recordings.js monoSamples: a channel 60 dB below the
      // loudest is left out), then written as 16-bit.
      const chans = Array.from({ length: Math.max(1, ...batches.map(b => b.channels.length)) }, () => new Float32Array(n));
      for (const b of batches) { const at = Math.round(b.t * rate) - first;
        chans.forEach((ch, c) => { const src = b.channels[Math.min(c, b.channels.length - 1)];
          for (let i = 0; i < src.length; i++) if (at + i >= 0 && at + i < n) ch[at + i] = src[i]; }); }
      const level = ch => Math.sqrt(ch.reduce((a, v) => a + v * v, 0) / Math.max(1, ch.length)), loudest = Math.max(...chans.map(level));
      const live = loudest ? chans.filter(ch => level(ch) > loudest * 0.001) : chans, want = new Float32Array(n);
      for (let i = 0; i < n; i++) { let s = 0; for (const ch of live) s += ch[i] / live.length; want[i] = Math.round(Math.max(-1, Math.min(1, s)) * 32767) / 32767; }
      let differ = 0, sum = 0, quiet = 0, blocks = 0;
      for (let i = 0; i < n; i++) { if (Math.abs(x[i] - want[i]) > 1.5 / 32767) differ++; sum += x[i] * x[i]; }
      const rms = Math.sqrt(sum / n);
      for (let i = 0; i + 256 <= n; i += 256) { let s = 0; for (let j = i; j < i + 256; j++) s += x[j] * x[j]; blocks++; if (Math.sqrt(s / 256) < 0.3 * rms) quiet++; }
      const { createPitchTracker } = await import('/pitch.js');
      const tr = createPitchTracker(rate), hz = [];
      for (let i = 0; i < n; i += 128) for (const p of tr.push(x.subarray(i, i + 128), 0)) if (p.hz) hz.push(p.hz);
      hz.sort((a, c) => a - c);
      return { seconds: n / rate, rate, rms, hz: hz[hz.length >> 1], differ, gaps, batches: batches.length,
               covers: !!batches.length && Math.round(batches[0].t * rate) <= first && end >= first + n, quiet, blocks };
    }""", info)


def test_the_take_is_the_same_with_the_guide_as_without(tone_studio):
    page = tone_studio
    page.add_init_script(CAPTURE_SPY)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.uncheck("#countin")
    without, _ = record(page, 1.5, guide=False)
    plain = captured_take(page, without)
    with_guide, data = record(page, 1.5, guide=True)
    guided = captured_take(page, with_guide)
    for info, take in ((without, plain), (with_guide, guided)):
        assert take["seconds"] == pytest.approx(info["frames"] / info["rate"], abs=0.002) and take["rate"] == info["rate"]
        # Every frame from the take's zero to Stop, with no gap: the worklet's batches run on without a break, cover the
        # take, and the stored take is exactly their frames.
        assert take["gaps"] == 0 and take["covers"] and take["differ"] == 0, take
        # The tone is in the take (the input's own start-up silence is at most a block or two).
        assert take["quiet"] <= 0.02 * take["blocks"], take
        assert abs(1200 * math.log2(take["hz"] / TONE_HZ)) <= 10
    assert guided["rms"] == pytest.approx(plain["rms"], rel=0.02)
    assert int(data["count"]) > 20


def test_the_guided_sing_step_shows_the_pitch(tone_browser, server_url):
    page, problems = open_page(tone_browser, server_url + "/", all_controls=False)
    expect(page.locator("#guide")).to_be_visible()
    page.set_viewport_size({"width": 400, "height": 860})
    page.click("#grecord")
    expect(page.locator("#gpitchguide")).to_be_visible(timeout=8000)
    page.wait_for_function("/^A4, \\d+ cents sharp$/.test(document.getElementById('gpitchnow').textContent)", timeout=10000)
    # The strip is drawn: the canvas has the line's colour in it.
    page.wait_for_timeout(500)
    drawn = page.evaluate("""() => { const c = document.getElementById('gpitchstrip'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i + 1] > 180 && d[i] < 160 && d[i + 3] > 200) n++; return n; }""")
    assert drawn > 50
    page.screenshot(path=str(SHOTS / "guided-pitch.png"))
    page.click("#grecord")
    expect(page.locator("#gpitchguide")).to_be_hidden(timeout=8000)
    page.context.close()
    assert not problems, problems


def test_the_capture_page_reads_the_pitch_against_the_chosen_key(tone_browser, server_url):
    page, problems = open_page(tone_browser, server_url + "/capture", all_controls=False)
    page.set_viewport_size({"width": 400, "height": 860})
    expect(page.locator("#record")).to_be_enabled()
    expect(page.locator("#showpitch")).to_be_checked()
    # E♭ major has B♭ and A♭ but no A: 69.25 is nearest B♭ (70), 75 cents flat of it.
    page.select_option("#pitchkey", "3:major")
    page.click("#record")
    wait_for_readings(page, 20)
    data = pitch_data(page)
    assert data["target"] == "70" and abs(int(data["cents"]) + 75) <= 5, data
    assert re.fullmatch(r"A♯4, 7\d cents flat", data["text"]), data["text"]
    # Any note: against A4.
    page.select_option("#pitchkey", "any")
    page.wait_for_function("document.getElementById('pitchnow').dataset.target === '69'")
    assert (int(pitch_data(page)["count"]) - 1) / (float(pitch_data(page)["to"]) - float(pitch_data(page)["from"])) >= 20
    page.screenshot(path=str(SHOTS / "capture-pitch.png"))
    page.click("#record")
    expect(page.locator("#status")).to_contain_text("Kept a", timeout=10000)
    expect(page.locator("#pitchguide")).to_be_hidden()
    # The choice is kept for next time.
    page.reload()
    expect(page.locator("#pitchkey")).to_have_value("any")
    page.context.close()
    assert not problems, problems


SILENT_MIC = """(() => {
  navigator.mediaDevices.getUserMedia = async () => {
    const ac = new AudioContext(), src = ac.createConstantSource(), dest = ac.createMediaStreamDestination();
    src.offset.value = 0; src.connect(dest); src.start(); await ac.resume();
    return dest.stream;
  };
})()"""


def test_silence_draws_nothing(studio):
    page = studio
    page.add_init_script(SILENT_MIC)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    page.wait_for_function("(document.getElementById('pitchnow')?.dataset.count | 0) >= 30")
    data = pitch_data(page)
    assert data["text"] == "Sing to see your pitch" and "hz" not in data
    assert page.locator("#melodyroll svg.pitchline path").get_attribute("d") == ""
    page.click("#finish")

