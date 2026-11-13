"""VOX.1: automated benchmark for WORLD vocal pitch correction through /api/tune.

Synthetic sung phrases with known MIDI targets are rendered detuned, at several sample rates,
with vibrato, breath noise and glides between notes. Each is sent through the real /api/tune
route (in process, like tests/test_api.py) and the output is measured with an independent YIN
pitch tracker (not WORLD's own F0 analysis). Metrics: pitch error against the intended notes,
length and note-transition timing, loudness change, and 0%-strength equivalence.

Thresholds are documented in docs/AUDIO.md ("Pitch-correction benchmark"). The measured metrics
are written as JSON to .pytest_cache/d/vox1/metrics.json, or to $TANDEM_VOX_REPORT if set.
"""
import asyncio
import io
import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import httpx
import numpy as np
import pytest

pytest.importorskip("pyworld")
import request_guards as guards  # noqa: E402
import tandem_backend as server  # noqa: E402
import world_tuning  # noqa: E402

RATES = [16000, 22050, 44100, 48000]
# (MIDI target, how far off it is sung in cents). A short phrase: C4 E4 G4 F4.
PHRASE = [(60, +40), (64, -35), (67, +30), (65, -45)]
# The same notes sung more than 50 cents off, so nearest-semitone snapping lands on the wrong note
# and only a tuner that follows the note targets can get them right.
FAR_PHRASE = [(60, +60), (64, -65), (67, +70), (65, -55)]
NOTE_SECONDS = 0.8
LEAD_SECONDS = 0.15  # silence before and after the phrase
CASES = {
    #             glide s, vibrato cents, noise SNR dB
    "steady":     (0.03, 0, None),
    "vibrato":    (0.03, 25, None),
    "noise":      (0.03, 0, 25),
    "transitions": (0.15, 0, None),
}
# Frames this close to a note change are transition, not note interior, and are not scored for pitch.
EDGE_SECONDS = 0.12

# Thresholds (keep in sync with docs/AUDIO.md).
MAX_MEDIAN_CENTS_TARGETS = 3.0    # with note targets, strength 1
MAX_P90_CENTS_TARGETS = 6.0
MAX_MEDIAN_CENTS_SNAP = 3.0       # nearest-semitone snapping, strength 1
MIN_IMPROVEMENT = 10.0            # median error must drop at least this many times
MAX_TRANSITION_SHIFT_S = 0.02     # note changes stay where they were sung
MAX_NOTE_LOUDNESS_CHANGE_DB = 1.0
MAX_CLIP_LOUDNESS_CHANGE_DB = 0.5
MAX_HALF_STRENGTH_RATIO = (0.35, 0.65)  # strength .5 leaves this share of the original error
MAX_KEEP_VIBRATO_CENTRE_CENTS = 5.0     # vibrato=1: each note's median pitch lands on its target
KEEP_VIBRATO_DEPTH_RATIO = (0.8, 1.2)   # vibrato=1: per-note pitch spread stays within this share


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def render(case, rate, seed=0, phrase=PHRASE):
    """A harmonic 'voice' singing `phrase` detuned, with the case's glide, vibrato and noise.

    Returns (samples, note list with intended targets and their times in seconds).
    """
    glide, vibrato_cents, snr_db = CASES[case]
    n_notes = len(phrase)
    total = LEAD_SECONDS * 2 + NOTE_SECONDS * n_notes
    t = np.arange(int(round(total * rate))) / rate
    rel = t - LEAD_SECONDS
    # Sung pitch in MIDI (fractional): each note held detuned, joined by linear glides.
    sung = np.array([m + c / 100 for m, c in phrase])
    idx = np.clip(np.floor(rel / NOTE_SECONDS).astype(int), 0, n_notes - 1)
    pitch = sung[idx].copy()
    for k in range(1, n_notes):
        start = k * NOTE_SECONDS - glide / 2
        in_glide = (rel >= start) & (rel < start + glide)
        frac = (rel[in_glide] - start) / glide
        pitch[in_glide] = sung[k - 1] + (sung[k] - sung[k - 1]) * frac
    if vibrato_cents:
        pitch += vibrato_cents / 100 * np.sin(2 * np.pi * 5.5 * rel)
    hz = 440.0 * 2 ** ((pitch - 69) / 12)
    phase = 2 * np.pi * np.cumsum(hz) / rate
    voice = sum((0.8 ** k) / k * np.sin(k * phase) for k in range(1, 11))
    # Amplitude: phrase envelope with 20 ms fades, silence in the lead-in and tail.
    sung_region = (rel >= 0) & (rel < NOTE_SECONDS * n_notes)
    env = np.zeros_like(t)
    env[sung_region] = 1
    fade = int(0.02 * rate)
    on = np.flatnonzero(sung_region)
    env[on[:fade]] = np.linspace(0, 1, fade)
    env[on[-fade:]] = np.linspace(1, 0, fade)
    x = 0.3 * voice / np.max(np.abs(voice)) * env
    if snr_db is not None:
        rng = np.random.default_rng(seed)
        sig_rms = np.sqrt(np.mean(x[sung_region] ** 2))
        x = x + rng.normal(0, sig_rms / 10 ** (snr_db / 20), len(x))
    notes = [{"m": m, "t": round(LEAD_SECONDS + k * NOTE_SECONDS, 3), "d": NOTE_SECONDS} for k, (m, _) in enumerate(phrase)]
    return x.astype(np.float64), notes


