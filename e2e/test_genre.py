"""GENRE.1: an optional genre for the song. With no genre the studio makes what it always made; a genre picked in the
top bar (or the guided Song step) is one edit that sets the instruments, and then the chords, the bass line, the
starter beat, the quantize controls, Detect tempo and a transcribed beat follow it. Every choice can still be changed."""
import io
import json
import os
import tempfile
import wave
from pathlib import Path

import numpy as np
from playwright.sync_api import expect

from test_guided import guided_page, open_view
from test_studio import count, download

SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())

# A tune in C major at 100 bpm (2.4 s bars): C E G A G E D C, then F A C A G E D C.
TUNE = [{"m": m, "t": round(i * 0.6, 3), "d": 0.5} for i, m in enumerate([60, 64, 67, 69, 67, 64, 62, 60, 65, 69, 72, 69, 67, 64, 62, 60])]


def open_tune(page, tmp_path, **extra):
    project = tmp_path / "tune.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano", "melody_locked": True,
                                   "notes": TUNE, "drums": [], **extra}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")


def saved(page, tmp_path):
    return json.loads(download(page, "#save", tmp_path).read_text())


def generate(page, style):
    page.select_option("#harmonystyle", style)
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("Generate " + ("bass line" if style == "bass" else "chords") + " in C major")


def chord_names(page):
    return page.eval_on_selector_all("#chordstrip .chordsym", "els => els.map(b => b.dataset.name)")


def by_onset(notes):
    out = {}
    for n in notes:
        out.setdefault(n["t"], []).append(n["m"])
    return out


def test_a_genre_changes_the_chords_bass_beat_and_controls_and_none_keeps_todays(studio, tmp_path):
    page = studio
    open_tune(page, tmp_path)
    expect(page.locator("#genre")).to_have_value("")

    # No genre: today's chords (a triad held each bar) and bass (root on 1, fifth on 3), and the straight beat.
    generate(page, "chords")
    plain = saved(page, tmp_path)
    assert "genre" not in plain
    plain_chords = by_onset(plain["harmony"])
    assert sorted(plain_chords) == [0, 2.4, 4.8, 7.2] and all(len(v) == 3 for v in plain_chords.values())
    assert chord_names(page) == ["C", "C", "F", "C"]
    generate(page, "bass")
    plain_bass = saved(page, tmp_path)["harmony"]
    assert [n["t"] for n in plain_bass] == [0, 1.2, 2.4, 3.6, 4.8, 6, 7.2, 8.4]
    page.click("#addgroove")
    plain_drums = saved(page, tmp_path)["drums"]

    # Jazz: one edit sets the genre and the instruments; the quantize controls and the starter beat follow it.
    page.select_option("#genre", "jazz")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Genre: Jazz")
    expect(page.locator("#instrument")).to_have_value("piano")
    expect(page.locator("#harmonyinstrument")).to_have_value("organ")
    expect(page.locator("#grid")).to_have_value("2")
    expect(page.locator("#swing")).to_have_value("100")
    expect(page.locator("#groove")).to_have_value("shuffle")
    expect(page.locator("#ggenre")).to_have_value("jazz")

    # Jazz chords: four-note seventh chords struck twice a bar, read back as maj7 chords.
    generate(page, "chords")
    jazz = saved(page, tmp_path)
    assert jazz["genre"] == "jazz" and jazz["harmony_instrument"] == "organ"
    jazz_chords = by_onset(jazz["harmony"])
    assert sorted(jazz_chords) == [0, 1.2, 2.4, 3.6, 4.8, 6, 7.2, 8.4] and all(len(v) == 4 for v in jazz_chords.values())
    # HARM.4: jazz changes chord in the middle of the first bar (Cmaj7 to G7) and goes back home.
    assert chord_names(page) == ["Cmaj7", "G7", "Cmaj7", "Fmaj7", "Cmaj7"]
    # A walking bass: a note on every beat, root, third, fifth, then a step into the next chord's root
    # (the first bar's G7 half: its fifth, then B into C).
    generate(page, "bass")
    walk = saved(page, tmp_path)["harmony"]
    assert len(walk) == 16 and [n["m"] for n in walk[:4]] == [36, 40, 50, 47] and walk[7]["m"] == 40 and walk[11]["m"] == 47  # E into F, B into C
    # The shuffle starter beat: hi-hats on the triplets, not the straight eighths.
    page.click("#addgroove")
    jazz_drums = saved(page, tmp_path)["drums"]
    assert jazz_drums != plain_drums
    hats = [h["t"] for h in jazz_drums if h["k"] == "hat"][:3]
    assert hats == [0, 0.4, 0.6]
    page.locator("#chordstrip").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "studio-genre-jazz.png"))

    # Every choice can still be changed: another instrument, another groove.
    page.select_option("#harmonyinstrument", "piano")
    expect(page.locator("#harmonyinstrument")).to_have_value("piano")

    # The saved genre comes back when the project is opened; choosing None again leaves the instruments.
    path = download(page, "#save", tmp_path).rename(tmp_path / "jazz.json")
    page.select_option("#genre", "")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: No genre")
    assert "genre" not in saved(page, tmp_path)
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#genre")).to_have_value("jazz")


