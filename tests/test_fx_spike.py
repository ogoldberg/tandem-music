"""FX.0: the spike's measurement (tools/fx-spike/spike.py) and, where the toolchain is present, its build.

The comparison and echo finding are checked on synthetic signals. The build test needs Emscripten
7.0.0 and a host clang++ (the operator's Mac; not CI) and checks the WebAssembly and native renders of
an impulse are bit for bit the same and echo where the delay puts them.
"""
import importlib.util
import pathlib
import shutil
import subprocess

import numpy as np
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "tools" / "fx-spike" / "spike.py"
spec = importlib.util.spec_from_file_location("fx_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)
RATE = spike.RATE


def test_compare_finds_a_one_ulp_difference():
    a = np.linspace(-0.5, 0.5, 1000, dtype=np.float32)
    assert spike.compare(a, a.copy())["bit_exact"]
    b = a.copy()
    b[500] = np.nextafter(b[500], np.float32(1))
    r = spike.compare(a, b)
    assert not r["bit_exact"]
    assert r["identical"] == 999
    assert 0 < r["max_abs_diff"] < 1e-6
    assert r["null_db"] < -100


def test_compare_refuses_renders_of_different_lengths():
    with pytest.raises(ValueError):
        spike.compare(np.zeros(10, np.float32), np.zeros(11, np.float32))


def test_the_expected_echoes_follow_the_routing():
    assert spike.delay_seconds("defaults") == pytest.approx(0.25)  # 1/8 at 120 bpm
    assert spike.delay_seconds("free") == pytest.approx(0.35)
    pp = spike.expected_echoes("defaults", 3)
    assert pp["left"] == pytest.approx([1.25, 1.75, 2.25])
    assert pp["right"] == pytest.approx([1.5, 2.0, 2.5])
    free = spike.expected_echoes("free", 2)
    assert free["left"] == free["right"] == pytest.approx([1.35, 1.7])


def test_echo_peaks_finds_each_echo_once():
    y = np.zeros(int(3 * RATE), np.float32)
    y[int(1.0 * RATE)] = 1.0  # the impulse itself is not an echo
    for t, g in [(1.25, 0.2), (1.75, 0.05), (2.25, 0.01)]:
        i = int(t * RATE)
        y[i:i + 40] = g * np.exp(-np.arange(40) / 5)  # a filtered echo: one peak, a short tail
    assert spike.echo_peaks(y) == pytest.approx([1.25, 1.75, 2.25], abs=1 / RATE)


def _toolchain():
    if not shutil.which("emcc") or not shutil.which("clang++") or not shutil.which("node"):
        return False
    out = subprocess.run(["emcc", "--version"], capture_output=True, text=True).stdout
    return " 7.0.0" in out.splitlines()[0]


@pytest.mark.skipif(not _toolchain(), reason="needs Emscripten 7.0.0, clang++ and node")
def test_wasm_and_native_builds_render_an_impulse_identically(tmp_path):
    build = tmp_path / "build"
    subprocess.run(["bash", str(REPO / "tools" / "fx-spike" / "build.sh"), str(build)], check=True,
                   capture_output=True)
    x = np.zeros(int(3.5 * RATE), np.float32)
    x[int(spike.IMPULSE_AT * RATE)] = 1.0
    (tmp_path / "impulse.f32").write_bytes(x.astype("<f4").tobytes())
    for setting in spike.SETTINGS:
        (nl, nr), _ = spike.run_native(build, tmp_path, "impulse", setting, len(x))
        (wl, wr), _ = spike.run_node(build, tmp_path, "impulse", setting, len(x))
        assert spike.compare(np.concatenate([nl, nr]), np.concatenate([wl, wr]))["bit_exact"]
        exp = spike.expected_echoes(setting, 2)
        # The SDK's float Smoother stalls about 1.7 samples short of the delay time, so each repeat
        # lands about two samples earlier than the last (the right channel's second echo, four delays in, is 5 early).
        assert spike.echo_peaks(nl)[:2] == pytest.approx(exp["left"], abs=8 / RATE)
        assert spike.echo_peaks(nr)[:2] == pytest.approx(exp["right"], abs=8 / RATE)
