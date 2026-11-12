"""End-to-end studio flows in a real Chromium against the real FastAPI app."""
import io
import json
import re
import time
import wave
import zipfile

import mido
import pytest
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
        assert w.getframerate() == 44100 and w.getnframes() > 44100
        samples = np.frombuffer(w.readframes(w.getnframes()), "<i2")
    assert np.abs(samples).max() > 1000, "exported arrangement is silent"

    mid = mido.MidiFile(file=io.BytesIO(download(page, "#exportmidi", tmp_path).read_bytes()))
    assert mid.type == 1 and [t.name for t in mid.tracks] == ["Tandem", "Melody", "Drums"]

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

    # The draft (in IndexedDB) survives a reload.
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
    expect(page.locator("#status")).to_have_text(re.compile(r"^\d+ vocal notes ready to edit\.$"), timeout=60_000)
    assert history_state(page)["undo"] == (True, "Undo: Detect sung notes")
    first = page.locator("#vocalnoteeditor .target").first
    detected = first.get_attribute("aria-valuetext")
    first.focus()
    page.keyboard.press("ArrowUp")
    raised = first.get_attribute("aria-valuetext")
    assert raised != detected
    assert history_state(page)["undo"] == (True, f"Undo: Move vocal target 1 to {raised}")
    page.click("#undo")
    assert first.get_attribute("aria-valuetext") == detected
    page.click("#redo")
    assert first.get_attribute("aria-valuetext") == raised
    page.click("#undo")
    page.click("#undo")  # detection itself
    expect(page.locator("#vocalnoteeditor")).to_have_text("Press Detect sung notes to edit the pitch targets.")
    expect(page.locator("#resetvocal")).to_be_disabled()
    page.click("#redo")
    expect(page.locator("#vocalnoteeditor .target")).not_to_have_count(0)

    # A new recording drops the old recording's targets from history instead of restoring them later.
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones-48k-2.wav")))
    expect(page.locator("#vocalnoteeditor")).to_have_text("Press Detect sung notes to edit the pitch targets.")
    assert history_state(page) == {"undo": (True, "Undo: Add note"), "redo": (False, "Nothing to redo")}
    page.click("#undo")
    expect(page.locator("#status")).to_have_text("Undid: Add note")
    expect(page.locator("#vocalnoteeditor")).to_have_text("Press Detect sung notes to edit the pitch targets.")


