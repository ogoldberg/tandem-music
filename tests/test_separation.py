"""SEP.1: separating the voice from background music (tandem_desktop/separation.py).

The route tests run everywhere with a stand-in for the model. The tests marked `model` run the
real HTDemucs model: they need requirements-models.txt and the weights, which they download once
through the MODEL.1 runtime (pinned and verified) into TANDEM_TEST_MODEL_HOME. Without those they
are skipped, unless TANDEM_REQUIRE_SEPARATION=1 (the `separation` CI job), which makes a missing
package or model a failure instead.
"""
import asyncio
import hashlib
import io
import json
import os
import time
import wave

import httpx
import numpy as np
import pytest

import tandem_backend as server
import tandem_desktop as desk
from tandem_desktop import models, separation
import separation_fixture as fx

PORT = 47996
SECRET = "s" * 43
REQUIRE = os.environ.get("TANDEM_REQUIRE_SEPARATION") == "1"


def wav_bytes(x, rate, channels=1):
    samples = np.clip(np.round(np.asarray(x) * 32767), -32768, 32767).astype("<i2")
    if channels == 2:
        samples = np.repeat(samples, 2)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return out.getvalue()


def wav_samples(data):
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768, w.getframerate(), w.getnchannels()


def call(sep, method, path, runtime=None, **kw):
    app = desk.guarded_app(PORT, SECRET, models=runtime, separation=sep)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers={desk.LAUNCH_HEADER: SECRET, **kw.pop("headers", {})}, **kw)
    return asyncio.run(go())


def finish(runtime, job_id, timeout=600):
    job = runtime.jobs.wait(job_id, timeout=timeout)
    assert job.state != "running", "the job did not finish"
    return job


# --- Routes, with a stand-in for the model --------------------------------------------------