def yin(x, rate, hop_s=0.01, win_s=0.04, fmin=150.0, fmax=600.0, threshold=0.15):
    """Independent YIN F0 tracker. Returns (frame centre times, f0 Hz with NaN when unvoiced)."""
    win, hop = int(win_s * rate), int(hop_s * rate)
    tau_min, tau_max = int(rate / fmax), int(rate / fmin)
    times, f0 = [], []
    for start in range(0, len(x) - win - tau_max, hop):
        frame = x[start:start + win + tau_max]
        if np.sqrt(np.mean(frame[:win] ** 2)) < 0.01:
            times.append((start + win / 2) / rate); f0.append(np.nan); continue
        d = np.array([np.sum((frame[:win] - frame[tau:tau + win]) ** 2) for tau in range(tau_max + 1)])
        cmnd = np.ones_like(d)
        cmnd[1:] = d[1:] * np.arange(1, tau_max + 1) / np.maximum(np.cumsum(d[1:]), 1e-12)
        below = np.flatnonzero(cmnd[tau_min:] < threshold)
        if not len(below):
            times.append((start + win / 2) / rate); f0.append(np.nan); continue
        tau = tau_min + below[0]
        while tau + 1 <= tau_max and cmnd[tau + 1] < cmnd[tau]:
            tau += 1
        # Parabolic interpolation around the minimum.
        if 1 <= tau < tau_max:
            a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
            denom = a - 2 * b + c
            tau = tau + (0.5 * (a - c) / denom if denom else 0)
        times.append((start + win / 2) / rate); f0.append(rate / tau)
    return np.array(times), np.array(f0)


def pitch_errors(x, rate, notes):
    """Absolute cents error from each note's intended pitch, over voiced note-interior frames."""
    times, f0 = yin(x, rate)
    errs = []
    for n in notes:
        lo, hi = n["t"] + EDGE_SECONDS, n["t"] + n["d"] - EDGE_SECONDS
        sel = (times >= lo) & (times < hi) & np.isfinite(f0)
        errs.append(np.abs(1200 * np.log2(f0[sel] / midi_hz(n["m"]))))
    return np.concatenate(errs)