def long_vocal_wav(path, seconds=180, rate=22050):
    """A 3-minute mono WAV of held sung-range tones (0.8 s each, 0.2 s apart) cycling through a scale."""
    scale = [60, 62, 64, 65, 67, 69, 71, 72]
    note_len, gap = 0.8, 0.2
    t = np.arange(int(rate * note_len)) / rate
    env = np.minimum(1, np.minimum(t, note_len - t) / 0.02)
    parts = []
    for i in range(int(seconds)):
        hz = 440.0 * 2 ** ((scale[i % len(scale)] - 69) / 12)
        parts += [0.4 * env * np.sin(2 * np.pi * hz * t), np.zeros(int(rate * gap))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.concatenate(parts) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def test_vocal_note_targets_cover_a_three_minute_recording(studio, tmp_path):
    """PERF.3: on-device Basic Pitch detects vocal note targets across the whole take, not just the first 60 s."""
    page = studio
    page.select_option("#mode", "vocal")
    page.set_input_files("#audiofile", str(long_vocal_wav(tmp_path / "vocal-3min.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 180\.0s\."))
    expect(page.locator("#detectvocal")).to_be_enabled()

    page.click("#detectvocal")
    expect(page.locator("#status")).to_have_text(re.compile(r"^\d+ vocal notes ready to edit\.$"), timeout=240_000)

    starts = [float(t) for t in page.locator("#vocalnoteeditor .target").evaluate_all("els => els.map(e => e.dataset.t)")]
    assert len(starts) > 128, f"only {len(starts)} targets: still capped at 128"
    assert max(starts) > 170, f"last target at {max(starts)} s: detection stops before the end"
    assert sum(1 for s in starts if s >= 60) > 100, "few targets after 60 s"


def record_tune_requests(page):
    """Wrap fetch so the test can read each /api/tune request's notes_json form field and URL.

    Playwright does not expose multipart bodies built from Blobs, so read the FormData itself.
    """
    page.evaluate("""() => {
      window.__tuneRequests = [];
      const original = window.fetch;
      window.fetch = (url, init) => {
        if (String(url).includes('/api/tune')) window.__tuneRequests.push({url: String(url), notes: init.body.get('notes_json')});
        return original(url, init);
      };
    }""")
    return lambda: page.evaluate("() => window.__tuneRequests")


def test_pitch_contour_editor_edits_drive_tuning_through_history(studio, tmp_path):
    """VOX.3: drag, resize, key/scale snap, keyboard steps and delete edit the targets /api/tune receives."""
    page = studio
    page.select_option("#mode", "vocal")
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones-48k.wav")))
    expect(page.locator("#detectvocal")).to_be_enabled()
    page.click("#detectvocal")
    expect(page.locator("#status")).to_have_text(re.compile(r"^\d+ vocal notes ready to edit\.$"), timeout=60_000)

    targets = page.locator("#vocalnoteeditor .target")
    pitch = lambda i: targets.nth(i).get_attribute("aria-valuetext")  # noqa: E731
    # One target per held tone, at the sung pitch, each with a confidence; the sung line is drawn.
    expect(targets).to_have_count(3)
    assert [pitch(i) for i in range(3)] == ["A4", "C5", "E5"]
    for i in range(3):
        assert re.search(r"confidence \d+%$", targets.nth(i).get_attribute("aria-label"))
    assert page.locator("#vocalnoteeditor canvas").count() == 1
    targets.nth(0).click()
    expect(page.locator("#vocalnoteinfo")).to_have_text(re.compile(r"^Note 1: .* target A4 · sung on target · confidence \d+%"))

    # Drag the second target up two rows (12 px each): C5 -> D5, recorded as one edit.
    box = targets.nth(1).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y - 12, steps=3)
    page.mouse.move(x, y - 24, steps=3)
    page.mouse.up()
    assert pitch(1) == "D5"
    assert history_state(page)["undo"] == (True, "Undo: Move vocal target 2 to D5")

    # Drag the first target's end edge left: it now covers less of the tone.
    before = float(targets.nth(0).get_attribute("data-d"))
    edge = targets.nth(0).locator(".edge.end").bounding_box()
    page.mouse.move(edge["x"] + edge["width"] / 2, edge["y"] + edge["height"] / 2)
    page.mouse.down()
    page.mouse.move(edge["x"] - 40, edge["y"] + edge["height"] / 2, steps=4)
    page.mouse.up()
    shorter = float(targets.nth(0).get_attribute("data-d"))
    assert 0.1 <= shorter < before - 0.05
    assert history_state(page)["undo"] == (True, "Undo: Resize vocal target 1")

    # Chromatic arrow step A4 -> A#4, then choose C major and snap: the tie between A4 and B4
    # goes to the sung pitch (A4).
    targets.nth(0).focus()
    page.keyboard.press("ArrowUp")
    assert pitch(0) == "A♯4"
    expect(page.locator("#snapvocal")).to_be_disabled()
    page.select_option("#tunescale", "major")
    assert history_state(page)["undo"] == (True, "Undo: Set key: C major")
    page.click("#snapvocal")
    expect(page.locator("#status")).to_have_text("Moved 1 vocal target into C major.")
    assert pitch(0) == "A4"
    # In a key, arrow keys step by scale degree: E5 -> F5.
    targets.nth(2).focus()
    page.keyboard.press("ArrowUp")
    assert pitch(2) == "F5"

    # Delete removes a target; undo brings it back.
    targets.nth(2).focus()
    page.keyboard.press("Delete")
    expect(targets).to_have_count(2)
    page.click("#undo")
    expect(targets).to_have_count(3)
    assert pitch(2) == "F5"

    # The edited targets and the Keep vibrato amount are what /api/tune receives.
    page.evaluate("v => { const e = document.getElementById('vibrato'); e.value = v; e.dispatchEvent(new Event('input')); }", "40")
    expect(page.locator("#vibratolevel")).to_have_text("40%")
    sent = record_tune_requests(page)
    page.click("#tune")
    expect(page.locator("#status")).to_have_text("Pitch correction complete", timeout=60_000)
    (request,) = sent()
    notes, url = json.loads(request["notes"]), request["url"]
    assert [n["m"] for n in notes] == [69, 74, 77]
    assert notes[0]["d"] == round(shorter, 3)
    assert all(set(n) == {"m", "t", "d"} for n in notes), "confidence stays in the browser"
    assert "vibrato=0.4" in url
    expect(page.locator("#playtuned")).to_be_enabled()

    # Undo walks back through the editor's own edits.
    page.click("#undo")  # F5 step
    assert pitch(2) == "E5"

    # Deleting every target does not fall back to snapping the whole take: Tune is off
    # and the editor points to Undo / Reset until a target is back (issue #23).
    for _ in range(3):
        targets.nth(0).focus()
        page.keyboard.press("Delete")
    expect(targets).to_have_count(0)
    expect(page.locator("#vocalnoteeditor")).to_have_text(re.compile(r"^Every vocal target was removed\..*Undo.*Reset note edits"))
    expect(page.locator("#tune")).to_be_disabled()
    expect(page.locator("#vocalnoteinfo")).to_have_text(re.compile(r"^Drag a note up or down"))
    page.click("#undo")
    expect(targets).to_have_count(1)
    expect(page.locator("#tune")).to_be_enabled()
    page.click("#redo")
    expect(page.locator("#tune")).to_be_disabled()
    page.click("#resetvocal")
    expect(targets).to_have_count(3)
    expect(page.locator("#tune")).to_be_enabled()


def expect_versions(page, names):
    """The version list shows exactly these names, newest first (it renders after an IndexedDB read)."""
    rows = page.locator("#versionlist .version span")
    if names:
        expect(rows).to_have_text([re.compile("^" + re.escape(n) + " · ") for n in names])
    else:
        expect(page.locator("#versionlist")).to_have_text("No saved versions yet.")


def test_named_versions_save_list_restore_survive_reload_and_delete(studio):
    """EDIT.2: named project versions are saved, listed, restored (undoably), kept across reloads and deleted."""
    page = studio
    expect(page.locator("#versionlist")).to_have_text("No saved versions yet.")

    page.click("#demo")
    assert len(note_pitches(page)) == 8
    page.fill("#versionname", "Example groove")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Example groove")
    assert page.input_value("#versionname") == ""

    page.click("#clearnotes")
    page.click("#addnote")
    page.fill("#bpm", "150")
    page.dispatch_event("#bpm", "change")
    page.fill("#versionname", "Sparse")
    page.press("#versionname", "Enter")
    expect(page.locator("#status")).to_have_text("Saved version: Sparse")
    expect_versions(page, ["Sparse", "Example groove"])

    # A blank name is refused and saves nothing.
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Give the version a name.")
    expect_versions(page, ["Sparse", "Example groove"])

    # Restoring brings back that version's notes, drums and tempo, and is one undoable edit.
    page.click("#versionlist .version:has-text('Example groove') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Example groove")
    assert note_pitches(page) == [60, 64, 67, 69, 67, 64, 62, 60]
    assert count(page, "hitcount") == 16
    assert page.input_value("#bpm") == "100"
    assert page.get_attribute("#undo", "title") == "Undo: Restore version: Example groove"
    page.click("#undo")
    assert note_pitches(page) == [60]
    assert page.input_value("#bpm") == "150"

    # Versions survive a reload.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect_versions(page, ["Sparse", "Example groove"])
    page.click("#versionlist .version:has-text('Example groove') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Example groove")
    assert len(note_pitches(page)) == 8

    page.click("#versionlist .version:has-text('Sparse') >> text=Delete")
    expect(page.locator("#status")).to_have_text("Deleted version: Sparse")
    expect_versions(page, ["Example groove"])
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect_versions(page, ["Example groove"])


def test_access_token_kept_for_this_tab_only(studio):
    """AI.3: the access token lives in sessionStorage for the tab's lifetime; the old localStorage copy is removed."""
    page = studio
    loaded = "document.getElementById('notecount').textContent !== ''"

    # A token an older version saved in localStorage is deleted on load and not filled in.
    page.evaluate("localStorage.setItem('tandem-token', 'old-saved-token')")
    page.reload()
    page.wait_for_function(loaded)
    assert page.evaluate("localStorage.getItem('tandem-token')") is None
    assert page.input_value("#token") == ""

    # A successful connection keeps the token for this tab only, never in localStorage.
    page.fill("#token", "tab-secret")
    page.click("#connect")
    expect(page.locator("#status")).to_have_text("Backend connection succeeded")
    assert page.evaluate("sessionStorage.getItem('tandem-token')") == "tab-secret"
    assert page.evaluate("localStorage.getItem('tandem-token')") is None

    # It survives a reload of the same tab...
    page.reload()
    page.wait_for_function(loaded)
    assert page.input_value("#token") == "tab-secret"

    # ...but a new tab starts without it.
    other = page.context.new_page()
    other.goto(page.url)
    other.wait_for_function(loaded)
    assert other.input_value("#token") == ""
    other.close()

    # Clearing the field and connecting again forgets the token.
    page.fill("#token", "")
    page.click("#connect")
    page.wait_for_function("sessionStorage.getItem('tandem-token') === null")
    assert page.evaluate("localStorage.getItem('tandem-token')") is None


def test_restoring_a_version_without_tempo_or_instrument_uses_the_defaults(studio):
    """Issue #21: like Open project, Restore falls back to 100 bpm and piano when a stored version lacks them."""
    page = studio
    entry = {"id": "hand", "name": "Hand edited", "savedAt": 1, "project": {"notes": [{"m": 62, "t": 0, "d": 0.5}], "drums": []}}
    page.evaluate("e => localStorage.setItem('tandem-versions', JSON.stringify([e]))", entry)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.fill("#bpm", "150")
    page.dispatch_event("#bpm", "change")
    page.select_option("#instrument", "marimba")
    page.click("#versionlist .version:has-text('Hand edited') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Hand edited")
    assert note_pitches(page) == [62]
    assert page.input_value("#bpm") == "100"
    assert page.input_value("#instrument") == "piano"


def test_unknown_instrument_in_a_version_or_draft_is_reported(studio):
    """Review of #31: a version or draft with an unknown instrument says so instead of failing at Play."""
    page = studio
    entry = {"id": "odd", "name": "Odd", "savedAt": 1, "project": {"instrument": "kazoo", "notes": [{"m": 62, "t": 0, "d": 0.5}], "drums": []}}
    page.evaluate("e => localStorage.setItem('tandem-versions', JSON.stringify([e]))", entry)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.click("#versionlist .version:has-text('Odd') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Unsupported instrument: kazoo")
    assert page.input_value("#instrument") == "piano"

    page.evaluate("localStorage.setItem('tandem-draft', JSON.stringify({bpm: 100, instrument: 'kazoo', notes: [{m: 60, t: 0, d: 0.5}], drums: []}))")
    page.reload()
    expect(page.locator("#status")).to_have_text("The saved draft uses an unsupported instrument (kazoo). Choose an instrument before playing.")
    assert note_pitches(page) == [60], "the draft's notes are kept"
    page.select_option("#instrument", "organ")
    page.click("#play")
    expect(page.locator("#status")).to_have_text("Playing composition")


IDB_DRAFT = """() => new Promise((resolve, reject) => {
  const open = indexedDB.open('tandem');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result, get = db.transaction('kv').objectStore('kv').get('draft');
    get.onsuccess = () => { db.close(); resolve(get.result ?? null); };
    get.onerror = () => reject(get.error);
  };
})"""


def draft(page):
    """The draft as stored in IndexedDB (STORE.2a). The page starts each draft write synchronously, so this
    read, opened afterwards, waits for the latest write."""
    return page.evaluate(IDB_DRAFT)


def midi_note_ons(data, channel):
    """(absolute tick, pitch) of every note-on on a channel (0-based) of the exported MIDI file, read with mido."""
    out = []
    for track in mido.MidiFile(file=io.BytesIO(data)).tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel == channel:
                out.append((tick, msg.note))
    return out


def midi_drum_ticks(data):
    """Absolute ticks of the drum-channel (channel 10) note-ons."""
    return [t for t, _ in midi_note_ons(data, 9)]


def test_detect_tempo_and_quantize_with_swing_are_undoable(studio, tmp_path):
    """ARR.1: Detect tempo sets the bpm from the timing; Quantize snaps to a swung grid; both undo."""
    page = studio
    page.click("#quantize")
    expect(page.locator("#status")).to_have_text("Nothing to quantize yet.")
    page.click("#detecttempo")
    expect(page.locator("#status")).to_have_text("Detect tempo needs at least four notes or drum hits.")

    page.click("#demo")
    before = draft(page)
    page.click("#detecttempo")
    expect(page.locator("#status")).to_have_text("Detected tempo: 133 bpm")
    assert page.input_value("#bpm") == "133"
    assert page.get_attribute("#undo", "title") == "Undo: Detect tempo"

    page.select_option("#grid", "2")
    page.fill("#swing", "100")
    page.dispatch_event("#swing", "input")
    expect(page.locator("#swingvalue")).to_have_text("100%")
    page.click("#quantize")
    expect(page.locator("#status")).to_have_text("Quantize to 1/8 with 100% swing at 133 bpm")
    assert page.get_attribute("#undo", "title") == "Undo: Quantize to 1/8 with 100% swing"
    beat = 60 / 133
    after = draft(page)
    assert [n["m"] for n in after["notes"]] == [n["m"] for n in before["notes"]]
    for i, n in enumerate(after["notes"]):
        assert abs(n["t"] - i * beat) < 1e-5
    # Every other hit was an offbeat eighth; full swing moves it to two thirds of the beat.
    for i, h in enumerate(after["drums"]):
        want = (i // 2) * beat + (beat * 2 / 3 if i % 2 else 0)
        assert abs(h["t"] - want) < 1e-5, (i, h["t"], want)
    assert len(after["drums"]) == 16

    # The exported MIDI carries the swung timing: at 960 ticks per beat, drum hits land on 0, 640, 960, 1600...
    hits = midi_drum_ticks(download(page, "#exportmidi", tmp_path).read_bytes())
    assert hits[:4] == [0, 640, 960, 1600]
    assert len(hits) == 16

    # Quantizing again changes nothing and records no edit.
    page.click("#quantize")
    expect(page.locator("#status")).to_have_text("Already on the 1/8 grid")
    assert page.get_attribute("#undo", "title") == "Undo: Quantize to 1/8 with 100% swing"

    page.click("#undo")
    assert draft(page)["notes"] == before["notes"]
    assert draft(page)["drums"] == before["drums"]
    page.click("#undo")
    assert page.input_value("#bpm") == "100"


def test_every_instrument_plays_and_exports_its_own_sound(studio, tmp_path):
    """ARR.1b: each melody instrument plays and renders a distinct, unclipped WAV; picks survive reload."""
    page = studio
    options = page.locator("#instrument option").evaluate_all("els => els.map(e => [e.value, e.textContent])")
    assert [v for v, _ in options] == ["piano", "marimba", "strings", "bass", "chip", "organ", "guitar", "flute"]
    assert dict(options)["chip"] == "8-bit"
    page.click("#demo")
    rendered = {}
    for value, _ in options:
        page.select_option("#instrument", value)
        page.click("#play")
        expect(page.locator("#status")).to_have_text("Playing composition")
        page.click("#stop")
        wav = download(page, "#exportwav", tmp_path).read_bytes()
        with wave.open(io.BytesIO(wav)) as w:
            samples = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
        peak = np.abs(samples).max()
        assert 1000 < peak < 32000, f"{value}: peak {peak}"
        rendered[value] = samples
    # Same notes and drums, so any difference comes from the voice.
    names = list(rendered)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            n = min(len(rendered[a]), len(rendered[b]))
            diff = np.abs(rendered[a][:n] - rendered[b][:n]).mean()
            assert diff > 50, f"{a} and {b} sound the same (mean diff {diff:.1f})"
    page.select_option("#instrument", "flute")
    assert page.get_attribute("#undo", "title") == "Undo: Change instrument"
    page.reload()
    expect(page.locator("#instrument")).to_have_value("flute")


def export_every_instrument(page, tmp_path):
    """Load the example, export it once per melody instrument and return {instrument: samples}."""
    page.click("#demo")
    rendered = {}
    for value in page.locator("#instrument option").evaluate_all("els => els.map(e => e.value)"):
        page.select_option("#instrument", value)
        wav = download(page, "#exportwav", tmp_path).read_bytes()
        with wave.open(io.BytesIO(wav)) as w:
            rendered[value] = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    return rendered


def test_instruments_play_from_samples_and_fall_back_to_oscillators(browser, server_url, tmp_path):
    """SND.1: every instrument exports from its recorded samples, which sound different from its
    oscillator voice; when the samples cannot be loaded the studio says so and uses the oscillators."""
    def studio_page(block_samples):
        # Service workers are blocked so page.route sees every sample request.
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        problems = []
        page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
        # A blocked sample's 404 is reported by Chromium as a failed resource load; nothing else may error.
        page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error" and not (block_samples and "404" in msg.text) else None)
        requested = []
        page.on("request", lambda r: requested.append(r.url) if "/vendor/gm-samples-1/" in r.url else None)
        if block_samples:
            page.route("**/vendor/gm-samples-1/**", lambda route: route.fulfill(status=404, body=""))
        page.goto(server_url + "/")
        page.wait_for_function("document.getElementById('notecount').textContent !== ''")
        return context, page, problems, requested

    context, page, problems, requested = studio_page(False)
    sampled = export_every_instrument(page, tmp_path)
    page.click("#play")
    expect(page.locator("#status")).to_have_text("Playing composition")
    assert all(u.startswith(server_url + "/vendor/gm-samples-1/") for u in requested) and requested
    assert any(u.endswith("/drums/kick.mp3") for u in requested)
    assert not problems, problems
    context.close()

    context, page, problems, _ = studio_page(True)
    synthesized = export_every_instrument(page, tmp_path)
    expect(page.locator("#status")).to_contain_text("synthesized Flute, drums (samples failed to load: HTTP 404")
    page.click("#play")
    expect(page.locator("#status")).to_contain_text("Playing composition with synthesized Flute, drums")
    assert not problems, problems
    context.close()

    for name, samples in sampled.items():
        peak = np.abs(samples).max()
        assert 1000 < peak < 32000, f"{name}: sampled peak {peak}"
        osc = synthesized[name]
        n = min(len(samples), len(osc))
        diff = np.abs(samples[:n] - osc[:n]).mean()
        assert diff > 200, f"{name}: samples sound like the oscillator voice (mean diff {diff:.1f})"


def test_export_wav_does_not_hang_when_sample_requests_stall(browser, server_url, tmp_path):
    """Issue #44: Export WAV waits for the samples for a limited time, then exports with the
    oscillator voices and says so, instead of waiting for a request that never answers."""
    context = browser.new_context(service_workers="block")
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    # Never answer a sample request: the handler neither fulfills nor continues it.
    page.route("**/vendor/gm-samples-1/**", lambda route: None)
    page.goto(server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.click("#demo")
    started = time.monotonic()
    with page.expect_download(timeout=40_000) as info:
        page.click("#exportwav")
    elapsed = time.monotonic() - started
    assert 14 < elapsed < 35, elapsed
    with wave.open(str(info.value.path())) as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    assert 1000 < np.abs(samples).max() < 32000
    expect(page.locator("#status")).to_have_text("Exported the WAV with synthesized Marimba, drums (samples still loading)")
    assert not problems, problems
    context.close()


def test_opening_a_project_with_an_unknown_instrument_is_rejected(studio, tmp_path):
    page = studio
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "kazoo", "notes": [], "drums": []}))
    page.set_input_files("#projectfile", str(bad))
    expect(page.locator("#status")).to_have_text("Unsupported instrument: kazoo")
    expect(page.locator("#instrument")).to_have_value("piano")


