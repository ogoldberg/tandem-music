"""SEP.1: separate the voice from background music with HTDemucs, in the Mac app only.

A recording is split into the vocal and the accompaniment (drums + bass + other) by the htdemucs
model of Demucs (code MIT; the weights' terms are LIC.1's question), whose weights the MODEL.1 runtime downloads and verifies (`HTDEMUCS` in
models.CATALOG). The weights are the safetensors file that Demucs' author publishes on Hugging Face,
pinned to one commit by URL, SHA-256 and size. They are loaded with safetensors, never with
torch.load (no pickle), and only the HTDemucs class is accepted from the file's metadata.

Routes (behind tandem_desktop.guarded_app; answers are JSON unless noted, never cached):
  POST /api/desktop/separate                     a 16-bit PCM WAV, mono or stereo, 8-96 kHz, up to
                                                 MAX_SECONDS: 202 with the separation job
  GET  /api/desktop/separate/<job id>/vocal.wav          the vocal, as WAV at the recording's
  GET  /api/desktop/separate/<job id>/accompaniment.wav  rate and length (mono, 16-bit)

The job (read and cancelled at /api/desktop/jobs/<id>) reports progress while the model runs.
The stems of the last KEEP_RESULTS separations are kept in memory for the window to fetch.
"""
import io
import json
import threading
import wave
from collections import OrderedDict

import numpy as np

from . import models

SEPARATE_PATH = "/api/desktop/separate"
STEMS = ("vocal", "accompaniment")
MAX_SECONDS = 600
MAX_BODY = 256 << 20
KEEP_RESULTS = 2
MODEL_ID = models.HTDEMUCS.id
WEIGHTS = models.HTDEMUCS.files[0].name
MODEL_CLASS = "demucs.htdemucs.HTDemucs"


class SeparationError(models.ModelError):
    pass