def transition_times(x, rate, notes):
    """When the tracked pitch crosses halfway between consecutive notes (seconds)."""
    times, f0 = yin(x, rate)
    midi = 69 + 12 * np.log2(f0 / 440)
    out = []
    for a, b in zip(notes, notes[1:]):
        mid = (a["m"] + b["m"]) / 2
        sel = (times >= b["t"] - 0.25) & (times < b["t"] + 0.25) & np.isfinite(midi)
        tt, mm = times[sel], midi[sel]
        above = (mm > mid) if b["m"] > a["m"] else (mm < mid)
        cross = np.flatnonzero(above)
        out.append(float(tt[cross[0]]) if len(cross) else np.nan)
    return np.array(out)


def rms_db(s):
    return 20 * np.log10(np.sqrt(np.mean(s * s)) + 1e-12)


def note_loudness_changes(x, y, rate, notes):
    out = []
    for n in notes:
        a, b = int((n["t"] + EDGE_SECONDS) * rate), int((n["t"] + n["d"] - EDGE_SECONDS) * rate)
        out.append(rms_db(y[a:b]) - rms_db(x[a:b]))
    return np.array(out)


def wav_bytes(samples, rate):
    """Encode like the browser does (tuning.js encodeWav16): round to the nearest 16-bit step."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.round(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def wav_samples(data):
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32767, w.getframerate()


ENGINES = ["server", "device"]
REPO = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def device_tune(x, rate, strength, notes=None, vibrato=None):
    """VOX.4: tune on the device engine (worldtune.js and the WORLD WebAssembly build, run by Node).

    It gets the same 16-bit samples the server gets, and its float output is written as a WAV the
    same way, so every metric compares the two engines on equal terms.
    """
    if NODE is None:
        pytest.fail("Node is needed to run the on-device tuning engine")
    sent = np.round(np.clip(x, -1, 1) * 32767) / 32767
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.f32", Path(tmp) / "out.f32"
        sent.astype("<f4").tofile(src)
        args = {"rate": rate, "strength": strength, "notes": notes, "vibrato": vibrato or 0}
        done = subprocess.run([NODE, str(REPO / "tests" / "world_device.mjs"), str(src), str(dst), json.dumps(args)],
                              capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr
        return wav_bytes(np.fromfile(dst, "<f4").astype(np.float64), rate)


@pytest.fixture(scope="module", params=ENGINES)
def tune(request):
    """Tune a clip with the real /api/tune route in process (rate limit out of the way), or on the
    device engine (VOX.4). Every benchmark test runs on both."""
    if request.param == "device":
        device_tune.engine = "device"
        yield device_tune
        return
    with pytest.MonkeyPatch.context() as mp:
        for name in ("TANDEM_ACCESS_TOKEN", "VERCEL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
                     "KV_REST_API_URL", "KV_REST_API_TOKEN"):
            mp.delenv(name, raising=False)
        mp.setenv("TANDEM_AUDIO_RATE_LIMIT", "100000")
        mp.setattr(guards, "upstash_transport", None)
        guards.reset_memory_store()

        def call(x, rate, strength, notes=None, vibrato=None):
            async def go():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as c:
                    data = {"notes_json": json.dumps(notes)} if notes is not None else {}
                    extra = f"&vibrato={vibrato}" if vibrato is not None else ""
                    return await c.post(f"/api/tune?strength={strength}{extra}", files={"file": ("v.wav", wav_bytes(x, rate), "audio/wav")}, data=data)
            r = asyncio.run(go())
            assert r.status_code == 200, r.text
            return r.content
        call.engine = "server"
        yield call


METRICS = {}


@pytest.fixture(scope="module")
def report(request, tune):
    """The metrics of one engine; all engines' metrics are written together."""
    yield METRICS.setdefault(tune.engine, {})
    metrics = METRICS
    target = os.getenv("TANDEM_VOX_REPORT")
    cache = getattr(request.config, "cache", None)  # absent under -p no:cacheprovider
    if target:
        path = Path(target)
    elif cache is not None:
        path = cache.mkdir("vox1") / "metrics.json"
    else:
        return
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True))