def wav_samples(path):
    with wave.open(io.BytesIO(path.read_bytes())) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)


def test_generated_harmony_is_editable_undoable_exported_and_saved(studio, tmp_path):
    """ARR.1c: Generate builds a chord or bass part from the melody's key; it plays, exports, undoes and persists."""
    page = studio
    page.click("#clearnotes")
    page.click("#genharmony")
    expect(page.locator("#status")).to_have_text("Add or transcribe a melody before generating harmony.")

    page.click("#demo")
    no_harmony = wav_samples(download(page, "#exportwav", tmp_path))
    page.click("#genharmony")
    expect(page.locator("#status")).to_have_text("Generate chords in C major (detected): C C")
    assert page.get_attribute("#undo", "title") == "Undo: Generate chords in C major"
    expect(page.locator("#harmonycount")).to_have_text("6 notes")
    expect(page.locator("#harmonyroll .note")).to_have_count(6)
    saved = draft(page)
    assert saved["harmony_instrument"] == "piano"
    assert sorted(n["m"] for n in saved["harmony"] if n["t"] == 0) == [52, 55, 60]
    assert saved["notes"] == [{"m": m, "t": round(i * 0.45, 2), "d": 0.36} for i, m in enumerate([60, 64, 67, 69, 67, 64, 62, 60])]

    page.click("#play")
    expect(page.locator("#status")).to_have_text("Playing composition")
    page.click("#stop")

    # MIDI: harmony on channel 2, one chord per 4/4 bar (3840 ticks); the melody stays on channel 1.
    data = download(page, "#exportmidi", tmp_path).read_bytes()
    assert sorted(midi_note_ons(data, 1)) == [(0, 52), (0, 55), (0, 60), (3840, 52), (3840, 55), (3840, 60)]
    assert [p for _, p in midi_note_ons(data, 0)] == [60, 64, 67, 69, 67, 64, 62, 60]
    # WAV: the harmony is audible in the mix and the mix does not clip.
    with_harmony = wav_samples(download(page, "#exportwav", tmp_path))
    assert np.abs(with_harmony).max() < 32000
    n = min(len(no_harmony), len(with_harmony))
    assert np.abs(with_harmony[:n] - no_harmony[:n]).mean() > 50

    # Tap a harmony note to remove it; that is an undoable edit.
    page.locator("#harmonyroll .note").first.click()
    expect(page.locator("#harmonycount")).to_have_text("5 notes")
    assert page.get_attribute("#undo", "title") == "Undo: Remove harmony note"
    page.click("#undo")
    expect(page.locator("#harmonycount")).to_have_text("6 notes")

    # A chosen key and the bass style replace the part; a chosen harmony instrument is kept.
    page.select_option("#harmonyinstrument", "organ")
    assert page.get_attribute("#undo", "title") == "Undo: Change harmony instrument"
    page.select_option("#harmonystyle", "bass")
    page.select_option("#harmonykey", "9:minor")
    page.click("#genharmony")
    expect(page.locator("#status")).to_have_text("Generate bass line in A minor: C Am")
    assert [(n["m"], n["t"]) for n in draft(page)["harmony"]] == [(36, 0), (43, 1.2), (45, 2.4), (52, 3.6)]
    expect(page.locator("#harmonyinstrument")).to_have_value("organ")

    # Versions and saved projects carry the harmony part.
    page.fill("#versionname", "with bass")
    page.click("#saveversion")
    page.click("#clearharmony")
    expect(page.locator("#harmonycount")).to_have_text("0 notes")
    page.get_by_title("Restore with bass").click()
    expect(page.locator("#harmonycount")).to_have_text("4 notes")
    expect(page.locator("#harmonyinstrument")).to_have_value("organ")
    project = json.loads(download(page, "#save", tmp_path).read_text())
    assert project["harmony_instrument"] == "organ" and len(project["harmony"]) == 4

    page.reload()
    expect(page.locator("#harmonycount")).to_have_text("4 notes")
    expect(page.locator("#harmonyinstrument")).to_have_value("organ")

    # A project saved before ARR.1c opens with no harmony; an unknown harmony instrument is rejected.
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano", "notes": [{"m": 60, "t": 0, "d": 0.5}], "drums": []}))
    page.set_input_files("#projectfile", str(old))
    expect(page.locator("#status")).to_have_text("Project opened")
    expect(page.locator("#harmonycount")).to_have_text("0 notes")
    expect(page.locator("#harmonyinstrument")).to_have_value("piano")
    bad = tmp_path / "bad-harmony.json"
    bad.write_text(json.dumps({"format": "tandem-project", "version": 1, "notes": [], "drums": [], "harmony": [], "harmony_instrument": "kazoo"}))
    page.set_input_files("#projectfile", str(bad))
    expect(page.locator("#status")).to_have_text("Unsupported harmony instrument: kazoo")


