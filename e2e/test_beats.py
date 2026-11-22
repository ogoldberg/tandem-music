"""BEAT.1: starter beats. A groove picked in the studio's drums panel or the guided Song step is written into the drum part as
ordinary hits at the song's speed: it is in the drum roll and the MIDI file, and one undo takes it away."""
import io
import json
import os
import tempfile
from pathlib import Path

import mido
from playwright.sync_api import expect

from test_guided import guided_page, open_view
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


def test_the_guided_beat_view_offers_the_starter_beats(browser, server_url):
    with guided_page(browser, server_url) as page:
        open_view(page, "beat")
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



def in_order(hits, a, b):
    """The hits from a to b seconds in time order, kick before snare before hi-hat when they fall together."""
    order = {"kick": 0, "snare": 1, "hat": 2}
    return sorted(((k, t) for k, t in hits if a <= t < b), key=lambda h: (h[1], order[h[0]]))


def drum_midi(page, tmp_path):
    mid = mido.MidiFile(file=io.BytesIO(download(page, "#exportmidi", tmp_path).read_bytes()))
    drums = next(t for t in mid.tracks if t.name == "Drums")
    now, ons = 0, []
    for msg in drums:
        now += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            ons.append((msg.note, now / mid.ticks_per_beat))
    return ons


def test_fills_follow_the_genre_go_every_four_bars_and_undo_as_one_edit(studio, tmp_path):
    """BEAT.2: with no sections a fill replaces the last half bar before every fourth bar where the beat goes on."""
    page = studio
    set_tempo(page, 120)
    expect(page.locator("#fill option")).to_have_count(6)
    expect(page.locator("#fill")).to_have_value("build")
    page.select_option("#genre", "rock")
    expect(page.locator("#fill")).to_have_value("roll")
    expect(page.locator("#fillabout")).to_contain_text("the snare on every sixteenth")
    page.select_option("#groove", "straight")
    page.select_option("#groovebars", "8")
    page.click("#addgroove")
    assert count(page, "hitcount") == 96
    page.click("#addfills")
    # 8 bars of 2 s: a fill before bar 4 (8 s); bar 8 is the end of the beat, so none there.
    expect(page.locator("#status")).to_have_text("Added 1 snare roll fill, one every four bars. Undo is available.")
    # The straight beat's 6 hits in 7..8 s became a kick and eight sixteenth snares.
    assert count(page, "hitcount") == 96 - 6 + 9
    hits = drum_hits(page)
    assert in_order(hits, 7, 8) == [("kick", 7.0)] + [("snare", 7 + i * 0.125) for i in range(8)]
    assert in_order(hits, 15, 16) == [("kick", 15.0), ("hat", 15.0), ("hat", 15.25), ("snare", 15.5), ("hat", 15.5), ("hat", 15.75)]
    page.locator("#drumroll").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "studio-fills.png"))

    # The MIDI file has the roll: eight snares (38) in beats 14 to 16.
    ons = drum_midi(page, tmp_path)
    assert len(ons) == 99
    assert [b for n, b in ons if n == 38 and 14 <= b < 16] == [14 + i * 0.25 for i in range(8)]

    # One edit: one undo gives the beat back; adding them again after redo changes nothing.
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Drum fills: Snare roll")
    page.click("#undo")
    assert count(page, "hitcount") == 96
    page.click("#redo")
    assert count(page, "hitcount") == 99
    page.click("#addfills")
    expect(page.locator("#status")).to_have_text("The fills are already there.")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Drum fills: Snare roll")


def test_fills_go_before_the_section_lines_and_never_out_of_silence(studio, tmp_path):
    page = studio
    # 120 bpm (2 s bars), a melody to 20 s, a verse to 12 s and a chorus to 20 s.
    project = tmp_path / "song.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True,
                                   "notes": [{"m": 60, "t": 0, "d": 1}, {"m": 64, "t": 19, "d": 1}], "drums": [],
                                   "sections": [{"name": "Verse", "from": 0, "to": 12}, {"name": "Chorus", "from": 12, "to": 20}]}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.click("#addfills")
    expect(page.locator("#status")).to_have_text("Add a beat first: a fill replaces the end of a bar of drums.")
    page.select_option("#groove", "straight")
    page.click("#addgroove")
    assert count(page, "hitcount") == 120
    page.click("#addfills")
    # Before the chorus (12 s) only: 20 s is the end, and the four-bar line (8 s) is not used with sections.
    expect(page.locator("#status")).to_have_text("Added 1 build fill before the section lines. Undo is available.")
    hits = drum_hits(page)
    assert in_order(hits, 11, 12) == [("kick", 11.0), ("hat", 11.0), ("snare", 11.25), ("kick", 11.5), ("snare", 11.5), ("snare", 11.75), ("snare", 11.875)]
    assert in_order(hits, 7, 8) == [("kick", 7.0), ("hat", 7.0), ("hat", 7.25), ("snare", 7.5), ("hat", 7.5), ("hat", 7.75)]

    # A beat that stops before the chorus: no fill leads into silence.
    page.click("#undo")
    page.click("#undo")
    page.select_option("#groovebars", "4")
    page.click("#addgroove")
    page.click("#addfills")
    expect(page.locator("#status")).to_contain_text("No place for a fill")
    assert count(page, "hitcount") == 48


def test_the_guided_beat_view_adds_fills(browser, server_url):
    with guided_page(browser, server_url) as page:
        open_view(page, "beat")
        expect(page.locator("#gfill option")).to_have_count(6)
        page.select_option("#ggroove", "straight")
        page.click("#ggrooveadd")
        expect(page.locator("#gdrumstate")).to_have_text("48 hits")
        # Four bars: the only four-bar line is the end of the beat.
        page.click("#gfilladd")
        expect(page.locator("#gstatus")).to_contain_text("No place for a fill")
        page.click("#gmore-beat summary")
        page.select_option("#groovebars", "8")
        page.click("#ggrooveadd")
        expect(page.locator("#gdrumstate")).to_have_text("96 hits")
        page.select_option("#gfill", "triplet")
        expect(page.locator("#fill")).to_have_value("triplet")
        page.click("#gfilladd")
        expect(page.locator("#gstatus")).to_contain_text("Added 1 triplet fill, one every four bars.")
        # Six straight hits become a kick, a hi-hat and five triplet snares.
        expect(page.locator("#gdrumstate")).to_have_text("97 hits")
        page.locator("#gfilladd").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "guided-fills.png"))
