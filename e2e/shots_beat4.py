"""BEAT.4 screenshots: the Beat view's Record a beat at phone width, the Sing step armed for a beat layer, and the Beat
view after the beat is read into the drums, with its layer under Takes.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_beat4.py
"""
import os
from pathlib import Path

from test_guided import guided_page, open_view, record_take, use_server_transcriber

SHOTS = Path(os.environ["SHOTS"])


def test_phone_record_a_beat_over_the_song(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        page.click('[data-mode="vocal"]')
        record_take(page)
        open_view(page, "beat")
        page.screenshot(path=str(SHOTS / "beat4-beat-view.png"))
        page.click("#gbeat")
        page.click("#grecopts > summary")
        page.screenshot(path=str(SHOTS / "beat4-sing-armed.png"))
        page.click("#grecord")
        page.wait_for_function("document.getElementById('greclabel').textContent === 'Tap to stop'")
        page.wait_for_timeout(4000)
        page.click("#grecord")
        page.wait_for_function("/^Recorded your beat as/.test(document.getElementById('gstatus').textContent)", timeout=90_000)
        page.screenshot(path=str(SHOTS / "beat4-beat-read.png"))
        open_view(page, "takes")
        page.locator("#layerlanes").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "beat4-takes-layer.png"))