def phrase_labels(page):
    return page.locator("#phraselist button").all_inner_texts()


def test_phrases_are_detected_and_moved_copied_and_transposed_with_undo(studio, tmp_path):
    """ARR.1d: the melody splits into phrases at rests; a chosen phrase moves, copies and transposes as one undoable edit."""
    page = studio
    expect(page.locator("#phraselist")).to_have_text("None yet")
    expect(page.locator("#phrasecopy")).to_be_disabled()

    # The example (100 bpm, 0.6 s beat) has no rest of a beat, so it is one phrase.
    page.click("#demo")
    assert phrase_labels(page) == ["1 · 0.0–3.5 s"]
    example = draft(page)["notes"]
    page.click("#genharmony")
    harmony = draft(page)["harmony"]
    assert harmony

    # Choose phrase 1; its notes are marked in the roll and the tools switch on.
    page.locator("#phraselist button").first.click()
    expect(page.locator("#phraselist button").first).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#melodyroll .note.inphrase")).to_have_count(8)
    expect(page.locator("#phrasecopy")).to_be_enabled()

    # Moving earlier is refused at the start of the song and records no edit.
    page.click("#phraseearlier")
    expect(page.locator("#status")).to_have_text("The phrase cannot move before the start of the song.")
    assert page.get_attribute("#undo", "title") == "Undo: Generate chords in C major"

    # Copy to the end: two 2.4 s bars later (the phrase lasts 3.51 s), as a second phrase that is now chosen.
    page.click("#phrasecopy")
    expect(page.locator("#status")).to_have_text("Copy phrase 1 to the end (2 bars later). Generate the harmony again to follow it.")
    assert phrase_labels(page) == ["1 · 0.0–3.5 s", "2 · 4.8–8.3 s"]
    expect(page.locator("#phraselist button").nth(1)).to_have_attribute("aria-pressed", "true")
    notes = draft(page)["notes"]
    assert notes[:8] == example
    assert [(n["m"], n["t"]) for n in notes[8:]] == [(n["m"], round(n["t"] + 4.8, 3)) for n in example]
    assert draft(page)["harmony"] == harmony, "phrase edits leave the harmony alone"

    # Transpose the copy up an octave and move it a beat later; phrase 1 is untouched.
    page.click("#phraseoctup")
    assert page.get_attribute("#undo", "title") == "Undo: Transpose phrase 2 up an octave"
    page.click("#phraselater")
    assert page.get_attribute("#undo", "title") == "Undo: Move phrase 2 a beat later"
    assert phrase_labels(page) == ["1 · 0.0–3.5 s", "2 · 5.4–8.9 s"]
    notes = draft(page)["notes"]
    assert notes[:8] == example
    assert [(n["m"], n["t"]) for n in notes[8:]] == [(n["m"] + 12, round(n["t"] + 5.4, 3)) for n in example]
    page.click("#phrasedown")
    assert draft(page)["notes"][8]["m"] == 71
    expect(page.locator("#status")).to_have_text("Transpose phrase 2 down 1 semitone. Generate the harmony again to follow it.")

    # Undo walks back through each phrase edit and clears the choice; redo reapplies.
    for label in ["Transpose phrase 2 down 1 semitone", "Move phrase 2 a beat later", "Transpose phrase 2 up an octave"]:
        page.click("#undo")
        expect(page.locator("#status")).to_have_text("Undid: " + label)
    expect(page.locator("#phrasecopy")).to_be_disabled()
    assert [n["m"] for n in draft(page)["notes"][8:]] == [n["m"] for n in example]
    page.click("#redo")
    assert [n["m"] for n in draft(page)["notes"][8:]] == [n["m"] + 12 for n in example]
    page.click("#undo")
    page.click("#undo")
    assert draft(page)["notes"] == example

    # A faster tempo shortens the beat, so the same 0.5 s rest splits the melody into two phrases.
    rest = tmp_path / "rest.json"
    rest.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "notes": [{"m": 60, "t": 0, "d": 0.4}, {"m": 62, "t": 0.9, "d": 0.4}], "drums": []}))
    page.set_input_files("#projectfile", str(rest))
    assert phrase_labels(page) == ["1 · 0.0–1.3 s"]
    page.fill("#bpm", "140")
    page.press("#bpm", "Enter")
    assert phrase_labels(page) == ["1 · 0.0–0.4 s", "2 · 0.9–1.3 s"]


