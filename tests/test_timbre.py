"""TIMBRE.1: the voice played as an instrument with RAVE timbre transfer (tandem_desktop/timbre.py).

The route tests run everywhere with a stand-in for the model. The TorchScript tests need torch and
julius (requirements-models.txt) and are skipped without them: they save a small scripted stand-in
with torch.jit.save and run it through load_rave and transfer, as the real models are. The tests
marked `model` run the real RAVE models (about 450 MB for the three): only when TANDEM_TEST_TIMBRE=1
and TANDEM_TEST_MODEL_HOME names a folder for them (downloaded once through the MODEL.1 runtime,
pinned and verified).
"""
import asyncio
import hashlib
import importlib.util
import io
import json
import os
import threading
import time
import wave

import httpx
import numpy as np
import pytest

import tandem_desktop as desk
from tandem_desktop import models, timbre

PORT = 47996
SECRET = "s" * 43


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
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
        return x, w.getframerate(), w.getnchannels()


def sung(rate, notes, step=0.5, start=0.0):
    """A sung-like line: MIDI `notes`, `step` seconds each, with vibrato and a few harmonics, after
    `start` seconds of silence."""
    out = [np.zeros(int(start * rate))]
    t = np.arange(int(step * rate)) / rate
    env = np.minimum(1, np.minimum(t / 0.03, (step - t) / 0.05))
    for m in notes:
        f = 440 * 2 ** ((m - 69) / 12) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * t))
        phase = 2 * np.pi * np.cumsum(f) / rate
        out.append(0.35 * env * sum(np.sin(h * phase) / h for h in (1, 2, 3)))
    return np.concatenate(out)


def call(t, method, path, runtime=None, **kw):
    app = desk.guarded_app(PORT, SECRET, models=runtime, timbre=t)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers={desk.LAUNCH_HEADER: SECRET, **kw.pop("headers", {})}, **kw)
    return asyncio.run(go())


def finish(runtime, job_id, timeout=900):
    job = runtime.jobs.wait(job_id, timeout=timeout)
    assert job.state != "running", "the job did not finish"
    return job


