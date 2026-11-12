"""MODEL.1: download, verify and run large audio models in the Mac app (tandem_desktop/models.py).

A tiny stand-in model is served by a stand-in file server on loopback, so these tests download real
bytes over HTTP, hash them and run jobs, without a large download or any model package."""
import asyncio
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time

import httpx
import pytest

import tandem_desktop as desk
from tandem_desktop import models

PORT = 47997
SECRET = "m" * 43


class FileServer:
    """Serves `files` (path -> bytes). A path in `hold` sends its first half, then waits for
    `release` before sending the rest, so a test can see progress and cancel mid-download."""

    def __init__(self):
        self.files, self.hold, self.release, self.halfway = {}, set(), threading.Event(), threading.Event()
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                body = outer.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                if self.path in outer.hold:
                    half = len(body) // 2
                    self.wfile.write(body[:half])
                    self.wfile.flush()
                    outer.halfway.set()
                    outer.release.wait(10)
                    try:
                        self.wfile.write(body[half:])
                    except OSError:
                        pass
                else:
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.httpd.shutdown()


@pytest.fixture
def files():
    server = FileServer()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setattr(models, "CHUNK", 16 * 1024)


def stand_in(files, name="tiny", payload=None, sha=None, size=None, packages=(), parts=1):
    """A stand-in model of `parts` files served by `files`; returns (spec, payloads)."""
    payloads, entries = [], []
    for i in range(parts):
        body = payload if payload is not None else os.urandom(200_000 + i)
        files.files[f"/{name}/weights-{i}.bin"] = body
        payloads.append(body)
        entries.append(models.ModelFile(f"weights-{i}.bin", f"{files.url}/{name}/weights-{i}.bin",
                                        sha or hashlib.sha256(body).hexdigest(), size or len(body)))
    return models.ModelSpec(name, f"Stand-in {name}", tuple(entries), packages=packages, licence="test"), payloads


def call(runtime, method, path, secret=SECRET, **kw):
    app = desk.guarded_app(PORT, SECRET, models=runtime)
    headers = {**kw.pop("headers", {}), **({desk.LAUNCH_HEADER: secret} if secret else {})}

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers=headers, **kw)
    return asyncio.run(go())


def finish(runtime, job_id):
    job = runtime.jobs.wait(job_id, timeout=20)
    assert job.state != "running", "the job did not finish"
    return job


def test_a_model_downloads_is_verified_and_reported_installed(tmp_path, files):
    spec, payloads = stand_in(files, parts=2)
    runtime = models.ModelRuntime(tmp_path, [spec])
    listed = call(runtime, "GET", "/api/desktop/models").json()["models"]
    # The size is known before the download starts.
    assert listed == [{"id": "tiny", "label": "Stand-in tiny", "size": sum(map(len, payloads)), "licence": "test",
                       "installed": False, "missing_packages": [], "ready": False, "download_job": None}]
    assert call(runtime, "GET", "/api/config").json()["models_installed"] == []

    r = call(runtime, "POST", "/api/desktop/models/tiny/download")
    assert r.status_code == 202 and r.json()["state"] == "running" and r.headers["cache-control"] == "no-store"
    job = finish(runtime, r.json()["id"])
    assert job.state == "done" and job.progress == 1.0, job.error
    for i, body in enumerate(payloads):
        assert (tmp_path / "models" / "tiny" / f"weights-{i}.bin").read_bytes() == body
    assert not list((tmp_path / "models" / "tiny").glob("*.part"))
    assert call(runtime, "GET", f"/api/desktop/jobs/{job.id}").json()["state"] == "done"
    assert call(runtime, "GET", "/api/desktop/models").json()["models"][0]["ready"] is True
    assert call(runtime, "GET", "/api/config").json()["models_installed"] == ["tiny"]
    # A second runtime (the next launch) finds it installed without downloading again.
    again = models.ModelRuntime(tmp_path, [spec])
    assert again.installed_ids() == ["tiny"]
    assert call(again, "POST", "/api/desktop/models/tiny/download").status_code == 409
    assert len(files.requests) == 2