def test_draft_and_versions_move_from_local_storage_to_indexeddb(studio):
    """STORE.2a: what an older Tandem left in localStorage is brought into IndexedDB once, then kept there."""
    page = studio
    old_draft = {"bpm": 132, "instrument": "flute", "melody_locked": True, "notes": [{"m": 65, "t": 0, "d": 0.5}], "drums": []}
    old_version = {"id": "old", "name": "From localStorage", "savedAt": 1, "project": {"bpm": 90, "notes": [{"m": 70, "t": 0, "d": 0.5}], "drums": []}}
    page.evaluate("""([d, v]) => { localStorage.setItem('tandem-draft', JSON.stringify(d));
                                    localStorage.setItem('tandem-versions', JSON.stringify([v])); }""", [old_draft, old_version])
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert note_pitches(page) == [65]
    assert page.input_value("#bpm") == "132" and page.input_value("#instrument") == "flute"
    expect_versions(page, ["From localStorage"])
    assert page.evaluate("[localStorage.getItem('tandem-draft'), localStorage.getItem('tandem-versions')]") == [None, None]
    assert draft(page)["notes"] == [{"m": 65, "t": 0, "d": 0.5}]
    expect(page.locator("#storageinfo")).not_to_have_text("")

    # From now on the draft and versions live in IndexedDB only.
    page.click("#addnote")
    page.fill("#versionname", "After the move")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: After the move")
    assert page.evaluate("[localStorage.getItem('tandem-draft'), localStorage.getItem('tandem-versions')]") == [None, None]
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert len(note_pitches(page)) == 2
    expect_versions(page, ["After the move", "From localStorage"])
    page.click("#versionlist .version:has-text('From localStorage') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: From localStorage")
    assert note_pitches(page) == [70]


def test_unreadable_old_versions_are_reported_and_kept(studio):
    """STORE.2a: versions in localStorage that cannot be parsed are left there and reported, never deleted."""
    page = studio
    page.evaluate("localStorage.setItem('tandem-versions', '{broken')")
    page.reload()
    expect(page.locator("#status")).to_contain_text("could not be read")
    assert page.evaluate("localStorage.getItem('tandem-versions')") == "{broken"
    expect_versions(page, [])


IDB_PUT = """([key, value]) => new Promise((resolve, reject) => {
  const open = indexedDB.open('tandem');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result, tx = db.transaction('kv', 'readwrite');
    tx.objectStore('kv').put(value, key);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  };
})"""


def test_unreadable_stored_versions_keep_the_draft_saving(studio):
    """STORE.2a: if the versions already in IndexedDB are unreadable, start-up reports it, keeps the old
    localStorage versions and still moves and saves the draft."""
    page = studio
    page.evaluate(IDB_PUT, ["versions", "broken"])
    old_draft = {"bpm": 120, "instrument": "piano", "melody_locked": True, "notes": [{"m": 62, "t": 0, "d": 0.5}], "drums": []}
    old_version = {"id": "old", "name": "Old", "savedAt": 1, "project": {"bpm": 90, "notes": [], "drums": []}}
    page.evaluate("""([d, v]) => { localStorage.setItem('tandem-draft', JSON.stringify(d));
                                    localStorage.setItem('tandem-versions', JSON.stringify([v])); }""", [old_draft, old_version])
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#status")).to_contain_text("unreadable")
    expect(page.locator("#versionlist")).to_contain_text("unreadable")
    assert note_pitches(page) == [62]
    assert page.evaluate("[localStorage.getItem('tandem-draft'), JSON.parse(localStorage.getItem('tandem-versions'))[0].id]") == [None, "old"]
    page.click("#addnote")
    assert len(draft(page)["notes"]) == 2
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert len(note_pitches(page)) == 2


