"""PRACTICE.1: practise a stretch of the song in a real Chromium. Chromium's fake microphone sings A4 40 cents sharp
without a break (a WAV file looped): Practise goes round the melody with the song, scores every pass, and marks each
note on the melody roll: the A4 notes 40 cents sharp, the C5 note far flat. Stop keeps the marks, Keep pass makes the
last pass a take, an edit to the melody clears the marks, and the project is unchanged by practising itself."""
import json
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
