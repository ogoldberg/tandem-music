"""FIX.3: chords, the starter beat and quantize share one bar grid. A melody sung in free time that starts late, with a
pickup before its first downbeat, gets chord bars and a starter beat that start together on that downbeat, and quantize
moves the chords part and the harmony voice with the melody, in the same edit."""
import json

from playwright.sync_api import expect

from conftest import show_part
from test_beats import drum_hits, set_tempo
from test_studio import wait_until

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


# GROW.1: a pinned grid. The tune is FIX.3's moved 0.27 s later, so its guessed bars would start at 1.64 s; the file pins
# them at 1.37 s.
PINNED = {"origin": 1.37}
LATER = [{"m": 67, "t": 1.34, "d": 0.25}] + [{"m": m, "t": round(1.64 + i * 0.6, 3), "d": 0.5}
                                            for i, m in enumerate([60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 72])]


def test_a_pinned_grid_keeps_the_bar_lines_when_a_note_is_added_and_survives_undo_and_a_reload(studio, tmp_path):
    page = studio
    open_song(page, tmp_path, notes=LATER, grid=PINNED, uses=["grid"])
    show_part(page, "melody")
    # A note added after the tune; the bars stay where the file pinned them, not where the notes would put them (1.64 s,
    # test_a_project_without_a_grid_shows_no_pinned_speed).
    page.click("#addnote")
    expect(page.locator("#melodyroll .note")).to_have_count(len(LATER) + 1)
    show_part(page, "harmony")
    page.select_option("#harmonystyle", "chords")
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("in C major")
    chords = starts(page, "harmonyroll")
    assert chords and all(abs((c - 1.37) / 2.4 - round((c - 1.37) / 2.4)) < 1e-3 for c in chords), chords
    show_part(page, "drums")
    page.select_option("#groove", "straight")
    page.select_option("#groovebars", "4")
    page.click("#addgroove")
    expect(page.locator("#status")).to_contain_text("Added the straight beat")
    assert [t for k, t in drum_hits(page) if k == "kick"][0] == 1.37
    # The grid is in the undo snapshots and the draft, and Save writes it with `uses`.
    page.click("#undo")
    page.click("#undo")
    page.click("#undo")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Open project")
    expect(page.locator("#melodyroll .note")).to_have_count(len(LATER))
    # The draft keeps the grid across a reload.
    wait_until(page, f"""async () => {{ const db = await new Promise(r => {{ const q = indexedDB.open('tandem'); q.onsuccess = () => r(q.result) }});
        const d = await new Promise(r => {{ const q = db.transaction('kv').objectStore('kv').get('draft'); q.onsuccess = () => r(q.result) }});
        db.close(); return !!(d && d.notes.length === {len(LATER)} && d.grid && d.grid.origin === 1.37) }}""", "the draft has the pinned grid")
    page.reload()
    expect(page.locator("#melodyroll .note")).to_have_count(len(LATER))
    show_part(page, "melody")
    expect(page.locator("#bpmpinned")).to_have_text(
        "The song's bars are pinned, so its speed can only be doubled or halved: 50 or 200 beats a minute.")
    with page.expect_download() as dl:
        page.click("#save")
    saved = json.loads(open(dl.value.path()).read())
    assert saved["grid"] == PINNED and saved["uses"] == ["grid"]


def test_with_the_grid_pinned_the_speed_controls_only_double_or_halve_and_say_why(studio, tmp_path):
    page = studio
    open_song(page, tmp_path, notes=LATER, grid=PINNED, uses=["grid"])
    show_part(page, "melody")
    why = "The song's bars are pinned, so its speed can only be doubled or halved: 50 or 200 beats a minute."
    expect(page.locator("#bpmpinned")).to_have_text(why)
    expect(page.locator("#gbpmpinned")).to_have_text(why)
    page.fill("#bpm", "93")
    page.dispatch_event("#bpm", "change")
    expect(page.locator("#status")).to_have_text(why)
    expect(page.locator("#bpm")).to_have_value("100")
    expect(page.locator("#undo")).not_to_have_attribute("title", "Undo: Change tempo")
    # Doubled, the bars are 1.2 s long and start on the same lines.
    set_tempo(page, 200)
    expect(page.locator("#bpmpinned")).to_have_text(
        "The song's bars are pinned, so its speed can only be doubled or halved: 100 beats a minute.")
    with page.expect_download() as dl:
        page.click("#save")
    assert json.loads(open(dl.value.path()).read())["grid"] == {"origin": 0.17}
    # Detect tempo finds the tune's own 100 bpm, the halved speed, which is taken.
    page.click("#detecttempo")
    expect(page.locator("#status")).to_have_text("Detected tempo: 100 bpm")
    expect(page.locator("#bpm")).to_have_value("100")
    page.click("#undo")
    expect(page.locator("#bpm")).to_have_value("200")
    page.click("#undo")
    expect(page.locator("#bpm")).to_have_value("100")
    with page.expect_download() as dl:
        page.click("#save")
    assert json.loads(open(dl.value.path()).read())["grid"] == PINNED


def test_a_project_without_a_grid_shows_no_pinned_speed(studio, tmp_path):
    page = studio
    open_song(page, tmp_path, notes=LATER)
    show_part(page, "harmony")
    page.select_option("#harmonystyle", "chords")
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("in C major")
    # Guessed from the notes, the bars start at 1.64 s.
    chords = starts(page, "harmonyroll")
    assert chords[0] == 1.64 and all(abs((c - 1.64) / 2.4 - round((c - 1.64) / 2.4)) < 1e-3 for c in chords), chords
    show_part(page, "melody")
    expect(page.locator("#bpmpinned")).to_be_hidden()
    set_tempo(page, 93)
    with page.expect_download() as dl:
        page.click("#save")
    saved = json.loads(open(dl.value.path()).read())
    assert "grid" not in saved and "uses" not in saved


def test_a_file_made_with_a_newer_tandem_is_refused(studio, tmp_path):
    page = studio
    project = tmp_path / "newer.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": BPM, "instrument": "piano",
                                   "melody_locked": True, "notes": LATER, "drums": [], "uses": ["grid", "comp-src"],
                                   "grid": PINNED}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_contain_text("This song was made with a newer Tandem. Update, then open it again.")
    assert page.locator("#melodyroll .note").count() == 0


def test_with_the_grid_pinned_detect_tempo_says_why_it_keeps_the_speed(studio, tmp_path):
    page = studio
    # Pinned at 120 beats a minute, a tune at 100: Detect tempo finds 100, which is not 60 (240 is past 220).
    project = tmp_path / "song.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano",
                                   "melody_locked": True, "drums": [], "notes": LATER, "grid": {"origin": 0.5},
                                   "uses": ["grid"]}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")
    show_part(page, "melody")
    page.click("#detecttempo")
    expect(page.locator("#status")).to_have_text("Detected tempo: 100 bpm. The song's bars are pinned, so its speed can "
                                                 "only be doubled or halved: 60 beats a minute.")
    expect(page.locator("#bpm")).to_have_value("120")
