"""REC.2: recording the voice counts in one bar on a click at the song's speed, the take's zero is the end of the count-in,
and the click (during the count-in, and while recording when asked) is never in the take. Chromium's fake microphone
(a beeping tone) is the input."""
import json
import os
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_studio import wait_until

# Every oscillator start, with its context's id, frequency and time, so the clicks the studio scheduled can be read back.
# It only observes: the oscillators play as they would.
CLICK_LOG = """(() => {
  window.__oscStarts = [];
  const ids = new WeakMap(); let next = 0;
  const start = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function (when) {
    if (!ids.has(this.context)) ids.set(this.context, ++next);
    window.__oscStarts.push({ ctx: ids.get(this.context), f: this.frequency.value, t: when ?? 0 });
    return start.apply(this, arguments);
  };
})()"""

ACCENT, CLICK = 1600, 1000
SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())


@pytest.fixture
def rec(studio):
    page = studio
    page.add_init_script(CLICK_LOG)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.fill("#bpm", "100")
    page.press("#bpm", "Tab")
    return page


def take_info(page):
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    return json.loads(page.locator("#finish").get_attribute("data-take"))


def clicks(page):
    return [c for c in page.evaluate("window.__oscStarts") if c["f"] in (ACCENT, CLICK)]


def test_one_bar_count_in_then_the_take_starts_at_its_end(rec):
    page = rec
    expect(page.locator("#countin")).to_be_checked()
    expect(page.locator("#recclick")).not_to_be_checked()
    # Every text the status line shows, in order: a beat lasts 0.6 s, shorter than a polling expect may wait between looks.
    page.evaluate("""() => { const s = document.getElementById('status'); window.__statuses = [];
      new MutationObserver(() => { const t = s.textContent; if (window.__statuses.at(-1) !== t) window.__statuses.push(t); })
        .observe(s, { childList: true, characterData: true, subtree: true }); }""")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    shown = page.evaluate("window.__statuses")
    assert shown[shown.index("Count-in: 1 of 4"):] == ["Count-in: 1 of 4", "Count-in: 2 of 4", "Count-in: 3 of 4",
                                                       "Count-in: 4 of 4", "Recording…"]
    page.wait_for_timeout(1500)
    page.click("#finish")
    info = take_info(page)
    # One bar at 100 beats a minute: four beats of 0.6 s.
    assert info["lead"] == pytest.approx(2.4) and info["beat"] == pytest.approx(0.6)
    # The count-in's four clicks are on its beats, the first accented, and the last a beat before the take's zero.
    cs = clicks(page)
    assert [c["f"] for c in cs] == [ACCENT, CLICK, CLICK, CLICK]
    zero = info["zero"]
    assert [round(c["t"] - zero, 4) for c in cs] == [-2.4, -1.8, -1.2, -0.6]
    # The take is exactly the frames from the count-in's end to Stop, so its zero is the end of the count-in; REC.3: moved
    # later by the round trip (here the browser's estimate), the delay before a voice singing along reaches the capture.
    assert info["measured"] is False and 0 <= info["latency"] < 0.5
    assert info["start"] == pytest.approx(zero + info["latency"], abs=1e-6)
    assert abs(info["frames"] - (info["end"] - info["start"]) * info["rate"]) <= 1
    expect(page.locator("#status")).to_contain_text("Recorded")
    seconds = page.evaluate("""async () => { const r = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
      let newest = null; for await (const e of r.values()) { const f = await e.getFile(); if (!newest || f.lastModified >= newest.lastModified) newest = f; }
      const ac = new OfflineAudioContext(1, 1, 44100); const b = await ac.decodeAudioData(await newest.arrayBuffer());
      let peak = 0; for (const x of b.getChannelData(0)) peak = Math.max(peak, Math.abs(x));
      return { seconds: b.duration, peak }; }""")
    # The stored take is that long, and it holds the microphone (the fake device's beeps), not silence.
    assert seconds["seconds"] == pytest.approx(info["frames"] / info["rate"], abs=0.002)
    assert 1.4 < seconds["seconds"] < 2.5
    assert seconds["peak"] > 0.05


