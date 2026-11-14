"""REC.2: recording the voice counts in one bar on a click at the song's speed, the take's zero is the end of the count-in,
and the click (during the count-in, and while recording when asked) is never in the take. Chromium's fake microphone
(a beeping tone) is the input."""
import json

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
    # The take is exactly the frames from the count-in's end to Stop, so its zero is the end of the count-in.
    assert abs(info["frames"] - (info["end"] - zero) * info["rate"]) <= 1
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
