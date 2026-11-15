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

MRT.1: a second engine plays the project's own notes. Google's Magenta RealTime 2 (the small model,
230M, exported for MLX; weights CC-BY 4.0, LIC.1; `MRT2_SMALL` in models.CATALOG) is steered by a
128-pitch piano roll every 40 ms frame (`piano_roll`: 2 on a note's first frame, 1 while it is held),
a style in words and drums on or off. The window sends the melody and harmony notes; the model is
stepped one frame at a time with that frame's notes from zero (`generate_notes`), the way MRT.0's spike
measured it, and the 48 kHz stereo it plays is folded to mono, like the other band.

Routes (behind tandem_desktop.guarded_app; answers are JSON unless noted, never cached):
  POST /api/desktop/band?style=&bpm=&key=&seconds=   the melody as a 16-bit PCM WAV: 202 with the job
  POST /api/desktop/band/notes?style=&seconds=&drums=  {"notes": [{m, t, d}]} as JSON: 202 with the job
  GET  /api/desktop/band/<job id>/band.wav           the band, mono 16-bit WAV (32 kHz from MusicGen,
                                                     48 kHz from Magenta RealTime 2), `seconds` long

One generation runs at a time, whichever engine (a second is answered 409), and one engine's model is
held in memory at a time. The job (read and cancelled at /api/desktop/jobs/<id>) reports progress
while the model runs; the audio of the last KEEP_RESULTS generations is kept in memory for the
window to fetch.
"""
import gc
import json
import os
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
NOTES_PATH = BAND_PATH + "/notes"
MRT_MODEL_ID = models.MRT2_SMALL.id
MRT_RATE = 48000
MRT_FRAME_RATE = 25  # one piano-roll frame and one model step every 40 ms
MRT_NOTES_GUIDANCE = 1.0  # the library's default, which MRT.0 measured
MAX_NOTES = 4096
MAX_NOTES_BODY = 1 << 20
BUSY = "A band is already being generated; wait for it or cancel it."
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


def clean_notes(data):
    """The notes of a /band/notes body ({"notes": [{m, t, d}]}): MIDI pitch 0-127, start and length in
    seconds, at most MAX_NOTES."""
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise BandError("Send the notes as JSON.") from None
    notes = body.get("notes") if isinstance(body, dict) else None
    if not isinstance(notes, list):
        raise BandError("Send the notes as JSON: {\"notes\": [{\"m\": 60, \"t\": 0, \"d\": 0.5}]}.")
    if len(notes) > MAX_NOTES:
        raise BandError(f"A band plays at most {MAX_NOTES} notes.")
    out = []
    for n in notes:
        if not isinstance(n, dict) or set(n) - {"m", "t", "d"}:
            raise BandError("Each note is {m, t, d}.")
        m, t, d = n.get("m"), n.get("t"), n.get("d")
        if isinstance(m, bool) or not isinstance(m, int) or not 0 <= m <= 127:
            raise BandError("A note's pitch (m) is a MIDI number from 0 to 127.")
        for v in (t, d):
            # An int is checked against the range below as it is: np.isfinite cannot take one too
            # large for a float (a long JSON integer), which would answer 500 instead of 400.
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not np.isfinite(v)):
                raise BandError("A note's start (t) and length (d) are numbers of seconds.")
        if t < 0 or t > MAX_INPUT_SECONDS or d <= 0 or d > MAX_INPUT_SECONDS:
            raise BandError(f"A note starts at 0 to {MAX_INPUT_SECONDS} s and lasts more than 0 s.")
        out.append({"m": m, "t": float(t), "d": float(d)})
    return out


def piano_roll(notes, seconds):
    """Magenta RealTime 2's piano roll for `seconds` of `notes`: (frames, 128) int8, one frame per
    40 ms from zero, 2 on a note's first frame, 1 on the frames it is held (at least one frame each)."""
    frames = int(round(seconds * MRT_FRAME_RATE))
    roll = np.zeros((frames, 128), dtype=np.int8)
    for n in notes:
        start = int(round(n["t"] * MRT_FRAME_RATE))
        if start >= frames:
            continue
        end = min(frames, max(start + 1, int(round((n["t"] + n["d"]) * MRT_FRAME_RATE))))
        roll[start + 1:end, n["m"]] = np.maximum(roll[start + 1:end, n["m"]], 1)
        roll[start, n["m"]] = 2
    return roll


def load_mrt(folder):
    """Magenta RealTime 2 from the verified folder (<home>/models/mrt2_small/): the exported graph and
    its state, and MusicCoCa from the same folder. Nothing is fetched from the network."""
    os.environ["HF_HUB_OFFLINE"] = "1"  # set outright: HF_HUB_OFFLINE=0 in the environment must not reach the network
    from magenta_rt import musiccoca, paths
    paths.set_magenta_home(folder.parent.parent)  # magenta_rt reads <home>/models/<name>/<name>.mlxfn
    from magenta_rt import MagentaRT2StdMlxfn
    from magenta_rt.config import DRUM_PIANOROLL, MUSICCOCA, PIANOROLL_WITH_ONSETS
    mrt = MagentaRT2StdMlxfn(size=folder.name, style_model=musiccoca.MusicCoCa(resource_dir=folder))
    return mrt, (MUSICCOCA.key, PIANOROLL_WITH_ONSETS.key, DRUM_PIANOROLL.key)


def generate_notes(loaded, roll, style, drums, job=None):
    """The band playing `roll` (from piano_roll), mono float32 at MRT_RATE, one 40 ms step per frame.
    `loaded` is load_mrt's (model, (style key, notes key, drums key))."""
    mrt, (style_key, notes_key, drums_key) = loaded
    tokens = mrt.tokenize_style(mrt.embed_style(style, use_mapper=True)).tolist()[:12]
    state, chunks = None, []
    for i, frame in enumerate(roll):
        if job is not None and i % MRT_FRAME_RATE == 0:
            job.report(0.05 + 0.9 * i / len(roll), "Playing your notes with the band")
        conditioning = {style_key: tokens, notes_key: frame.tolist(), drums_key: [1 if drums else 0]}
        wav, state = mrt.generate(conditioning=conditioning, cfg_scales={"notes": MRT_NOTES_GUIDANCE},
                                  frames=1, state=state)
        chunks.append(np.asarray(wav.samples, dtype=np.float32))
    y = np.concatenate(chunks, 0) if chunks else np.zeros(0, dtype=np.float32)
    audio = y.mean(axis=1) if y.ndim == 2 else y
    n = int(round(len(roll) / MRT_FRAME_RATE * MRT_RATE))
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

    def _model(self, engine, folder):
        """The engine's model, loaded once; loading one engine lets the other's go first, so only one
        large model is held in memory."""
        with self._load_lock:
            if self._loaded is None or self._loaded[0] != engine:
                self._loaded = None
                gc.collect()
                model = load_musicgen(folder, self.device_name) if engine == MODEL_ID else load_mrt(folder)
                self._loaded = (engine, model)
            return self._loaded[1]

    def _run(self, model_id, label, work):
        """A generation as a MODEL.1 job, refused while either engine is generating."""
        with self._lock:
            if any(self.runtime.jobs.running(kind="run", model=m) for m in (MODEL_ID, MRT_MODEL_ID)):
                raise models.ModelBusy(BUSY)
            return self.runtime.run(model_id, label, work, busy=BUSY)

    def _keep(self, job, wav):
        with self._lock:
            self._results[job.id] = wav
            while len(self._results) > KEEP_RESULTS:
                self._results.popitem(last=False)

    def start(self, data, style, bpm=None, key=None, seconds=None):
        x, rate = decode_wav(data, MAX_INPUT_SECONDS, "The band")
        text = prompt(style, bpm, key)
        length = len(x) / rate
        seconds = min(MAX_SECONDS, length) if seconds is None else seconds
        if not (1 <= seconds <= MAX_SECONDS):
            raise BandError(f"A band is 1 to {MAX_SECONDS} seconds long.")
        if np.max(np.abs(x[:int(seconds * rate)])) < 1e-3:
            raise BandError("The melody is silent, so there is nothing for the band to follow.")

        def work(folder, job):
            job.report(0.02, "Loading MusicGen-Melody")
            loaded = self._model(MODEL_ID, folder)
            band = generate(loaded, x, rate, text, seconds, job)
            job.check()
            self._keep(job, encode_wav(band, RATE))
            return {"seconds": round(seconds, 2), "rate": RATE, "prompt": text}

        return self._run(MODEL_ID, "Generate the band", work)

    def start_notes(self, data, style, seconds=None, drums=True):
        """MRT.1: Magenta RealTime 2 plays the notes in `data` (a /band/notes body) from zero."""
        notes = clean_notes(data)
        text = clean_style(style)
        if not notes:
            raise BandError("There are no notes for the band to play; add a melody or chords first.")
        end = max(n["t"] + n["d"] for n in notes)
        seconds = min(MAX_SECONDS, end) if seconds is None else seconds
        if not (1 <= seconds <= MAX_SECONDS):
            raise BandError(f"A band is 1 to {MAX_SECONDS} seconds long.")
        roll = piano_roll(notes, seconds)
        if not roll.any():
            raise BandError("No note starts in the band's length, so there is nothing for it to play.")

        def work(folder, job):
            job.report(0.02, "Loading Magenta RealTime 2")
            mrt = self._model(MRT_MODEL_ID, folder)
            band = generate_notes(mrt, roll, text, drums, job)
            job.check()
            self._keep(job, encode_wav(band, MRT_RATE))
            return {"seconds": round(seconds, 2), "rate": MRT_RATE, "style": text, "drums": bool(drums)}

        return self._run(MRT_MODEL_ID, "Generate the band from the notes", work)

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
            if path == NOTES_PATH:
                if method != "POST":
                    return await models._reply(send, 405, {"error": "Method not allowed"})
                query = urllib.parse.parse_qs(scope.get("query_string", b"").decode("latin-1"))
                style = query.get("style", [""])[0]
                seconds = _number(query, "seconds", 1, MAX_SECONDS)
                drums = query.get("drums", ["1"])[0]
                if drums not in ("0", "1"):
                    raise BandError("drums must be 0 or 1.")
                data = await _body(scope, receive, MAX_NOTES_BODY)
                if data is None:
                    return await models._reply(send, 413, {"error": "Too many notes for one band."})
                job = await anyio.to_thread.run_sync(lambda: self.start_notes(data, style, seconds, drums == "1"))
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
