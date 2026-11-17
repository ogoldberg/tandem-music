"""PRACTICE.1: practise a stretch of the song in a real Chromium. Chromium's fake microphone sings A4 40 cents sharp
without a break (a WAV file looped): Practise goes round the melody with the song, scores every pass, and marks each
note on the melody roll: the A4 notes 40 cents sharp, the C5 note far flat. Stop keeps the marks, Keep pass makes the
last pass a take, an edit to the melody clears the marks, and the project is unchanged by practising itself."""
import json
import re
import os
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_pitchguide import open_page, write_tone
from test_studio import IDB_DRAFT, wait_until

SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())
SHARP = 40
TONE_HZ = 440 * 2 ** (SHARP / 1200)
NOTES = [{"m": 69, "t": 0.5, "d": 0.5}, {"m": 69, "t": 1.0, "d": 0.5}, {"m": 72, "t": 1.5, "d": 0.5}, {"m": 69, "t": 2.0, "d": 0.5}]


@pytest.fixture(scope="module")
def sharp_browser(playwright, tmp_path_factory):
    """A Chromium of its own whose fake microphone sings A4 40 cents sharp."""
    wav = tmp_path_factory.mktemp("sharp") / "sharp.wav"
    write_tone(wav, hz=TONE_HZ)
    browser = playwright.chromium.launch(args=[
        "--enable-unsafe-swiftshader", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        f"--use-file-for-fake-audio-capture={wav}"])
    yield browser
    browser.close()


@pytest.fixture
def practice_page(sharp_browser, server_url):
    page, problems = open_page(sharp_browser, server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    yield page
    page.context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def with_melody(page, notes=NOTES):
    page.evaluate("notes => localStorage.setItem('tandem-draft', JSON.stringify({bpm: 120, instrument: 'piano', notes, drums: []}))", notes)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    wait_until(page, f"async () => {{ const d = await ({IDB_DRAFT})(); return !!d && d.notes?.length === {len(notes)}; }}", "the draft is stored")


def marks(page):
    return page.eval_on_selector_all("#melodyroll .note", "els => els.map(b => [b.dataset.practice ?? null, b.dataset.cents ?? null, b.querySelector('.prmark')?.textContent ?? null])")


def test_practise_scores_each_pass_marks_the_roll_and_leaves_the_project_alone(practice_page):
    page = practice_page
    with_melody(page)
    page.uncheck("#countin")
    before = page.evaluate(IDB_DRAFT)
    expect(page.locator("#practicebar")).to_be_hidden()

    page.click("#practice")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#practicestop")).to_be_visible()
    expect(page.locator("#status")).to_contain_text("Sing the melody (0.5 to 2.5 s)", timeout=8000)
    # Two whole passes of the 2 s stretch.
    page.wait_for_function("(document.getElementById('practiceinfo').dataset.passes | 0) >= 2", timeout=20000)
    data = json.loads(page.locator("#practiceinfo").get_attribute("data-pass"))
    assert data["from"] == 0.5 and data["to"] == 2.5
    scores = {s["i"]: s for s in data["scores"]}
    assert sorted(scores) == [0, 1, 2, 3]
    for i in (0, 1, 3):
        assert scores[i]["sung"] and scores[i]["pitch"] == "sharp", scores[i]
        assert abs(scores[i]["cents"] - SHARP) <= 8, scores[i]
        assert scores[i]["spread"] <= 5, scores[i]
    # C5 is sung as A4: three semitones flat, and never near enough to settle or come in.
    assert scores[2]["pitch"] == "flat" and abs(scores[2]["cents"] + 300 - SHARP) <= 10, scores[2]
    assert scores[2]["settle"] is None and scores[2]["timing"] is None
    # The first note comes in with the pass; the A4 after it is tied over from the one before, so it has no onset.
    assert scores[0]["timing"] == "on", scores[0]
    assert scores[1]["onset"] is None
    assert data["summary"] == {"notes": 4, "sung": 4, "inTune": 0, "missed": 0, "onTime": 1,
                               "worst": {"i": 2, "m": 72, "cents": scores[2]["cents"]}}
    expect(page.locator("#practiceinfo")).to_contain_text("0 of 4 notes in tune; furthest off: C5, 2")

    m = marks(page)
    assert [x[0] for x in m] == ["sharp", "sharp", "flat", "sharp"]
    assert all(x[2].startswith("+") for k, x in enumerate(m) if k != 2) and m[2][2].startswith("−")
    title = page.locator("#melodyroll .note").nth(0).get_attribute("title")
    assert "cents sharp, on time" in title, title
    page.locator("#melodyroll").screenshot(path=str(SHOTS / "practice-roll.png"))
    page.screenshot(path=str(SHOTS / "practice-studio.png"))

    # Stop: the run ends, the last pass's marks stay.
    passes = int(page.locator("#practiceinfo").get_attribute("data-passes"))
    page.click("#practicestop")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#status")).to_contain_text("Stopped practising after")
    expect(page.locator("#practicestop")).to_be_hidden()
    expect(page.locator("#practicekeep")).to_be_enabled()
    assert int(page.locator("#practiceinfo").get_attribute("data-passes")) >= passes
    assert [x[0] for x in marks(page)] == ["sharp", "sharp", "flat", "sharp"]
    # Practising changed nothing in the project.
    assert page.evaluate(IDB_DRAFT) == before

    # Keep pass: the last pass becomes the take, from the song's zero (silence up to the stretch's start).
    page.click("#practicekeep")
    expect(page.locator("#status")).to_have_text("Kept the last pass as a take.", timeout=10000)
    expect(page.locator("#original")).to_be_enabled()
    seconds = page.evaluate("""async () => { const r = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
      let newest = null; for await (const e of r.values()) { const f = await e.getFile(); if (!newest || f.lastModified >= newest.lastModified) newest = f; }
      const b = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(await newest.arrayBuffer());
      const x = b.getChannelData(0), lead = Math.floor(0.45 * b.sampleRate); let quiet = 0, loud = 0;
      for (let i = 0; i < lead; i++) quiet = Math.max(quiet, Math.abs(x[i]));
      for (let i = Math.ceil(0.6 * b.sampleRate); i < x.length; i++) loud = Math.max(loud, Math.abs(x[i]));
      return {seconds: b.duration, quiet, loud}; }""")
    assert abs(seconds["seconds"] - 2.5) < 0.01, seconds
    assert seconds["quiet"] == 0 and seconds["loud"] > 0.05, seconds

    # An edit to the melody clears the marks.
    page.click("#addnote")
    assert all(x[0] is None for x in marks(page))
    expect(page.locator("#practicebar")).to_be_hidden()
    expect(page.locator("#practiceinfo")).to_have_text("")


def test_play_stops_practising_and_there_is_nothing_to_practise_without_a_melody(practice_page):
    page = practice_page
    page.click("#practice")
    expect(page.locator("#status")).to_have_text("Practice needs a melody: record or write one first.")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")

    with_melody(page)
    page.uncheck("#countin")
    page.click("#practice")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "true")
    page.click("#play")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#practicestop")).to_be_hidden()


