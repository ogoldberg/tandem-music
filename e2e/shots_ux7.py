"""UX.7 screenshots: each change view at phone width with its More fold open, the three new views, Recording options and the
Ask Tandem connection in Settings.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_ux7.py
"""
import os
from pathlib import Path

from test_guided import guided_page, open_view

SHOTS = Path(os.environ["SHOTS"])
FOLDS = {"voice": "#gmore-voice", "notes": "#gmoretools", "timing": "#gmore-timing", "chords": "#gmore-chords",
         "voice2": "#gmore-voice2", "beat": "#gmore-beat", "sound": "#gmore-sound"}


def test_phone_views_with_more_open(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")
        for view in ["voice", "notes", "timing", "chords", "voice2", "beat", "sound", "sections", "takes", "practise", "ask"]:
            open_view(page, view)
            if view in FOLDS:
                page.click(FOLDS[view] + " > summary")
            page.screenshot(path=str(SHOTS / f"ux7-{view}.png"), full_page=True)
        page.click("#gviewback")
        page.click('#steps [data-step="sing"]')
        page.click("#grecopts > summary")
        page.screenshot(path=str(SHOTS / "ux7-sing-options.png"), full_page=True)
        page.click("#gsettings")
        page.locator("#gaiconn").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "ux7-settings-ai.png"))
