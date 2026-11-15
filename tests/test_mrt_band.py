"""MRT.1: a band from the notes, made with Magenta RealTime 2 (tandem_desktop/band.py).

The route tests run everywhere with a stand-in for the model that records what it is given each
step, so they check that the notes become the piano roll frame by frame. The test marked `model`
runs the real mrt2_small through MLX (Apple silicon, the packages in requirements-models.txt): it
runs only when TANDEM_TEST_MRT=1 and TANDEM_TEST_MODEL_HOME names a folder for the weights
(1.04 GB, downloaded once through the MODEL.1 runtime, pinned and verified).
"""
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import threading
import time
import wave

import numpy as np
import pytest

from tandem_desktop import band, models
from test_band import call, finish

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "notation-project.json"
STEP = band.MRT_RATE // band.MRT_FRAME_RATE  # samples per 40 ms frame
KEYS = ("style-key", "notes-key", "drums-key")


def installed_runtime(home, *ids):
    """A runtime whose models `ids` are installed: one stand-in file each, pinned in place of the real ones."""
    body = b"stand-in weights"
    specs = [models.ModelSpec(i, i, (models.ModelFile("w.safetensors", "https://example.test/w",
                                                      hashlib.sha256(body).hexdigest(), len(body)),)) for i in ids]
    runtime = models.ModelRuntime(home, specs)
    for spec in specs:
        folder = runtime.store.folder(spec)
        folder.mkdir(parents=True)
        (folder / "w.safetensors").write_bytes(body)
        st = (folder / "w.safetensors").stat()
        (folder / models.RECORD).write_text(json.dumps(
            {"w.safetensors": {"sha256": spec.files[0].sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    return runtime


class StandInMRT:
    """Records each step's conditioning and plays a 220 Hz tone, one 40 ms stereo frame a step."""

    def __init__(self, release=None):
        self.steps, self.styles, self.release = [], [], release

    def embed_style(self, text, use_mapper=False):
        self.styles.append((text, use_mapper))
        return "embedding"

    def tokenize_style(self, embedding):
        assert embedding == "embedding"
        return np.arange(20)

    def generate(self, conditioning, cfg_scales, frames, state):
        assert frames == 1 and cfg_scales == {"notes": band.MRT_NOTES_GUIDANCE}
        if state is None:  # a new band starts from the model's initial state
            self.steps = []
        assert state == (None if not self.steps else len(self.steps)), "each step carries the state on"
        if self.release is not None:
            assert self.release.wait(10)
        self.steps.append(conditioning)
        t = (len(self.steps) - 1) * STEP + np.arange(STEP)
        tone = 0.3 * np.sin(2 * np.pi * 220 * t / band.MRT_RATE)

        class Wav:
            samples = np.stack([tone, tone], 1).astype(np.float32)
        return Wav(), len(self.steps)


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    runtime = installed_runtime(tmp_path, band.MODEL_ID, band.MRT_MODEL_ID)
    made = {"mrt": [], "loads": []}

    def load(folder):
        made["loads"].append(("mrt", folder.name))
        mrt = StandInMRT(made.get("release"))
        made["mrt"].append(mrt)
        return mrt, KEYS

    def load_musicgen(folder, on=None):
        made["loads"].append(("musicgen", folder.name))
        return "model", "tokenizer"

    def generate(loaded, x, rate, text, seconds, job=None):
        job.report(0.5, "Playing your melody with the band")
        if made.get("release") is not None:
            assert made["release"].wait(10)
        return np.zeros(int(seconds * band.RATE), dtype=np.float32)
    monkeypatch.setattr(band, "load_mrt", load)
    monkeypatch.setattr(band, "load_musicgen", load_musicgen)
    monkeypatch.setattr(band, "generate", generate)
    return runtime, made


def samples(data):
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768, w.getframerate()


def fixture_notes():
    project = json.loads(FIXTURE.read_text())["project"]
    return project["notes"] + project["harmony"]


# --- The piano roll ---------------------------------------------------------------------------

def test_a_note_is_its_onset_frame_then_held_frames_from_zero():
    roll = band.piano_roll([{"m": 60, "t": 0.0, "d": 0.2}, {"m": 64, "t": 0.4, "d": 0.01}], 1.0)
    assert roll.shape == (25, 128) and roll.dtype == np.int8
    assert roll[0, 60] == 2 and (roll[1:5, 60] == 1).all() and roll[5, 60] == 0
    # A note shorter than a frame still sounds for one frame: its onset.
    assert roll[10, 64] == 2 and roll[11, 64] == 0
    assert roll.sum() == 2 + 4 + 2


def test_a_repeated_note_starts_again_and_the_roll_stops_at_the_length():
    roll = band.piano_roll([{"m": 67, "t": 0.0, "d": 0.4}, {"m": 67, "t": 0.2, "d": 0.4}, {"m": 48, "t": 0.9, "d": 5.0},
                            {"m": 50, "t": 1.0, "d": 1.0}], 1.0)
    assert roll[:, 67].tolist()[:16] == [2, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0]
    assert roll[22, 48] == 2 and (roll[23:, 48] == 1).all(), "a long note is held to the end of the band"
    assert not roll[:, 50].any(), "a note starting at the end is not in the band"


@pytest.mark.parametrize("body,words", [
    (b"not json", "as JSON"),
    (b'{"melody": []}', "as JSON"),
    (b'{"notes": [{"m": 128, "t": 0, "d": 1}]}', "0 to 127"),
    (b'{"notes": [{"m": 60.5, "t": 0, "d": 1}]}', "0 to 127"),
    (b'{"notes": [{"m": 60, "t": -1, "d": 1}]}', "starts at 0"),
    (b'{"notes": [{"m": 60, "t": 0, "d": 0}]}', "lasts more than"),
    (b'{"notes": [{"m": 60, "t": "0", "d": 1}]}', "numbers of seconds"),
    (b'{"notes": [{"m": 60, "t": 0, "d": 1, "v": 1}]}', "{m, t, d}"),
])
def test_bad_notes_are_refused(body, words):
    with pytest.raises(band.BandError, match=words.replace("{", r"\{").replace("}", r"\}")):
        band.clean_notes(body)


# --- The route, with a stand-in model ------------------------------------------------------------

def test_the_notes_become_the_piano_roll_frame_by_frame_and_the_band_comes_back(stand_in):
    runtime, made = stand_in
    notes = fixture_notes()
    r = call(band.Band(runtime), "POST", "/api/desktop/band/notes?style=pop%20band&seconds=10&drums=0", runtime,
             content=json.dumps({"notes": notes}), headers={"content-type": "application/json"})
    assert r.status_code == 202, r.text
    job = finish(runtime, r.json()["id"])
    assert job.state == "done", job.error
    assert job.result == {"seconds": 10, "rate": 48000, "style": "pop band", "drums": False}
    (mrt,) = made["mrt"]
    assert made["loads"] == [("mrt", "mrt2_small")]
    assert mrt.styles == [("pop band", True)], "the style is mapped from words to music space"
    # One step per 40 ms frame, each with that frame's notes, the style tokens and the drums setting.
    want = band.piano_roll(notes, 10)
    assert len(mrt.steps) == len(want) == 250
    for i, step in enumerate(mrt.steps):
        assert set(step) == set(KEYS)
        assert step["notes-key"] == want[i].tolist(), f"frame {i}"
        assert step["style-key"] == list(range(12)) and step["drums-key"] == [0]
    melody_first = min(notes, key=lambda n: n["t"])
    assert mrt.steps[0]["notes-key"][melody_first["m"]] == 2, "the band starts with the song, at zero"


def test_the_band_is_kept_by_its_route_and_fetched_as_mono_48_khz(stand_in):
    runtime, made = stand_in
    b = band.Band(runtime)
    job = finish(runtime, b.start_notes(json.dumps({"notes": [{"m": 60, "t": 0, "d": 2}]}).encode(), "rock", 2, True).id)
    assert job.state == "done", job.error
    r = call(b, "GET", f"/api/desktop/band/{job.id}/band.wav", runtime)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    y, rate = samples(r.content)
    assert rate == 48000 and len(y) == 2 * 48000
    t = np.arange(len(y)) / rate
    assert np.max(np.abs(y - 0.3 * np.sin(2 * np.pi * 220 * t))) < 2 / 32768, "the stereo frames are joined in order"
    assert made["mrt"][0].steps[0]["drums-key"] == [1]


def test_the_length_defaults_to_the_notes_and_is_at_most_30_s(stand_in):
    runtime, made = stand_in
    b = band.Band(runtime)
    job = finish(runtime, b.start_notes(json.dumps({"notes": [{"m": 60, "t": 1, "d": 1.5}]}).encode(), "rock").id)
    assert job.result["seconds"] == 2.5 and len(made["mrt"][0].steps) == round(2.5 * 25)
    job = finish(runtime, b.start_notes(json.dumps({"notes": [{"m": 60, "t": 0, "d": 100}]}).encode(), "rock").id)
    assert job.result["seconds"] == 30 and len(made["mrt"][0].steps) == 750
    assert made["loads"] == [("mrt", "mrt2_small")], "the model is loaded once"


@pytest.mark.parametrize("query,body,status,words", [
    ("style=rock&drums=2", b'{"notes": [{"m": 60, "t": 0, "d": 1}]}', 400, "drums must be 0 or 1"),
    ("style=&drums=1", b'{"notes": [{"m": 60, "t": 0, "d": 1}]}', 400, "Describe the band's style"),
    ("style=rock&seconds=31", b'{"notes": [{"m": 60, "t": 0, "d": 1}]}', 400, "seconds must be between 1 and 30"),
    ("style=rock", b'{"notes": []}', 400, "no notes"),
    ("style=rock&seconds=2", b'{"notes": [{"m": 60, "t": 5, "d": 1}]}', 400, "No note starts"),
    ("style=rock", b"[]", 400, "as JSON"),
])
def test_bad_requests_are_refused_before_any_job_starts(stand_in, query, body, status, words):
    runtime, made = stand_in
    r = call(band.Band(runtime), "POST", "/api/desktop/band/notes?" + query, runtime, content=body)
    assert r.status_code == status and words in r.json()["error"], r.text
    assert runtime.jobs.running() == [] and made["loads"] == []


def test_too_many_notes_are_refused(stand_in, monkeypatch):
    runtime, _ = stand_in
    many = json.dumps({"notes": [{"m": 60, "t": i * 0.01, "d": 0.01} for i in range(band.MAX_NOTES + 1)]}).encode()
    with pytest.raises(band.BandError, match="at most 4096 notes"):
        band.clean_notes(many)
    monkeypatch.setattr(band, "MAX_NOTES_BODY", 100)
    r = call(band.Band(runtime), "POST", "/api/desktop/band/notes?style=rock", runtime, content=many)
    assert r.status_code == 413
    r = call(band.Band(runtime), "GET", "/api/desktop/band/notes", runtime)
    assert r.status_code == 405


def test_one_band_at_a_time_whichever_engine_and_one_model_held(stand_in):
    runtime, made = stand_in
    release = made["release"] = threading.Event()
    b = band.Band(runtime)
    notes = json.dumps({"notes": [{"m": 60, "t": 0, "d": 1}]}).encode()
    first = b.start_notes(notes, "rock", 1)
    try:
        for start in (lambda: b.start_notes(notes, "rock", 1),
                      lambda: b.start(wav_tone(), "rock", None, None, 1)):
            with pytest.raises(models.ModelBusy, match="already being generated"):
                start()
    finally:
        release.set()
    assert finish(runtime, first.id).state == "done"
    made["release"] = None
    # MusicGen next: the Magenta model is let go before MusicGen is loaded, and loaded again after.
    assert finish(runtime, b.start(wav_tone(), "rock", None, None, 1).id).state == "done"
    assert b._loaded[0] == band.MODEL_ID
    assert finish(runtime, b.start_notes(notes, "rock", 1).id).state == "done"
    assert b._loaded[0] == band.MRT_MODEL_ID
    assert made["loads"] == [("mrt", "mrt2_small"), ("musicgen", "musicgen-melody"), ("mrt", "mrt2_small")]


def wav_tone():
    rate = 16000
    x = 0.4 * np.sin(2 * np.pi * 330 * np.arange(rate) / rate)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return out.getvalue()


def test_a_band_from_the_notes_needs_its_model_downloaded(tmp_path):
    runtime = models.ModelRuntime(tmp_path, [models.MRT2_SMALL])
    r = call(band.Band(runtime), "POST", "/api/desktop/band/notes?style=rock", runtime,
             content=b'{"notes": [{"m": 60, "t": 0, "d": 1}]}')
    assert r.status_code == 400 and r.json()["error"] == "Download Band from the notes (Magenta RealTime 2) first (1.04 GB)."


# --- The catalog and the packages ----------------------------------------------------------------

def test_the_catalog_pins_mrt2_small_in_one_folder_without_pickles():
    spec = models.MRT2_SMALL
    assert spec in models.CATALOG and spec.id == band.MRT_MODEL_ID == "mrt2_small"
    assert "CC-BY 4.0" in spec.licence and "CC-BY-NC" not in spec.licence and "LIC.1" in spec.licence
    names = [f.name for f in spec.files]
    # magenta_rt finds the graph at models/<name>/<name>.mlxfn: the folder is the model's id.
    assert {f"{spec.id}.mlxfn", f"{spec.id}_state.safetensors", "spm.model", "text_encoder.tflite", "mapper.tflite",
            "pretrained_vector_quantizer.tflite"} == set(names)
    assert not [n for n in names if n.endswith((".bin", ".pt", ".pth", ".ckpt", ".pkl", ".npz"))]
    for f in spec.files:
        assert f.url.startswith("https://huggingface.co/google/magenta-realtime-2/resolve/010aa0dcb0dfd27b24f0ad07b4dad63e8f9521cc/")
        assert f.url.endswith("/" + f.name)
    assert spec.size == 1042112092 and set(spec.packages) == {"magenta_rt", "mlx"}


def test_magenta_rt_and_mlx_are_pinned_for_apple_silicon_only():
    lines = [line for line in (ROOT / "requirements-models.txt").read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    pins = {line.split("==")[0].split("[")[0].strip().lower(): line for line in lines if "==" in line}
    for name, version in (("magenta-rt", "2.0.3"), ("mlx", "0.31.1"), ("mlx-metal", "0.31.1")):
        assert f"=={version};" in pins[name].replace(" ", ""), pins[name]
        assert 'sys_platform=="darwin"' in pins[name].replace(" ", "") and 'platform_machine=="arm64"' in pins[name].replace(" ", "")


# --- The real model --------------------------------------------------------------------------------

def _need_model():
    missing = [p for p in models.MRT2_SMALL.packages if importlib.util.find_spec(p) is None]
    home = os.environ.get("TANDEM_TEST_MODEL_HOME")
    if os.environ.get("TANDEM_TEST_MRT") != "1" or not home:
        pytest.skip("set TANDEM_TEST_MRT=1 and TANDEM_TEST_MODEL_HOME to run Magenta RealTime 2 (1.04 GB)")
    if missing:
        pytest.skip(f"needs the packages {', '.join(missing)} (requirements-models.txt, Apple silicon)")
    return home


def _spike():
    spec = importlib.util.spec_from_file_location("mrt_spike", ROOT / "tools" / "mrt-spike" / "spike.py")
    spike = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spike)
    return spike


@pytest.mark.model
def test_the_band_plays_the_project_notes_better_than_the_same_notes_a_tritone_up():
    """The fixture's melody and chords, and the same notes a tritone up: each band's strongest pitch
    class, frame by frame, matches the notes it was given far better than the other notes."""
    home = _need_model()
    runtime = models.ModelRuntime(home)
    if not runtime.store.installed(models.MRT2_SMALL):
        job = runtime.jobs.wait(runtime.start_download(models.MRT2_SMALL.id).id, timeout=7200)
        assert job.state == "done", job.error
    spike, b = _spike(), band.Band(runtime)
    notes = fixture_notes()
    up = [{**n, "m": n["m"] + 6} for n in notes]
    rolls = [band.piano_roll(notes, 10), band.piano_roll(up, 10)]
    for i, given in enumerate((notes, up)):
        started = time.monotonic()
        job = finish(runtime, b.start_notes(json.dumps({"notes": given}).encode(), "pop band with piano, bass and drums", 10).id)
        assert job.state == "done", job.error
        took = time.monotonic() - started
        y, rate = samples(b.audio(job.id))
        assert rate == 48000 and len(y) == 10 * 48000 and np.sqrt(np.mean(y ** 2)) > 0.01
        own, other = spike.scores(y, [rolls[i], rolls[1 - i]])
        print(f"\nMRT.1: 10 s band ({'tritone up' if i else 'the notes'}) in {took:.1f} s, model load included;"
              f" frame match own {own['frame_match_best']} (lag {own['best_lag_ms']} ms), other {other['frame_match_best']}")
        assert own["frame_match_best"] >= 0.5 and own["frame_match_best"] > other["frame_match_best"] + 0.3
