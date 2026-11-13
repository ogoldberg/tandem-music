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


class Server:
    """A uvicorn process serving the app on a free port; stop() takes it down (a real network outage)."""

    def __init__(self, log_path):
        port = _free_port()
        self.log_path = log_path
        self.log = open(log_path, "wb")
        # Run the app the way local dev does, without provider or Vercel settings leaking in.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TANDEM_", "VERCEL", "UPSTASH_"))}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tandem_backend:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        self.url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        try:
            while True:
                if self.proc.poll() is not None:
                    raise RuntimeError("uvicorn exited early:\n" + log_path.read_text(errors="replace"))
                try:
                    if httpx.get(self.url + "/api/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("uvicorn did not become healthy within 30 s")
                time.sleep(0.2)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


# UI.1: the studio opens in the guided steps for a new person. The tests written for the studio's controls open it with
# every control shown instead, as a person who chose "Show every control" would; e2e/test_guided.py starts fresh contexts
# without this to test the guided view. It only sets the view when the page has no saved choice, so a test can still switch.
ALL_CONTROLS = """try{if(!localStorage.getItem('tandem-guide'))localStorage.setItem('tandem-guide',JSON.stringify({view:'all'}))}catch(e){}"""


@pytest.fixture
def context(context):
    context.add_init_script(ALL_CONTROLS)
    return context


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    # Server output goes to a file: an unread pipe would block uvicorn once it filled.
    # E2E_SERVER_LOG puts it at a known path (CI uploads it when the job fails).
    if os.environ.get("E2E_SERVER_LOG"):
        log_path = Path(os.environ["E2E_SERVER_LOG"]).resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        log_path = tmp_path_factory.mktemp("server") / "uvicorn.log"
    server = Server(log_path)
    try:
        yield server.url
    finally:
        server.stop()


@pytest.fixture
def own_server(tmp_path):
    """A server for this test alone, so the test can stop it and check what works with no network.
    (Playwright's set_offline does not cover a service worker's own requests.)"""
    server = Server(tmp_path / "uvicorn.log")
    yield server
    server.stop()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, browser_name):
    """Let Chromium fall back to software WebGL (SwiftShader) on GPU-less machines such as CI runners.

    Chromium no longer does that by default, so Basic Pitch's TensorFlow.js would drop to its
    pure-JS CPU backend, which is too slow to transcribe a long take within the test timeouts.
    """
    args = [*browser_type_launch_args.get("args", [])]
    if browser_name == "chromium":
        # A synthetic microphone (a beeping tone) and no permission prompt, for the capture tests (MOB.1).
        args += ["--enable-unsafe-swiftshader", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
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
