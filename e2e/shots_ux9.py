"""UX.9 screenshots: the guided view at 1440 px with the hub and a change view side by side, the same at tablet width (one
view at a time), and the desktop studio's rail after Show every control from the Chords view.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_ux9.py
"""
import os
from pathlib import Path

from test_guided import guided_page, open_view

SHOTS = Path(os.environ["SHOTS"])
DESKTOP = {"viewport": {"width": 1440, "height": 900}, "is_mobile": False, "has_touch": False}
TABLET = {"viewport": {"width": 820, "height": 1180}, "is_mobile": False, "has_touch": True}


def test_desktop_hub_and_view_side_by_side(browser, server_url):
    with guided_page(browser, server_url, **DESKTOP) as page:
        page.click("#gdemo")
        page.screenshot(path=str(SHOTS / "ux9-desktop-hub.png"))
        open_view(page, "chords")
        page.screenshot(path=str(SHOTS / "ux9-desktop-chords.png"))
        open_view(page, "notes")
        page.screenshot(path=str(SHOTS / "ux9-desktop-notes.png"))
        open_view(page, "chords")
        page.click("#gsettings")
        page.click("#gshowall")
        page.screenshot(path=str(SHOTS / "ux9-desktop-studio-from-chords.png"))


def test_tablet_one_view_at_a_time(browser, server_url):
    with guided_page(browser, server_url, **TABLET) as page:
        page.click("#gdemo")
        open_view(page, "chords")
        page.screenshot(path=str(SHOTS / "ux9-tablet-chords.png"))
        page.click("#gsettings")
        page.click("#gshowall")
        page.screenshot(path=str(SHOTS / "ux9-tablet-studio-from-chords.png"))