def installed_runtime(home, specs):
    """A runtime with a stand-in file pinned and installed in place of each spec's model file."""
    body = b"stand-in model"
    stand_ins = [models.ModelSpec(s.id, s.label, (models.ModelFile(s.files[0].name, "https://example.test/m",
                                                                 hashlib.sha256(body).hexdigest(), len(body)),))
                 for s in specs]
    runtime = models.ModelRuntime(home, stand_ins)
    for spec in stand_ins:
        folder = runtime.store.folder(spec)
        folder.mkdir(parents=True)
        (folder / spec.files[0].name).write_bytes(body)
        st = (folder / spec.files[0].name).stat()
        (folder / models.RECORD).write_text(json.dumps(
            {spec.files[0].name: {"sha256": spec.files[0].sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    return runtime


# --- Routes, with a stand-in for the model --------------------------------------------------

@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """A runtime with every instrument installed (stand-in files), with load_rave and transfer
    replaced: the stand-in 'instrument' is the recording at half volume."""
    runtime = installed_runtime(tmp_path, [spec for spec, _ in timbre.INSTRUMENTS.values()])
    calls = {"loads": [], "release": None}

    def load(path, rate):
        calls["loads"].append(path.name)
        assert path.read_bytes() == b"stand-in model" and rate == 48000
        return "model"

    def transfer(model, x, rate, sr, job=None):
        assert model == "model"
        for i in range(5):
            job.report(0.05 + 0.9 * i / 5, "Playing your voice on the instrument")
            if calls["release"] is not None:
                assert calls["release"].wait(10)
        return (0.5 * x).astype(np.float32)
    monkeypatch.setattr(timbre, "load_rave", load)
    monkeypatch.setattr(timbre, "transfer", transfer)
    return runtime, calls


def test_the_voice_comes_back_as_the_instrument_at_its_own_rate_and_length(stand_in):
    runtime, calls = stand_in
    t = timbre.Timbre(runtime)
    x = sung(44100, [60, 62, 64, 65, 67], step=0.4)
    r = call(t, "POST", "/api/desktop/timbre?instrument=sax", content=wav_bytes(x, 44100, channels=2))
    assert r.status_code == 202 and r.headers["cache-control"] == "no-store", r.text
    job = finish(runtime, r.json()["id"])
    assert job.state == "done", job.error
    seen = call(t, "GET", f"/api/desktop/jobs/{job.id}", runtime=runtime).json()
    assert seen["result"] == {"instrument": "sax", "seconds": 2.0, "rate": 44100}
    assert seen["model"] == "rave-sax"
    r = call(t, "GET", f"/api/desktop/timbre/{job.id}/timbre.wav")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.headers["cache-control"] == "no-store"
    y, rate, channels = wav_samples(r.content)
    assert (rate, channels, len(y)) == (44100, 1, len(x))
    assert np.max(np.abs(y - 0.5 * x)) < 3 / 32768
    # Each instrument is its own model; the model is loaded for every recording.
    for name in ("guitar", "organ", "sax"):
        assert finish(runtime, t.start(wav_bytes(x, 44100), name).id).state == "done"
    assert calls["loads"] == ["sax_soprano_franziskaschroeder_b2048_r48000_z20.ts", "guitar_iil_b2048_r48000_z16.ts",
                              "organ_bach_b2048_r48000_z16.ts", "sax_soprano_franziskaschroeder_b2048_r48000_z20.ts"]


def test_only_the_last_recordings_are_kept(stand_in):
    runtime, _ = stand_in
    t = timbre.Timbre(runtime)
    data = wav_bytes(sung(16000, [60, 64]), 16000)
    ids = [finish(runtime, t.start(data, "guitar").id).id for _ in range(timbre.KEEP_RESULTS + 1)]
    assert call(t, "GET", f"/api/desktop/timbre/{ids[0]}/timbre.wav").status_code == 404
    assert call(t, "GET", f"/api/desktop/timbre/{ids[-1]}/timbre.wav").status_code == 200


def test_one_instrument_plays_at_a_time_with_progress_and_cancel(stand_in):
    runtime, calls = stand_in
    calls["release"] = threading.Event()
    t = timbre.Timbre(runtime)
    data = wav_bytes(sung(16000, [60, 64, 67]), 16000)
    job = t.start(data, "sax")
    deadline = time.monotonic() + 10
    while "Playing" not in job.message and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.state == "running" and "Playing your voice" in job.message and job.progress > 0
    # Another instrument is refused too, not only the same model.
    for name in ("sax", "organ"):
        r = call(t, "POST", f"/api/desktop/timbre?instrument={name}", runtime=runtime, content=data)
        assert r.status_code == 409 and "already being played" in r.json()["error"]
    assert call(t, "DELETE", f"/api/desktop/jobs/{job.id}", runtime=runtime).status_code == 200
    calls["release"].set()
    assert finish(runtime, job.id).state == "cancelled"
    assert call(t, "GET", f"/api/desktop/timbre/{job.id}/timbre.wav").status_code == 404
    calls["release"] = None
    assert finish(runtime, t.start(data, "organ").id).state == "done"


@pytest.mark.parametrize("query,data,status,words", [
    ("instrument=sax", b"not a wav", 400, "not a WAV"),
    ("instrument=", None, 400, "Choose an instrument: sax, guitar, organ."),
    ("instrument=violin", None, 400, "Choose an instrument"),
    ("", None, 400, "Choose an instrument"),
])
def test_bad_requests_are_refused_before_any_job_starts(stand_in, query, data, status, words):
    runtime, _ = stand_in
    data = data if data is not None else wav_bytes(sung(16000, [60, 64]), 16000)
    r = call(timbre.Timbre(runtime), "POST", f"/api/desktop/timbre?{query}", content=data)
    assert r.status_code == status and words in r.json()["error"], r.text
    assert runtime.jobs.running() == [] and not runtime.jobs._jobs


def test_a_silent_too_long_or_too_large_recording_is_refused(stand_in, monkeypatch):
    runtime, _ = stand_in
    t = timbre.Timbre(runtime)
    r = call(t, "POST", "/api/desktop/timbre?instrument=sax", content=wav_bytes(np.zeros(16000 * 2), 16000))
    assert r.status_code == 400 and "silent" in r.json()["error"]
    r = call(t, "POST", "/api/desktop/timbre?instrument=sax", content=wav_bytes(np.zeros(8000 * (timbre.MAX_SECONDS + 1)), 8000))
    assert r.status_code == 400 and "takes recordings up to 10 minutes" in r.json()["error"]
    monkeypatch.setattr(timbre, "MAX_BODY", 1000)
    r = call(t, "POST", "/api/desktop/timbre?instrument=sax", content=wav_bytes(np.zeros(4000), 8000))
    assert r.status_code == 413
    assert not runtime.jobs._jobs


def test_an_instrument_needs_its_model_downloaded(tmp_path):
    runtime = models.ModelRuntime(tmp_path)
    r = call(timbre.Timbre(runtime), "POST", "/api/desktop/timbre?instrument=guitar",
             content=wav_bytes(sung(16000, [60, 64]), 16000))
    assert r.status_code == 400 and "Download Electric guitar (RAVE) first (163.9 MB)" in r.json()["error"], r.text


def test_the_routes_answer_only_the_apps_own_window_and_unknown_paths(stand_in):
    runtime, _ = stand_in
    app = desk.guarded_app(PORT, SECRET, timbre=timbre.Timbre(runtime))

    async def go(headers, path="/api/desktop/timbre?instrument=sax", method="POST"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers=headers, content=wav_bytes(sung(16000, [60, 64]), 16000))
    assert asyncio.run(go({})).status_code == 403
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET, "origin": "https://evil.example"})).status_code == 403
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, method="GET")).status_code == 405
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/timbre/x/timbre.wav", "POST")).status_code == 405
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/timbre/x/timbre.wav", "GET")).status_code == 404
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/timbre/x/other.wav", "GET")).status_code == 404
    assert not runtime.jobs._jobs
    # Without a timbre object (the hosted app never has one) the route does not exist.
    bare = desk.guarded_app(PORT, SECRET)

    async def bare_go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bare), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.post("/api/desktop/timbre?instrument=sax", headers={desk.LAUNCH_HEADER: SECRET})
    assert asyncio.run(bare_go()).status_code == 404


