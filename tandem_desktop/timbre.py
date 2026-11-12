"""TIMBRE.1: play the person's own voice as an instrument with RAVE timbre transfer, in the Mac app only.

The window sends a sung or hummed recording; a RAVE model (an encoder and decoder trained on one
instrument: soprano saxophone, electric guitar or church organ, from the Intelligent Instruments
Lab, CC-BY-NC 4.0, LIC.1) encodes it and decodes it again as that instrument, so the phrasing,
pitch and loudness are the person's and the sound is the instrument's. The result is a new
recording of the same length and rate as the one sent; the original stays.

The models are the TorchScript files RAVE exports for realtime use, downloaded and verified by the
MODEL.1 runtime (`RAVE_MODELS` in models.CATALOG, pinned to one commit by URL, SHA-256 and size)
and loaded with torch.jit.load only after the runtime hashed them again. They are streaming
(causal, with cached convolutions), so the audio is fed in blocks, which keeps progress and cancel
working; the model is loaded fresh for every recording, because its caches carry the end of the
previous recording into the next one.

Routes (behind tandem_desktop.guarded_app; answers are JSON unless noted, never cached):
  POST /api/desktop/timbre?instrument=<sax|guitar|organ>   a 16-bit PCM WAV, mono or stereo, 8-96 kHz,
                                                           up to MAX_SECONDS: 202 with the job
  GET  /api/desktop/timbre/<job id>/timbre.wav             the instrument recording, mono 16-bit WAV
                                                           at the recording's rate and length

One recording is played by an instrument at a time (another is answered 409). The job (read and
cancelled at /api/desktop/jobs/<id>) reports progress block by block; the audio of the last
KEEP_RESULTS recordings is kept in memory for the window to fetch.
"""
import threading
import urllib.parse
from collections import OrderedDict

import numpy as np

from . import models
from .separation import _body, decode_wav, encode_wav

TIMBRE_PATH = "/api/desktop/timbre"
# The instruments the window offers, by the name it sends, with each model's sample rate.
INSTRUMENTS = {"sax": (models.RAVE_SAX, 48000), "guitar": (models.RAVE_GUITAR, 48000),
               "organ": (models.RAVE_ORGAN, 48000)}
MAX_SECONDS = 600
MAX_BODY = 256 << 20
KEEP_RESULTS = 2
BLOCK = 2048            # RAVE's block size: the models take whole blocks
CHUNK = BLOCK * 32      # samples fed per call (about 1.4 s at 48 kHz)
PEAK = 0.99


class TimbreError(models.ModelError):
    pass


def instrument_spec(name):
    try:
        return INSTRUMENTS[name]
    except KeyError:
        raise TimbreError("Choose an instrument: " + ", ".join(INSTRUMENTS) + ".") from None


def model_rate(model):
    """The sample rate a RAVE TorchScript model says it runs at (RAVE v1 exports call it
    sampling_rate, v2 and later sr)."""
    for name in ("sampling_rate", "sr"):
        if hasattr(model, name):
            return int(getattr(model, name))
    raise TimbreError("The instrument model does not say its sample rate.")


def load_rave(path, rate):
    """A RAVE model from its verified TorchScript file, checked to be an encoder and decoder at `rate`."""
    import torch
    model = torch.jit.load(str(path), map_location="cpu")
    model.eval()
    if not all(hasattr(model, name) for name in ("encode", "decode", "forward")):
        raise TimbreError("The instrument model is not a RAVE encoder and decoder.")
    if model_rate(model) != rate:
        raise TimbreError(f"The instrument model runs at {model_rate(model)} Hz, not the {rate} Hz Tandem expects.")
    return model


def transfer(model, x, rate, sr, job=None):
    """Mono samples `x` at `rate` played by the RAVE `model` (which runs at `sr`): mono float32 at
    `rate`, the same length as `x`, its peak at most PEAK. `job` gets progress and stops the work
    when cancelled."""
    import julius
    import torch
    wav = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
    if rate != sr:
        wav = julius.resample_frac(wav, rate, sr)
    n = wav.shape[-1]
    wav = torch.nn.functional.pad(wav, (0, -n % BLOCK))
    out = []
    with torch.no_grad():
        for start in range(0, wav.shape[-1], CHUNK):
            if job is not None:
                job.report(0.05 + 0.9 * start / wav.shape[-1], "Playing your voice on the instrument")
            out.append(model.forward(wav[start:start + CHUNK][None, None])[0, 0])
    y = torch.cat(out)[:n]
    if rate != sr:
        y = julius.resample_frac(y, sr, rate)
    y = y.numpy().astype(np.float32)
    y = y[:len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > PEAK:
        y = y * (PEAK / peak)
    return y.astype(np.float32)


class Timbre:
    """The /api/desktop/timbre routes, running RAVE through the MODEL.1 runtime."""

    def __init__(self, runtime):
        self.runtime = runtime
        self._start_lock = threading.Lock()
        self._results = OrderedDict()
        self._lock = threading.Lock()

    def start(self, data, instrument):
        spec, sr = instrument_spec(instrument)
        x, rate = decode_wav(data, MAX_SECONDS, "Playing the voice as an instrument")
        if np.max(np.abs(x)) < 1e-3:
            raise TimbreError("The recording is silent, so there is nothing for the instrument to play.")

        def work(folder, job):
            job.report(0.02, "Loading the " + spec.label)
            model = load_rave(folder / spec.files[0].name, sr)
            y = transfer(model, x, rate, sr, job)
            job.check()
            with self._lock:
                self._results[job.id] = encode_wav(y, rate)
                while len(self._results) > KEEP_RESULTS:
                    self._results.popitem(last=False)
            return {"instrument": instrument, "seconds": round(len(x) / rate, 2), "rate": rate}

        # One at a time across instruments: the runtime refuses a second run of the same model only.
        with self._start_lock:
            if any(self.runtime.jobs.running(kind="run", model=s.id) for s, _ in INSTRUMENTS.values()):
                raise models.ModelBusy("Your voice is already being played by an instrument; wait for it or cancel it.")
            return self.runtime.run(spec.id, "Play the voice as " + spec.label, work)

    def audio(self, job_id):
        with self._lock:
            return self._results.get(job_id)

    async def __call__(self, scope, receive, send):
        import anyio
        path, method = scope.get("path", ""), scope.get("method", "")
        try:
            if path == TIMBRE_PATH:
                if method != "POST":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                query = urllib.parse.parse_qs(scope.get("query_string", b"").decode("latin-1"))
                instrument = query.get("instrument", [""])[0]
                instrument_spec(instrument)
                data = await _body(scope, receive, MAX_BODY)
                if data is None:
                    return await models._reply(send, 413, {"error": "The recording is too large."})
                job = await anyio.to_thread.run_sync(lambda: self.start(data, instrument))
                return await models._reply(send, 202, job.public())
            rest = path[len(TIMBRE_PATH) + 1:].split("/") if path.startswith(TIMBRE_PATH + "/") else []
            if len(rest) == 2 and rest[1] == "timbre.wav":
                if method != "GET":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                wav = self.audio(rest[0])
                if wav is None:
                    return await models._reply(send, 404, {"error": "No such recording; play it on the instrument again."})
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"audio/wav"), (b"content-length", str(len(wav)).encode()),
                                        (b"cache-control", b"no-store")]})
                return await send({"type": "http.response.body", "body": wav})
            return await models._reply(send, 404, {"error": "Not found"})
        except models.ModelError as exc:
            status = 409 if isinstance(exc, models.ModelBusy) else 400
            return await models._reply(send, status, {"error": str(exc)})
