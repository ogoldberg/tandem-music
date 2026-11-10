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


def version_names(page):
    return [t.split(" · ")[0] for t in page.locator("#versionlist .version span").all_text_contents()]


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
    assert version_names(page) == ["Sparse", "Example groove"]

    # A blank name is refused and saves nothing.
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Give the version a name.")
    assert version_names(page) == ["Sparse", "Example groove"]

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
    assert version_names(page) == ["Sparse", "Example groove"]
    page.click("#versionlist .version:has-text('Example groove') >> text=Restore")
    assert len(note_pitches(page)) == 8

    page.click("#versionlist .version:has-text('Sparse') >> text=Delete")
    expect(page.locator("#status")).to_have_text("Deleted version: Sparse")
    assert version_names(page) == ["Example groove"]
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert version_names(page) == ["Example groove"]


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


def draft(page):
    return page.evaluate("JSON.parse(localStorage.getItem('tandem-draft'))")


def midi_drum_ticks(data):
    """Absolute ticks of the drum-channel note-ons in Tandem's single-track MIDI export."""
    assert data[:4] == b"MThd" and data[14:18] == b"MTrk"
    i, end, tick, out = 22, 22 + int.from_bytes(data[18:22], "big"), 0, []
    while i < end:
        delta = 0
        while True:
            b = data[i]; i += 1
            delta = (delta << 7) | (b & 127)
            if b < 128:
                break
        tick += delta
        status = data[i]
        if status == 255:
            i += 3 + data[i + 2]
        else:
            if status == 153:
                out.append(tick)
            i += 3
    return out


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


def test_opening_a_project_with_an_unknown_instrument_is_rejected(studio, tmp_path):
    page = studio
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "kazoo", "notes": [], "drums": []}))
    page.set_input_files("#projectfile", str(bad))
    expect(page.locator("#status")).to_have_text("Unsupported instrument: kazoo")
    expect(page.locator("#instrument")).to_have_value("piano")