def test_the_click_goes_on_while_recording_and_count_in_can_be_off(rec):
    page = rec
    page.check("#recclick")
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…")
    page.wait_for_timeout(2000)
    page.click("#finish")
    info = take_info(page)
    assert info["lead"] == 0
    cs = clicks(page)
    # No count-in: the click starts at the take's zero, a beat apart, the first of each bar accented.
    offsets = [round(c["t"] - info["zero"], 4) for c in cs]
    assert offsets[:4] == [0, 0.6, 1.2, 1.8]
    assert [c["f"] for c in cs][:1] == [ACCENT] and all(c["f"] == CLICK for c in cs[1:4])
    # Every click is in the recording's own context, which records only the microphone: the click is not in the take.
    assert len({c["ctx"] for c in cs}) == 1
    assert info["frames"] > 0


def test_stopping_during_the_count_in_records_nothing(rec):
    page = rec
    page.click("#record")
    # Any beat of the count-in will do (polled every frame: a beat is shorter than a polling expect may wait).
    page.wait_for_function("document.getElementById('status').textContent.startsWith('Count-in: ')")
    page.click("#finish")
    expect(page.locator("#status")).to_have_text("Stopped during the count-in: nothing was recorded")
    assert take_info(page)["frames"] == 0
    expect(page.locator("#record")).to_be_enabled()
    expect(page.locator("#original")).to_be_disabled()


# A silent microphone: getUserMedia gives a stream that carries only zeros, and counts how often it was asked for.
SILENT_MIC = """(() => {
  window.__micRequests = 0;
  navigator.mediaDevices.getUserMedia = async () => {
    window.__micRequests++;
    const ac = new AudioContext(), src = ac.createConstantSource(), dest = ac.createMediaStreamDestination();
    src.offset.value = 0; src.connect(dest); src.start(); await ac.resume();
    return dest.stream;
  };
})()"""


def stored_take_peak(page):
    return page.evaluate("""async () => { const r = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
      let newest = null; for await (const e of r.values()) { const f = await e.getFile(); if (!newest || f.lastModified >= newest.lastModified) newest = f; }
      const ac = new OfflineAudioContext(1, 1, 44100); const b = await ac.decodeAudioData(await newest.arrayBuffer());
      let peak = 0; for (const x of b.getChannelData(0)) peak = Math.max(peak, Math.abs(x));
      return { seconds: b.duration, peak }; }""")


def test_the_click_is_not_in_the_take(rec):
    page = rec
    page.add_init_script(SILENT_MIC)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.fill("#bpm", "100")
    page.press("#bpm", "Tab")
    page.check("#recclick")
    # Two quick presses start one take: the second press finds the first still opening the microphone.
    page.evaluate("() => { document.getElementById('record').onclick(); document.getElementById('record').onclick(); }")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    page.wait_for_timeout(1500)
    page.click("#finish")
    info = take_info(page)
    assert page.evaluate("window.__micRequests") == 1
    # The click played through the count-in and on into the take ...
    offsets = [round(c["t"] - info["zero"], 4) for c in clicks(page)]
    assert offsets[:4] == [-2.4, -1.8, -1.2, -0.6] and 0 in offsets and 0.6 in offsets
    # ... and the take of a silent microphone is silent: none of it was recorded.
    take = stored_take_peak(page)
    assert take["seconds"] == pytest.approx(info["frames"] / info["rate"], abs=0.002) and take["seconds"] > 1
    assert take["peak"] < 1e-4


# REC.3: every sound started, with its context, kind and time: buffer sources (the drum samples and recorded parts) and
# oscillators (the click and the oscillator drums), so what the take's context played under the take can be read back.
SOUND_LOG = """(() => {
  window.__sounds = [];
  const ids = new WeakMap(); let next = 0;
  const id = c => { if (!ids.has(c)) ids.set(c, ++next); return ids.get(c); };
  for (const [cls, kind] of [[AudioBufferSourceNode, 'buffer'], [OscillatorNode, 'osc']]) {
    const start = cls.prototype.start;
    cls.prototype.start = function (when) {
      window.__sounds.push({ ctx: id(this.context), kind, f: kind === 'osc' ? this.frequency.value : null, t: when ?? 0 });
      return start.apply(this, arguments);
    };
  }
})()"""