def summary(errs):
    return {"median_cents": round(float(np.median(errs)), 2), "p90_cents": round(float(np.percentile(errs, 90)), 2), "frames": int(len(errs))}


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("case", list(CASES))
def test_note_targets_correct_pitch_and_keep_timing_and_level(case, rate, tune, report):
    x, notes = render(case, rate)
    out = tune(x, rate, 1.0, notes)
    y, out_rate = wav_samples(out)
    assert out_rate == rate
    assert len(y) == len(x), "tuned clip changed length"

    before, after = pitch_errors(x, rate, notes), pitch_errors(y, rate, notes)
    shift = np.abs(transition_times(y, rate, notes) - transition_times(x, rate, notes))
    note_db = note_loudness_changes(x, y, rate, notes)
    clip_db = rms_db(y) - rms_db(x)
    m = report.setdefault(f"targets/{case}/{rate}", {})
    m.update(before=summary(before), after=summary(after), transition_shift_s=[round(float(s), 3) for s in shift],
             note_loudness_change_db=[round(float(d), 2) for d in note_db], clip_loudness_change_db=round(float(clip_db), 2))

    assert len(after) > 0.8 * len(before), "tuned clip lost voiced frames"
    assert np.median(after) <= MAX_MEDIAN_CENTS_TARGETS, m
    assert np.percentile(after, 90) <= MAX_P90_CENTS_TARGETS, m
    assert np.median(before) >= MIN_IMPROVEMENT * np.median(after), m
    assert np.all(shift <= MAX_TRANSITION_SHIFT_S), m
    assert np.all(np.abs(note_db) <= MAX_NOTE_LOUDNESS_CHANGE_DB), m
    assert abs(clip_db) <= MAX_CLIP_LOUDNESS_CHANGE_DB, m


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("case", ["steady", "noise"])
def test_nearest_semitone_snapping_without_targets(case, rate, tune, report):
    x, notes = render(case, rate)
    y, _ = wav_samples(tune(x, rate, 1.0))
    assert len(y) == len(x)
    before, after = pitch_errors(x, rate, notes), pitch_errors(y, rate, notes)
    m = report.setdefault(f"snap/{case}/{rate}", {})
    m.update(before=summary(before), after=summary(after))
    assert np.median(after) <= MAX_MEDIAN_CENTS_SNAP, m
    assert np.median(before) >= MIN_IMPROVEMENT * np.median(after), m


@pytest.mark.parametrize("rate", RATES)
def test_note_targets_beat_snapping_when_sung_more_than_half_a_semitone_off(rate, tune, report):
    x, notes = render("steady", rate, phrase=FAR_PHRASE)
    targeted, _ = wav_samples(tune(x, rate, 1.0, notes))
    snapped, _ = wav_samples(tune(x, rate, 1.0))
    assert len(targeted) == len(x)
    before = pitch_errors(x, rate, notes)
    after, snap = pitch_errors(targeted, rate, notes), pitch_errors(snapped, rate, notes)
    m = report.setdefault(f"far_off/steady/{rate}", {})
    m.update(before=summary(before), after=summary(after), snap_without_targets=summary(snap))
    # The fixture must actually tell the two modes apart: snapping goes to the neighbouring semitone.
    assert np.median(snap) >= 80, m
    assert np.median(after) <= MAX_MEDIAN_CENTS_TARGETS, m
    assert np.percentile(after, 90) <= MAX_P90_CENTS_TARGETS, m


def note_cents(x, rate, notes):
    """Per note: signed cents from the intended pitch over voiced note-interior frames."""
    times, f0 = yin(x, rate)
    out = []
    for n in notes:
        sel = (times >= n["t"] + EDGE_SECONDS) & (times < n["t"] + n["d"] - EDGE_SECONDS) & np.isfinite(f0)
        out.append(1200 * np.log2(f0[sel] / midi_hz(n["m"])))
    return out


