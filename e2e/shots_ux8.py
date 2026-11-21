"""UX.8 screenshots: the Share step at phone width with its player card and In your song, empty and with a song, while
playing, and the view a Change link opens.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_ux8.py
"""
import os
from pathlib import Path

from test_guided import guided_page

SHOTS = Path(os.environ["SHOTS"])


def test_phone_share_step(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click('#steps [data-step="share"]')
        page.screenshot(path=str(SHOTS / "ux8-share-empty.png"))
        page.click('#steps [data-step="sing"]')
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")
        page.click("#gtile-chords")
        page.click("#gchords")
        page.wait_for_function("document.querySelectorAll('#gsongparts li[data-view=chords]').length > 0")
        page.click("#gviewdone")
        page.click('#steps [data-step="share"]')
        page.screenshot(path=str(SHOTS / "ux8-share.png"))
        page.click("#gshareplay")
        page.wait_for_function("Number(document.getElementById('timeline').dataset.t || 0) > 0.5", timeout=20_000)
        page.screenshot(path=str(SHOTS / "ux8-share-playing.png"))
        page.click("#gsharestop")
        page.click('#gsongparts li[data-view="chords"] button')
        page.screenshot(path=str(SHOTS / "ux8-change-chords.png"))
        page.click("#gviewdone")
        page.screenshot(path=str(SHOTS / "ux8-back-on-share.png"), full_page=True)