# Keeps a measured round trip for the microphone and output the page will record with, through latency.js itself.
SET_LATENCY = """async seconds => {
  const { deviceKeyFor, saveLatency } = await import('/latency.js');
  const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } });
  const ac = new AudioContext(), key = await deviceKeyFor(ac, s, navigator.mediaDevices);
  saveLatency(localStorage, key, seconds); s.getTracks().forEach(t => t.stop()); await ac.close(); return key;
}"""

DRUM_OSC = (140, 210, 1200)


def take_sounds(page, info):
    """The drum sounds the take's context started, as song times (seconds from the take's zero)."""
    sounds = page.evaluate("window.__sounds")
    ctx = next(s["ctx"] for s in sounds if s["kind"] == "osc" and s["f"] in (ACCENT, CLICK))
    return sorted(round(s["t"] - info["zero"], 3) for s in sounds
                  if s["ctx"] == ctx and (s["kind"] == "buffer" or s["f"] in DRUM_OSC))


def test_the_song_plays_from_the_takes_zero_and_the_take_is_moved_by_the_measured_round_trip(studio):
    page = studio
    page.add_init_script(SOUND_LOG)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.evaluate(SET_LATENCY, 0.25)
    page.fill("#bpm", "120")
    page.dispatch_event("#bpm", "change")
    page.select_option("#groove", "four")
    page.select_option("#groovebars", "4")
    page.click("#addgroove")
    expect(page.locator("#hitcount")).to_have_text("40 hits")
    drums = page.evaluate("() => [...document.querySelectorAll('#drumroll .hit')].map(e => e.title)")
    want = sorted(round(float(x.split(" ")[2].rstrip("s")), 3) for x in drums)
    expect(page.locator("#recsong")).to_be_checked()
    expect(page.locator("#recnote")).to_contain_text("Use headphones")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=10000)
    page.wait_for_timeout(1500)
    page.click("#finish")
    info = take_info(page)
    # The song played in the take's own context, from the take's zero (the end of the count-in): every drum hit at its time.
    assert info["song"] is True and info["lead"] == 2.0
    assert take_sounds(page, info) == want
    # The take is moved by the measured round trip: its first frame is the one captured 0.25 s after the song's zero.
    assert info["measured"] is True and info["latency"] == 0.25
    assert info["start"] == pytest.approx(info["zero"] + 0.25, abs=1e-6)
    assert abs(info["frames"] - (info["end"] - info["start"]) * info["rate"]) <= 1
    expect(page.locator("#latencyinfo")).to_have_attribute("data-ms", "250")
    expect(page.locator("#latencyinfo")).to_contain_text("250 ms earlier to line up (measured)")
    page.locator("#recnote").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "studio-record-over.png"))


def test_without_the_song_or_anything_heard_the_take_is_not_moved(studio):
    page = studio
    page.add_init_script(SOUND_LOG)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.evaluate(SET_LATENCY, 0.25)
    page.select_option("#groove", "straight")
    page.click("#addgroove")
    page.uncheck("#recsong")
    page.check("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=10000)
    page.wait_for_timeout(500)
    page.click("#finish")
    info = take_info(page)
    # The song did not play (only the count-in's clicks), and the take sung to the count-in is still moved.
    assert info["song"] is False and take_sounds(page, info) == []
    assert info["latency"] == 0.25
    # Nothing heard at all (no count-in, no click, no song): the take is not moved.
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=10000)
    page.wait_for_timeout(800)
    page.click("#finish")
    wait_until(page, "async () => JSON.parse(document.getElementById('finish').dataset.take || '{}').lead === 0", "the second take")
    info = take_info(page)
    assert info["latency"] == 0 and info["start"] == info["zero"]
