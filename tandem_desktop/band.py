"""GEN.2: a backing band that follows the person's own melody, made with MusicGen-Melody in the Mac app.

The window sends the melody as audio (the project's melody notes rendered with their instrument, or the
recorded take) and a style in words; MusicGen-Melody (Meta, 1.5B parameters, weights CC-BY-NC 4.0, LIC.1)
generates up to MAX_SECONDS of full-band audio whose harmony follows the melody's chroma, from time
zero, with the tempo and key written into the text prompt. The model's files are downloaded and
verified by the MODEL.1 runtime (`MUSICGEN_MELODY` in models.CATALOG) and loaded with transformers from
safetensors only, from the verified folder only (no network, no remote code, no pickle).

The chroma the model is conditioned on is computed here (`melody_chroma`), the same way transformers'
MusicgenMelodyFeatureExtractor does it, because that class needs torchaudio, which has no release for
the torch Tandem pins: a 16384-point power spectrogram every 4096 samples at 32 kHz, folded into
12 pitch classes, keeping only the strongest one in each frame.

Routes (behind tandem_desktop.guarded_app; answers are JSON unless noted, never cached):
  POST /api/desktop/band?style=&bpm=&key=&seconds=   the melody as a 16-bit PCM WAV: 202 with the job
  GET  /api/desktop/band/<job id>/band.wav           the band, mono 16-bit WAV at 32 kHz, `seconds` long

One generation runs at a time (a second is answered 409). The job (read and cancelled at
/api/desktop/jobs/<id>) reports progress while the model runs; the audio of the last KEEP_RESULTS
generations is kept in memory for the window to fetch.
"""
import re
import threading
import urllib.parse
from collections import OrderedDict

import numpy as np

from . import models
from .separation import _body, decode_wav, encode_wav

BAND_PATH = "/api/desktop/band"
MODEL_ID = models.MUSICGEN_MELODY.id
MAX_SECONDS = 30
MAX_INPUT_SECONDS = 600
MAX_BODY = 128 << 20
MAX_STYLE = 200
KEEP_RESULTS = 2
RATE = 32000
N_FFT = 16384
HOP = 4096
FRAME_RATE = 50  # EnCodec 32 kHz tokens per second
GUIDANCE = 3.0
KEY_RE = re.compile(r"^[A-G][#b]? (major|minor)$")


class BandError(models.ModelError):
    pass


def clean_style(style):
    """The style in words, one line of printable text, at most MAX_STYLE characters."""
    text = " ".join(str(style or "").split())
    if not text:
        raise BandError("Describe the band's style, for example: lo-fi band with brushed drums.")
    if len(text) > MAX_STYLE:
        raise BandError(f"Keep the style under {MAX_STYLE} characters.")
    if not text.isprintable():
        raise BandError("The style can only hold printable text.")
    return text


def prompt(style, bpm=None, key=None):
    """The text MusicGen is given: the style, then the tempo and key of the project when known."""
    parts = [clean_style(style)]
    if bpm is not None:
        if not (40 <= bpm <= 240):
            raise BandError("The tempo must be between 40 and 240 BPM.")
        parts.append(f"{bpm:g} bpm")
    if key:
        if not KEY_RE.match(key):
            raise BandError("The key must look like 'C major' or 'F# minor'.")
        parts.append(f"in {key}")
    return ", ".join(parts)


