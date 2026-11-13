"""VOX.4: a long recording is tuned in the browser with the WORLD WebAssembly build, offline.

The studio is opened once from its own server (so the service worker caches the app and the WORLD
files), the server is stopped, and a 60 s take sung 40 cents sharp is tuned on the device: no
request leaves the page, and every note comes back on its semitone.
"""
import io
import wave

import numpy as np
from playwright.sync_api import expect

from test_capture import assert_server_down, wait_for_service_worker
from conftest import ALL_CONTROLS

RATE = 22050
SCALE = [60, 62, 64, 65, 67, 69, 71, 72]
NOTE, GAP, SHARP_CENTS = 0.8, 0.2, 40


def sharp_take(path, seconds):
    t = np.arange(int(RATE * NOTE)) / RATE
    env = np.minimum(1, np.minimum(t, NOTE - t) / 0.02)
    parts = []
    for i in range(int(seconds)):
        hz = 440.0 * 2 ** ((SCALE[i % len(SCALE)] + SHARP_CENTS / 100 - 69) / 12)
        voice = sum(0.7 ** k / k * np.sin(2 * np.pi * k * hz * t) for k in range(1, 7))
        parts += [0.3 * env * voice / np.max(np.abs(voice)), np.zeros(int(RATE * GAP))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(np.round(np.concatenate(parts) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def note_cents(x, rate, seconds):
    """Each note's pitch from the strongest FFT peak of its middle, in cents from its semitone."""
    out = []
    for i in range(int(seconds)):
        a = int((i * (NOTE + GAP) + 0.2) * rate)
        mid = x[a:a + int(0.4 * rate)] * np.hanning(int(0.4 * rate))
        spectrum = np.abs(np.fft.rfft(mid, 16 * len(mid)))
        hz = np.argmax(spectrum) * rate / (16 * len(mid))
        out.append(1200 * np.log2(hz / (440.0 * 2 ** ((SCALE[i % len(SCALE)] - 69) / 12))))
    return np.array(out)


def test_a_long_take_is_tuned_on_the_device_with_no_network(browser, own_server, tmp_path):
    context = browser.new_context(base_url=own_server.url, accept_downloads=True)
    context.add_init_script(ALL_CONTROLS)
    page = context.new_page()
    problems, requests = [], []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    try:
        page.goto("/")
        wait_for_service_worker(page)
        page.reload()
        page.wait_for_function("!!navigator.serviceWorker.controller")
        own_server.stop()
        assert_server_down(own_server)
        context.on("request", lambda r: requests.append(r.url))
        seconds = 60
        page.select_option("#mode", "vocal")
        page.set_input_files("#audiofile", str(sharp_take(tmp_path / "take-60s.wav", seconds)))
        expect(page.locator("#tune")).to_be_enabled(timeout=30_000)
        expect(page.locator("#tuneengine")).to_have_value("device")
        page.evaluate("() => { const e = document.getElementById('tunestrength'); e.value = 100; e.dispatchEvent(new Event('input')); }")
        requests.clear()
        page.click("#tune")
        expect(page.locator("#status")).to_have_text("Pitch correction complete", timeout=240_000)
        expect(page.locator("#tuneinfo")).to_contain_text("on this device")
        assert not [u for u in requests if "/api/" in u], requests
        with page.expect_download() as info:
            page.click("#downloadtuned")
        with wave.open(str(info.value.path())) as w:
            rate, y = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768
        assert abs(len(y) / rate - seconds) < 0.01, len(y) / rate
        before = note_cents(np.frombuffer(sharp_take(tmp_path / "again.wav", seconds).read_bytes()[44:], "<i2") / 32768, RATE, seconds)
        after = note_cents(y, rate, seconds)
        assert np.all(np.abs(before - SHARP_CENTS) < 5), before
        assert np.all(np.abs(after) < 5), after
    finally:
        context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)