@pytest.mark.parametrize("change", ["hash", "size", "longer"])
def test_a_file_that_does_not_match_its_pin_is_refused_and_nothing_is_kept(tmp_path, files, change):
    body = os.urandom(100_000)
    if change == "hash":
        spec, _ = stand_in(files, payload=body, sha="0" * 64)
    elif change == "size":
        spec, _ = stand_in(files, payload=body, size=len(body) + 1)
    else:  # the server sends more than pinned, with no content-length to warn first
        spec, _ = stand_in(files, payload=body, size=len(body) - 10, sha=hashlib.sha256(body[:-10]).hexdigest())
    runtime = models.ModelRuntime(tmp_path, [spec])
    job = finish(runtime, runtime.start_download("tiny").id)
    assert job.state == "failed" and "Nothing was installed" in job.error
    assert call(runtime, "GET", f"/api/desktop/jobs/{job.id}").json()["error"] == job.error
    assert [p.name for p in (tmp_path / "models" / "tiny").iterdir()] == []
    assert runtime.installed_ids() == []


def test_a_failed_download_says_what_the_server_answered(tmp_path, files):
    spec, _ = stand_in(files)
    del files.files["/tiny/weights-0.bin"]
    runtime = models.ModelRuntime(tmp_path, [spec])
    job = finish(runtime, runtime.start_download("tiny").id)
    assert job.state == "failed" and "answered 404" in job.error


def test_progress_is_reported_while_the_download_runs(tmp_path, files):
    spec, _ = stand_in(files)
    files.hold.add("/tiny/weights-0.bin")
    runtime = models.ModelRuntime(tmp_path, [spec])
    job_id = call(runtime, "POST", "/api/desktop/models/tiny/download").json()["id"]
    assert files.halfway.wait(10)
    deadline = time.monotonic() + 10
    while (seen := call(runtime, "GET", f"/api/desktop/jobs/{job_id}").json())["progress"] < 0.3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert seen["state"] == "running" and 0.3 <= seen["progress"] < 1 and "Downloading Stand-in tiny" in seen["message"]
    # Asking again while it runs rejoins the same job, and the model cannot be removed meanwhile.
    assert call(runtime, "POST", "/api/desktop/models/tiny/download").json()["id"] == job_id
    assert call(runtime, "GET", "/api/desktop/models").json()["models"][0]["download_job"] == job_id
    assert call(runtime, "DELETE", "/api/desktop/models/tiny").status_code == 409
    files.release.set()
    assert finish(runtime, job_id).state == "done"


def test_a_download_can_be_cancelled_and_leaves_no_partial_file(tmp_path, files):
    spec, _ = stand_in(files)
    files.hold.add("/tiny/weights-0.bin")
    runtime = models.ModelRuntime(tmp_path, [spec])
    job_id = runtime.start_download("tiny").id
    assert files.halfway.wait(10)
    assert call(runtime, "DELETE", f"/api/desktop/jobs/{job_id}").status_code == 200
    files.release.set()
    job = finish(runtime, job_id)
    assert job.state == "cancelled" and job.error == ""
    assert [p.name for p in (tmp_path / "models" / "tiny").iterdir()] == []
    assert runtime.installed_ids() == []


def test_a_run_reports_progress_and_its_result(tmp_path, files):
    spec, payloads = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    assert finish(runtime, runtime.start_download("tiny").id).state == "done"
    steps = threading.Event()
    seen = []

    def work(folder, job):
        data = (folder / "weights-0.bin").read_bytes()
        for i in range(4):
            job.report(i / 4, f"step {i}")
            seen.append(job.progress)
        steps.wait(10)
        return {"bytes": len(data)}

    job = runtime.run("tiny", "Stand-in run", work)
    deadline = time.monotonic() + 10
    while len(seen) < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    running = call(runtime, "GET", f"/api/desktop/jobs/{job.id}").json()
    assert running["state"] == "running" and running["message"] == "step 3" and running["progress"] == 0.75
    steps.set()
    assert finish(runtime, job.id).state == "done"
    done = call(runtime, "GET", f"/api/desktop/jobs/{job.id}").json()
    assert done["result"] == {"bytes": len(payloads[0])} and done["progress"] == 1.0


