"""PITCH.0 spike: RMVPE and PESTO against the studio's YIN and Basic Pitch's contour.

Every tracker reads the same clips (VOX.1's sung phrase at four rates in four variants, white noise
alone, and SEP.1's fixture voice: alone, in the mix and separated by HTDemucs), each with its true
pitch, and writes the pitch it heard. `score` compares them. Nothing in Tandem imports this file,
and nothing is played aloud. Commands and environments: tools/pitch-spike/README.md.

  clips      the clips and their true pitch (the repository's .venv: numpy, pyworld)
  separate   SEP.1's mix through HTDemucs, as the Mac app runs it (an environment with
             requirements-models.txt; the model is fetched and hash-checked by MODEL.1's runtime)
  track      one Python tracker over every clip: yin-bench (the VOX.1 benchmark's own scorer),
             rmvpe (ONNX Runtime), pesto (PyTorch) or pesto-stream (PESTO's streaming ONNX export,
             fed one 10 ms step at a time)
  export     PESTO's streaming model as ONNX at a rate and step (for pesto-stream and the browser)
  weights    what the weight files are and whether MODEL.1 could load them
  score      every tracker against the truth, to results.json
  table      results.json as the Markdown tables in docs/AUDIO.md

`yin_live.mjs` (Node) runs pitch.js's tracker, the live guide's code, and `browser.py` runs Basic
Pitch's contour and PESTO in ONNX Runtime Web in Chromium.
"""
import argparse
import json
import math
import os
import pathlib
import sys
import time
import wave

import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[2]
TRUTH_HOP = 0.005          # seconds between true pitch values
GUARD = 0.05               # frames this close to a voicing change in the truth are not scored
GROSS_CENTS = 50           # a pitch further off than this is a gross error
VOX_RATES = [16000, 22050, 44100, 48000]
VOX_CASES = ["steady", "vibrato", "noise", "transitions"]
PESTO_CHECKPOINT = "mir-1k_g7"
STEP = 0.01                # every tracker but YIN-live and Basic Pitch reads one pitch per 10 ms


# ---------------------------------------------------------------- WAV and JSON

