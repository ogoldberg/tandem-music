"""GEN.2: a backing band that follows the melody, made with MusicGen-Melody (tandem_desktop/band.py).

The route tests run everywhere with a stand-in for the model. The chroma tests need torch, julius
and transformers (requirements-models.txt) and are skipped without them. The tests marked `model`
run the real MusicGen-Melody: its weights are 6.2 GB, too large for CI, so they run only when
TANDEM_TEST_BAND=1 and TANDEM_TEST_MODEL_HOME names a folder for the weights (downloaded once
through the MODEL.1 runtime, pinned and verified).
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
from tandem_desktop import band, models

PORT = 47995
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


def tune(rate, notes, step=0.5, shift=0):
    """A melody of MIDI `notes`, `step` seconds each, as a soft sawtooth-like tone with harmonics."""
    out = []
    t = np.arange(int(step * rate)) / rate
    env = np.minimum(1, np.minimum(t / 0.02, (step - t) / 0.05))
    for m in notes:
        f = 440 * 2 ** ((m + shift - 69) / 12)
        out.append(0.4 * env * sum(np.sin(2 * np.pi * f * h * t) / h for h in (1, 2, 3)))
    return np.concatenate(out)


def call(b, method, path, runtime=None, **kw):
    app = desk.guarded_app(PORT, SECRET, models=runtime, band=b)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers={desk.LAUNCH_HEADER: SECRET, **kw.pop("headers", {})}, **kw)
    return asyncio.run(go())


def finish(runtime, job_id, timeout=900):
    job = runtime.jobs.wait(job_id, timeout=timeout)
    assert job.state != "running", "the job did not finish"
    return job


# --- The prompt -----------------------------------------------------------------------------

def test_the_prompt_is_the_style_then_the_tempo_and_key():
    assert band.prompt("  lo-fi   band\twith brushed drums ", 92, "F# minor") == "lo-fi band with brushed drums, 92 bpm, in F# minor"
    assert band.prompt("rock", 120.5) == "rock, 120.5 bpm"
    assert band.prompt("rock") == "rock"


@pytest.mark.parametrize("style,bpm,key,words", [
    ("", None, None, "Describe the band's style"),
    ("   ", None, None, "Describe the band's style"),
    ("x" * (band.MAX_STYLE + 1), None, None, "under 200 characters"),
    ("rock\x07", None, None, "printable"),
    ("rock", 20, None, "between 40 and 240"),
    ("rock", None, "H major", "'C major'"),
    ("rock", None, "C major; ignore", "'C major'"),
])
def test_a_bad_style_tempo_or_key_is_refused(style, bpm, key, words):
    with pytest.raises(band.BandError, match=words):
        band.prompt(style, bpm, key)


# --- Routes, with a stand-in for the model --------------------------------------------------

@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """A runtime whose musicgen-melody files are installed (one stand-in file pinned in place of
    the real ones), with load_musicgen and generate replaced: the stand-in 'band' is the melody
    resampled to 32 kHz, `seconds` long, at half volume."""
    body = b"stand-in weights"
    spec = models.ModelSpec(band.MODEL_ID, "Backing band (MusicGen-Melody)",
                            (models.ModelFile("config.json", "https://example.test/c", hashlib.sha256(body).hexdigest(), len(body)),))
    runtime = models.ModelRuntime(tmp_path, [spec])
    folder = runtime.store.folder(spec)
    folder.mkdir(parents=True)
    (folder / "config.json").write_bytes(body)
    st = (folder / "config.json").stat()
    (folder / models.RECORD).write_text(json.dumps({"config.json": {"sha256": spec.files[0].sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    calls = {"load": 0, "release": None, "texts": []}

    def load(path, on=None):
        calls["load"] += 1
        assert (path / "config.json").read_bytes() == body
        return "model", "tokenizer"

    def generate(loaded, x, rate, text, seconds, job=None):
        assert loaded == ("model", "tokenizer")
        calls["texts"].append(text)
        for i in range(5):
            job.report(0.05 + 0.9 * i / 5, "Playing your melody with the band")
            if calls["release"] is not None:
                assert calls["release"].wait(10)
        n = int(round(seconds * band.RATE))
        src = np.interp(np.arange(n) * rate / band.RATE, np.arange(len(x)), x, right=0)
        return (0.5 * src).astype(np.float32)
    monkeypatch.setattr(band, "load_musicgen", load)
    monkeypatch.setattr(band, "generate", generate)
    return runtime, calls


def test_a_band_comes_back_as_a_wav_at_32_khz_and_the_asked_length(stand_in):
    runtime, calls = stand_in
    b = band.Band(runtime)
    x = tune(44100, [60, 62, 64, 65, 67, 69, 71, 72] * 2)  # 8 s
    r = call(b, "POST", "/api/desktop/band?style=lo-fi%20band&bpm=96&key=C%20major&seconds=5",
             content=wav_bytes(x, 44100, channels=2))
    assert r.status_code == 202 and r.headers["cache-control"] == "no-store", r.text
    job = finish(runtime, r.json()["id"])
    assert job.state == "done", job.error
    seen = call(b, "GET", f"/api/desktop/jobs/{job.id}", runtime=runtime).json()
    assert seen["result"] == {"seconds": 5.0, "rate": 32000, "prompt": "lo-fi band, 96 bpm, in C major"}
    r = call(b, "GET", f"/api/desktop/band/{job.id}/band.wav")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.headers["cache-control"] == "no-store"
    y, rate, channels = wav_samples(r.content)
    assert (rate, channels, len(y)) == (32000, 1, 5 * 32000)
    assert calls["texts"] == ["lo-fi band, 96 bpm, in C major"]
    # Without `seconds` the band is as long as the melody, up to MAX_SECONDS.
    job = finish(runtime, b.start(wav_bytes(x, 44100), "rock").id)
    assert job.result["seconds"] == 8.0
    long = np.tile(x, 5)  # 40 s
    job = finish(runtime, b.start(wav_bytes(long, 44100), "rock").id)
    assert job.result["seconds"] == band.MAX_SECONDS
    # The model is loaded once and kept for the next band.
    assert calls["load"] == 1


def test_only_the_last_bands_are_kept(stand_in):
    runtime, _ = stand_in
    b = band.Band(runtime)
    data = wav_bytes(tune(16000, [60, 64, 67, 72]), 16000)
    ids = [finish(runtime, b.start(data, "rock").id).id for _ in range(band.KEEP_RESULTS + 1)]
    assert call(b, "GET", f"/api/desktop/band/{ids[0]}/band.wav").status_code == 404
    assert call(b, "GET", f"/api/desktop/band/{ids[-1]}/band.wav").status_code == 200


def test_a_band_reports_progress_one_at_a_time_and_can_be_cancelled(stand_in):
    runtime, calls = stand_in
    calls["release"] = threading.Event()
    b = band.Band(runtime)
    data = wav_bytes(tune(16000, [60, 64, 67, 72]), 16000)
    job = b.start(data, "rock")
    deadline = time.monotonic() + 10
    while "Playing" not in job.message and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.state == "running" and "Playing your melody" in job.message and job.progress > 0
    r = call(b, "POST", "/api/desktop/band?style=rock", runtime=runtime, content=data)
    assert r.status_code == 409 and "already being generated" in r.json()["error"]
    assert call(b, "DELETE", f"/api/desktop/jobs/{job.id}", runtime=runtime).status_code == 200
    calls["release"].set()
    assert finish(runtime, job.id).state == "cancelled"
    assert call(b, "GET", f"/api/desktop/band/{job.id}/band.wav").status_code == 404


@pytest.mark.parametrize("query,data,status,words", [
    ("style=rock", b"not a wav", 400, "not a WAV"),
    ("style=", None, 400, "Describe the band's style"),
    ("style=rock&bpm=fast", None, 400, "bpm must be a number"),
    ("style=rock&bpm=300", None, 400, "bpm must be between 40 and 240"),
    ("style=rock&seconds=31", None, 400, "seconds must be between 1 and 30"),
    ("style=rock&seconds=nan", None, 400, "seconds must be between 1 and 30"),
    ("style=rock&key=X%20major", None, 400, "'C major'"),
])
def test_bad_requests_are_refused_before_any_job_starts(stand_in, query, data, status, words):
    runtime, _ = stand_in
    data = data if data is not None else wav_bytes(tune(16000, [60, 64, 67, 72]), 16000)
    r = call(band.Band(runtime), "POST", f"/api/desktop/band?{query}", content=data)
    assert r.status_code == status and words in r.json()["error"], r.text
    assert runtime.jobs.running() == [] and not runtime.jobs._jobs


def test_a_silent_short_or_too_long_melody_is_refused(stand_in, monkeypatch):
    runtime, _ = stand_in
    b = band.Band(runtime)
    r = call(b, "POST", "/api/desktop/band?style=rock", content=wav_bytes(np.zeros(16000 * 3), 16000))
    assert r.status_code == 400 and "silent" in r.json()["error"]
    r = call(b, "POST", "/api/desktop/band?style=rock", content=wav_bytes(tune(16000, [60], step=0.5), 16000))
    assert r.status_code == 400 and "1 to 30 seconds" in r.json()["error"]
    r = call(b, "POST", "/api/desktop/band?style=rock",
             content=wav_bytes(np.zeros(8000 * (band.MAX_INPUT_SECONDS + 1)), 8000))
    assert r.status_code == 400 and "The band takes recordings up to 10 minutes" in r.json()["error"]
    monkeypatch.setattr(band, "MAX_BODY", 1000)
    r = call(b, "POST", "/api/desktop/band?style=rock", content=wav_bytes(np.zeros(4000), 8000))
    assert r.status_code == 413
    assert not runtime.jobs._jobs


def test_a_band_needs_the_model_downloaded(tmp_path):
    runtime = models.ModelRuntime(tmp_path)
    r = call(band.Band(runtime), "POST", "/api/desktop/band?style=rock", content=wav_bytes(tune(16000, [60, 64, 67, 72]), 16000))
    assert r.status_code == 400 and "Download Backing band (MusicGen-Melody) first (6.23 GB)" in r.json()["error"], r.text


def test_the_routes_answer_only_the_apps_own_window_and_unknown_paths(stand_in):
    runtime, _ = stand_in
    app = desk.guarded_app(PORT, SECRET, band=band.Band(runtime))

    async def go(headers, path="/api/desktop/band?style=rock", method="POST"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.request(method, path, headers=headers, content=wav_bytes(tune(16000, [60, 64, 67, 72]), 16000))
    assert asyncio.run(go({})).status_code == 403
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET, "origin": "https://evil.example"})).status_code == 403
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, method="GET")).status_code == 405
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/band/x/band.wav", "POST")).status_code == 405
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/band/x/band.wav", "GET")).status_code == 404
    assert asyncio.run(go({desk.LAUNCH_HEADER: SECRET}, "/api/desktop/band/x/other.wav", "GET")).status_code == 404
    assert not runtime.jobs._jobs
    # Without a band object (the hosted app never has one) the route does not exist.
    bare = desk.guarded_app(PORT, SECRET)

    async def bare_go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bare), base_url=f"http://127.0.0.1:{PORT}") as c:
            return await c.post("/api/desktop/band?style=rock", headers={desk.LAUNCH_HEADER: SECRET})
    assert asyncio.run(bare_go()).status_code == 404


def test_the_catalog_pins_musicgen_melody_without_pickles():
    spec = models.MUSICGEN_MELODY
    assert spec in models.CATALOG and "CC-BY-NC 4.0" in spec.licence and "LIC.1" in spec.licence
    names = [f.name for f in spec.files]
    assert not [n for n in names if n.endswith((".bin", ".pt", ".pth", ".ckpt", ".pkl"))]
    assert {"config.json", "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors", "tokenizer.json"} <= set(names)
    for f in spec.files:
        assert f.url.startswith("https://huggingface.co/facebook/musicgen-melody/resolve/") and len(f.url.split("/")[-2]) == 40
    assert set(spec.packages) <= {"torch", "transformers", "safetensors", "julius"}


def test_transformers_is_pinned_in_requirements_models():
    text = open(os.path.join(os.path.dirname(__file__), "..", "requirements-models.txt")).read()
    pinned = {line.split("==")[0].strip().lower() for line in text.splitlines() if "==" in line and not line.startswith("#")}
    assert {"torch", "transformers", "safetensors"} <= pinned


# --- The chroma the model follows ------------------------------------------------------------

def _need_packages():
    missing = [p for p in models.MUSICGEN_MELODY.packages if importlib.util.find_spec(p) is None]
    if missing:
        pytest.skip(f"needs the packages {', '.join(missing)} (requirements-models.txt)")


def test_the_chroma_of_a_tone_is_its_pitch_class():
    _need_packages()
    rate = 44100
    for midi in (57, 60, 66):  # A, C, F#
        f = 440 * 2 ** ((midi - 69) / 12)
        x = 0.5 * np.sin(2 * np.pi * f * np.arange(rate * 2) / rate)
        chroma = band.melody_chroma(x, rate, 2)
        assert chroma.shape == (1, 2 * band.RATE // band.HOP + 1, 12)
        assert (chroma.sum(-1) == 1).all()
        # The chroma bins start at C, as in audiocraft's and transformers' extractors.
        assert (chroma[0].argmax(-1) == (midi - 60) % 12).all()


def test_the_chroma_follows_the_melody_and_stops_at_seconds():
    _need_packages()
    rate = 32000
    x = tune(rate, [60, 67], step=1.0)
    chroma = band.melody_chroma(x, rate, 2)[0].argmax(-1).tolist()
    assert chroma[1:6] == [0] * 5 and chroma[-6:-1] == [7] * 5  # C, then G
    assert band.melody_chroma(x, rate, 1).shape[1] == band.RATE // band.HOP + 1
    # A melody shorter than one analysis window is padded, not refused.
    assert band.melody_chroma(x[:4000], rate, 0.125).shape == (1, band.N_FFT // band.HOP + 1, 12)


def test_the_chroma_matches_transformers_feature_extractor_when_torchaudio_is_there():
    _need_packages()
    if importlib.util.find_spec("torchaudio") is None:
        pytest.skip("torchaudio has no release for the pinned torch; the chroma is checked against pitch above")
    from transformers import MusicgenMelodyFeatureExtractor
    rate = 32000
    x = tune(rate, [60, 62, 64, 65, 67], step=0.4).astype(np.float32)
    want = MusicgenMelodyFeatureExtractor()(x, sampling_rate=rate, return_tensors="pt")["input_features"]
    got = band.melody_chroma(x, rate, len(x) / rate)
    assert got.shape == want.shape and (got == want).all()


# --- The real model -------------------------------------------------------------------------

def _need_model():
    _need_packages()
    home = os.environ.get("TANDEM_TEST_MODEL_HOME")
    if os.environ.get("TANDEM_TEST_BAND") != "1" or not home:
        pytest.skip("set TANDEM_TEST_BAND=1 and TANDEM_TEST_MODEL_HOME to run MusicGen-Melody (6.2 GB)")
    return home


@pytest.fixture(scope="module")
def runtime():
    home = _need_model()
    rt = models.ModelRuntime(home)
    if not rt.store.installed(models.MUSICGEN_MELODY):
        job = rt.jobs.wait(rt.start_download(models.MUSICGEN_MELODY.id).id, timeout=7200)
        assert job.state == "done", job.error
    return rt


def profile(x, rate):
    """The share of frames whose strongest pitch class is each of the 12."""
    chroma = band.melody_chroma(x, rate, len(x) / rate)[0].numpy()
    return chroma.mean(0)


MELODY = [60, 64, 67, 64, 60, 64, 67, 72, 71, 67, 62, 67, 60, 64, 67, 64]  # C major, then G, then C


@pytest.mark.model
def test_the_band_follows_the_melody_it_is_given(runtime):
    """Two bands, one from the melody and one from the same melody a tritone up: each band's pitch
    classes match its own melody better than the other's."""
    b = band.Band(runtime)
    bands, melodies = [], []
    for shift in (0, 6):
        x = tune(32000, MELODY, step=0.5, shift=shift)
        melodies.append(profile(x, 32000))
        started = time.monotonic()
        job = finish(runtime, b.start(wav_bytes(x, 32000), "pop band with piano, bass and drums", 120, None, 8).id)
        assert job.state == "done", job.error
        y, rate, _ = wav_samples(b.audio(job.id))
        print(f"\nGEN.2: 8 s band (shift {shift}) in {time.monotonic() - started:.1f} s")
        assert rate == band.RATE and len(y) == 8 * band.RATE
        assert np.sqrt(np.mean(y ** 2)) > 0.01  # not silence
        bands.append(profile(y, rate))
    cos = lambda a, b: float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))  # noqa: E731
    own = [cos(bands[i], melodies[i]) for i in range(2)]
    other = [cos(bands[i], melodies[1 - i]) for i in range(2)]
    print(f"GEN.2 chroma match: own melody {own}, the other melody {other}")
    assert own[0] > other[0] and own[1] > other[1]