def decode_wav(data, max_seconds=MAX_SECONDS):
    """A 16-bit PCM WAV as (mono float32 samples, rate)."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            rate, ch, frames, width = w.getframerate(), w.getnchannels(), w.getnframes(), w.getsampwidth()
            if not (8000 <= rate <= 96000) or ch not in (1, 2) or width != 2 or frames <= 0:
                raise SeparationError("Send a 16-bit PCM WAV, mono or stereo, 8-96 kHz.")
            if frames / rate > max_seconds:
                raise SeparationError(f"Separation takes recordings up to {max_seconds // 60} minutes.")
            raw = w.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise SeparationError(f"That is not a WAV recording: {exc}") from exc
    raw = raw[:len(raw) - len(raw) % (2 * ch)]
    if not raw:
        raise SeparationError("The WAV recording has no audio frames.")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    if ch == 2:
        x = x.reshape(-1, 2).mean(axis=1)
    return x, rate


def encode_wav(x, rate):
    samples = np.clip(np.round(np.asarray(x, dtype=np.float64) * 32768), -32768, 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return out.getvalue()


def load_htdemucs(path):
    """The htdemucs model from its safetensors file: the tensors and the init arguments, with the
    class checked to be HTDemucs (the file is pinned by hash, and this keeps a changed pin from
    naming any other class)."""
    from demucs.apply import BagOfModels
    from demucs.hf import _decode_json
    from demucs.htdemucs import HTDemucs
    from demucs.states import load_model
    from safetensors import safe_open
    with safe_open(str(path), framework="pt") as fh:
        meta = fh.metadata() or {}
        state = {k: fh.get_tensor(k) for k in fh.keys()}
    if meta.get("klass") != MODEL_CLASS or "structure" in meta:
        raise SeparationError("The separation model file is not the HTDemucs model Tandem expects.")
    model = load_model({"klass": HTDemucs, "args": _decode_json(json.loads(meta["args"])),
                        "kwargs": _decode_json(json.loads(meta["kwargs"])), "state": state})
    model.eval()
    return BagOfModels([model])


def device():
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def separate(bag, x, rate, job=None, on=None):
    """Split mono samples `x` at `rate` into (vocal, accompaniment), both mono at `rate` and the
    same length as `x`. The accompaniment is the drums, bass and other stems summed. `job` gets
    progress and stops the work when cancelled."""
    import julius
    import torch
    on = on or device()
    sr = bag.samplerate
    mix = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
    if rate != sr:
        mix = julius.resample_frac(mix, rate, sr)
    length = mix.shape[-1]
    wav = mix.expand(bag.audio_channels, -1)
    mean, std = wav.mean(), wav.std()
    if not torch.isfinite(std) or std < 1e-6:  # silence: nothing to separate
        return np.zeros_like(x), np.zeros_like(x)
    wav = (wav - mean) / std

    segment = float(bag.models[0].segment) * sr

    def progress(info):
        if job is not None and info.get("state") == "end":
            job.report(min(0.99, 0.05 + 0.9 * (info.get("segment_offset", 0) + segment) / max(1, length)),
                       "Separating the voice from the music")
        elif job is not None:
            job.check()

    from demucs.apply import apply_model
    with torch.no_grad():
        out = apply_model(bag, wav[None], device=on, split=True, overlap=0.25, shifts=1, progress=False,
                          callback=progress)[0]
    out = (out * std + mean).mean(dim=1)  # sources x samples, back to mono
    voc = bag.sources.index("vocals")
    vocal = out[voc]
    accompaniment = out.sum(dim=0) - vocal
    stems = torch.stack([vocal, accompaniment]).cpu()
    if rate != sr:
        stems = julius.resample_frac(stems, sr, rate)
    stems = stems.numpy()
    n = len(x)
    stems = stems[:, :n] if stems.shape[1] >= n else np.pad(stems, ((0, 0), (0, n - stems.shape[1])))
    return stems[0].astype(np.float32), stems[1].astype(np.float32)


class Separation:
    """The /api/desktop/separate routes, running HTDemucs through the MODEL.1 runtime."""

    def __init__(self, runtime, device_name=None):
        self.runtime = runtime
        self.device_name = device_name
        self._bag = None
        self._bag_lock = threading.Lock()
        self._results = OrderedDict()
        self._lock = threading.Lock()

    def _model(self, folder):
        with self._bag_lock:
            if self._bag is None:
                self._bag = load_htdemucs(folder / WEIGHTS)
            return self._bag

    def start(self, data):
        x, rate = decode_wav(data)

        def work(folder, job):
            job.report(0.02, "Loading the separation model")
            bag = self._model(folder)
            vocal, accompaniment = separate(bag, x, rate, job, self.device_name)
            job.check()
            stems = {"vocal": encode_wav(vocal, rate), "accompaniment": encode_wav(accompaniment, rate)}
            with self._lock:
                self._results[job.id] = stems
                while len(self._results) > KEEP_RESULTS:
                    self._results.popitem(last=False)
            return {"stems": list(STEMS), "seconds": round(len(x) / rate, 2)}

        return self.runtime.run(MODEL_ID, "Separate the voice from the music", work,
                                busy="A separation is already running; wait for it or cancel it.")

    def stem(self, job_id, name):
        with self._lock:
            return self._results.get(job_id, {}).get(name)

    async def __call__(self, scope, receive, send):
        import anyio
        path, method = scope.get("path", ""), scope.get("method", "")
        try:
            if path == SEPARATE_PATH:
                if method != "POST":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                data = await _body(scope, receive, MAX_BODY)
                if data is None:
                    return await models._reply(send, 413, {"error": "The recording is too large to separate."})
                job = await anyio.to_thread.run_sync(self.start, data)
                return await models._reply(send, 202, job.public())
            rest = path[len(SEPARATE_PATH) + 1:].split("/") if path.startswith(SEPARATE_PATH + "/") else []
            if len(rest) == 2 and rest[1].endswith(".wav") and rest[1][:-4] in STEMS:
                if method != "GET":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                wav = self.stem(rest[0], rest[1][:-4])
                if wav is None:
                    return await models._reply(send, 404, {"error": "No such separation; separate the recording again."})
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"audio/wav"), (b"content-length", str(len(wav)).encode()),
                                        (b"cache-control", b"no-store")]})
                return await send({"type": "http.response.body", "body": wav})
            return await models._reply(send, 404, {"error": "Not found"})
        except models.ModelError as exc:
            status = 409 if isinstance(exc, models.ModelBusy) else 400
            return await models._reply(send, status, {"error": str(exc)})


async def _body(scope, receive, limit):
    """The request body, or None when it is (or says it is) larger than `limit`."""
    for name, value in scope.get("headers", []):
        if name == b"content-length" and value.isdigit() and int(value) > limit:
            return None
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b""
        part = message.get("body", b"")
        size += len(part)
        if size > limit:
            return None
        chunks.append(part)
        if not message.get("more_body"):
            return b"".join(chunks)