# The microphone answers only when the test opens the gate, so Practise is held while it starts.
GATE_MIC = """() => { const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices); let open;
  window.__micGate = new Promise(r => { open = r; }); window.__openMic = () => open();
  navigator.mediaDevices.getUserMedia = async c => { await window.__micGate; return real(c); }; }"""


@pytest.mark.parametrize("control", ["#play", "#stop", "#calibrate"])
def test_play_stop_and_measure_cancel_a_practice_still_starting(practice_page, control):
    page = practice_page
    with_melody(page)
    page.uncheck("#countin")
    page.evaluate(GATE_MIC)
    page.click("#practice")
    # Still waiting for the microphone: nothing has started yet.
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")
    page.click(control)
    page.evaluate("() => window.__openMic()")
    if control == "#calibrate":
        expect(page.locator("#status")).to_contain_text(re.compile("Measured the delay|Could not measure the delay"), timeout=20000)
    # Practice never starts over the control: give a start that was not cancelled time to get going.
    page.wait_for_timeout(1500)
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#practicestop")).to_be_hidden()
    expect(page.locator("#status")).not_to_contain_text("Sing the melody")
    expect(page.locator("#status")).not_to_contain_text("Mic unavailable")
    # The cancelled start leaves nothing behind: Practise starts again.
    page.click("#stop")
    page.click("#practice")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "true", timeout=8000)
    page.click("#practicestop")