def test_detect_tempo_looks_in_the_genres_range(studio, tmp_path):
    page = studio
    # Notes every 0.4 s: 150 bpm in the studio's 60..180 range, 75 bpm in hip-hop's 70..110.
    open_tune(page, tmp_path)
    page.click("#clearnotes")
    eighths = [{"m": 60 + (i % 3), "t": round(i * 0.4, 3), "d": 0.3} for i in range(16)]
    project = tmp_path / "eighths.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "notes": eighths, "drums": []}))
    page.set_input_files("#projectfile", str(project))
    page.click("#detecttempo")
    expect(page.locator("#status")).to_have_text("Detected tempo: 150 bpm")
    page.click("#undo")
    page.select_option("#genre", "hiphop")
    page.click("#detecttempo")
    expect(page.locator("#status")).to_have_text("Detected tempo: 75 bpm")


def beat_wav(path, times, rate=48000):
    """A beatbox: a low thump (kick) on the even hits and a noise burst (hi-hat) on the odd ones."""
    x = np.zeros(int(rate * (max(times) + 0.6)))
    rng = np.random.default_rng(7)
    for i, t in enumerate(times):
        n = int(rate * 0.08)
        tt = np.arange(n) / rate
        hit = np.sin(2 * np.pi * 70 * tt) * np.exp(-tt * 40) if i % 2 == 0 else rng.uniform(-1, 1, n) * np.exp(-tt * 60)
        s = int(rate * t)
        x[s:s + n] += 0.6 * hit
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def test_a_transcribed_beat_is_read_into_the_genres_groove_and_undo_gives_it_as_played(studio, tmp_path):
    page = studio
    # Hits every 0.4 s, each up to 25 ms early or late.
    times = [0.3 + i * 0.4 + d for i, d in enumerate([0, 0.02, -0.015, 0.025, -0.02, 0.01, -0.025, 0.015, 0, -0.01, 0.02, -0.02])]
    page.select_option("#genre", "hiphop")
    page.select_option("#mode", "rhythm")
    page.set_input_files("#audiofile", str(beat_wav(tmp_path / "beat.wav", times)))
    expect(page.locator("#analyze")).to_be_enabled()
    page.click("#analyze")
    expect(page.locator("#status")).to_have_text("Transcription complete")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Read the beat as Hip-hop")
    read = saved(page, tmp_path)
    # Hip-hop's tempo range finds about 75 bpm (not 150), and the hits land exactly on its grid: each a pair of
    # sixteenths (an eighth, 30 / bpm seconds) after the last.
    assert abs(read["bpm"] - 75) <= 2
    ts = sorted(h["t"] for h in read["drums"])
    assert len(ts) == 12 and all(abs((b - a) - 30 / read["bpm"]) < 2e-6 for a, b in zip(ts, ts[1:]))
    # Undo gives the hits as they were played, at the old tempo.
    page.click("#undo")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Transcribe drums")
    played = saved(page, tmp_path)
    assert played["bpm"] == 100
    gaps = [b - a for a, b in zip(sorted(h["t"] for h in played["drums"]), sorted(h["t"] for h in played["drums"])[1:])]
    assert any(abs(g - 0.4) > 0.01 for g in gaps)


def test_the_guided_sound_view_picks_a_genre(browser, server_url):
    with guided_page(browser, server_url) as page:
        open_view(page, "sound")
        expect(page.locator("#ggenre")).to_be_visible()
        expect(page.locator("#ggenreabout")).to_contain_text("None")
        page.select_option("#ggenre", "electronic")
        expect(page.locator("#ggenreabout")).to_contain_text("four on the floor")
        expect(page.locator("#genre")).to_have_value("electronic")
        expect(page.locator("#ginstrument")).to_have_value("chip")
        expect(page.locator("#ggroove")).to_have_value("four")
        page.screenshot(path=str(SHOTS / "guided-genre.png"))


def test_a_version_keeps_its_genre_and_restoring_one_without_a_genre_clears_it(studio, tmp_path):
    page = studio
    open_tune(page, tmp_path)
    page.fill("#versionname", "Plain")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Plain")
    page.select_option("#genre", "jazz")
    page.fill("#versionname", "Jazzy")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Jazzy")
    page.select_option("#genre", "rock")
    page.click('#versionlist button[title="Restore Jazzy"]')
    expect(page.locator("#status")).to_contain_text("Restored version: Jazzy")
    expect(page.locator("#genre")).to_have_value("jazz")
    page.click('#versionlist button[title="Restore Plain"]')
    expect(page.locator("#status")).to_contain_text("Restored version: Plain")
    expect(page.locator("#genre")).to_have_value("")
