"""HARM.4 screenshots: Twinkle hummed low (C3) in the studio with chords generated with no genre and with jazz,
the chord strip and the chords roll under the melody.

Not collected by the suite (no test_ prefix). Run by path: SHOTS=<dir> python -m pytest e2e/shots_harm4.py
"""
import json
import os
from pathlib import Path

from playwright.sync_api import expect

from test_genre import chord_names

SHOTS = Path(os.environ["SHOTS"])
C, D, E, F, G, A = 48, 50, 52, 53, 55, 57
TWINKLE = [[C, C, G, G], [A, A, G], [F, F, E, E], [D, D, C], [G, G, F, F], [E, E, D], [G, G, F, F], [E, E, D],
           [C, C, G, G], [A, A, G], [F, F, E, E], [D, D, C]]


def notes():
    out, beat = [], 0.6
    for b, bar in enumerate(TWINKLE):
        lens = [1, 1, 2] if len(bar) == 3 else [1, 1, 1, 1]
        at = b * 4
        for m, n in zip(bar, lens):
            out.append({"m": m, "t": round(at * beat, 3), "d": round(n * beat * 0.9, 3)})
            at += n
    return out


def test_twinkle_hummed_low_with_chords(studio, tmp_path):
    page = studio
    project = tmp_path / "twinkle.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano",
                                   "melody_locked": True, "notes": notes(), "drums": []}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.locator('#lanes .lanehead[data-part="harmony"]').click()
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("Generate chords in C major")
    print("none:", page.text_content("#status"), chord_names(page))
    page.locator("#chordstrip").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "harm4-twinkle-none.png"), full_page=True)
    page.select_option("#genre", "jazz")
    page.locator('#lanes .lanehead[data-part="harmony"]').click()
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("Generate chords in C major")
    print("jazz:", page.text_content("#status"), chord_names(page))
    page.locator("#chordstrip").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "harm4-twinkle-jazz.png"), full_page=True)