@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """A runtime whose htdemucs files are installed (a stand-in file pinned in place of the real
    one), with load_htdemucs and separate replaced: the stand-in 'vocal' is the first half of the
    recording, the 'accompaniment' the second."""
    body = b"stand-in weights"
    spec = models.ModelSpec(separation.MODEL_ID, "Voice separation (HTDemucs)",
                            (models.ModelFile(separation.WEIGHTS, "https://example.test/w", hashlib.sha256(body).hexdigest(), len(body)),))
    runtime = models.ModelRuntime(tmp_path, [spec])
    folder = runtime.store.folder(spec)
    folder.mkdir(parents=True)
    (folder / separation.WEIGHTS).write_bytes(body)
    st = (folder / separation.WEIGHTS).stat()
    (folder / models.RECORD).write_text(json.dumps({separation.WEIGHTS: {"sha256": spec.files[0].sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    calls = {"load": 0, "release": None}

    def load(path):
        calls["load"] += 1
        assert path.read_bytes() == body
        return "bag"

    def separate(bag, x, rate, job=None, on=None):
        assert bag == "bag"
        for i in range(5):
            job.report(i / 5, "Separating the voice from the music")
            if calls["release"] is not None:
                assert calls["release"].wait(10)
        half = np.zeros_like(x)
        n = len(x) // 2
        vocal, acc = half.copy(), half.copy()
        vocal[:n], acc[n:] = x[:n], x[n:]
        return vocal, acc
    monkeypatch.setattr(separation, "load_htdemucs", load)
    monkeypatch.setattr(separation, "separate", separate)
    return runtime, calls


def test_separation_returns_both_stems_at_the_recordings_rate_and_length(stand_in):
    runtime, calls = stand_in
    sep = separation.Separation(runtime)
    x = 0.5 * np.sin(2 * np.pi * 220 * np.arange(48000) / 48000)
    r = call(sep, "POST", "/api/desktop/separate", content=wav_bytes(x, 48000, channels=2))
    assert r.status_code == 202 and r.headers["cache-control"] == "no-store", r.text
    job = finish(runtime, r.json()["id"])
    assert job.state == "done", job.error
    seen = call(sep, "GET", f"/api/desktop/jobs/{job.id}", runtime=runtime).json()
    assert seen["result"] == {"stems": ["vocal", "accompaniment"], "seconds": 1.0}
    got = {}
    for stem in ("vocal", "accompaniment"):
        r = call(sep, "GET", f"/api/desktop/separate/{job.id}/{stem}.wav")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.headers["cache-control"] == "no-store"
        got[stem], rate, channels = wav_samples(r.content)
        assert rate == 48000 and channels == 1 and len(got[stem]) == len(x)
    assert np.allclose(got["vocal"] + got["accompaniment"], x, atol=3 / 32768)
    # The model is loaded once and kept for the next separation.
    assert finish(runtime, sep.start(wav_bytes(x, 48000)).id).state == "done"
    assert calls["load"] == 1


def test_only_the_last_separations_are_kept(stand_in, monkeypatch):
    runtime, _ = stand_in
    sep = separation.Separation(runtime)
    data = wav_bytes(np.zeros(8000), 8000)
    ids = [finish(runtime, sep.start(data).id).id for _ in range(separation.KEEP_RESULTS + 1)]
    assert call(sep, "GET", f"/api/desktop/separate/{ids[0]}/vocal.wav").status_code == 404
    assert call(sep, "GET", f"/api/desktop/separate/{ids[-1]}/vocal.wav").status_code == 200


def test_a_separation_reports_progress_and_can_be_cancelled(stand_in):
    import threading
    runtime, calls = stand_in
    calls["release"] = threading.Event()
    sep = separation.Separation(runtime)
    job = sep.start(wav_bytes(np.zeros(8000), 8000))
    deadline = time.monotonic() + 10
    while "Separating" not in job.message and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.state == "running" and "Separating the voice" in job.message
    # A second separation waits for the first.
    r = call(sep, "POST", "/api/desktop/separate", runtime=runtime, content=wav_bytes(np.zeros(8000), 8000))
    assert r.status_code == 409 and "already running" in r.json()["error"]
    assert call(sep, "DELETE", f"/api/desktop/jobs/{job.id}", runtime=runtime).status_code == 200
    calls["release"].set()
    assert finish(runtime, job.id).state == "cancelled"
    assert call(sep, "GET", f"/api/desktop/separate/{job.id}/vocal.wav").status_code == 404


def test_two_separations_started_at_once_run_one_at_a_time(stand_in, monkeypatch):
    # Codex review of #67: the busy check and the job's registration must be one step, or two
    # requests arriving together both pass the check and run the model at the same time.
    import concurrent.futures
    import threading
    runtime, calls = stand_in
    calls["release"] = threading.Event()
    installed = runtime.store.installed

    def slow_installed(spec):
        time.sleep(0.1)  # the time between the check and the registration, made long
        return installed(spec)
    monkeypatch.setattr(runtime.store, "installed", slow_installed)
    sep = separation.Separation(runtime)
    data = wav_bytes(np.zeros(8000), 8000)
    gate = threading.Barrier(2)

    def start():
        gate.wait(timeout=5)
        try:
            return sep.start(data)
        except models.ModelBusy as e:
            return e
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            got = [f.result(timeout=10) for f in [pool.submit(start) for _ in range(2)]]
        busy = [g for g in got if isinstance(g, models.ModelBusy)]
        assert len(busy) == 1 and "already running" in str(busy[0]), got
    finally:
        calls["release"].set()
        for job in runtime.jobs.running():
            runtime.jobs.wait(job.id, timeout=10)


@pytest.mark.parametrize("data,status,words", [
    (b"not a wav", 400, "not a WAV"),
    (b"", 400, "not a WAV"),
])
def test_a_recording_that_is_not_a_wav_is_refused(stand_in, data, status, words):
    runtime, _ = stand_in
    r = call(separation.Separation(runtime), "POST", "/api/desktop/separate", content=data)
    assert r.status_code == status and words in r.json()["error"]


def test_too_long_or_too_large_a_recording_is_refused(stand_in, monkeypatch):
    runtime, _ = stand_in
    sep = separation.Separation(runtime)
    r = call(sep, "POST", "/api/desktop/separate", content=wav_bytes(np.zeros(8000 * (separation.MAX_SECONDS + 1)), 8000))
    assert r.status_code == 400 and "up to 10 minutes" in r.json()["error"]
    monkeypatch.setattr(separation, "MAX_BODY", 1000)
    r = call(sep, "POST", "/api/desktop/separate", content=wav_bytes(np.zeros(4000), 8000))
    assert r.status_code == 413
    assert runtime.jobs.running() == []


def test_separation_needs_the_model_downloaded(tmp_path):
    runtime = models.ModelRuntime(tmp_path)
    r = call(separation.Separation(runtime), "POST", "/api/desktop/separate", content=wav_bytes(np.zeros(8000), 8000))
    assert r.status_code == 400 and "Download Voice separation (HTDemucs) first (84.0 MB)" in r.json()["error"]


def test_the_routes_answer_only_the_apps_own_window_and_unknown_paths(stand_in):
    runtime, _ = stand_in
    sep = separation.Separation(runtime)
    app = desk.guarded_app(PORT, SECRET, separation=sep)

    async def go(headers, path="/api/desktop/separate", method="POST"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers=headers, content=wav_bytes(np.zeros(800), 8000))
    assert asyncio.run(go({})).status_code == 403
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET, "origin": "https://evil.example"})).status_code == 403
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, method="GET")).status_code == 405
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/separate/x/drums.wav", "GET")).status_code == 404
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/separate/x/vocal.wav", "GET")).status_code == 404
    # Without a separation object (the hosted app never has one) the route does not exist.
    bare = desk.guarded_app(PORT, SECRET)

    async def bare_go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bare), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.post("/api/desktop/separate", headers={desk.LAUNCH_HEADER: SECRET})
    assert asyncio.run(bare_go()).status_code == 404