def test_the_catalog_pins_three_instrument_models_to_one_commit():
    assert set(timbre.INSTRUMENTS) == {"sax", "guitar", "organ"}
    commits = set()
    for spec, rate in timbre.INSTRUMENTS.values():
        assert spec in models.CATALOG and spec in models.RAVE_MODELS and rate == 48000
        assert "CC-BY-NC 4.0" in spec.licence and "LIC.1" in spec.licence
        (f,) = spec.files
        assert f.name.endswith(".ts") and "_r48000_" in f.name
        assert f.url == "https://huggingface.co/Intelligent-Instruments-Lab/rave-models/resolve/" + f.url.split("/")[-2] + "/" + f.name
        commits.add(f.url.split("/")[-2])
        assert set(spec.packages) == {"torch", "julius"}
    assert len(commits) == 1 and len(commits.pop()) == 40


# --- load_rave and transfer, with a TorchScript stand-in -------------------------------------

def _need_packages():
    missing = [p for p in models.RAVE_SAX.packages if importlib.util.find_spec(p) is None]
    if missing:
        pytest.skip(f"needs the packages {', '.join(missing)} (requirements-models.txt)")


def scripted(path, rate=48000, name="sampling_rate", methods=True):
    """Save a TorchScript stand-in for a RAVE model, its rate in the attribute `name`: forward halves
    the audio, and a cache carries the last sample of each call into the next one (added to its first
    sample), as streaming models carry their convolution caches."""
    import torch

    class StandIn(torch.nn.Module):
        def __init__(self):
            super().__init__()
            setattr(self, name, rate)
            self.register_buffer("cache", torch.zeros(1))
            self.calls = 0

        @torch.jit.export
        def encode(self, x):
            return x

        @torch.jit.export
        def decode(self, z):
            return z

        def forward(self, x):
            assert x.shape[-1] % 2048 == 0
            y = 0.5 * x
            y[..., 0] = y[..., 0] + self.cache
            self.cache = y[..., -1].reshape(1).clone()
            self.calls += 1
            return y

    class Bare(torch.nn.Module):
        def __init__(self):
            super().__init__()
            setattr(self, name, rate)

        def forward(self, x):
            return x

    torch.jit.save(torch.jit.script(StandIn() if methods else Bare()), str(path))
    return path