def test_a_run_can_be_cancelled(tmp_path, files):
    spec, _ = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    finish(runtime, runtime.start_download("tiny").id)

    def work(folder, job):
        while True:
            job.report(0.5, "working")
            time.sleep(0.01)

    job = runtime.run("tiny", "Endless run", work)
    time.sleep(0.05)
    call(runtime, "DELETE", f"/api/desktop/jobs/{job.id}")
    assert finish(runtime, job.id).state == "cancelled"


def test_a_run_asked_to_be_alone_is_refused_while_another_runs(tmp_path, files):
    spec, _ = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    finish(runtime, runtime.start_download("tiny").id)
    release = threading.Event()
    first = runtime.run("tiny", "First", lambda folder, job: release.wait(10), busy="one at a time")
    try:
        with pytest.raises(models.ModelBusy, match="one at a time"):
            runtime.run("tiny", "Second", lambda folder, job: None, busy="one at a time")
        # Without `busy`, runs of one model may overlap, as before.
        assert finish(runtime, runtime.run("tiny", "Alongside", lambda folder, job: None).id).state == "done"
    finally:
        release.set()
    assert finish(runtime, first.id).state == "done"
    assert finish(runtime, runtime.run("tiny", "After", lambda folder, job: None, busy="one at a time").id).state == "done"


def test_a_job_error_is_reported(tmp_path, files):
    spec, _ = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    finish(runtime, runtime.start_download("tiny").id)

    def work(folder, job):
        raise RuntimeError("the model ran out of memory")

    job = finish(runtime, runtime.run("tiny", "Failing run", work).id)
    assert job.state == "failed"
    assert call(runtime, "GET", f"/api/desktop/jobs/{job.id}").json()["error"] == "RuntimeError: the model ran out of memory"


def test_a_file_changed_on_disk_is_refused_before_loading(tmp_path, files):
    spec, payloads = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    finish(runtime, runtime.start_download("tiny").id)
    path = tmp_path / "models" / "tiny" / "weights-0.bin"
    stat = path.stat()
    path.write_bytes(bytes(len(payloads[0])))  # same size, other bytes
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # even with the old modification time
    ran = []
    job = finish(runtime, runtime.run("tiny", "Run", lambda folder, job: ran.append(folder)).id)
    assert job.state == "failed" and "has changed" in job.error and ran == []


def test_a_model_not_downloaded_or_missing_a_package_does_not_run(tmp_path, files):
    spec, _ = stand_in(files, packages=("tandem_no_such_package",))
    runtime = models.ModelRuntime(tmp_path, [spec])
    with pytest.raises(models.ModelError, match="Download Stand-in tiny first"):
        runtime.run("tiny", "Run", lambda folder, job: None)
    finish(runtime, runtime.start_download("tiny").id)
    described = call(runtime, "GET", "/api/desktop/models").json()["models"][0]
    assert described["installed"] is True and described["ready"] is False
    assert described["missing_packages"] == ["tandem_no_such_package"]
    assert runtime.installed_ids() == []
    job = finish(runtime, runtime.run("tiny", "Run", lambda folder, job: None).id)
    assert job.state == "failed" and "tandem_no_such_package" in job.error and "requirements-models.txt" in job.error


def test_a_model_can_be_removed(tmp_path, files):
    spec, _ = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    finish(runtime, runtime.start_download("tiny").id)
    r = call(runtime, "DELETE", "/api/desktop/models/tiny")
    assert r.status_code == 200 and r.json()["installed"] is False
    assert not (tmp_path / "models" / "tiny").exists()


def test_not_enough_disk_space_is_refused_before_downloading(tmp_path, files, monkeypatch):
    spec, _ = stand_in(files)
    monkeypatch.setattr(models.shutil, "disk_usage", lambda path: type("U", (), {"free": 1000})())
    runtime = models.ModelRuntime(tmp_path, [spec])
    job = finish(runtime, runtime.start_download("tiny").id)
    assert job.state == "failed" and "free disk space" in job.error and files.requests == []


