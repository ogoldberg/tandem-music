"""DESK.1: the Mac app's launcher server serves a working studio (Chromium stands in for WKWebView)."""
import os
import socket

import pytest

import tandem_desktop as desk


@pytest.fixture
def desktop_url(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("TANDEM_", "VERCEL", "UPSTASH_")):
            monkeypatch.delenv(key)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server, thread = desk.start_server(port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        desk.stop_server(server, thread)


def test_the_launcher_server_loads_the_studio_without_errors(page, desktop_url):
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error" else None)
    page.goto(desktop_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    # The module script and its static imports came through the Host check, or notecount would be empty.
    assert page.evaluate("fetch('/api/config').then(r => r.json()).then(c => c.runtime)") == "desktop"
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)
