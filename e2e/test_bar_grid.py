"""FIX.3: chords, the starter beat and quantize share one bar grid. A melody sung in free time that starts late, with a
pickup before its first downbeat, gets chord bars and a starter beat that start together on that downbeat, and quantize
moves the chords part and the harmony voice with the melody, in the same edit."""
import json

from playwright.sync_api import expect

from conftest import show_part
from test_beats import drum_hits, set_tempo

BPM = 100  # a 0.6 s beat, a 2.4 s bar


def open_song(page, tmp_path, **parts):
    project = tmp_path / "song.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": BPM, "instrument": "piano",
                                   "melody_locked": True, "drums": [], **parts}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")


def starts(page, roll):
    titles = page.eval_on_selector_all(f"#{roll} .note", "els => els.map(b => b.title)")
    return sorted({round(float(t.split(" at ")[1].split("s")[0]), 3) for t in titles})


def test_chords_and_the_starter_beat_start_on_the_late_melody_s_first_downbeat(studio, tmp_path):
    page = studio
    # In free time: the beat the notes agree on falls at 1.37 s, with a half-beat pickup at 1.07 s before it.
    pitches = [60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 72]
    notes = [{"m": 67, "t": 1.07, "d": 0.25}] + [{"m": m, "t": round(1.37 + i * 0.6, 3), "d": 0.5} for i, m in enumerate(pitches)]
    open_song(page, tmp_path, notes=notes)

    show_part(page, "harmony")
    page.select_option("#harmonystyle", "chords")
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("in C major")
    # A chord a bar from the first downbeat: the pickup is left unaccompanied, the bar lines do not move to it.
    chords = starts(page, "harmonyroll")
    assert chords == [round(1.37 + k * 2.4, 3) for k in range(len(chords))] and len(chords) == 3

    show_part(page, "drums")
    page.select_option("#groove", "straight")
    page.select_option("#groovebars", "4")
    page.click("#addgroove")
    expect(page.locator("#status")).to_contain_text("Added the straight beat")
    kicks = [t for k, t in drum_hits(page) if k == "kick"]
    assert kicks[0] == 1.37
    # Every chord starts on a kick.
    assert all(any(abs(c - k) < 1e-3 for k in kicks) for c in chords), (chords, kicks)


def test_quantize_moves_the_chords_and_the_harmony_voice_with_the_melody(studio, tmp_path):
    page = studio
    # Sung to the count-in: on the beat grid from zero, each note a little late or early, the other parts too.
    jitter = [0.02, -0.025, 0.015, 0.03, -0.02, 0.01, -0.015, 0.025]
    open_song(page, tmp_path,
              notes=[{"m": 60 + 2 * (i % 4), "t": round(i * 0.6 + j, 3), "d": 0.5} for i, j in enumerate(jitter)],
              harmony=[{"m": m, "t": t, "d": 2.2} for t in (0.03, 2.38) for m in (48, 52, 55)],
              voice2=[{"m": 64 + 2 * (i % 4), "t": round(i * 0.6 - j, 3), "d": 0.5} for i, j in enumerate(jitter)])
    set_tempo(page, BPM)
    show_part(page, "melody")
    page.select_option("#grid", "2")
    page.click("#quantize")
    expect(page.locator("#status")).to_have_text(f"Quantize to 1/8 at {BPM} bpm")
    on_beats = [round(i * 0.6, 3) for i in range(8)]
    assert starts(page, "melodyroll") == on_beats
    assert starts(page, "harmonyroll") == [0, 2.4]
    assert starts(page, "voice2roll") == on_beats
    # One edit: one undo puts all three back as they were.
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Quantize to 1/8")
    page.click("#undo")
    assert starts(page, "harmonyroll") == [0.03, 2.38]
    assert starts(page, "voice2roll")[1] == 0.625


def test_quantize_lines_up_a_song_that_has_only_chords(studio, tmp_path):
    page = studio
    open_song(page, tmp_path, notes=[], harmony=[{"m": m, "t": t, "d": 2.2} for t in (0.03, 2.38) for m in (48, 52, 55)])
    show_part(page, "melody")
    page.select_option("#grid", "2")
    page.click("#quantize")
    expect(page.locator("#status")).to_have_text(f"Quantize to 1/8 at {BPM} bpm")
    assert starts(page, "harmonyroll") == [0, 2.4]
