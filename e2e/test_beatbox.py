"""SEC.6: with "This device" chosen a beat take is read into drum hits on the device (beatbox.js) and never
sent to /api/analyze; the hits are the ones the server's reader finds in the same take."""
from pathlib import Path

from playwright.sync_api import expect

from test_guided import guided_page, plan, record_take
from test_layers import record
from test_studio import draft

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "beatbox.wav"


def analyze_requests(page):
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/api/analyze" in r.url else None)
    return seen


def test_the_device_reads_a_beat_as_the_server_does_without_sending_it(studio):
    page = studio
    seen = analyze_requests(page)
    page.select_option("#mode", "rhythm")
    page.set_input_files("#audiofile", str(FIXTURE))
    expect(page.locator("#analyze")).to_be_enabled()

    # The server's reading of the take, through the studio's own upload.
    page.select_option("#transcriber", "heuristic")
    with page.expect_response(lambda r: r.url.endswith("/api/analyze?mode=rhythm")):
        page.click("#analyze")
    expect(page.locator("#status")).to_have_text("Transcription complete")
    server = draft(page)["drums"]
    # The browser decodes the take at its own rate, so the names may differ from the fixture's; the count does not.
    assert len(server) == 16
    assert len(seen) == 1

    # On the device: the same hits, and nothing sent.
    page.select_option("#transcriber", "basic-pitch")
    page.click("#analyze")
    expect(page.locator("#status")).to_have_text("Transcription complete")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Transcribe drums")
    assert draft(page)["drums"] == server
    assert len(seen) == 1


def test_a_layer_transcribed_into_the_drums_on_the_device_is_not_sent(studio):
    # Chromium's fake microphone (a beeping tone) is the input: a take, then a layer over it.
    page = studio
    seen = analyze_requests(page)
    page.uncheck("#countin")
    record(page, 1.5)
    expect(page.locator("#reclayer")).to_be_enabled(timeout=10000)
    page.check("#reclayer")
    record(page, 2.0)
    expect(page.locator("#status")).to_contain_text("Recorded Layer 2 as a track of its own", timeout=10000)
    lid = page.evaluate("document.querySelector('#layerlanes .lane').dataset.layer")
    expect(page.locator("#transcriber")).to_have_value("basic-pitch")
    page.select_option(f"#layerinto-{lid}", "drums")
    page.click(f"#layertranscribe-{lid}")
    expect(page.locator("#status")).to_contain_text("Transcribed Layer 2 into the drums", timeout=30000)
    expect(page.locator(f'#layerlanes .lane[data-layer="{lid}"] .layerhead small')).to_contain_text("in the drums")
    assert seen == []


def test_a_guided_beat_take_on_this_device_becomes_drums_with_no_upload(browser, server_url):
    with guided_page(browser, server_url) as page:
        seen = analyze_requests(page)
        page.click("#gsettings")
        expect(page.locator("#gtranscriber")).to_have_value("device")
        page.click("#ghelpersback")
        page.click('[data-mode="rhythm"]')
        record_take(page)
        assert dict(plan(page))["Turn your beat into drum hits"] == "done"
        assert seen == []
        hits = draft(page)["drums"]
        assert page.locator("#hitcount").text_content().split()[0] == str(len(hits))