def test_a_rave_model_is_checked_for_its_methods_and_rate(tmp_path):
    _need_packages()
    model = timbre.load_rave(scripted(tmp_path / "a.ts"), 48000)
    assert timbre.model_rate(model) == 48000
    assert timbre.model_rate(timbre.load_rave(scripted(tmp_path / "b.ts", 44100, "sr"), 44100)) == 44100
    with pytest.raises(timbre.TimbreError, match="runs at 44100 Hz, not the 48000 Hz"):
        timbre.load_rave(scripted(tmp_path / "c.ts", 44100), 48000)
    with pytest.raises(timbre.TimbreError, match="not a RAVE encoder and decoder"):
        timbre.load_rave(scripted(tmp_path / "d.ts", methods=False), 48000)


def test_transfer_feeds_whole_blocks_in_order_and_keeps_rate_and_length(tmp_path):
    _need_packages()
    model = timbre.load_rave(scripted(tmp_path / "a.ts", 48000), 48000)
    x = sung(48000, [60, 64, 67, 72] * 3, step=0.5)[:-777]  # not a whole number of blocks
    y = timbre.transfer(model, x, 48000, 48000)
    assert y.dtype == np.float32 and len(y) == len(x)
    # Fed in order: the cache adds the end of each block to the start of the next.
    want = 0.5 * x
    for start in range(timbre.CHUNK, len(x), timbre.CHUNK):
        want[start] += want[start - 1]
    assert np.max(np.abs(y - want)) < 1e-5
    assert model.calls == -(-len(x) // timbre.CHUNK)
    # At another rate the recording is resampled to the model's and back: same length, same pitch.
    x = sung(22050, [69] * 4, step=0.5)
    y = timbre.transfer(timbre.load_rave(scripted(tmp_path / "b.ts"), 48000), x, 22050, 48000)
    assert len(y) == len(x)
    spectrum = np.abs(np.fft.rfft(y[5000:-5000]))
    assert abs(np.argmax(spectrum) * 22050 / len(y[5000:-5000]) - 440) < 3


def test_transfer_keeps_the_peak_under_full_scale_and_reports_progress(tmp_path):
    _need_packages()

    class Job:
        def __init__(self):
            self.seen = []

        def report(self, progress, message):
            self.seen.append((progress, message))
    model = timbre.load_rave(scripted(tmp_path / "a.ts"), 48000)
    x = np.full(48000 * 4, 1.0)  # forward halves it, the caches add up to 1.0 at block starts
    job = Job()
    y = timbre.transfer(model, x * 1.9, 48000, 48000, job)
    assert np.max(np.abs(y)) <= timbre.PEAK + 1e-6
    assert len(job.seen) == -(-len(x) // timbre.CHUNK)
    assert [p for p, _ in job.seen] == sorted(p for p, _ in job.seen) and job.seen[0][1] == "Playing your voice on the instrument"


def test_the_model_is_loaded_fresh_for_every_recording(tmp_path, monkeypatch):
    """A streaming model's caches carry the end of one recording into the next, so the route loads
    the model again for each one: the same recording twice gives the same instrument recording."""
    _need_packages()
    spec = models.RAVE_SAX
    runtime = installed_runtime(tmp_path / "home", [spec])
    folder = runtime.store.folder(runtime.spec(spec.id))
    path = scripted(folder / spec.files[0].name)
    body = path.read_bytes()
    runtime.catalog[spec.id] = models.ModelSpec(spec.id, spec.label, (models.ModelFile(
        spec.files[0].name, "https://example.test/m", hashlib.sha256(body).hexdigest(), len(body)),))
    st = path.stat()
    (folder / models.RECORD).write_text(json.dumps(
        {spec.files[0].name: {"sha256": hashlib.sha256(body).hexdigest(), "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    t = timbre.Timbre(runtime)
    data = wav_bytes(sung(48000, [60, 64, 67]), 48000)
    first, second = (finish(runtime, t.start(data, "sax").id) for _ in range(2))
    assert first.state == second.state == "done", (first.error, second.error)
    assert t.audio(first.id) == t.audio(second.id)


# --- The real models ------------------------------------------------------------------------

def _need_model():
    _need_packages()
    home = os.environ.get("TANDEM_TEST_MODEL_HOME")
    if os.environ.get("TANDEM_TEST_TIMBRE") != "1" or not home:
        pytest.skip("set TANDEM_TEST_TIMBRE=1 and TANDEM_TEST_MODEL_HOME to run the RAVE instrument models (450 MB)")
    return home


@pytest.fixture(scope="module")
def runtime():
    home = _need_model()
    rt = models.ModelRuntime(home)
    for spec in models.RAVE_MODELS:
        if not rt.store.installed(spec):
            job = rt.jobs.wait(rt.start_download(spec.id).id, timeout=3600)
            assert job.state == "done", job.error
    return rt


def pitch(x, rate):
    """The fundamental of a steady stretch of audio, by autocorrelation (80-1000 Hz)."""
    x = x - x.mean()
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    lo, hi = int(rate / 1000), int(rate / 80)
    return rate / (lo + np.argmax(ac[lo:hi]))


LINE = [60, 62, 64, 65, 67, 65, 64, 62, 67, 72]


@pytest.mark.model
@pytest.mark.parametrize("instrument", sorted(timbre.INSTRUMENTS))
def test_the_instrument_plays_the_sung_line_in_time_and_in_tune(runtime, instrument):
    rate, step, start = 44100, 0.5, 0.5
    x = sung(rate, LINE, step=step, start=start)
    t = timbre.Timbre(runtime)
    began = time.monotonic()
    job = finish(runtime, t.start(wav_bytes(x, rate), instrument).id)
    assert job.state == "done", job.error
    y, got_rate, _ = wav_samples(t.audio(job.id))
    print(f"\nTIMBRE.1 {instrument}: {len(x) / rate:.1f} s in {time.monotonic() - began:.1f} s")
    assert got_rate == rate and len(y) == len(x)
    # In time: quiet before the line starts, and sounding within 60 ms of it.
    env = np.abs(y)
    loud = env[int((start + 1) * rate):].max()
    assert env[:int((start - 0.05) * rate)].max() < 0.1 * loud
    onset = np.argmax(env > 0.1 * loud) / rate
    print(f"TIMBRE.1 {instrument}: onset {onset - start:+.3f} s")
    assert abs(onset - start) < 0.06
    # In tune: most notes come back within a semitone of the sung pitch.
    errors = []
    for i, m in enumerate(LINE):
        a = int((start + i * step + 0.15) * rate)
        f = pitch(y[a:a + int(0.25 * rate)], rate)
        errors.append(12 * np.log2(f / (440 * 2 ** ((m - 69) / 12))))
    print(f"TIMBRE.1 {instrument}: semitones off per note {np.round(errors, 2).tolist()}")
    assert sum(abs(e) < 1 for e in errors) >= 8
