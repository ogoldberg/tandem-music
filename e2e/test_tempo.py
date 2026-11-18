"""FIX.4: Find the speed keeps the tempo a take was sung to. Chromium's fake microphone plays a hit every second: at the
project's 90 bpm that is a dotted quarter, which fits 60 bpm better than 90 (the 3:2 trap). Recorded after the count-in,
Detect tempo keeps 90; the same hits imported, or recorded with nothing heard, read as 60."""
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


def record_and_transcribe(page, *, count_in):
    page.set_checked("#countin", count_in)
    page.set_checked("#pitchguide", False)
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    page.wait_for_timeout(6500)
    page.click("#finish")
    wait_until(page, "async () => !!document.getElementById('finish').dataset.take", "the take has finished")
    expect(page.locator("#status")).to_contain_text("Recorded")
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
