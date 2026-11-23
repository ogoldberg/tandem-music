"""SHEET.1 screenshots: Twinkle with generated chords, its words and two sections, as a song sheet on screen and printed
(a PDF), and the guided Share step's Song sheet card on a phone.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_sheet.py
"""
import json
import os
from pathlib import Path

from playwright.sync_api import expect

from shots_harm4 import notes
from test_guided import guided_page

SHOTS = Path(os.environ["SHOTS"])
WORDS = """Twin-kle twin-kle lit-tle star,
how I won-der what you are.
Up a-bove the world so high,
like a dia-mond in the sky.

Twin-kle twin-kle lit-tle star,
how I won-der what you are."""


def test_twinkle_song_sheet(studio, tmp_path):
    page = studio
    project = tmp_path / "twinkle.json"
    song = notes()
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano",
                                   "melody_locked": True, "notes": [{**n, "m": n["m"] + 12} for n in song], "drums": [],
                                   "lyrics": WORDS,
                                   "sections": [{"name": "Verse", "from": 0, "to": 19.2}, {"name": "Chorus", "from": 19.2, "to": 28.8}]}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.locator('#lanes .lanehead[data-part="harmony"]').click()
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    page.fill("#songname", "Twinkle")
    page.locator("#songname").dispatch_event("change")
    page.click("#songsheet")
    expect(page.locator("#sheetview")).to_be_visible()
    page.set_viewport_size({"width": 1100, "height": 900})
    page.screenshot(path=str(SHOTS / "sheet-screen.png"))
    page.emulate_media(media="print")
    page.screenshot(path=str(SHOTS / "sheet-print.png"), full_page=True)
    (SHOTS / "sheet.pdf").write_bytes(page.pdf(format="A4"))
    page.emulate_media(media="screen")


def test_guided_share_card(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.click('#steps [data-step="song"]')
        page.click("#gtile-chords")
        page.click("#gchords")
        page.click('#steps [data-step="share"]')
        page.locator("#gsongsheet").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "sheet-guided-share.png"))
        page.click("#gsongsheet")
        expect(page.locator("#sheetview")).to_be_visible()
        page.screenshot(path=str(SHOTS / "sheet-phone.png"))