def test_practise_a_marked_section_scores_only_its_notes(practice_page):
    from test_playhead import drag_loop, loop_bounds
    page = practice_page
    with_melody(page)
    page.uncheck("#countin")
    drag_loop(page, 1.0, 2.0)
    expect(page.locator("#loop")).to_have_attribute("aria-pressed", "true")
    start, end = loop_bounds(page)
    assert 0.9 <= start <= 1.1 and 1.9 <= end <= 2.1, (start, end)
    page.click("#practice")
    expect(page.locator("#status")).to_contain_text(f"Sing the marked section ({start:.1f} to {end:.1f} s)", timeout=8000)
    page.wait_for_function("(document.getElementById('practiceinfo').dataset.passes | 0) >= 2", timeout=20000)
    data = json.loads(page.locator("#practiceinfo").get_attribute("data-pass"))
    assert abs(data["from"] - start) < 0.01 and abs(data["to"] - end) < 0.01, data
    inside = [i for i, n in enumerate(NOTES) if data["from"] <= n["t"] < data["to"]]
    assert inside == [1, 2], inside
    scores = {s["i"]: s for s in data["scores"]}
    assert sorted(scores) == inside, scores
    assert scores[1]["pitch"] == "sharp" and abs(scores[1]["cents"] - SHARP) <= 8, scores[1]
    assert scores[2]["pitch"] == "flat", scores[2]
    assert data["summary"]["notes"] == 2, data["summary"]
    # Only the section's notes are marked on the roll.
    assert [x[0] for x in marks(page)] == [None, "sharp", "flat", None]
    page.click("#practicestop")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")


IDB_PRACTICE = IDB_DRAFT.replace("get('draft')", "get('practice')")


def history(page):
    return json.loads(page.locator("#practiceprogress").get_attribute("data-history") or "[]")


def test_your_range_and_a_stretchs_progress_are_kept_on_the_device_across_a_reload(practice_page):
    """PRACTICE.2: each pass adds its held notes to the range and its scores to the stretch's day, kept in IndexedDB
    beside the draft (never in the project); both are there after a reload, a recorded take adds to the range, and
    Forget range and progress clears them."""
    page = practice_page
    with_melody(page)
    page.uncheck("#countin")
    before = page.evaluate(IDB_DRAFT)
    expect(page.locator("#rangebox")).to_be_hidden()

    page.click("#practice")
    expect(page.locator("#practiceprogress")).to_have_text("First time practising this stretch.", timeout=8000)
    page.wait_for_function("JSON.parse(document.getElementById('practiceprogress').dataset.history || '[]').reduce((n, d) => n + d.passes, 0) >= 2", timeout=20000)
    page.click("#practicestop")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")
    page.wait_for_timeout(300)
    days = history(page)
    assert len(days) == 1 and days[0]["passes"] >= 2, days
    passes = days[0]["passes"]
    # A4 40 cents sharp, held the whole time: the range is A4 alone; no pass had a note in tune.
    assert days[0]["notes"] == 4 * passes and days[0]["inTune"] == 0 and days[0]["best"] == 0, days
    expect(page.locator("#practiceprogress")).to_have_text(f"Best pass today: 0 of 4 in tune ({passes} passes).")
    expect(page.locator("#rangebox")).to_be_visible()
    rng = json.loads(page.locator("#vocalrange").get_attribute("data-range"))
    assert rng == {"low": 69, "high": 69, "passes": passes, "takes": 0}, rng
    expect(page.locator("#vocalrange")).to_have_text(f"Your range: A4 only, held steadily over {passes} passes.")
    page.screenshot(path=str(SHOTS / "practice-progress.png"))
    # Kept on the device, not in the project.
    stored = page.evaluate(IDB_PRACTICE)
    assert stored["version"] == 1 and stored["range"]["held"]["69"] > 2 and len(stored["phrases"]) == 1, stored
    assert page.evaluate(IDB_DRAFT) == before

    # After a reload the range is shown at once, and practising the same stretch picks up its history.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#vocalrange")).to_have_text(f"Your range: A4 only, held steadily over {passes} passes.")
    page.uncheck("#countin")
    page.click("#practice")
    expect(page.locator("#practiceprogress")).to_have_text(f"Best pass today: 0 of 4 in tune ({passes} passes).", timeout=8000)
    page.wait_for_function(f"JSON.parse(document.getElementById('practiceprogress').dataset.history || '[]').reduce((n, d) => n + d.passes, 0) > {passes}", timeout=20000)
    page.click("#practicestop")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")

    # A take recorded with Record adds its held notes to the range.
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    page.wait_for_timeout(1500)
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    page.wait_for_function("JSON.parse(document.getElementById('vocalrange').dataset.range || '{}').takes === 1", timeout=10000)
    expect(page.locator("#vocalrange")).to_contain_text("and 1 take.")

    # Forget clears the range and every stretch's history.
    page.click("#practiceforget")
    expect(page.locator("#status")).to_have_text("Forgot your range and progress on this device.")
    expect(page.locator("#rangebox")).to_be_hidden()
    assert page.evaluate(IDB_PRACTICE) == {"version": 1, "range": {"held": {}, "passes": 0, "takes": 0}, "phrases": []}
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#rangebox")).to_be_hidden()