def melody_chroma(x, rate, seconds):
    """The first `seconds` of mono samples `x` at `rate` as MusicGen-Melody's chroma condition: a
    (1, frames, 12) float tensor, one-hot on the strongest pitch class of each frame."""
    import julius
    import torch
    from transformers.audio_utils import chroma_filter_bank
    wav = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
    if rate != RATE:
        wav = julius.resample_frac(wav, rate, RATE)
    wav = wav[:int(round(seconds * RATE))]
    if wav.shape[-1] < N_FFT:
        pad = N_FFT - wav.shape[-1]
        wav = torch.nn.functional.pad(wav, (pad // 2, pad - pad // 2))
    spec = torch.stft(wav, N_FFT, hop_length=HOP, win_length=N_FFT, window=torch.hann_window(N_FFT),
                      center=True, pad_mode="reflect", return_complex=True).abs() ** 2
    filters = torch.from_numpy(chroma_filter_bank(sampling_rate=RATE, num_frequency_bins=N_FFT, tuning=0,
                                                  num_chroma=12)).float()
    chroma = torch.einsum("cf,ft->tc", filters, spec)
    out = torch.zeros_like(chroma)
    out.scatter_(1, chroma.argmax(dim=1, keepdim=True), 1.0)
    return out[None]


def device():
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def load_musicgen(folder, on=None):
    """MusicGen-Melody and its tokenizer from the verified folder, from safetensors only."""
    from transformers import AutoTokenizer, MusicgenMelodyForConditionalGeneration
    model = MusicgenMelodyForConditionalGeneration.from_pretrained(
        str(folder), local_files_only=True, use_safetensors=True, trust_remote_code=False)
    tokenizer = AutoTokenizer.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
    model.eval()
    return model.to(on or device()), tokenizer


class _Progress:
    """A transformers streamer that turns each generated step into job progress (and stops the work
    there once the job is cancelled: Job.report raises JobCancelled)."""

    def __init__(self, job, steps):
        self.job, self.steps, self.done = job, steps, -1

    def put(self, _tokens):
        self.done += 1  # the first call carries the start token, not a generated step
        if self.job is not None and self.done > 0 and (self.done % 10 == 0 or self.done == self.steps):
            self.job.report(0.05 + 0.9 * min(1.0, self.done / self.steps), "Playing your melody with the band")

    def end(self):
        pass


def generate(loaded, x, rate, text, seconds, job=None):
    """`seconds` of band audio (mono float32 at RATE) following the melody in `x` (mono at `rate`)."""
    import torch
    model, tokenizer = loaded
    on = model.device
    steps = int(round(seconds * FRAME_RATE))
    inputs = tokenizer([text], return_tensors="pt", padding=True)
    chroma = melody_chroma(x, rate, seconds)
    with torch.no_grad():
        out = model.generate(input_ids=inputs["input_ids"].to(on), attention_mask=inputs["attention_mask"].to(on),
                             input_features=chroma.to(on), do_sample=True, guidance_scale=GUIDANCE,
                             max_new_tokens=steps, streamer=_Progress(job, steps))
    audio = out[0, 0].float().cpu().numpy()
    n = int(round(seconds * RATE))
    audio = audio[:n] if len(audio) >= n else np.pad(audio, (0, n - len(audio)))
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    return audio.astype(np.float32)


def _number(query, name, low, high, default=None):
    raw = query.get(name, [None])[0]
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError:
        raise BandError(f"{name} must be a number.") from None
    if not np.isfinite(value) or not (low <= value <= high):
        raise BandError(f"{name} must be between {low:g} and {high:g}.")
    return value


class Band:
    """The /api/desktop/band routes, running MusicGen-Melody through the MODEL.1 runtime."""

    def __init__(self, runtime, device_name=None):
        self.runtime = runtime
        self.device_name = device_name
        self._loaded = None
        self._load_lock = threading.Lock()
        self._results = OrderedDict()
        self._lock = threading.Lock()

    def _model(self, folder):
        with self._load_lock:
            if self._loaded is None:
                self._loaded = load_musicgen(folder, self.device_name)
            return self._loaded

    def start(self, data, style, bpm=None, key=None, seconds=None):
        x, rate = decode_wav(data, MAX_INPUT_SECONDS)
        text = prompt(style, bpm, key)
        length = len(x) / rate
        seconds = min(MAX_SECONDS, length) if seconds is None else seconds
        if not (1 <= seconds <= MAX_SECONDS):
            raise BandError(f"A band is 1 to {MAX_SECONDS} seconds long.")
        if np.max(np.abs(x[:int(seconds * rate)])) < 1e-3:
            raise BandError("The melody is silent, so there is nothing for the band to follow.")

        def work(folder, job):
            job.report(0.02, "Loading MusicGen-Melody")
            loaded = self._model(folder)
            band = generate(loaded, x, rate, text, seconds, job)
            job.check()
            with self._lock:
                self._results[job.id] = encode_wav(band, RATE)
                while len(self._results) > KEEP_RESULTS:
                    self._results.popitem(last=False)
            return {"seconds": round(seconds, 2), "rate": RATE, "prompt": text}

        return self.runtime.run(MODEL_ID, "Generate the band", work,
                                busy="A band is already being generated; wait for it or cancel it.")

    def audio(self, job_id):
        with self._lock:
            return self._results.get(job_id)

    async def __call__(self, scope, receive, send):
        import anyio
        path, method = scope.get("path", ""), scope.get("method", "")
        try:
            if path == BAND_PATH:
                if method != "POST":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                query = urllib.parse.parse_qs(scope.get("query_string", b"").decode("latin-1"))
                style = query.get("style", [""])[0]
                bpm = _number(query, "bpm", 40, 240)
                seconds = _number(query, "seconds", 1, MAX_SECONDS)
                key = query.get("key", [""])[0] or None
                data = await _body(scope, receive, MAX_BODY)
                if data is None:
                    return await models._reply(send, 413, {"error": "The melody recording is too large."})
                job = await anyio.to_thread.run_sync(lambda: self.start(data, style, bpm, key, seconds))
                return await models._reply(send, 202, job.public())
            rest = path[len(BAND_PATH) + 1:].split("/") if path.startswith(BAND_PATH + "/") else []
            if len(rest) == 2 and rest[1] == "band.wav":
                if method != "GET":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                wav = self.audio(rest[0])
                if wav is None:
                    return await models._reply(send, 404, {"error": "No such band; generate it again."})
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"audio/wav"), (b"content-length", str(len(wav)).encode()),
                                        (b"cache-control", b"no-store")]})
                return await send({"type": "http.response.body", "body": wav})
            return await models._reply(send, 404, {"error": "Not found"})
        except models.ModelError as exc:
            status = 409 if isinstance(exc, models.ModelBusy) else 400
            return await models._reply(send, status, {"error": str(exc)})
