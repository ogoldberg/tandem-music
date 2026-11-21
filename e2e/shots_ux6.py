"""UX.6 screenshots: Timing with Before chosen on a desktop window (the phone one comes from test_guided.py).

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_ux6.py
"""
import os
from pathlib import Path

from test_guided import guided_page, open_view
from test_midi import MOCK_MIDI

SHOTS = Path(os.environ["SHOTS"])


def test_desktop_timing_before(browser, server_url):
    desktop = {"viewport": {"width": 1280, "height": 900}, "is_mobile": False, "has_touch": False, "device_scale_factor": 1}
    with guided_page(browser, server_url, init=MOCK_MIDI, **desktop) as page:
        page.click("#gdemo")
        open_view(page, "timing")
        page.fill("#gbpm", "120")
        page.locator("#gbpm").press("Tab")
        page.click('[data-beat="tightly"]')
        page.click("#gbefore")
        page.locator("#gviewplays").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "ux6-desktop-before.png"))
