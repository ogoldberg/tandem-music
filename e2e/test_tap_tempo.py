"""TEMPO.1: Tap the speed. In the guided Sing step four or more taps set the song's tempo as one edit once the taps
stop, and the count-in then runs at it; on the capture page they set the beat's speed, and the count-in and beat follow."""
import json

import pytest
from playwright.sync_api import expect

from test_capture import open_capture, phone  # noqa: F401  (the phone fixture)
from test_guided import guided_page
from test_recording import SHOTS, SOUND_LOG
from test_studio import wait_until

# Clicks the button n times, gap milliseconds apart on the page's clock (each aimed at its own time, so a late one
# does not push the rest later).
TAPS = """async ([sel, gap, n]) => { const b = document.querySelector(sel), t0 = performance.now();
  for (let i = 0; i < n; i++) { while (performance.now() < t0 + i * gap) await new Promise(r => setTimeout(r, 1)); b.click(); } }"""


def tap(page, sel, bpm, n):
    page.evaluate(TAPS, [sel, 60000 / bpm, n])


def test_taps_in_the_sing_step_set_the_tempo_as_one_edit_and_the_count_in_follows(browser, server_url):
    with guided_page(browser, server_url) as page:
        expect(page.locator("#gtapspeed")).to_have_text("100 beats a minute")
        # Three taps are not enough: nothing changes.
        tap(page, "#gtap", 120, 3)
        expect(page.locator("#gtapinfo")).to_have_text("Tap 1 more time")
        expect(page.locator("#gtapinfo")).to_have_text("Tap at least 4 times to set the speed", timeout=5000)
        assert page.input_value("#bpm") == "100"

        tap(page, "#gtap", 120, 6)
        expect(page.locator("#gtapinfo")).to_contain_text("stop tapping to keep it")
        assert page.input_value("#bpm") == "100", "the tempo is set once the taps stop, not while tapping"
        expect(page.locator("#gtapinfo")).to_contain_text("from your taps", timeout=5000)
        bpm = int(page.input_value("#bpm"))
        assert abs(bpm - 120) <= 3
        expect(page.locator("#gtapspeed")).to_have_text(f"{bpm} beats a minute")
        expect(page.locator("#gtapinfo")).to_have_text(f"Speed set to {bpm} beats a minute from your taps")
        page.locator(".gtapcard").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "tap-sing.png"))

        # One edit: one Undo puts 100 back, Redo the tapped speed.
        page.click("#gundo")
        expect(page.locator("#gtapspeed")).to_have_text("100 beats a minute")
        assert page.input_value("#bpm") == "100"
        page.click("#gredo")
        expect(page.locator("#gtapspeed")).to_have_text(f"{bpm} beats a minute")

        # The count-in (on by default) is one bar at the tapped speed.
        page.click("#grecord")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop", timeout=10000)
        page.wait_for_timeout(800)
        page.click("#grecord")
        wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
        info = json.loads(page.locator("#finish").get_attribute("data-take"))
        assert info["beat"] == pytest.approx(60 / bpm) and info["lead"] == pytest.approx(4 * 60 / bpm)


def test_taps_then_record_at_once_record_at_the_tapped_speed(browser, server_url):
    """Record ends a run of taps: the take does not wait for the pause."""
    with guided_page(browser, server_url) as page:
        tap(page, "#gtap", 90, 5)
        page.click("#grecord")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop", timeout=10000)
        bpm = int(page.input_value("#bpm"))
        assert abs(bpm - 90) <= 3
        page.wait_for_timeout(600)
        page.click("#grecord")
        wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
        info = json.loads(page.locator("#finish").get_attribute("data-take"))
        assert info["beat"] == pytest.approx(60 / bpm)


def test_taps_on_the_capture_page_set_the_beat_speed_and_the_count_in(phone):  # noqa: F811
    page = phone
    page.add_init_script(SOUND_LOG)
    open_capture(page)
    page.click("#takeopts summary")
    page.select_option("#beat", "four")
    page.check("#countin")
    tap(page, "#tap", 75, 6)
    expect(page.locator("#tapinfo")).to_contain_text("from your taps", timeout=5000)
    bpm = int(page.input_value("#bpm"))
    assert abs(bpm - 75) <= 3
    expect(page.locator("#tapinfo")).to_have_text(f"Speed set to {bpm} beats a minute from your taps.")
    page.screenshot(path=str(SHOTS / "tap-capture.png"))
    # Kept with the take settings, so a reload keeps it.
    page.reload()
    expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
    assert page.input_value("#bpm") == str(bpm)

    page.click("#record")
    expect(page.locator("#status")).to_have_text(
        f"Recording over Four on the floor at {bpm} bpm… tap Stop when the idea is down.", timeout=15000)
    info = json.loads(page.locator("#record").get_attribute("data-take"))
    page.wait_for_timeout(1000)
    page.click("#record")
    expect(page.locator("#status")).to_contain_text(f"at {bpm} bpm.")
    clicks = [s for s in page.evaluate("window.__sounds") if s["kind"] == "osc" and s["f"] in (1600, 1000)]
    beat = 60 / bpm
    assert [round(c["t"] - info["zero"], 4) for c in clicks] == [round(-k * beat, 4) for k in (4, 3, 2, 1)]