def write_wav(path, x, rate):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.round(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def read_wav(path):
    with wave.open(str(path)) as w:
        rate, n = w.getframerate(), w.getnframes()
        data = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32767
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, rate


def nan_list(a):
    return [None if not np.isfinite(v) else round(float(v), 5) for v in a]


def from_list(a):
    return np.array([np.nan if v is None else v for v in a], dtype=np.float64)


def hz_to_midi(hz):
    hz = np.asarray(hz, dtype=np.float64)
    out = np.full(hz.shape, np.nan)
    ok = np.isfinite(hz) & (hz > 0)
    out[ok] = 69 + 12 * np.log2(hz[ok] / 440)
    return out


# ---------------------------------------------------------------- the clips and their truth

def vox_truth(case, rate, phrase=None):
    """The pitch VOX.1's render() sings, per sample: (MIDI with NaN where it is silent, the samples'
    voice phase). The same arithmetic as tests/test_vocal_benchmark.py render(); a test checks that
    synthesizing from it gives render()'s samples."""
    import test_vocal_benchmark as vox
    phrase = phrase or vox.PHRASE
    glide, vibrato_cents, _ = vox.CASES[case]
    n_notes = len(phrase)
    total = vox.LEAD_SECONDS * 2 + vox.NOTE_SECONDS * n_notes
    t = np.arange(int(round(total * rate))) / rate
    rel = t - vox.LEAD_SECONDS
    sung = np.array([m + c / 100 for m, c in phrase])
    idx = np.clip(np.floor(rel / vox.NOTE_SECONDS).astype(int), 0, n_notes - 1)
    pitch = sung[idx].copy()
    for k in range(1, n_notes):
        start = k * vox.NOTE_SECONDS - glide / 2
        in_glide = (rel >= start) & (rel < start + glide)
        frac = (rel[in_glide] - start) / glide
        pitch[in_glide] = sung[k - 1] + (sung[k] - sung[k - 1]) * frac
    if vibrato_cents:
        pitch += vibrato_cents / 100 * np.sin(2 * np.pi * 5.5 * rel)
    voiced = (rel >= 0) & (rel < vox.NOTE_SECONDS * n_notes)
    return np.where(voiced, pitch, np.nan), pitch


def sep_truth():
    """SEP.1's fixture voice f0 (MIDI, one value per 5 ms WORLD frame, NaN where silent), the very
    values separation_fixture.voice() hands pyworld.synthesize: the same loop and random draws."""
    import separation_fixture as fx
    rng = np.random.default_rng(1)
    period = 5.0
    n = int((fx.LEAD_SECONDS * 2 + fx.NOTE_SECONDS * len(fx.MELODY)) * 1000 / period)
    rel = np.arange(n) * period / 1000 - fx.LEAD_SECONDS
    f0 = np.zeros(n)
    for i in range(n):
        k = int(np.floor(rel[i] / fx.NOTE_SECONDS))
        if rel[i] < 0 or k >= len(fx.MELODY):
            continue
        within = rel[i] - k * fx.NOTE_SECONDS
        m = fx.MELODY[k] + 0.3 * np.sin(2 * np.pi * 5.5 * within) * min(1, within / 0.2)
        if k and within < 0.04:
            m = fx.MELODY[k - 1] + (fx.MELODY[k] - fx.MELODY[k - 1]) * within / 0.04
        f0[i] = fx.midi_hz(m) * (1 + 0.003 * rng.standard_normal())
    return np.where(f0 > 0, hz_to_midi(np.where(f0 > 0, f0, 1)), np.nan)


def truth_record(midi, hop):
    return {"hop": hop, "midi": nan_list(midi)}


def cmd_clips(args):
    sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
    import test_vocal_benchmark as vox
    import separation_fixture as fx
    out = pathlib.Path(args.out) / "clips"
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for case in VOX_CASES:
        for rate in VOX_RATES:
            x, _ = vox.render(case, rate)
            truth, _ = vox_truth(case, rate)
            step = int(round(TRUTH_HOP * rate))
            name = f"vox-{case}-{rate}"
            write_wav(out / f"{name}.wav", x, rate)
            (out / f"{name}.truth.json").write_text(json.dumps(truth_record(truth[::step], step / rate)))
            made.append(name)
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.05, 3 * 44100)
    write_wav(out / "noise-44100.wav", noise, 44100)
    (out / "noise-44100.truth.json").write_text(json.dumps(truth_record(np.full(600, np.nan), TRUTH_HOP)))
    made.append("noise-44100")
    mix, voice, _ = fx.song()
    f0 = sep_truth()
    for name, x in (("sep-voice-44100", voice), ("sep-mix-44100", mix)):
        write_wav(out / f"{name}.wav", x, fx.RATE)
        (out / f"{name}.truth.json").write_text(json.dumps(truth_record(f0, 0.005)))
        made.append(name)
    print(f"{len(made)} clips in {out}")


def cmd_separate(args):
    """SEP.1's mix separated by HTDemucs through the Mac app's own code (models.ModelRuntime fetches
    and hash-checks the weights; separation.separate is what /api/desktop/separate runs)."""
    sys.path.insert(0, str(REPO))
    from tandem_desktop import models, separation
    rt = models.ModelRuntime(pathlib.Path(args.model_home))
    if not rt.store.installed(models.HTDEMUCS):
        job = rt.jobs.wait(rt.start_download(models.HTDEMUCS.id).id, timeout=1800)
        if job.state != "done":
            sys.exit(f"download failed: {job.error}")
    rt.store.verify(models.HTDEMUCS)  # hashed again before loading, as the app does
    bag = separation.load_htdemucs(rt.store.folder(models.HTDEMUCS) / separation.WEIGHTS)
    clips = pathlib.Path(args.out) / "clips"
    mix, rate = read_wav(clips / "sep-mix-44100.wav")
    started = time.monotonic()
    vocal, _ = separation.separate(bag, mix.astype(np.float32), rate)
    print(f"separated {len(mix) / rate:.1f} s in {time.monotonic() - started:.1f} s on {separation.device()}")
    write_wav(clips / "sep-separated-44100.wav", vocal, rate)
    (clips / "sep-separated-44100.truth.json").write_text((clips / "sep-mix-44100.truth.json").read_text())


# ---------------------------------------------------------------- the Python trackers

def track_yin_bench(x, rate):
    sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
    import test_vocal_benchmark as vox
    times, f0 = vox.yin(x, rate)
    return times, hz_to_midi(f0)


