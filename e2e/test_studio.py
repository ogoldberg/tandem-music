"""End-to-end studio flows in a real Chromium against the real FastAPI app."""
import io
import json
import re
import wave

import numpy as np
from playwright.sync_api import expect

# A4, C5, E5: what the server melody analyzer must find in the imported recording.
TONES = [(440.0, 69), (523.25, 72), (659.25, 76)]


def tone_wav(path, rate=48000, seconds=0.6, gap=0.15):
    """Mono 16-bit WAV of three sung-range tones separated by silence, at a 48 kHz device rate."""
    parts = []
    for hz, _ in TONES:
        t = np.arange(int(rate * seconds)) / rate
        env = np.minimum(1, np.minimum(t, seconds - t) / 0.02)
        parts += [0.4 * env * np.sin(2 * np.pi * hz * t), np.zeros(int(rate * gap))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.concatenate(parts) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def note_pitches(page):
    titles = page.locator("#melodyroll .note").evaluate_all("els => els.map(e => e.title)")
    return [int(re.match(r"MIDI (\d+) at", t).group(1)) for t in titles]


def count(page, which):
    return int(page.locator("#" + which).text_content().split()[0])


def download(page, button, tmp_path):
    with page.expect_download() as info:
        page.click(button)
    target = tmp_path / info.value.suggested_filename
    info.value.save_as(target)
    return target


def test_import_transcribe_edit_play_export_save_reload(studio, tmp_path):
    page = studio
    expect(page.locator("#status")).to_have_text("Ready")
    assert count(page, "notecount") == 0

    # Import a 48 kHz recording: the browser decodes it, then posts a mono WAV to the server.
    page.select_option("#mode", "melody")
    page.select_option("#transcriber", "heuristic")
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones-48k.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 2\.\ds\."))
    expect(page.locator("#analyze")).to_be_enabled()

    with page.expect_response(lambda r: r.url.endswith("/api/analyze?mode=melody")) as analyzed:
        page.click("#analyze")
    assert analyzed.value.status == 200
    expect(page.locator("#status")).to_have_text("Transcription complete")
    assert note_pitches(page) == [m for _, m in TONES]
    assert count(page, "notecount") == 3

    # Edit a note (tapping removes it), then undo the edit.
    page.locator("#melodyroll .note").nth(1).click()
    assert note_pitches(page) == [69, 76]
    page.click("#undo")
    assert note_pitches(page) == [69, 72, 76]
    page.click("#addnote")
    assert note_pitches(page) == [69, 72, 76, 60]
    page.select_option("#drum", "snare")
    page.click("#addhit")
    assert count(page, "hitcount") == 1

    page.click("#play")
    expect(page.locator("#status")).to_have_text("Playing composition")
    page.click("#stop")
    expect(page.locator("#status")).to_have_text("Stopped")

    wav = download(page, "#exportwav", tmp_path).read_bytes()
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 22050 and w.getnframes() > 22050
        samples = np.frombuffer(w.readframes(w.getnframes()), "<i2")
    assert np.abs(samples).max() > 1000, "exported arrangement is silent"

    mid = download(page, "#exportmidi", tmp_path).read_bytes()
    assert mid[:4] == b"MThd" and b"MTrk" in mid

    saved_path = download(page, "#save", tmp_path)
    saved = json.loads(saved_path.read_text())
    assert saved["format"] == "tandem-project" and saved["version"] == 1
    assert [n["m"] for n in saved["notes"]] == [69, 72, 76, 60]
    assert saved["drums"] == [{"k": "snare", "t": 0.25}]

    # Clear, then open the saved project.
    page.click("#clearnotes")
    page.click("#clearhits")
    assert count(page, "notecount") == 0 and count(page, "hitcount") == 0
    page.set_input_files("#projectfile", str(saved_path))
    expect(page.locator("#status")).to_have_text("Project opened")
    assert note_pitches(page) == [69, 72, 76, 60]
    assert count(page, "hitcount") == 1

    # The localStorage draft survives a reload.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert note_pitches(page) == [69, 72, 76, 60]
    assert count(page, "hitcount") == 1


def history_state(page):
    """Undo/redo availability and the edit each button would act on (from the button titles)."""
    return {b: (page.locator("#" + b).is_enabled(), page.locator("#" + b).get_attribute("title")) for b in ("undo", "redo")}


def test_undo_redo_across_manual_ai_load_and_vocal_target_edits(studio, tmp_path):
    """EDIT.1: one history covers manual edits, AI actions, project loads and vocal tuning targets."""
    page = studio
    assert history_state(page) == {"undo": (False, "Nothing to undo"), "redo": (False, "Nothing to redo")}

    # Load example, then a manual edit: tapping a note removes it.
    page.click("#demo")
    assert count(page, "notecount") == 8 and count(page, "hitcount") == 16
    page.locator("#melodyroll .note").nth(0).click()
    assert note_pitches(page) == [64, 67, 69, 67, 64, 62, 60]
    page.select_option("#instrument", "strings")
    page.fill("#bpm", "140")
    page.press("#bpm", "Tab")
    expect(page.locator("#bpm")).to_have_value("140")

    # An AI edit through the real chat form and action applier; only the model reply is canned,
    # since e2e runs without provider credentials.
    reply = {"reply": "Slower, with an extra kick.", "actions": [
        {"type": "set_tempo", "bpm": 90}, {"type": "add_hit", "drum": "kick", "start": 4.0}]}
    page.route("**/api/chat", lambda route: route.fulfill(status=200, json=reply))
    page.fill("#prompt", "slow it down and add a kick")
    page.click("#chatform button[type=submit]")
    expect(page.locator("#status")).to_have_text("Applied 2 AI edit(s). Undo is available.")
    expect(page.locator("#bpm")).to_have_value("90")
    assert count(page, "hitcount") == 17
    assert history_state(page)["undo"] == (True, "Undo: AI edit")

    # Open a project file.
    project = tmp_path / "other.json"
    project.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "bass",
                                   "melody_locked": True, "notes": [{"m": 50, "t": 0, "d": 0.5}], "drums": []}))
    page.set_input_files("#projectfile", str(project))
    expect(page.locator("#status")).to_have_text("Project opened")
    assert note_pitches(page) == [50] and count(page, "hitcount") == 0

    # Ctrl+Z inside a text field is left to the field.
    page.click("#prompt")
    page.keyboard.press("Control+z")
    assert note_pitches(page) == [50]

    # Undo back through every edit type: button, Ctrl+Z and Cmd+Z.
    page.click("#undo")  # Open project
    expect(page.locator("#bpm")).to_have_value("90")
    assert count(page, "hitcount") == 17
    assert history_state(page) == {"undo": (True, "Undo: AI edit"), "redo": (True, "Redo: Open project")}
    page.click("h1")  # leave the text field so the shortcut reaches the studio
    page.keyboard.press("Control+z")  # AI edit
    expect(page.locator("#bpm")).to_have_value("140")
    assert count(page, "hitcount") == 16
    page.keyboard.press("Meta+z")  # tempo
    expect(page.locator("#bpm")).to_have_value("100")
    page.click("#undo")  # instrument
    expect(page.locator("#instrument")).to_have_value("marimba")
    page.click("#undo")  # removed note comes back
    assert note_pitches(page) == [60, 64, 67, 69, 67, 64, 62, 60]
    page.click("#undo")  # example
    assert count(page, "notecount") == 0 and count(page, "hitcount") == 0
    expect(page.locator("#status")).to_have_text("Undid: Load example")
    assert history_state(page) == {"undo": (False, "Nothing to undo"), "redo": (True, "Redo: Load example")}

    # Redo forward again: button, Ctrl+Shift+Z, Ctrl+Y.
    page.click("#redo")
    assert count(page, "notecount") == 8
    page.keyboard.press("Control+Shift+z")
    assert note_pitches(page) == [64, 67, 69, 67, 64, 62, 60]
    page.keyboard.press("Control+y")
    expect(page.locator("#instrument")).to_have_value("strings")
    for _ in range(3):
        page.click("#redo")
    assert note_pitches(page) == [50]
    expect(page.locator("#bpm")).to_have_value("120")
    assert history_state(page)["redo"] == (False, "Nothing to redo")

    # A new edit after undo clears redo.
    page.click("#undo")
    assert history_state(page)["redo"][0] is True
    page.click("#addnote")
    assert history_state(page) == {"undo": (True, "Undo: Add note"), "redo": (False, "Nothing to redo")}

    # An edit that changes nothing is not recorded: clearing an empty drum track.
    assert count(page, "hitcount") == 17
    page.click("#clearhits")
    page.click("#clearhits")
    page.click("#undo")
    assert count(page, "hitcount") == 17

    # Vocal tuning targets: detect sung notes on device, edit a target, undo and redo it.
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones-48k.wav")))
    expect(page.locator("#detectvocal")).to_be_enabled()
    page.click("#detectvocal")
    expect(page.locator("#status")).to_have_text("Vocal notes ready to edit.", timeout=60_000)
    first = page.locator("#vocalnoteeditor .row").first.locator("span")
    detected = first.text_content()
    page.locator("#vocalnoteeditor .row").first.locator("button", has_text="+").click()
    assert first.text_content() != detected
    assert history_state(page)["undo"] == (True, "Undo: Raise vocal target 1")
    page.click("#undo")
    assert first.text_content() == detected
    page.click("#redo")
    assert first.text_content() != detected
    page.click("#undo")
    page.click("#undo")  # detection itself
    expect(page.locator("#vocalnoteeditor")).to_have_text("Press Detect sung notes to edit the pitch targets.")
    expect(page.locator("#resetvocal")).to_be_disabled()
    page.click("#redo")
    expect(page.locator("#vocalnoteeditor .row")).not_to_have_count(0)

    # A new recording drops the old recording's targets from history instead of restoring them later.
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones-48k-2.wav")))
    expect(page.locator("#vocalnoteeditor")).to_have_text("Press Detect sung notes to edit the pitch targets.")
    assert history_state(page) == {"undo": (True, "Undo: Add note"), "redo": (False, "Nothing to redo")}
    page.click("#undo")
    expect(page.locator("#status")).to_have_text("Undid: Add note")
    expect(page.locator("#vocalnoteeditor")).to_have_text("Press Detect sung notes to edit the pitch targets.")