SEED_PRACTICE = """record => new Promise((resolve, reject) => {
  const open = indexedDB.open('tandem');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result, tx = db.transaction('kv', 'readwrite');
    tx.objectStore('kv').put(record, 'practice');
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  };
})"""


def test_a_warm_up_in_your_range_is_added_after_the_song_and_practised(practice_page):
    """PRACTICE.3: with no range kept yet a warm-up is refused; with D4 to A5 held, the D major arpeggio goes into the
    melody a bar after the song's end (6 s at 120 bpm, the song ending at 2.5 s) as one edit, inside the range and on the
    beats, the Timeline marks it, Practise sings it and scores its notes, and Undo takes it out."""
    page = practice_page
    with_melody(page)
    page.uncheck("#countin")
    page.evaluate("() => { const k = document.getElementById('harmonykey'); k.value = '2:major'; k.dispatchEvent(new Event('change')); }")
    page.select_option("#warmup", "arpeggio")
    page.click("#addwarmup")
    expect(page.locator("#status")).to_contain_text("Your range is not known yet")
    assert page.locator("#notecount").text_content().startswith("4 ")

    page.evaluate(SEED_PRACTICE, {"version": 1, "range": {"held": {"62": 1, "81": 1}, "passes": 2, "takes": 0}, "phrases": []})
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#vocalrange")).to_have_text("Your range: D4 to A5, held steadily over 2 passes.")
    page.uncheck("#countin")
    page.evaluate("() => { const k = document.getElementById('harmonykey'); k.value = '2:major'; k.dispatchEvent(new Event('change')); }")
    page.select_option("#warmup", "arpeggio")
    page.click("#addwarmup")
    expect(page.locator("#status")).to_contain_text("Arpeggio added from 6.0 to 10.0 s (D4 to D5)")
    expect(page.locator("#undo")).to_have_attribute("title", re.compile("Add warm-up: Arpeggio"))
    draft = lambda: page.evaluate(IDB_DRAFT)
    wait_until(page, f"async () => (await ({IDB_DRAFT})())?.notes?.length === 11", "the warm-up is in the draft")
    notes = draft()["notes"]
    assert notes[:4] == NOTES, notes[:4]
    assert notes[4:] == [{"m": m, "t": 6 + 0.5 * i, "d": 1 if i == 6 else 0.5} for i, m in enumerate([62, 66, 69, 74, 69, 66, 62])], notes[4:]
    from test_playhead import loop_bounds
    expect(page.locator("#loop")).to_have_attribute("aria-pressed", "true")
    assert loop_bounds(page) == (6.0, 10.0), loop_bounds(page)
    page.screenshot(path=str(SHOTS / "practice-warmup.png"))

    page.click("#practice")
    expect(page.locator("#status")).to_contain_text("Sing the marked section (6.0 to 10.0 s)", timeout=8000)
    page.wait_for_function("(document.getElementById('practiceinfo').dataset.passes | 0) >= 1", timeout=20000)
    data = json.loads(page.locator("#practiceinfo").get_attribute("data-pass"))
    scores = {s["i"]: s for s in data["scores"]}
    assert sorted(scores) == list(range(4, 11)), scores
    # The fake microphone sings A4 40 cents sharp: the two A4s of the arpeggio read sharp by about that.
    for i in (6, 8):
        assert scores[i]["pitch"] == "sharp" and abs(scores[i]["cents"] - SHARP) <= 8, scores[i]
    page.click("#practicestop")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")

    page.click("#undo")
    wait_until(page, f"async () => (await ({IDB_DRAFT})())?.notes?.length === 4", "Undo takes the warm-up out")