def test_controls_are_inert_while_storage_opens(page, server_url):
    """STORE.2a: an edit made while the stored draft is still loading would be overwritten by it, so the page
    ignores input until start-up has read the draft."""
    page.add_init_script("""(() => {
      const open = IDBFactory.prototype.open;
      IDBFactory.prototype.open = function (...args) {
        if (args[0] === 'tandem' && window.__inertAtOpen === undefined) window.__inertAtOpen = document.body.inert;
        return open.apply(this, args);
      };
    })()""")
    page.goto(server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert page.evaluate("window.__inertAtOpen") is True
    assert page.evaluate("document.body.inert") is False


def test_work_survives_a_browser_restart(browser_type, browser_type_launch_args, server_url, tmp_path):
    """STORE.2a: the draft, versions and recordings are on disk in the browser profile, not only in the open page."""
    profile = tmp_path / "profile"
    problems = []

    def open_studio():
        context = browser_type.launch_persistent_context(str(profile), **browser_type_launch_args)
        page = context.pages[0] if context.pages else context.new_page()
        page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: problems.append(f"console.error: {msg.text}") if msg.type == "error" else None)
        page.goto(server_url + "/")
        page.wait_for_function("document.getElementById('notecount').textContent !== ''")
        return context, page

    context, page = open_studio()
    import_recording(page, tone_wav(tmp_path / "a.wav"))
    page.click("#polish")
    expect(page.locator("#status")).to_have_text("Vocal polished. Compare Original and Polished.")
    links = wait_for_draft_audio(page, ["original", "polished"])
    page.click("#demo")
    page.fill("#versionname", "Before restart")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Before restart")
    page.click("#clearhits")
    page.fill("#bpm", "141")
    page.dispatch_event("#bpm", "change")
    assert draft(page)["bpm"] == 141
    context.close()

    context, page = open_studio()
    try:
        expect(page.locator("#status")).to_have_text("Restored the draft and its recording.")
        for button in ["#original", "#polished", "#downloadvocal"]:
            expect(page.locator(button)).to_be_enabled()
        assert draft_audio(page) == links
        assert page.evaluate(OPFS_FILES) == sorted(link["id"] for link in links.values())
        version_audio = page.evaluate(IDB_GET, "versions")[0]["audio"]
        assert version_audio == links
        assert page.input_value("#bpm") == "141"
        assert len(note_pitches(page)) == 8 and count(page, "hitcount") == 0
        expect_versions(page, ["Before restart"])
        page.click("#versionlist .version:has-text('Before restart') >> text=Restore")
        expect(page.locator("#status")).to_have_text("Restored version: Before restart")
        assert count(page, "hitcount") == 16
    finally:
        context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_without_indexeddb_the_studio_works_and_says_nothing_is_saved(page, server_url):
    """STORE.2a: a browser with no IndexedDB still edits and plays, and says work is not being saved."""
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.add_init_script("Object.defineProperty(window, 'indexedDB', {value: undefined})")
    page.goto(server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    message = "Saving on this device is unavailable: This browser has no IndexedDB, so work cannot be saved on this device."
    expect(page.locator("#status")).to_have_text(message)
    expect(page.locator("#versionlist")).to_have_text(message)
    page.click("#demo")
    assert len(note_pitches(page)) == 8
    page.fill("#versionname", "Nowhere to go")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text(message)
    assert not errors


def test_indexeddb_store_updates_are_atomic_in_a_real_browser(studio):
    """STORE.2a: openKV against Chromium's IndexedDB: a failed update writes nothing; parallel updates all land."""
    page = studio
    result = page.evaluate("""async () => {
      const { openKV } = await import('/storage.js');
      const kv = await openKV(indexedDB, { name: 'tandem-kv-test' });
      await kv.set('list', [1]);
      let refused = null;
      try { await kv.update('list', v => { v.push(2); throw new Error('no thanks'); }); } catch (e) { refused = e.message; }
      const afterRefusal = await kv.get('list');
      await Promise.all([3, 4, 5].map(n => kv.update('list', v => [[...v, n], v.length])));
      await kv.setMany([['a', {x: 1}], ['b', 'two']]);
      const out = { refused, afterRefusal, list: await kv.get('list'), a: await kv.get('a'), b: await kv.get('b'), missing: (await kv.get('nope')) === undefined };
      kv.close();
      await new Promise(r => { const d = indexedDB.deleteDatabase('tandem-kv-test'); d.onsuccess = d.onerror = r; });
      return out;
    }""")
    assert result == {"refused": "no thanks", "afterRefusal": [1], "list": [1, 3, 4, 5], "a": {"x": 1}, "b": "two", "missing": True}


IDB_GET = """key => new Promise((resolve, reject) => {
  const open = indexedDB.open('tandem');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result, req = db.transaction('kv').objectStore('kv').get(key);
    req.onsuccess = () => { db.close(); resolve(req.result ?? null); };
    req.onerror = () => reject(req.error);
  };
})"""

OPFS_FILES = """async () => {
  const dir = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings', { create: true });
  const names = [];
  for await (const entry of dir.values()) names.push(entry.name);
  return names.sort();
}"""


def draft_audio(page):
    return page.evaluate(IDB_GET, "draft-audio") or {}


def wait_for_draft_audio(page, slots):
    page.wait_for_function(f"""async () => {{ const v = await ({IDB_GET})('draft-audio');
        return !!v && {json.dumps(sorted(slots))}.every(s => v[s]) && Object.keys(v).length === {len(slots)}; }}""")
    return draft_audio(page)


def import_recording(page, path):
    page.set_input_files("#audiofile", str(path))
    expect(page.locator("#status")).to_contain_text("Recorded")


def test_recording_and_polish_survive_a_reload(studio, tmp_path):
    """STORE.2a: the imported recording and its polished take are kept in OPFS and restored with the draft."""
    page = studio
    import_recording(page, tone_wav(tmp_path / "a.wav"))
    links = wait_for_draft_audio(page, ["original"])
    assert page.evaluate(OPFS_FILES) == [links["original"]["id"]]
    page.click("#polish")
    expect(page.locator("#status")).to_have_text("Vocal polished. Compare Original and Polished.")
    links = wait_for_draft_audio(page, ["original", "polished"])
    assert links["polished"]["type"] == "audio/wav"
    assert page.evaluate(OPFS_FILES) == sorted([links["original"]["id"], links["polished"]["id"]])

    page.reload()
    expect(page.locator("#status")).to_have_text("Restored the draft and its recording.")
    for button in ["#original", "#polished", "#downloadvocal", "#tune", "#analyze"]:
        expect(page.locator(button)).to_be_enabled()
    expect(page.locator("#playtuned")).to_be_disabled()
    # The restored polished take is the same audio that was stored.
    with page.expect_download() as info:
        page.click("#downloadvocal")
    saved = tmp_path / "restored.wav"
    info.value.save_as(saved)
    digest = page.evaluate("async b => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new Uint8Array(b)))].map(x => x.toString(16).padStart(2, '0')).join('')",
                           list(saved.read_bytes()))
    assert digest == links["polished"]["id"]


def test_versions_keep_their_own_recordings(studio, tmp_path):
    """STORE.2a: each version restores the recording saved with it; a version saved without one keeps the
    current recording; deleting a version deletes recordings nothing else links to."""
    page = studio
    page.fill("#versionname", "No audio")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: No audio")
    import_recording(page, tone_wav(tmp_path / "a.wav"))
    a = wait_for_draft_audio(page, ["original"])["original"]["id"]
    page.fill("#versionname", "Take A")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Take A")
    import_recording(page, tone_wav(tmp_path / "b.wav", seconds=0.4))
    page.wait_for_function(f"async () => (await ({IDB_GET})('draft-audio'))?.original?.id !== '{a}'")
    b = draft_audio(page)["original"]["id"]
    page.fill("#versionname", "Take B")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Take B")
    assert page.evaluate(OPFS_FILES) == sorted([a, b])

    page.click("#versionlist .version:has-text('Take A') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Take A")
    assert draft_audio(page) == {"original": {"id": a, "type": "audio/wav"}}
    page.click("#versionlist .version:has-text('No audio') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: No audio")
    expect(page.locator("#original")).to_be_enabled()
    assert draft_audio(page)["original"]["id"] == a
    page.click("#versionlist .version:has-text('Take B') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Take B")
    page.wait_for_function(f"async () => (await ({IDB_GET})('draft-audio'))?.original?.id === '{b}'")

    # A is linked only from Take A now, so deleting Take A deletes its file.
    page.click("#versionlist .version:has-text('Take A') >> text=Delete")
    expect(page.locator("#status")).to_have_text("Deleted version: Take A")
    page.wait_for_function(f"async () => JSON.stringify(await ({OPFS_FILES})()) === '{json.dumps([b])}'")
    page.reload()
    expect(page.locator("#status")).to_have_text("Restored the draft and its recording.")
    assert page.evaluate(OPFS_FILES) == [b]


def test_a_missing_recording_is_reported(studio, tmp_path):
    """STORE.2a: if a linked recording has gone from the device, start-up says so and keeps the project."""
    page = studio
    import_recording(page, tone_wav(tmp_path / "a.wav"))
    a = wait_for_draft_audio(page, ["original"])["original"]["id"]
    page.evaluate(f"""async () => {{ const dir = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
                                     await dir.removeEntry('{a}'); }}""")
    page.reload()
    expect(page.locator("#status")).to_have_text("Restored the draft. The original recording is no longer on this device.")
    expect(page.locator("#original")).to_be_disabled()


def test_full_storage_is_reported_when_keeping_a_recording(studio, tmp_path):
    """STORE.2a: a quota error while writing the recording is reported, and the recording still plays."""
    page = studio
    page.add_init_script("""FileSystemWritableFileStream.prototype.write = function () {
      return Promise.reject(new DOMException('full', 'QuotaExceededError'));
    };""")
    page.reload()
    page.wait_for_function("!document.body.inert")
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "a.wav")))
    expect(page.locator("#status")).to_have_text("Could not keep the recording on this device: Browser storage is full. Delete older versions or recordings, then try again.")
    expect(page.locator("#original")).to_be_enabled()
    assert draft_audio(page) == {}
    assert page.evaluate(OPFS_FILES) == []


