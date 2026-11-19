"""FIX.4: Find the speed keeps the tempo a take was sung to. Chromium's fake microphone plays a hit every second: at the
project's 90 bpm that is a dotted quarter, which fits 60 bpm better than 90 (the 3:2 trap). Recorded after the count-in,
Detect tempo keeps 90; the same hits imported, or recorded with nothing heard, read as 60."""
import re

import pytest
from playwright.sync_api import expect

from test_genre import beat_wav
from test_pitchguide import open_page
from test_studio import wait_until

HITS = [0.3 + i for i in range(12)]


@pytest.fixture(scope="module")
def hits_wav(tmp_path_factory):
    return beat_wav(tmp_path_factory.mktemp("hits") / "hits.wav", HITS)


@pytest.fixture(scope="module")
def hits_browser(playwright, hits_wav):
    """A Chromium of its own whose fake microphone plays the hits."""
    browser = playwright.chromium.launch(args=[
        "--enable-unsafe-swiftshader", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        f"--use-file-for-fake-audio-capture={hits_wav}"])
    yield browser
    browser.close()


@pytest.fixture
def hits_studio(hits_browser, server_url):
    page, problems = open_page(hits_browser, server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    page.fill("#bpm", "90")
    page.press("#bpm", "Tab")
    page.select_option("#mode", "rhythm")
    yield page
    page.context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def record_take(page, *, count_in, while_recording=None):
    page.set_checked("#countin", count_in)
    page.set_checked("#pitchguide", False)
    page.evaluate("delete document.getElementById('finish').dataset.take")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    if while_recording:
        while_recording()
    page.wait_for_timeout(6500)
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    expect(page.locator("#status")).to_contain_text("Recorded")


def record_and_transcribe(page, *, count_in):
    record_take(page, count_in=count_in)
    transcribe(page)


def transcribe(page):
    expect(page.locator("#analyze")).to_be_enabled()
    page.click("#analyze")
    expect(page.locator("#status")).to_have_text("Transcription complete", timeout=20000)


def detect(page):
    page.click("#detecttempo")
    return page.locator("#status")


def test_a_take_after_the_count_in_keeps_the_project_tempo(hits_studio):
    page = hits_studio
    record_and_transcribe(page, count_in=True)
    expect(detect(page)).to_have_text("Tempo is already 90 bpm (the take was sung to it)")
    expect(page.locator("#bpm")).to_have_value("90")


def test_the_same_hits_with_nothing_heard_are_read_freely(hits_studio):
    page = hits_studio
    # No count-in, no click and nothing in the song to play: nothing set the tempo, so the hits decide it.
    expect(page.locator("#recclick")).not_to_be_checked()
    record_and_transcribe(page, count_in=False)
    expect(detect(page)).to_have_text("Detected tempo: 60 bpm")


def test_the_same_hits_imported_are_read_freely(hits_studio, hits_wav):
    page = hits_studio
    page.set_input_files("#audiofile", str(hits_wav))
    expect(page.locator("#analyze")).to_be_enabled()
    transcribe(page)
    expect(detect(page)).to_have_text("Detected tempo: 60 bpm")


def comp_second_take_in(page):
    """Use the first take and comp the second in from 2 s, so the song's take is a recording rendered from both."""
    ids = page.eval_on_selector_all("#takelist .takerow", "els => els.map(e => e.dataset.take)")
    assert len(ids) == 2, ids
    page.click(f"#usetake-{ids[0]}")
    expect(page.locator("#takesinfo")).to_have_text("The song uses Take 1", timeout=15000)
    page.fill("#compfrom", "2")
    page.fill("#compto", "9")
    page.select_option("#comptake", ids[1])
    page.click("#compin")
    expect(page.locator("#takesinfo")).to_contain_text("The song uses a comp", timeout=15000)
    # The comp's recording is rendered and loaded after the list says so; its last step is this status, which would
    # otherwise land on top of the next action's.
    expect(page.locator("#status")).to_have_text(re.compile(r"^Using Take 1 .*, Take 2 "), timeout=15000)


def test_a_comp_of_takes_after_the_count_in_keeps_the_tempo(hits_studio):
    page = hits_studio
    record_take(page, count_in=True)
    record_take(page, count_in=True)
    comp_second_take_in(page)
    transcribe(page)
    expect(detect(page)).to_have_text("Tempo is already 90 bpm (the take was sung to it)")
    expect(page.locator("#detecttempo")).to_have_attribute("data-sung", "90")


def test_a_comp_with_a_take_recorded_with_nothing_heard_is_read_freely(hits_studio):
    page = hits_studio
    record_take(page, count_in=False)
    record_take(page, count_in=True)
    comp_second_take_in(page)
    transcribe(page)
    # The comp is read freely: no tempo it was sung to. Which tempo the hits then give depends on where take 2's
    # hits fall after the 2 s seam, which moves with how long the count-in and the start took, so it is not checked
    # here (the 3:2 reading itself is checked on whole takes above).
    status = detect(page)
    expect(page.locator("#detecttempo")).to_have_attribute("data-sung", "")
    expect(status).not_to_contain_text("sung to it")


def set_bpm(page, bpm):
    page.fill("#bpm", str(bpm))
    page.press("#bpm", "Tab")


def test_the_tempo_a_take_was_sung_to_survives_a_reload(hits_studio):
    page = hits_studio
    record_and_transcribe(page, count_in=True)
    page.wait_for_timeout(500)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#hitcount")).not_to_have_text("0")
    expect(page.locator("#bpm")).to_have_value("90")
    expect(detect(page)).to_have_text("Tempo is already 90 bpm (the take was sung to it)")


def test_the_take_keeps_the_tempo_it_started_at_when_the_tempo_changes_while_recording(hits_studio):
    page = hits_studio
    record_take(page, count_in=True, while_recording=lambda: set_bpm(page, 100))
    transcribe(page)
    # Sung to the 90 bpm count-in: at 100 it is not the tempo it was sung to, so the hits decide (60).
    expect(detect(page)).to_have_text("Detected tempo: 60 bpm")
    page.click("#undo")
    set_bpm(page, 90)
    expect(detect(page)).to_have_text("Tempo is already 90 bpm (the take was sung to it)")