@pytest.mark.parametrize("interrupt", ["failed", "cancelled"])
def test_a_retry_keeps_the_files_already_verified_and_needs_space_only_for_the_rest(tmp_path, files, monkeypatch, interrupt):
    spec, payloads = stand_in(files, parts=2)
    runtime = models.ModelRuntime(tmp_path, [spec])
    second = "/tiny/weights-1.bin"
    if interrupt == "failed":
        body = files.files.pop(second)
        job = finish(runtime, runtime.start_download("tiny").id)
        assert job.state == "failed" and "answered 404" in job.error
        files.files[second] = body
    else:
        files.hold.add(second)
        job_id = runtime.start_download("tiny").id
        assert files.halfway.wait(10)
        runtime.jobs.cancel(job_id)
        files.release.set()
        assert finish(runtime, job_id).state == "cancelled"
        files.hold.clear()
    folder = tmp_path / "models" / "tiny"
    assert sorted(p.name for p in folder.iterdir()) == ["verified.json", "weights-0.bin"]
    assert runtime.installed_ids() == []
    # Room for the remaining file only: the first one is already on disk and is not counted again.
    room = len(payloads[1]) + models.FREE_SPACE_MARGIN
    monkeypatch.setattr(models.shutil, "disk_usage", lambda path: type("U", (), {"free": room})())
    files.requests.clear()
    job = finish(runtime, runtime.start_download("tiny").id)
    assert job.state == "done", job.error
    assert files.requests == [second]
    assert runtime.installed_ids() == ["tiny"]


def test_a_kept_file_changed_on_disk_is_downloaded_again(tmp_path, files):
    spec, payloads = stand_in(files, parts=2)
    runtime = models.ModelRuntime(tmp_path, [spec])
    assert finish(runtime, runtime.start_download("tiny").id).state == "done"
    first = tmp_path / "models" / "tiny" / "weights-0.bin"
    first.write_bytes(b"x" * len(payloads[0]))
    os.utime(first, ns=(1, 1))
    (tmp_path / "models" / "tiny" / "weights-1.bin").unlink()
    files.requests.clear()
    assert finish(runtime, runtime.start_download("tiny").id).state == "done"
    assert sorted(files.requests) == ["/tiny/weights-0.bin", "/tiny/weights-1.bin"]
    assert first.read_bytes() == payloads[0]


def test_the_routes_need_the_launch_secret_and_answer_unknown_names(tmp_path, files):
    spec, _ = stand_in(files)
    runtime = models.ModelRuntime(tmp_path, [spec])
    assert call(runtime, "GET", "/api/desktop/models", secret=None).status_code == 403
    assert call(runtime, "POST", "/api/desktop/models/tiny/download", secret="x" * 43).status_code == 403
    assert files.requests == []
    assert call(runtime, "POST", "/api/desktop/models/nope/download").status_code == 404
    assert call(runtime, "GET", "/api/desktop/jobs/nope").status_code == 404
    assert call(runtime, "PUT", "/api/desktop/models").status_code == 405
    assert call(runtime, "GET", "/api/desktop/models/tiny/download").status_code == 405
    # Without a runtime (and on the hosted app) the routes do not exist.
    assert call(None, "GET", "/api/desktop/models").status_code == 404


@pytest.mark.parametrize("bad", [
    dict(id="Bad Id"), dict(name="../escape"), dict(name="verified.json"), dict(sha256="abc"),
    dict(size=0), dict(url="http://example.com/w.bin"),
])
def test_a_catalog_entry_must_pin_its_files(bad):
    file = dict(name="w.bin", url="https://example.com/w.bin", sha256="a" * 64, size=10)
    model_id = bad.pop("id", "ok")
    file.update(bad)
    with pytest.raises(ValueError):
        models.ModelSpec(model_id, "Model", (models.ModelFile(**file),))


def test_the_catalog_entries_pin_their_files():
    for spec in models.CATALOG:
        assert spec.files and spec.size > 0


def test_the_hosted_app_imports_none_of_it():
    code = ("import sys, asyncio, httpx, tandem_backend\n"
            "async def go():\n"
            "    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tandem_backend.app), base_url='http://t') as c:\n"
            "        return (await c.get('/api/config')).json()\n"
            "config = asyncio.run(go())\n"
            "print(sorted(m for m in sys.modules if m.startswith('tandem_desktop') or m.split('.')[0] in ('torch', 'torchaudio', 'demucs')))\n"
            "print(config['models_installed'])\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TANDEM_", "VERCEL", "UPSTASH_"))}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout.splitlines()
    assert out == ["[]", "[]"]