def test_without_opfs_recordings_work_but_are_not_kept(studio, tmp_path):
    """STORE.2a: in a browser without OPFS the studio still records, and says the recording will not be kept."""
    page = studio
    page.add_init_script("delete StorageManager.prototype.getDirectory;")
    page.reload()
    message = "Recordings cannot be kept on this device in this browser, so a recording lasts only until the page is closed."
    expect(page.locator("#status")).to_have_text(message)
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "a.wav")))
    expect(page.locator("#status")).to_contain_text("Recorded")
    expect(page.locator("#status")).to_contain_text(message)
    expect(page.locator("#original")).to_be_enabled()


STEMS = ["mix.wav", "melody.wav", "harmony.wav", "drums.wav", "vocal-original.wav", "vocal-polished.wav"]


def test_stems_line_up_with_the_mix_and_the_midi_has_a_track_per_part(studio, tmp_path):
    """EXP.1: Export stems gives one WAV per part and recorded vocal, all 44.1 kHz from zero and the same
    length, whose parts sum to the mixed WAV; the MIDI file has a named track per part, tempo and key."""
    page = studio
    page.click("#exportstems")
    expect(page.locator("#status")).to_have_text("Stem export failed: Nothing to export yet: add notes or drums, or record a take.")

    page.click("#demo")
    page.click("#genharmony")
    expect(page.locator("#status")).to_have_text("Generate chords in C major (detected): C C")
    take = tone_wav(tmp_path / "take.wav")
    import_recording(page, take)
    page.click("#polish")
    expect(page.locator("#status")).to_have_text("Vocal polished. Compare Original and Polished.")

    path = download(page, "#exportstems", tmp_path)
    assert path.name == "tandem-stems.zip"
    expect(page.locator("#status")).to_have_text(
        "Exported 5 stems (melody, harmony, drums, original vocal, polished vocal) and the MIDI file")
    stems = {}
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == STEMS + ["tandem.mid"]
        for name in STEMS:
            with wave.open(io.BytesIO(z.read(name))) as w:
                assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100), name
                stems[name] = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
        midi_in_zip = z.read("tandem.mid")
    frames = {len(v) for v in stems.values()}
    assert len(frames) == 1, "every stem is the same length"
    n = frames.pop()
    parts = stems["melody.wav"] + stems["harmony.wav"] + stems["drums.wav"]
    for name in ["melody.wav", "harmony.wav", "drums.wav"]:
        assert 1000 < np.abs(stems[name]).max() < 32000, name
    # The parts add up to the mix within 16-bit rounding (one step per stem); vocals are not in the mix.
    assert np.abs(stems["mix.wav"] - parts).max() <= 2
    # Export WAV is that same mix: as long, and equal to within one 16-bit step (two renders of the same
    # graph in Chromium differ by float noise at a handful of samples).
    mix = wav_samples(download(page, "#exportwav", tmp_path))
    assert len(mix) == n
    assert np.abs(mix - stems["mix.wav"]).max() <= 1

    # Everything starts at zero: the first note, kick and chord sound within the first 10 ms.
    for name in ["melody.wav", "harmony.wav", "drums.wav"]:
        assert np.argmax(np.abs(stems[name]) > 100) < 441, name
    # The vocal is the take resampled from 48 kHz, from zero: tone, silence from 0.6 s to 0.75 s, tone.
    vocal = stems["vocal-original.wav"]
    with wave.open(str(take)) as w:
        source = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    assert np.abs(vocal[int(2.26 * 44100):]).max() == 0, "silence after the take, to the common length"
    assert np.abs(vocal[:441]).max() > 1000
    assert np.abs(vocal[int(0.61 * 44100):int(0.74 * 44100)]).max() < 200
    expected = np.interp(np.arange(int(2.25 * 44100)) / 44100, np.arange(len(source)) / 48000, source)
    got = vocal[:len(expected)]
    assert np.corrcoef(expected, got)[0, 1] > 0.99
    assert np.abs(stems["vocal-polished.wav"]).max() > 1000

    # MIDI, read with a standard parser: type 1, 960 ticks per beat, tempo, 4/4, key and a named track per part.
    data = download(page, "#exportmidi", tmp_path).read_bytes()
    assert data == midi_in_zip
    mid = mido.MidiFile(file=io.BytesIO(data))
    assert mid.type == 1 and mid.ticks_per_beat == 960
    assert [t.name for t in mid.tracks] == ["Tandem", "Melody", "Harmony", "Drums"]
    meta = {m.type: m for m in mid.tracks[0] if m.is_meta}
    assert meta["set_tempo"].tempo == mido.bpm2tempo(100)
    assert (meta["time_signature"].numerator, meta["time_signature"].denominator) == (4, 4)
    assert meta["key_signature"].key == "C"
    # 100 bpm: a 0.45 s step is 720 ticks, a 0.225 s drum step 360 ticks.
    assert midi_note_ons(data, 0) == [(i * 720, m) for i, m in enumerate([60, 64, 67, 69, 67, 64, 62, 60])]
    assert sorted(midi_note_ons(data, 1)) == [(0, 52), (0, 55), (0, 60), (3840, 52), (3840, 55), (3840, 60)]
    assert midi_drum_ticks(data) == [i * 360 for i in range(16)]
    programs = [[(m.channel, m.program) for m in t if m.type == "program_change"] for t in mid.tracks]
    assert programs == [[], [(0, 12)], [(1, 0)], []], "marimba melody, piano harmony, General MIDI drums"
    assert {m.channel for m in mid.tracks[3] if m.type == "note_on"} == {9}

    # A key chosen for the harmony is the key written into the file.
    page.select_option("#harmonykey", "9:minor")
    minor = mido.MidiFile(file=io.BytesIO(download(page, "#exportmidi", tmp_path).read_bytes()))
    assert [m.key for m in minor.tracks[0] if m.type == "key_signature"] == ["Am"]