class Rmvpe:
    """RMVPE from rmvpe.onnx with the preprocessing of RVC's infer/lib/rmvpe.py (the code these
    weights come with): 16 kHz, a centred 1024-point STFT (Hann, reflect padding) every 160
    samples, 128 HTK mel bands from 30 Hz to 8 kHz, log clamped at 1e-5, frames padded to a
    multiple of 32; decoded as the salience-weighted mean of the 9 bins around the peak, unvoiced
    when the peak is at most 0.03."""
    HOP, N_FFT, THRESHOLD = 160, 1024, 0.03

    def __init__(self, path, provider="CPUExecutionProvider"):
        import librosa
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(path), providers=[provider])
        self.mel = librosa.filters.mel(sr=16000, n_fft=self.N_FFT, n_mels=128, fmin=30, fmax=8000, htk=True)
        self.window = np.hanning(self.N_FFT + 1)[:-1]  # periodic, as torch.hann_window
        self.cents = np.pad(20 * np.arange(360) + 1997.3794084376191, (4, 4))

    def log_mel(self, x16):
        pad = self.N_FFT // 2
        y = np.pad(x16, pad, mode="reflect")
        frames = 1 + (len(y) - self.N_FFT) // self.HOP
        idx = np.arange(self.N_FFT)[None, :] + self.HOP * np.arange(frames)[:, None]
        mag = np.abs(np.fft.rfft(y[idx] * self.window, axis=1)).T
        return np.log(np.maximum(self.mel @ mag, 1e-5)).astype(np.float32)

    def decode(self, hidden):
        center = np.argmax(hidden, axis=1) + 4
        sal = np.pad(hidden, ((0, 0), (4, 4)))
        rows = np.arange(len(hidden))[:, None]
        cols = center[:, None] + np.arange(-4, 5)[None, :]
        s, c = sal[rows, cols], self.cents[cols]
        cents = (s * c).sum(1) / s.sum(1)
        cents[hidden.max(axis=1) <= self.THRESHOLD] = np.nan
        return hz_to_midi(10 * 2 ** (cents / 1200))

    def __call__(self, x, rate):
        import librosa
        x16 = librosa.resample(x, orig_sr=rate, target_sr=16000) if rate != 16000 else x
        mel = self.log_mel(x16)
        n = mel.shape[1]
        mel = np.pad(mel, ((0, 0), (0, 32 * ((n - 1) // 32 + 1) - n)))
        name = self.session.get_inputs()[0].name
        hidden = self.session.run(None, {name: mel[None]})[0][0][:n]
        return np.arange(n) * self.HOP / 16000, self.decode(hidden)


def pesto_path(src):
    sys.path.insert(0, str(pathlib.Path(src)))


class Pesto:
    """PESTO in PyTorch, offline over the whole clip, one pitch every 10 ms."""

    def __init__(self, src, threshold):
        pesto_path(src)
        self.threshold = threshold
        self.models = {}

    def __call__(self, x, rate):
        import torch
        from pesto import load_model
        if rate not in self.models:
            self.models[rate] = load_model(PESTO_CHECKPOINT, step_size=STEP * 1000, sampling_rate=rate)
        with torch.no_grad():
            hz, conf, _ = self.models[rate](torch.from_numpy(x.astype(np.float32)), sr=rate, convert_to_freq=True, return_activations=False)
        hz, conf = hz.numpy().ravel(), conf.numpy().ravel()
        midi = hz_to_midi(hz)
        midi[conf < self.threshold] = np.nan
        return np.arange(len(hz)) * STEP, midi, conf


class PestoStream:
    """PESTO's streaming ONNX export, fed one 10 ms step at a time with its cache carried over, as a
    live tracker would run it. Its outputs come late; `score` finds and reports the lag."""

    def __init__(self, folder, threshold):
        # The export's prediction is in semitones (MIDI): StatelessPESTO calls the model without convert_to_freq.
        self.folder, self.threshold = pathlib.Path(folder), threshold
        self.sessions, self.step_times = {}, []

    def __call__(self, x, rate):
        import onnxruntime as ort
        chunk = int(round(rate * STEP))
        if rate not in self.sessions:
            path = self.folder / f"pesto-stream-{rate}-{chunk}.onnx"
            # No model for 22,050 Hz: PESTO's 220-sample step is too short for its lowest CQT kernel at that
            # rate, so the export fails; those clips are skipped.
            self.sessions[rate] = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]) if path.exists() else None
        s = self.sessions[rate]
        if s is None:
            return None
        cache = np.zeros((1, s.get_inputs()[1].shape[1]), dtype=np.float32)
        steps = len(x) // chunk
        midi, conf = np.empty(steps), np.empty(steps)
        for i in range(steps):
            started = time.perf_counter()
            pred, c, _, _, cache = s.run(None, {"audio": x[None, i * chunk:(i + 1) * chunk].astype(np.float32), "cache": cache})
            self.step_times.append(time.perf_counter() - started)
            midi[i], conf[i] = float(np.ravel(pred)[0]), float(np.ravel(c)[0])  # fractional MIDI
        midi[conf < self.threshold] = np.nan
        # The step's reading is stamped at the end of the audio it has seen so far.
        return (np.arange(steps) + 1) * chunk / rate, midi, conf


def clip_names(clips):
    return sorted(p.name[:-4] for p in pathlib.Path(clips).glob("*.wav"))


def cmd_track(args):
    clips = pathlib.Path(args.out) / "clips"
    out = pathlib.Path(args.out) / "tracks" / args.tracker
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    if args.tracker == "yin-bench":
        tracker = track_yin_bench
    elif args.tracker == "rmvpe":
        tracker = Rmvpe(args.weights, args.provider)
    elif args.tracker == "pesto":
        tracker = Pesto(args.pesto_src, args.threshold)
    elif args.tracker == "pesto-stream":
        tracker = PestoStream(args.onnx_dir, args.threshold)
    else:
        sys.exit(f"unknown tracker {args.tracker}")
    load = time.monotonic() - started
    timed_steps = []  # pesto-stream: the time of every step of the timed runs
    for name in clip_names(clips):
        x, rate = read_wav(clips / f"{name}.wav")
        if tracker(x[: rate], rate) is None:  # warm up (kernels for this rate, first-run allocation)
            print(f"{args.tracker} {name}: skipped (no model for {rate} Hz)")
            continue
        if args.tracker == "pesto-stream":
            tracker.step_times.clear()
        started = time.perf_counter()
        got = tracker(x, rate)
        seconds = time.perf_counter() - started
        if args.tracker == "pesto-stream":
            timed_steps.extend(tracker.step_times)
        t, midi = got[0], got[1]
        rec = {"tracker": args.tracker, "clip": name, "t": [round(float(v), 5) for v in t], "midi": nan_list(midi),
               "seconds": seconds, "audio_seconds": len(x) / rate, "load_seconds": load}
        if len(got) > 2:
            rec["confidence"] = [round(float(v), 4) for v in got[2]]
        if args.tracker == "rmvpe":
            rec["provider"] = args.provider
        (out / f"{name}.json").write_text(json.dumps(rec))
        print(f"{args.tracker} {name}: {seconds / (len(x) / rate) * 1000:.1f} ms per second of audio")
    if timed_steps:
        st = np.array(timed_steps) * 1000
        (out / "steps.json").write_text(json.dumps({"runtime": "onnxruntime-python", "steps": len(st),
            "mean_ms": float(st.mean()), "p50_ms": float(np.median(st)), "p99_ms": float(np.percentile(st, 99)), "max_ms": float(st.max())}))
        print(f"pesto-stream steps: mean {st.mean():.3f} ms, p99 {np.percentile(st, 99):.3f} ms")


def cmd_export(args):
    """PESTO's streaming model as ONNX, one `chunk` of samples per step: PESTO's own
    realtime/export_onnx.py export (its StatelessPESTO wrapper carries the cache in and out), but
    with torch's TorchScript exporter (dynamo=False), which that script was written for; torch
    2.15's default exporter cannot convert the model's roll. Then 200 steps of noise through
    ONNX Runtime and the PyTorch streaming model side by side: the largest difference is printed."""
    import onnxruntime as ort
    import torch
    pesto_path(args.pesto_src)
    from pesto import load_model
    from realtime.onnx_wrapper import StatelessPESTO
    chunk = int(round(args.rate * STEP))
    path = pathlib.Path(args.onnx_dir) / f"pesto-stream-{args.rate}-{chunk}.onnx"
    path.parent.mkdir(parents=True, exist_ok=True)

    def streaming():
        return load_model(PESTO_CHECKPOINT, step_size=STEP * 1000, sampling_rate=args.rate, streaming=True, max_batch_size=1, mirror=1.0).eval()
    wrapped = StatelessPESTO(streaming()).eval()
    torch.onnx.export(wrapped, (torch.randn(1, chunk).clip(-1, 1), wrapped.init_cache(batch_size=1)), str(path), dynamo=False,
                      input_names=["audio", "cache"], output_names=["prediction", "confidence", "volume", "activations", "cache_out"])
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    reference = streaming()
    cache = np.zeros((1, session.get_inputs()[1].shape[1]), dtype=np.float32)
    rng = np.random.default_rng(0)
    worst = {"prediction": 0.0, "confidence": 0.0}
    for _ in range(200):
        x = (rng.standard_normal((1, chunk)) * 0.1).astype(np.float32)
        pred, conf, _, _, cache = session.run(None, {"audio": x, "cache": cache})
        with torch.no_grad():
            tp, tc, _ = reference(torch.from_numpy(x), return_activations=False)
        worst["prediction"] = max(worst["prediction"], float(np.max(np.abs(pred - tp.numpy()))))
        worst["confidence"] = max(worst["confidence"], float(np.max(np.abs(conf - tc.numpy()))))
    print(path, path.stat().st_size, "bytes; cache", cache.shape[1], "values; largest difference to PyTorch over 200 steps:", worst)


def cmd_weights(args):
    """Each weight file's size, SHA-256 and whether it loads without running pickle code."""
    import hashlib
    import torch
    report = {}
    for path in args.files:
        p = pathlib.Path(path)
        entry = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        if p.suffix == ".ckpt":
            try:
                torch.load(p, map_location="cpu", weights_only=True)
                entry["weights_only"] = "loads"
            except Exception as e:
                entry["weights_only"] = "refused: " + str(e).split("WeightsUnpickler error: ")[-1].split("\n")[0][:200]
        if p.suffix == ".onnx":
            import onnx
            m = onnx.load(str(p))
            entry["onnx_opset"] = [o.version for o in m.opset_import]
            entry["inputs"] = [(i.name, [d.dim_value or d.dim_param for d in i.type.tensor_type.shape.dim]) for i in m.graph.input]
        report[p.name] = entry
    print(json.dumps(report, indent=1))


# ---------------------------------------------------------------- scoring

def truth_at(truth, hop, t):
    """True MIDI at times `t`: linear between neighbouring truth values, NaN when either is silent."""
    pos = np.asarray(t) / hop
    i = np.floor(pos).astype(int)
    ok = (i >= 0) & (i + 1 < len(truth))
    out = np.full(len(pos), np.nan)
    a, b = truth[np.clip(i, 0, len(truth) - 1)], truth[np.clip(i + 1, 0, len(truth) - 1)]
    frac = pos - i
    out[ok] = (a + (b - a) * frac)[ok]
    return out


def near_change(truth, hop, t, guard=GUARD):
    """Frames within `guard` s of where the truth turns voiced or silent."""
    voiced = np.isfinite(truth)
    edges = np.flatnonzero(voiced[1:] != voiced[:-1]) * hop + hop / 2
    if not len(edges):
        return np.zeros(len(t), dtype=bool)
    d = np.min(np.abs(np.asarray(t)[:, None] - edges[None, :]), axis=1)
    return d < guard


def score_track(truth, hop, t, est, lag=0.0):
    """Pitch and voicing of one tracker on one clip. `lag` (s) is taken off each reading's time."""
    t = np.asarray(t, dtype=np.float64) - lag
    est = np.asarray(est, dtype=np.float64)
    inside = (t >= 0) & (t <= (len(truth) - 1) * hop)
    t, est = t[inside], est[inside]
    ref = truth_at(truth, hop, t)
    keep = ~near_change(truth, hop, t)
    ref_v, est_v = np.isfinite(ref) & keep, np.isfinite(est)
    unvoiced = ~np.isfinite(ref) & keep
    both = ref_v & est_v
    cents = np.abs(est[both] - ref[both]) * 100
    octave = np.zeros(len(cents), dtype=bool)
    for k in (1, 2):
        octave |= np.abs(cents - 1200 * k) < GROSS_CENTS
    fine = cents[cents <= GROSS_CENTS]
    return {
        "voiced_frames": int(ref_v.sum()), "unvoiced_frames": int(unvoiced.sum()),
        "median_cents": float(np.median(fine)) if len(fine) else None,
        "p90_cents": float(np.percentile(fine, 90)) if len(fine) else None,
        "gross": float((cents > GROSS_CENTS).mean()) if len(cents) else None,
        "octave": float(octave.mean()) if len(cents) else None,
        "voicing_recall": float(both.sum() / ref_v.sum()) if ref_v.sum() else None,
        "false_alarm": float((unvoiced & est_v).sum() / unvoiced.sum()) if unvoiced.sum() else None,
    }


def best_lag(truth, hop, t, est, span=0.1, step=0.0025):
    """The time shift (s) that gives the lowest median error on the clip: how late a tracker stamps its readings."""
    best, where = None, 0.0
    for lag in np.arange(-span, span + step / 2, step):
        s = score_track(truth, hop, t, est, lag)
        if s["median_cents"] is not None and s["voicing_recall"] and s["voicing_recall"] > 0.5:
            if best is None or s["median_cents"] < best:
                best, where = s["median_cents"], float(lag)
    return round(where, 4)


def cmd_score(args):
    root = pathlib.Path(args.out)
    clips = root / "clips"
    results = {}
    for folder in sorted((root / "tracks").iterdir()):
        for f in sorted(folder.glob("*.json")):
            if f.name == "steps.json":
                continue
            rec = json.loads(f.read_text())
            tr = json.loads((clips / f"{rec['clip']}.truth.json").read_text())
            truth, hop = from_list(tr["midi"]), tr["hop"]
            est = from_list(rec["midi"])
            lag = best_lag(truth, hop, rec["t"], est) if rec["clip"].startswith("vox-vibrato") else None
            s = score_track(truth, hop, rec["t"], est)
            s.update({"lag": lag, "seconds": rec["seconds"], "audio_seconds": rec["audio_seconds"], "load_seconds": rec.get("load_seconds")})
            results.setdefault(folder.name, {})[rec["clip"]] = s
        steps = folder / "steps.json"
        if steps.exists():
            results.setdefault(folder.name, {})["_steps"] = json.loads(steps.read_text())
    browser_steps = root / "tracks" / "browser-steps.json"
    if browser_steps.exists():
        results["_browser_steps"] = json.loads(browser_steps.read_text())
    (root / "results.json").write_text(json.dumps(results, indent=1))
    print(f"scored {sum(len(v) for v in results.values())} tracks into {root / 'results.json'}")


def cmd_sweep(args):
    """PESTO's voicing at other confidence thresholds, from the confidences `track` kept: per group of
    clips, the share of sung frames found, of silent frames voiced, and of white noise voiced."""
    root = pathlib.Path(args.out)
    clips = root / "clips"
    groups = {"VOX.1 (all)": "vox-", "SEP.1 voice alone": "sep-voice", "SEP.1 separated": "sep-separated", "noise alone": "noise-"}
    print(f"| {args.tracker} threshold | " + " | ".join(f"{g}: found / on silence" for g in groups) + " |")
    print("|---|" + "---|" * len(groups))
    for th in args.thresholds:
        cells = []
        for prefix in groups.values():
            found, silent = [], []
            for f in sorted((root / "tracks" / args.tracker).glob(prefix + "*.json")):
                rec = json.loads(f.read_text())
                tr = json.loads((clips / f"{rec['clip']}.truth.json").read_text())
                truth, hop = from_list(tr["midi"]), tr["hop"]
                conf = np.array(rec["confidence"])
                # Voicing only: a step is sung when its confidence passes `th` (its pitch does not matter here).
                est = np.where(conf >= th, 60.0, np.nan)
                sc = score_track(truth, hop, rec["t"], est)
                found.append(sc["voicing_recall"]); silent.append(sc["false_alarm"])
            f_ = [v for v in found if v is not None]; s_ = [v for v in silent if v is not None]
            cells.append(f"{fmt(sum(f_) / len(f_) if f_ else None, pct=True)} / {fmt(sum(s_) / len(s_) if s_ else None, pct=True)}")
        print(f"| {th} | " + " | ".join(cells) + " |")


def fmt(v, digits=1, pct=False):
    if v is None:
        return "–"
    return f"{v * 100:.{digits}f}%" if pct else f"{v:.{digits}f}"


def cmd_table(args):
    results = json.loads((pathlib.Path(args.out) / "results.json").read_text())
    trackers = [k for k in results if not k.startswith("_")]
    groups = [("VOX.1 steady", "vox-steady-"), ("VOX.1 vibrato", "vox-vibrato-"), ("VOX.1 noise", "vox-noise-"),
              ("VOX.1 glides", "vox-transitions-"), ("SEP.1 voice alone", "sep-voice"), ("SEP.1 separated", "sep-separated"),
              ("SEP.1 mix", "sep-mix")]
    print("| Tracker | Clips | Median / p90 cents | Gross | Octave | Voiced found | Voiced on silence |")
    print("|---|---|---|---|---|---|---|")
    for tr in trackers:
        for label, prefix in groups:
            rows = [v for k, v in results[tr].items() if k.startswith(prefix)]
            if not rows:
                continue
            def mean(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return sum(vals) / len(vals) if vals else None
            def worst(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return max(vals) if vals else None
            print(f"| {tr} | {label} ({len(rows)}) | {fmt(mean('median_cents'))} / {fmt(worst('p90_cents'))} | {fmt(mean('gross'), pct=True)} | "
                  f"{fmt(mean('octave'), pct=True)} | {fmt(mean('voicing_recall'), pct=True)} | {fmt(mean('false_alarm'), pct=True)} |")
    print()
    print("| Tracker | Noise alone: frames voiced | Lag on vibrato (ms) | ms per second of audio (44.1 kHz clips) | Load (s) |")
    print("|---|---|---|---|---|")
    for tr in trackers:
        r = results[tr]
        noise = r.get("noise-44100", {}).get("false_alarm")
        lags = [v["lag"] for k, v in r.items() if k.startswith("vox-vibrato") and v.get("lag") is not None]
        speed = [(v["seconds"], v["audio_seconds"]) for k, v in r.items() if k.endswith("44100") and "seconds" in v]
        ms = sum(s for s, _ in speed) / sum(a for _, a in speed) * 1000 if speed else None
        load = next((v.get("load_seconds") for k, v in r.items() if not k.startswith("_")), None)
        lag = f"{min(lags) * 1000:.0f} to {max(lags) * 1000:.0f}" if lags else "–"
        print(f"| {tr} | {fmt(noise, pct=True)} | {lag} | {fmt(ms)} | {fmt(load, 2)} |")
    for tr in trackers:
        if "_steps" in results[tr]:
            print(f"\n{tr} steps ({results[tr]['_steps']['runtime']}): {json.dumps(results[tr]['_steps'])}")
    if "_browser_steps" in results:
        print(f"\nbrowser steps: {json.dumps(results['_browser_steps'])}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("clips", "separate", "track", "export", "weights", "score", "table", "sweep"):
        s = sub.add_parser(name)
        if name != "weights":
            s.add_argument("--out", required=name != "export", help="the spike's working folder")
        if name == "separate":
            s.add_argument("--model-home", required=True)
        if name == "track":
            s.add_argument("--tracker", required=True, choices=["yin-bench", "rmvpe", "pesto", "pesto-stream"])
            s.add_argument("--weights", help="rmvpe.onnx")
            s.add_argument("--provider", default="CPUExecutionProvider")
            s.add_argument("--pesto-src", help="a checkout of SonyCSLParis/pesto")
            s.add_argument("--onnx-dir", help="where `export` wrote the streaming models")
            s.add_argument("--threshold", type=float, default=0.5, help="PESTO's confidence below which a step is unvoiced")
        if name == "export":
            s.add_argument("--pesto-src", required=True)
            s.add_argument("--onnx-dir", required=True)
            s.add_argument("--rate", type=int, required=True)
        if name == "weights":
            s.add_argument("files", nargs="+")
        if name == "sweep":
            s.add_argument("--tracker", required=True)
            s.add_argument("--thresholds", type=float, nargs="+", default=[0.05, 0.1, 0.2, 0.3, 0.5])
    args = p.parse_args(argv)
    {"clips": cmd_clips, "separate": cmd_separate, "track": cmd_track, "export": cmd_export,
     "weights": cmd_weights, "score": cmd_score, "table": cmd_table, "sweep": cmd_sweep}[args.cmd](args)


if __name__ == "__main__":
    main()
