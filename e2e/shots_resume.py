"""RESUME.1 screenshots on a phone: the Welcome back card when Tandem opens on a song in progress, and the line over
Record once the card is away.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_resume.py
"""
import os
from pathlib import Path

from playwright.sync_api import expect

from test_guided import guided_page
from test_resume import KV_GET, faster, name_song, reopen, with_example
from test_studio import wait_until

SHOTS = Path(os.environ["SHOTS"])


def test_welcome_back(browser, server_url):
    with guided_page(browser, server_url) as page:
        with_example(page)
        name_song(page, "Rain song")
        bpm = faster(page)
        wait_until(page, f"async () => (await ({KV_GET})('draft'))?.bpm === {bpm}", "the change is the stored draft")
        reopen(page)
        expect(page.locator("#gresume")).to_be_visible()
        page.screenshot(path=str(SHOTS / "resume-card.png"))
        page.click("#gresumekeep")
        page.click('#steps [data-step="sing"]')
        expect(page.locator("#ginto")).to_be_visible()
        page.locator("#grecord").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "resume-into-line.png"))
