"""DESK.1/DESK.2: the Mac app's launcher server serves a working studio (Chromium stands in for
WKWebView). The page gets the per-launch secret from desk.launch_script, the same script the
launcher adds to its window at document start."""
import io
import os
import re
import socket
import wave

import httpx
import numpy as np
import pytest
from playwright.sync_api import expect

import tandem_desktop as desk


@pytest.fixture
def desktop(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("TANDEM_", "VERCEL", "UPSTASH_")):
            monkeypatch.delenv(key)
    # A hosted limit this low would stop the second request; the app's own window has none.
    monkeypatch.setenv("TANDEM_AUDIO_RATE_LIMIT", "1")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    secret = desk.new_launch_secret()
    server, thread = desk.start_server(port, secret)
    try:
        yield {"url": f"http://127.0.0.1:{port}", "port": port, "secret": secret}
    finally:
        desk.stop_server(server, thread)


def open_app(page, desktop):
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error" else None)
    page.add_init_script(desk.launch_script(desktop["port"], desktop["secret"]))
    page.goto(desktop["url"] + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    return problems


def test_the_launcher_server_loads_the_studio_without_errors(page, desktop):
    problems = open_app(page, desktop)
    # The module script and its static imports came through the Host check, or notecount would be empty.
    config = page.evaluate("fetch('/api/config', {headers: {[tandemLaunch.header]: tandemLaunch.secret}}).then(r => r.json())")
    assert config["runtime"] == "desktop" and config["limits"]["tune_seconds"] == 600
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_without_the_secret_the_api_refuses_the_page(desktop):
    # What a web page in an ordinary browser gets: no secret, so no API (it cannot set the header
    # cross-origin anyway, and its Origin is refused).
    assert httpx.get(desktop["url"] + "/api/config").status_code == 403
    assert httpx.get(desktop["url"] + "/api/config", headers={"origin": "https://ogoldberg.github.io",
                                                              desk.LAUNCH_HEADER: desktop["secret"]}).status_code == 403


def held_tones_wav(path, seconds, rate=22050):
    """Mono WAV of held sung-range tones, 0.8 s each with 0.2 s gaps, cycling through a scale."""
    scale = [60, 62, 64, 65, 67, 69, 71, 72]
    t = np.arange(int(rate * 0.8)) / rate
    env = np.minimum(1, np.minimum(t, 0.8 - t) / 0.02)
    parts = []
    for i in range(int(seconds)):
        hz = 440.0 * 2 ** ((scale[i % len(scale)] - 69) / 12) * 1.02  # a little sharp, so there is something to correct
        parts += [0.4 * env * np.sin(2 * np.pi * hz * t), np.zeros(int(rate * 0.2))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((np.concatenate(parts) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def test_a_long_take_is_tuned_in_one_request_in_the_mac_app(page, desktop, tmp_path):
    """DESK.2: a 70 s take, which the hosted app sends as five chunks, goes to the local server in
    one request carrying the launch secret, and so does the next one (no rate limit)."""
    problems = open_app(page, desktop)
    api = []
    page.on("request", lambda r: api.append(r) if "/api/" in r.url else None)
    page.select_option("#mode", "vocal")
    page.set_input_files("#audiofile", str(held_tones_wav(tmp_path / "take-70s.wav", 70)))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 70\.0s\."))
    for _ in range(2):
        page.click("#tune")
        expect(page.locator("#status")).to_have_text("Pitch correction complete", timeout=180_000)
    tunes = [r for r in api if "/api/tune" in r.url]
    assert len(tunes) == 2, [r.url for r in api]
    assert all(r.headers.get(desk.LAUNCH_HEADER) == desktop["secret"] for r in api)
    assert desktop["secret"] not in " ".join(r.url for r in api)
    expect(page.locator("#tuneinfo")).to_contain_text("Corrected")
    with page.expect_download() as info:
        page.click("#downloadtuned")
    with wave.open(str(info.value.path())) as w:
        assert w.getnframes() == 70 * w.getframerate()  # the whole take, decoded at the device rate
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)