def test_the_catalog_pins_the_htdemucs_weights():
    spec = models.HTDEMUCS
    assert spec in models.CATALOG and "MIT" in spec.licence and "LIC.1" in spec.licence
    (f,) = spec.files
    assert f.url.startswith("https://huggingface.co/adefossez/HTDemucs/resolve/") and len(f.url.split("/")[-2]) == 40
    assert set(spec.packages) <= {"torch", "demucs", "safetensors", "julius"}


def test_the_model_packages_are_pinned_in_requirements_models():
    text = open(os.path.join(os.path.dirname(__file__), "..", "requirements-models.txt")).read()
    pinned = {line.split("==")[0].strip().lower() for line in text.splitlines() if "==" in line and not line.startswith("#")}
    assert {"torch", "demucs", "safetensors"} <= pinned


# --- The real model -------------------------------------------------------------------------

def _need_model():
    missing = [p for p in models.HTDEMUCS.packages if __import__("importlib").util.find_spec(p) is None]
    home = os.environ.get("TANDEM_TEST_MODEL_HOME")
    why = (f"needs the packages {', '.join(missing)} (requirements-models.txt)" if missing
           else "set TANDEM_TEST_MODEL_HOME to a folder for the HTDemucs weights" if not home else "")
    if why:
        if REQUIRE:
            pytest.fail("TANDEM_REQUIRE_SEPARATION=1 but the separation test " + why)
        pytest.skip(why)
    return home


@pytest.fixture(scope="module")
def runtime():
    home = _need_model()
    rt = models.ModelRuntime(home)
    if not rt.store.installed(models.HTDEMUCS):
        job = rt.jobs.wait(rt.start_download(models.HTDEMUCS.id).id, timeout=900)
        assert job.state == "done", job.error
    return rt


