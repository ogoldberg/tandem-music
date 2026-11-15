"""ROFORMER.0: the spike's clips, its measures and its overlap-add (tools/roformer-spike/spike.py).

These check the measurement, not the models: the RoFormers and HTDemucs run only through the spike's own commands.
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pytest

pytest.importorskip("pyworld")
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import separation_fixture as fx  # noqa: E402

SPIKE = REPO / "tools" / "roformer-spike" / "spike.py"
spec = importlib.util.spec_from_file_location("roformer_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


@pytest.fixture(scope="module")
def song():
    return fx.song()


def test_the_clips_are_the_fixtures_mix_its_parts_and_the_mix_repeated(tmp_path, song):
    spike.cmd_clips(type("A", (), {"out": str(tmp_path)}))
    clips = tmp_path / "clips"
    mix, voice, band = (spike.read_wav(clips / f"{n}.wav")[0] for n in ("mix", "voice", "band"))
    q = 1.5 / 32767  # one 16-bit step each way
    assert np.max(np.abs(mix - song[0])) <= q and np.max(np.abs(voice + band - mix)) <= 3 * q
    long, rate = spike.read_wav(clips / "song.wav")
    assert rate == spike.RATE and len(long) == spike.SONG_SECONDS * rate
    assert np.array_equal(long[len(mix):2 * len(mix)], mix)


def test_a_perfect_vocal_has_no_error_and_no_band(song):
    mix, voice, band = song
    m = spike.measures(voice.copy(), voice, band, mix)
    assert m["sdr_db"] >= 150 and abs(m["band_gain"]) < 1e-9 and m["corr_voice"] == 1


def test_band_left_in_the_vocal_is_measured_at_its_level(song):
    mix, voice, band = song
    m = spike.measures(0.9 * voice + 0.1 * band, voice, band, mix)
    assert m["band_gain"] == pytest.approx(0.1, abs=1e-4)
    expect = 20 * np.log10(0.1 * spike.rms(band) / (0.9 * spike.rms(voice)))
    assert m["band_in_vocal_db"] == pytest.approx(expect, abs=0.01)
    # The error is the band plus the voice's lost tenth.
    err = 0.1 * band - 0.1 * voice
    assert m["sdr_db"] == pytest.approx(10 * np.log10(np.sum(voice ** 2) / np.sum(err ** 2)), abs=0.01)


def test_a_vocal_that_is_the_band_reads_as_the_band(song):
    mix, voice, band = song
    m = spike.measures(band.copy(), voice, band, mix)
    assert m["band_gain"] == pytest.approx(1, abs=1e-6) and m["corr_band"] == 1 and m["sdr_db"] < 0


def test_the_summary_is_the_mean_and_range_of_the_runs():
    s = spike.summary([{"recall": 0.5, "sdr_db": 6}, {"recall": 0.75, "sdr_db": 8}])
    assert s == {"recall": 0.625, "recall_range": [0.5, 0.75], "sdr_db": 7, "sdr_db_range": [6, 8]}


@pytest.mark.parametrize("seconds", [3.0, 9.0, 20.3])
@pytest.mark.parametrize("stems_axis", [False, True])
def test_the_overlap_add_gives_back_what_the_model_gives_for_each_chunk(seconds, stems_axis):
    """With a model that hands its chunk back unchanged, the windows and padding cancel: the track
    comes out as it went in, at its own length, for tracks shorter and longer than a chunk."""
    torch = pytest.importorskip("torch")

    class Same(torch.nn.Module):
        def forward(self, x):
            return x[:, None] if stems_axis else x

    cfg = {"audio": {"chunk_size": 44100 * 4}, "inference": {"num_overlap": 2, "batch_size": 3}}
    rng = np.random.default_rng(3)
    x = rng.standard_normal((2, int(seconds * 44100))).astype(np.float32)
    y = spike.demix(Same(), cfg, x, "cpu", lambda: None)
    assert y.shape == x.shape
    assert np.max(np.abs(y - x)) < 1e-5


def test_the_overlap_add_uses_the_inference_chunk_size_when_the_config_has_one():
    torch = pytest.importorskip("torch")
    seen = []

    class Spy(torch.nn.Module):
        def forward(self, x):
            seen.append(x.shape[-1])
            return x

    cfg = {"audio": {"chunk_size": 44100 * 8}, "inference": {"chunk_size": 44100, "num_overlap": 4, "batch_size": 2}}
    spike.demix(Spy(), cfg, np.zeros((2, 44100 * 3), np.float32), "cpu", lambda: None)
    assert set(seen) == {44100}


def test_every_model_is_pinned_to_one_commit_with_its_hash_and_licence():
    for name, m in spike.MODELS.items():
        assert "/resolve/" in m["url"] and m["url"].endswith(m["file"]), name
        commit = m["url"].split("/resolve/")[1].split("/")[0]
        assert len(commit) == 40, name
        assert len(m["sha256"]) == 64 and m["bytes"] > 0 and m["licence"], name