@pytest.mark.parametrize("rate", RATES)
def test_keep_vibrato_centres_each_note_and_keeps_its_wobble(rate, tune, report):
    """VOX.3: with vibrato=1 the note centre moves onto the target and the vibrato survives."""
    x, notes = render("vibrato", rate)
    y, _ = wav_samples(tune(x, rate, 1.0, notes, vibrato=1))
    assert len(y) == len(x)
    before, after = note_cents(x, rate, notes), note_cents(y, rate, notes)
    centre = [float(np.mean(a)) for a in after]
    depth_before = [float(np.std(b)) for b in before]
    depth_after = [float(np.std(a)) for a in after]
    report[f"keep_vibrato/vibrato/{rate}"] = {"note_centre_cents": [round(c, 2) for c in centre],
                                             "vibrato_std_cents_before": [round(d, 2) for d in depth_before],
                                             "vibrato_std_cents_after": [round(d, 2) for d in depth_after]}
    assert max(abs(c) for c in centre) <= MAX_KEEP_VIBRATO_CENTRE_CENTS, report[f"keep_vibrato/vibrato/{rate}"]
    for b, a in zip(depth_before, depth_after):
        assert KEEP_VIBRATO_DEPTH_RATIO[0] * b <= a <= KEEP_VIBRATO_DEPTH_RATIO[1] * b, report[f"keep_vibrato/vibrato/{rate}"]


@pytest.mark.parametrize("rate", RATES)
def test_half_strength_corrects_about_half_way(rate, tune, report):
    x, notes = render("steady", rate)
    y, _ = wav_samples(tune(x, rate, 0.5, notes))
    before, after = np.median(pitch_errors(x, rate, notes)), np.median(pitch_errors(y, rate, notes))
    report[f"half_strength/steady/{rate}"] = {"before_median_cents": round(float(before), 2), "after_median_cents": round(float(after), 2)}
    lo, hi = MAX_HALF_STRENGTH_RATIO
    assert lo * before <= after <= hi * before


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("with_targets", [False, True])
def test_zero_strength_returns_the_input_unchanged(rate, with_targets, tune, report):
    x, notes = render("vibrato", rate)
    sent = wav_bytes(x, rate)
    out = tune(x, rate, 0.0, notes if with_targets else None)
    sent_pcm, got_pcm = sent[44:], out[44:]
    diff = np.abs(np.frombuffer(sent_pcm, "<i2").astype(int) - np.frombuffer(got_pcm, "<i2").astype(int))
    report[f"zero_strength/{'targets' if with_targets else 'snap'}/{rate}"] = {"max_lsb_diff": int(diff.max()), "samples_changed": int(np.count_nonzero(diff))}
    assert len(got_pcm) == len(sent_pcm)
    assert diff.max() == 0, "0% strength changed the audio"


# VOX.4: the device engine is the server's WORLD compiled to WebAssembly, with the same options and
# the same F0 correction, so it must give the server's audio up to floating-point rounding.
MIN_DEVICE_SNR_DB = 70.0
MAX_DEVICE_DIFF_LSB = 32


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("case", list(CASES))
def test_device_engine_matches_the_server(case, rate):
    x, notes = render(case, rate)
    sent = np.round(np.clip(x, -1, 1) * 32767) / 32767
    for kwargs in ({"notes": notes}, {}):
        expected, _ = world_tuning.world_tune(sent, rate, strength=1.0, **kwargs)
        expected = np.round(np.clip(expected, -1, 1) * 32767) / 32767
        got, _ = wav_samples(device_tune(x, rate, 1.0, kwargs.get("notes")))
        diff = got - expected
        snr = 10 * np.log10(np.sum(expected ** 2) / max(np.sum(diff ** 2), 1e-30))
        METRICS.setdefault("device_vs_server", {})[f"{'targets' if kwargs else 'snap'}/{case}/{rate}"] = {
            "snr_db": round(float(snr), 1), "max_diff_lsb": int(round(np.max(np.abs(diff)) * 32767))}
        assert len(got) == len(expected)
        assert snr >= MIN_DEVICE_SNR_DB, (case, rate, kwargs.keys(), snr)
        assert np.max(np.abs(diff)) * 32767 <= MAX_DEVICE_DIFF_LSB, (case, rate, kwargs.keys())