def test_export_musicxml_writes_the_melody_and_harmony_as_sheet_music(studio, tmp_path):
    """EXP.2: Export MusicXML downloads a MusicXML 4.0 score that a notation reader (music21) reads back
    as the example song: the melody on the sixteenth grid at its tempo, the chords, 4/4 and the key."""
    import music21
    page = studio
    page.click("#demo")
    page.click("#genharmony")
    target = download(page, "#exportmusicxml", tmp_path)
    assert target.name == "tandem.musicxml"
    expect(page.locator("#status")).to_have_text("Exported the MusicXML score")
    score = music21.converter.parse(str(target), format="musicxml").stripTies()
    melody, harmony = score.parts
    assert (melody.partName, harmony.partName) == ("Melody", "Harmony")
    # 100 bpm: each 0.45 s step of the example is three sixteenths (0.75 of a quarter).
    notes = [(n.pitch.midi, float(n.offset), float(n.quarterLength)) for n in melody.flatten().notes]
    assert notes == [(m, i * 0.75, 0.75) for i, m in enumerate([60, 64, 67, 69, 67, 64, 62, 60])]
    chords = [(sorted(p.midi for p in c.pitches), float(c.offset)) for c in harmony.flatten().notes]
    assert chords == [([52, 55, 60], 0.0), ([52, 55, 60], 4.0)]
    key = melody.flatten().getElementsByClass(music21.key.Key).first()
    assert (key.sharps, key.mode) == (0, "major")
    assert score.flatten().getElementsByClass(music21.tempo.MetronomeMark).first().number == 100

    # The key chosen for the harmony is the key written into the score, as for the MIDI file.
    page.select_option("#harmonykey", "9:minor")
    minor = music21.converter.parse(str(download(page, "#exportmusicxml", tmp_path)), format="musicxml")
    key = minor.parts[0].flatten().getElementsByClass(music21.key.Key).first()
    assert (key.sharps, key.mode) == (0, "minor")

    # With no melody or harmony there is nothing to write, and the studio says so instead of downloading.
    page.click("#clearnotes")
    page.click("#clearharmony")
    page.click("#exportmusicxml")
    expect(page.locator("#status")).to_contain_text("Nothing to write as notation yet")


def test_export_dawproject_writes_note_and_audio_tracks_a_daw_can_open(studio, tmp_path):
    """EXP.3: Export DAWproject downloads a .dawproject zip whose project.xml and metadata.xml are valid
    against the DAWproject 1.0 schemas, with the parts as note tracks in beats at the project tempo and
    every recording as a 44.1 kHz WAV on an audio track from zero; only the most finished take plays."""
    from pathlib import Path
    from lxml import etree
    xsd = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "dawproject-1.0"
    page = studio
    page.click("#exportdawproject")
    expect(page.locator("#status")).to_have_text("DAWproject export failed: Nothing to export yet: add notes or drums, or record a take.")

    page.click("#demo")
    page.click("#genharmony")
    import_recording(page, tone_wav(tmp_path / "take.wav"))
    page.click("#polish")
    expect(page.locator("#status")).to_have_text("Vocal polished. Compare Original and Polished.")
    page.select_option("#harmonykey", "9:minor")
    path = download(page, "#exportdawproject", tmp_path)
    assert path.name == "tandem.dawproject"
    expect(page.locator("#status")).to_have_text("Exported the DAWproject file with 2 audio tracks")

    with zipfile.ZipFile(path) as z:
        assert z.namelist() == ["project.xml", "metadata.xml", "audio/vocal-polished.wav", "audio/vocal-original.wav"]
        project = etree.fromstring(z.read("project.xml"))
        metadata = etree.fromstring(z.read("metadata.xml"))
        wavs = {}
        for name in z.namelist()[2:]:
            with wave.open(io.BytesIO(z.read(name))) as w:
                assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100), name
                wavs[name] = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    for name, doc in (("Project.xsd", project), ("MetaData.xsd", metadata)):
        schema = etree.XMLSchema(etree.parse(str(xsd / name)))
        assert schema.validate(doc), schema.error_log.filter_from_errors()
    assert metadata.findtext("Comment") == "Key: A minor"
    assert project.find("Transport/Tempo").get("value") == "100"

    lanes = {l.get("track"): l for l in project.iter("Lanes") if l.get("track")}
    tracks = {t.get("name"): (t, lanes[t.get("id")]) for t in project.find("Structure").iter("Track")}
    assert list(tracks) == ["Melody", "Harmony", "Drums", "Vocal (polished)", "Vocal (original)", "Master"]
    # 100 bpm: the example's 0.45 s steps are 0.75 of a beat.
    melody = [(int(n.get("key")), float(n.get("time"))) for n in tracks["Melody"][1].iter("Note")]
    assert melody == [(m, pytest.approx(i * 0.75)) for i, m in enumerate([60, 64, 67, 69, 67, 64, 62, 60])]
    assert sorted(int(n.get("key")) for n in tracks["Harmony"][1].iter("Note")) == [52, 52, 55, 55, 60, 60]
    assert {n.get("key") for n in tracks["Drums"][1].iter("Note")} <= {"36", "38", "42"}
    for name, muted, file in (("Vocal (polished)", "false", "audio/vocal-polished.wav"), ("Vocal (original)", "true", "audio/vocal-original.wav")):
        track, lane = tracks[name]
        assert track.find("Channel/Mute").get("value") == muted
        audio = lane.find("Clips/Clip/Warps/Audio")
        assert audio.find("File").get("path") == file
        # The clip's length is its WAV's, and the take is there from zero: it is not silent, it sounds in
        # the first 10 ms, and its first 0.5 s is the imported take's first tone.
        samples = wavs[file]
        assert float(audio.get("duration")) == pytest.approx(len(samples) / 44100, abs=1e-6)
        assert float(lane.find("Clips/Clip").get("time")) == 0
        assert np.abs(samples).max() > 1000, name
        assert np.argmax(np.abs(samples) > 100) < 441, name
        first = samples[441:22050] * np.hanning(22050 - 441)
        peak_hz = np.argmax(np.abs(np.fft.rfft(first))) * 44100 / len(first)
        assert peak_hz == pytest.approx(TONES[0][0], abs=5), name


def test_an_edit_during_the_stem_export_does_not_change_what_is_exported(studio, tmp_path):
    """#62 review: the export works on the project as it was when Export stems was pressed, so clearing
    the melody and the drums while it renders leaves the stems, the mix and the MIDI agreeing on the old
    project. The first part's render is held until both edits are made, so the drums render after them."""
    page = studio
    page.click("#demo")
    page.evaluate("""() => {
        const start = OfflineAudioContext.prototype.startRendering;
        window.renderHeld = false;
        OfflineAudioContext.prototype.startRendering = function () {
            if (window.releaseRender || this.length === 1) return start.call(this);
            window.renderHeld = true;
            return new Promise(resolve => { window.releaseRender = () => resolve(start.call(this)); });
        };
    }""")
    with page.expect_download() as info:
        page.click("#exportstems")
        page.wait_for_function("window.renderHeld")
        page.click("#clearnotes")
        page.click("#clearhits")
        page.evaluate("window.releaseRender()")
    assert count(page, "notecount") == 0
    path = tmp_path / "stems.zip"
    info.value.save_as(path)
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == ["mix.wav", "melody.wav", "drums.wav", "tandem.mid"]
        for stem in ("melody.wav", "drums.wav"):
            with wave.open(io.BytesIO(z.read(stem))) as w:
                assert np.abs(np.frombuffer(w.readframes(w.getnframes()), "<i2")).max() > 1000, stem
        data = z.read("tandem.mid")
    assert [p for _, p in midi_note_ons(data, 0)] == [60, 64, 67, 69, 67, 64, 62, 60]
