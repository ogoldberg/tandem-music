"""BEAT.1: starter beats. A groove picked in the studio's drums panel or the guided Song step is written into the drum part as
ordinary hits at the song's speed: it is in the drum roll and the MIDI file, and one undo takes it away."""
import io
import json
import os
import tempfile
from pathlib import Path

import mido
from playwright.sync_api import expect

from test_guided import guided_page
from test_studio import count, download

SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())


def set_tempo(page, bpm):
    page.fill("#bpm", str(bpm))
    page.dispatch_event("#bpm", "change")
    expect(page.locator("#keyspeed")).to_contain_text(f"{bpm} BPM")


def drum_hits(page):
    titles = page.locator("#drumroll .hit").evaluate_all("els => els.map(e => e.title)")
    return [(k, float(t.rstrip("s"))) for k, _, t in (x.split(" ") for x in titles)]


def test_a_starter_beat_is_in_the_drum_roll_and_the_midi_file_and_undoes(studio, tmp_path):
    page = studio
    set_tempo(page, 120)
    expect(page.locator("#groove option")).to_have_count(4)
    page.select_option("#groove", "four")
    expect(page.locator("#grooveabout")).to_contain_text("a kick on every beat")
    page.select_option("#groovebars", "4")
    page.click("#addgroove")
    expect(page.locator("#status")).to_have_text("Added the four on the floor beat: 4 bars at 120 BPM. Undo is available.")
    # Four on the floor at 120 bpm: a kick every half second, snares on 2 and 4, hi-hats between the beats.
    assert count(page, "hitcount") == 40
    hits = drum_hits(page)
    assert [t for k, t in hits if k == "kick"] == [i * 0.5 for i in range(16)]
    assert [t for k, t in hits if k == "snare"] == [b * 2 + x for b in range(4) for x in (0.5, 1.5)]
    assert [t for k, t in hits if k == "hat"] == [i * 0.5 + 0.25 for i in range(16)]
    page.locator("#drumroll").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "studio-beat.png"))

    # The MIDI file: 40 drum notes on channel 10, the kicks on every beat.
    mid = mido.MidiFile(file=io.BytesIO(download(page, "#exportmidi", tmp_path).read_bytes()))
    drums = next(t for t in mid.tracks if t.name == "Drums")
    now, ons = 0, []
    for msg in drums:
        now += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            ons.append((msg.note, now / mid.ticks_per_beat))
    assert len(ons) == 40 and all(m.channel == 9 for m in drums if m.type == "note_on")
    assert [b for n, b in ons if n == 36] == list(range(16))

    # One undo removes the whole beat; redo brings it back.
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Starter beat: Four on the floor")
    page.click("#undo")
    assert count(page, "hitcount") == 0
    page.click("#redo")
    assert count(page, "hitcount") == 40


def test_the_beat_replaces_the_drums_unless_they_are_kept_and_can_last_as_long_as_the_song(studio, tmp_path):
    page = studio
    # A song whose melody ends at 9 s, at 120 bpm (2 s bars), with one beatboxed hit off the grid.
    project = tmp_path / "song.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True,
                                   "notes": [{"m": 60, "t": 0, "d": 1}, {"m": 64, "t": 8, "d": 1}], "drums": [{"k": "snare", "t": 0.3}]}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")
    expect(page.locator("#groovebars")).to_have_value("song")
    page.select_option("#groove", "straight")
    page.click("#addgroove")
    # 9 s of song is 5 bars of 12 hits; the beatboxed snare is gone.
    assert count(page, "hitcount") == 60 and ("snare", 0.3) not in drum_hits(page)
    page.click("#undo")
    page.check("#groovekeep")
    page.select_option("#groove", "halftime")
    page.click("#addgroove")
    expect(page.locator("#status")).to_contain_text("with your drums")
    assert count(page, "hitcount") == 5 * 11 + 1 and ("snare", 0.3) in drum_hits(page)


def test_the_guided_song_step_offers_the_starter_beats(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click('#steps [data-step="song"]')
        expect(page.locator("#gdrumstate")).to_have_text("None yet")
        expect(page.locator("#ggroove option")).to_have_count(4)
        page.select_option("#ggroove", "shuffle")
        page.click("#ggrooveadd")
        # An empty song: four bars at 100 bpm, 12 hits a bar.
        expect(page.locator("#gdrumstate")).to_have_text("48 hits")
        expect(page.locator("#gnodrums")).to_be_enabled()
        page.screenshot(path=str(SHOTS / "guided-beat.png"))
        page.click("#gnodrums")
        expect(page.locator("#gdrumstate")).to_have_text("None yet")

