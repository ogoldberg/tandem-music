"""Browser end-to-end fixtures: a real uvicorn server and a page that fails on console errors."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    port = _free_port()
    # Server output goes to a file: an unread pipe would block uvicorn once it filled.
    log_path = tmp_path_factory.mktemp("server") / "uvicorn.log"
    log = open(log_path, "wb")
    # Run the app the way local dev does, without provider or Vercel settings leaking in.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TANDEM_", "VERCEL", "UPSTASH_"))}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tandem_backend:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    try:
        while True:
            if proc.poll() is not None:
                raise RuntimeError("uvicorn exited early:\n" + log_path.read_text(errors="replace"))
            try:
                if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not become healthy within 30 s")
            time.sleep(0.2)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Let Chromium fall back to software WebGL (SwiftShader) on GPU-less machines such as CI runners.

    Chromium no longer does that by default, so Basic Pitch's TensorFlow.js would drop to its
    pure-JS CPU backend, which is too slow to transcribe a long take within the test timeouts.
    """
    args = [*browser_type_launch_args.get("args", []), "--enable-unsafe-swiftshader"]
    return {**browser_type_launch_args, "args": args}


@pytest.fixture
def studio(page, server_url):
    """The studio page, loaded fresh. The test fails on any uncaught page error or console error."""
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text} @ {msg.location}")
            if msg.type == "error" else None)
    page.goto(server_url + "/")
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    yield page
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)