@pytest.fixture(scope="module")
def separated(runtime):
    """The fixture song separated by the real model, through the route."""
    mix, vocal, acc = fx.song()
    sep = separation.Separation(runtime)
    started = time.monotonic()
    r = call(sep, "POST", "/api/desktop/separate", runtime=runtime, content=wav_bytes(mix, fx.RATE))
    assert r.status_code == 202, r.text
    job = finish(runtime, r.json()["id"])
    assert job.state == "done", job.error
    stems = {s: wav_samples(call(sep, "GET", f"/api/desktop/separate/{job.id}/{s}.wav").content)[0] for s in separation.STEMS}
    return {"mix": mix, "vocal": vocal, "acc": acc, "stems": stems, "seconds": time.monotonic() - started, "sep": sep}


# Acceptance (docs/AUDIO.md): the share of the melody's notes the server's transcriber finds, a
# note counting when transcribed notes of its pitch cover at least half of it. The transcriber
# itself finds about 0.62 of them in the voice heard alone; separation may cost at most
# MAX_LOSS_TO_VOICE_ALONE of that, and must find at least MIN_RECALL_SEPARATED.
MIN_RECALL_SEPARATED = 0.6
MAX_LOSS_TO_VOICE_ALONE = 0.1
MAX_RECALL_MIXTURE = 0.2


@pytest.mark.model
def test_transcription_finds_the_melody_after_separation_and_not_before(separated):
    before = fx.recall(server.analyze_melody(separated["mix"].astype(np.float32), fx.RATE))
    after = fx.recall(server.analyze_melody(separated["stems"]["vocal"].astype(np.float32), fx.RATE))
    alone = fx.recall(server.analyze_melody(separated["vocal"].astype(np.float32), fx.RATE))
    print(f"\nSEP.1 melody recall: mixture {before:.2f}, separated vocal {after:.2f}, voice alone {alone:.2f};"
          f" {len(separated['mix']) / fx.RATE:.1f} s separated in {separated['seconds']:.1f} s")
    assert after >= MIN_RECALL_SEPARATED
    assert after >= alone - MAX_LOSS_TO_VOICE_ALONE
    assert before <= MAX_RECALL_MIXTURE
    assert after - before >= 0.4


@pytest.mark.model
def test_the_stems_are_the_voice_and_the_band(separated):
    stems, vocal, acc = separated["stems"], separated["vocal"], separated["acc"]
    for stem in stems.values():
        assert len(stem) == len(separated["mix"])
    corr = lambda a, b: float(np.corrcoef(a, b)[0, 1])  # noqa: E731
    assert corr(stems["vocal"], vocal) > 0.8 and corr(stems["accompaniment"], acc) > 0.9
    assert abs(corr(stems["vocal"], acc)) < 0.3
    # Together the stems give back the recording.
    residual = stems["vocal"] + stems["accompaniment"] - separated["mix"]
    assert np.sqrt(np.mean(residual ** 2)) < 0.1 * np.sqrt(np.mean(separated["mix"] ** 2))


@pytest.mark.model
def test_another_rate_comes_back_at_that_rate_and_length(runtime):
    mix, _, _ = fx.song(22050)
    sep = separation.Separation(runtime)
    job = finish(runtime, sep.start(wav_bytes(mix[:22050 * 3], 22050)).id)
    assert job.state == "done", job.error
    x, rate, channels = wav_samples(sep.stem(job.id, "vocal"))
    assert (rate, channels, len(x)) == (22050, 1, 22050 * 3)


@pytest.mark.model
def test_silence_separates_into_silence(runtime):
    sep = separation.Separation(runtime)
    job = finish(runtime, sep.start(wav_bytes(np.zeros(44100), 44100)).id)
    assert job.state == "done", job.error
    assert not wav_samples(sep.stem(job.id, "vocal"))[0].any()


def test_a_weights_file_naming_another_class_is_refused(tmp_path):
    pytest.importorskip("safetensors")
    torch = pytest.importorskip("torch")
    pytest.importorskip("demucs")
    from safetensors.torch import save_file
    path = tmp_path / "w.safetensors"
    save_file({"x": torch.zeros(1)}, str(path), metadata={"klass": "os.system", "args": "[]", "kwargs": "{}"})
    with pytest.raises(separation.SeparationError, match="not the HTDemucs model"):
        separation.load_htdemucs(path)
