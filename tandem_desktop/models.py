"""MODEL.1: download, verify and run large audio models in the Mac app.

Models are listed in a catalog (`CATALOG`): each names its files by URL, SHA-256 and size, and the
Python packages it needs (PyTorch and friends come from requirements-models.txt, installed only for
the Mac app, never in requirements.txt for the hosted app). Nothing is bundled: a model's files are
downloaded on request into <home>/models/<id>/, the size is known before the download starts, each
file is hashed while it streams and refused unless it matches its pinned SHA-256, and every file is
hashed again before a model is loaded (`ModelRuntime.run`), so a file changed on disk is never used.

Downloads and model runs are background jobs (`Jobs`): each reports progress, can be cancelled, and
reports its error instead of failing silently, so a minute-long run never blocks the window. The
routes below exist only behind tandem_desktop.guarded_app (the launch secret, the app's own origin
and host), which also hands this object to the hosted app as scope["tandem_models"] so /api/config
can say which models are installed. The hosted app (tandem_backend, Vercel) never imports this
module.

Routes (all answers are JSON and not cached):
  GET    /api/desktop/models                 the catalog: size, installed, missing packages, ready
  POST   /api/desktop/models/<id>/download   start (or rejoin) the download job; 202 with the job
  DELETE /api/desktop/models/<id>            remove the downloaded files
  GET    /api/desktop/jobs/<job id>          a job's state, progress, message and error
  DELETE /api/desktop/jobs/<job id>          cancel a job
"""
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import anyio

MODELS_PATH = "/api/desktop/models"
JOBS_PATH = "/api/desktop/jobs"
RECORD = "verified.json"
CHUNK = 1 << 20
KEEP_FINISHED = 32
FREE_SPACE_MARGIN = 256 << 20
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ModelError(Exception):
    """Something the person should be told, in words: a bad hash, no space, a missing package."""


class ModelBusy(ModelError):
    """The model is downloading, running or already installed (answered 409)."""


class NoSuchModel(ModelError):
    """The catalog has no model with that id (answered 404)."""


class JobCancelled(Exception):
    """Raised inside a job's work when the job was cancelled."""


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    files: tuple
    packages: tuple = ()
    licence: str = ""

    def __post_init__(self):
        if not ID_RE.match(self.id):
            raise ValueError(f"model id {self.id!r} must be lowercase letters, digits and hyphens")
        if not self.files:
            raise ValueError(f"model {self.id} names no files")
        names = [f.name for f in self.files]
        if len(set(names)) != len(names):
            raise ValueError(f"model {self.id} names a file twice")
        for f in self.files:
            if not NAME_RE.match(f.name) or f.name == RECORD:
                raise ValueError(f"model {self.id}: unusable file name {f.name!r}")
            if not SHA_RE.match(f.sha256):
                raise ValueError(f"model {self.id}: {f.name} needs its SHA-256 as 64 lowercase hex digits")
            if not isinstance(f.size, int) or f.size <= 0:
                raise ValueError(f"model {self.id}: {f.name} needs its size in bytes")
            if not f.url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
                raise ValueError(f"model {self.id}: {f.name} must be downloaded over https")

    @property
    def size(self):
        return sum(f.size for f in self.files)


# SEP.1: Demucs' htdemucs model, the safetensors weights its author publishes on Hugging Face,
# pinned to one commit of adefossez/HTDemucs. Run by tandem_desktop/separation.py. Demucs' code is
# MIT; the weights' terms for distribution are checked under LIC.1.
HTDEMUCS = ModelSpec(
    "htdemucs", "Voice separation (HTDemucs)",
    (ModelFile("955717e8.safetensors",
               "https://huggingface.co/adefossez/HTDemucs/resolve/cbc8a9b1a87023b7fd74e7b3412e6321c0eab003/955717e8.safetensors",
               "d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd", 84025440),),
    packages=("torch", "demucs", "safetensors", "julius"),
    licence="Demucs code MIT; weights' terms for distribution checked under LIC.1")

# GEN.2: Meta's MusicGen-Melody (1.5B parameters) in the Hugging Face transformers format, pinned
# to one commit of facebook/musicgen-melody: the config, the two safetensors shards with their
# index, and the T5 tokenizer. The repository's state_dict.bin files (pickles) are not downloaded.
# Run by tandem_desktop/band.py. The weights are CC-BY-NC 4.0: non-commercial use only (LIC.1).
_MUSICGEN = "https://huggingface.co/facebook/musicgen-melody/resolve/68d653a95788ec0d2b0abccab22c0b3a200c2d90/"
MUSICGEN_MELODY = ModelSpec(
    "musicgen-melody", "Backing band (MusicGen-Melody)",
    tuple(ModelFile(name, _MUSICGEN + name, sha, size) for name, sha, size in (
        ("config.json", "16018e4e7906feea208af7ad0b30b175301ca8708b37f3743adf9a1fc565e8a6", 7781),
        ("generation_config.json", "0c496442cb17f12f111b0baaf340a3a015baf80083deb806fab90229eb8d6d14", 224),
        ("model.safetensors.index.json", "fbf97fdcda4fbcb6dc50404ce4b73e94e352aa091f91eff7174de00bc3a5598f", 68461),
        ("model-00001-of-00002.safetensors", "3deb583fd977128b24f59c86d6706f01b35b4ab8553e8355cca6969a9b7440b4", 4966269512),
        ("model-00002-of-00002.safetensors", "01268b3a5f9819026a9ee6b76df35574e7dd521de3e6431c7fad16b44ce5a9c0", 1263380400),
        ("special_tokens_map.json", "5c87151ef0f72a99d1f766a4c418bd2a1f90aaa30a8e22fe5eca9641daebb64f", 2201),
        ("tokenizer.json", "ca7dc3c343c9fb095db86dca7fe7945fff7608c25e170daf6c477bdca99b93ff", 2422346),
        ("tokenizer_config.json", "cf78390648a76b34c0b3b24f2625521963360f6b386eb159129917243b6ecd41", 20794),
        ("spiece.model", "d60acb128cf7b7f2536e8f38a5b18a05535c9e14c7a355904270e15b0945ea86", 791656),
    )),
    packages=("torch", "transformers", "safetensors", "julius"),
    licence="MusicGen weights CC-BY-NC 4.0 (non-commercial use only; LIC.1); code MIT")

# TIMBRE.1: RAVE instrument models from the Intelligent Instruments Lab, one TorchScript file each,
# pinned to one commit of Intelligent-Instruments-Lab/rave-models. Run by tandem_desktop/timbre.py.
# RAVE publishes its models only as TorchScript (no safetensors): torch.jit.load runs TorchScript code
# in torch's own interpreter, not Python, and the file is loaded only after its SHA-256 matches the pin.
# The models are CC-BY-NC 4.0: non-commercial use only (LIC.1).
_RAVE = "https://huggingface.co/Intelligent-Instruments-Lab/rave-models/resolve/c25a03d625840c40cd3a48779ed72f2a1947d7b4/"
_RAVE_LICENCE = "RAVE models CC-BY-NC 4.0 (non-commercial use only; LIC.1)"
RAVE_SAX = ModelSpec(
    "rave-sax", "Soprano saxophone (RAVE)",
    (ModelFile("sax_soprano_franziskaschroeder_b2048_r48000_z20.ts", _RAVE + "sax_soprano_franziskaschroeder_b2048_r48000_z20.ts",
               "216cf07fe8c121671b23771b03652c23fa39a20f7e7072d093cce1aef3fda3ae", 121405924),),
    packages=("torch", "julius"), licence=_RAVE_LICENCE)
RAVE_GUITAR = ModelSpec(
    "rave-guitar", "Electric guitar (RAVE)",
    (ModelFile("guitar_iil_b2048_r48000_z16.ts", _RAVE + "guitar_iil_b2048_r48000_z16.ts",
               "02458214e23890d6818504319a5b9903eabfe87a524491f6524f453e7f3dbcf0", 163881670),),
    packages=("torch", "julius"), licence=_RAVE_LICENCE)
RAVE_ORGAN = ModelSpec(
    "rave-organ", "Church organ (RAVE)",
    (ModelFile("organ_bach_b2048_r48000_z16.ts", _RAVE + "organ_bach_b2048_r48000_z16.ts",
               "f7c06309e0388e666993226c06ed1438b56adc23b2a5a3b8f9155ed26990423c", 163879431),),
    packages=("torch", "julius"), licence=_RAVE_LICENCE)
RAVE_MODELS = (RAVE_SAX, RAVE_GUITAR, RAVE_ORGAN)

# The models Tandem can download. Each model that uses this runtime (SEP.1 Demucs, GEN.2
# MusicGen-Melody, TIMBRE.1 RAVE) adds its entry here with its pinned files.
CATALOG = (HTDEMUCS, MUSICGEN_MELODY) + RAVE_MODELS


@dataclass
class Job:
    id: str
    kind: str
    label: str
    model: str = ""
    state: str = "running"  # running, done, failed, cancelled
    progress: float = 0.0
    message: str = ""
    error: str = ""
    result: object = None
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def report(self, progress=None, message=None):
        """Called by the work: progress from 0 to 1 and a short message. Raises JobCancelled once
        the job is cancelled, so long work stops at its next report."""
        self.check()
        if progress is not None:
            self.progress = min(1.0, max(0.0, float(progress)))
        if message is not None:
            self.message = str(message)[:200]

    def check(self):
        if self.cancel_event.is_set():
            raise JobCancelled()

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def public(self):
        out = {"id": self.id, "kind": self.kind, "label": self.label, "model": self.model, "state": self.state,
               "progress": round(self.progress, 4), "message": self.message, "error": self.error}
        if self.state == "done" and isinstance(self.result, (dict, list, str, int, float, bool)):
            out["result"] = self.result
        return out


class Jobs:
    """Background jobs, one thread each. Finished jobs are kept (the last KEEP_FINISHED) so the
    window can read how they ended."""

    def __init__(self):
        self._jobs = OrderedDict()
        self._lock = threading.Lock()

    def start(self, kind, label, work, model=""):
        job = Job(id=secrets.token_urlsafe(12), kind=kind, label=label, model=model)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        threading.Thread(target=self._run, args=(job, work), name=f"tandem-job-{kind}", daemon=True).start()
        return job

    def _run(self, job, work):
        try:
            job.result = work(job)
            job.check()
            job.state, job.progress = "done", 1.0
        except JobCancelled:
            job.state, job.message = "cancelled", "Cancelled."
        except ModelError as exc:
            job.state, job.error = "failed", str(exc)[:500]
        except Exception as exc:  # report every failure; the window must never wait forever
            job.state, job.error = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            job.finished = time.time()

    def _trim(self):
        done = [k for k, j in self._jobs.items() if j.state != "running"]
        for k in done[:max(0, len(done) - KEEP_FINISHED)]:
            del self._jobs[k]

    def get(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id):
        job = self.get(job_id)
        if job is not None and job.state == "running":
            job.cancel_event.set()
        return job

    def running(self, kind=None, model=None):
        with self._lock:
            return [j for j in self._jobs.values() if j.state == "running"
                    and (kind is None or j.kind == kind) and (model is None or j.model == model)]

    def wait(self, job_id, timeout=None):
        """For tests and callers in Python: wait until the job has finished."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            job = self.get(job_id)
            if job is None or job.state != "running":
                return job
            if deadline is not None and time.monotonic() > deadline:
                return job
            time.sleep(0.01)


def _sha256(path, job=None):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            if job is not None:
                job.check()
            digest.update(chunk)
    return digest.hexdigest()


class ModelStore:
    """The downloaded files: <home>/models/<id>/<file name>, with verified.json recording each
    file's hash, size and modification time once it was verified."""

    def __init__(self, home):
        self.root = Path(home) / "models"

    def folder(self, spec):
        return self.root / spec.id

    def _record(self, spec):
        try:
            return json.loads((self.folder(spec) / RECORD).read_text())
        except (OSError, ValueError):
            return {}

    def _kept(self, spec, f, record):
        """`f` is present and unchanged since it was verified (by size and modification time)."""
        entry = record.get(f.name)
        try:
            st = (self.folder(spec) / f.name).stat()
        except OSError:
            return False
        return isinstance(entry, dict) and entry.get("sha256") == f.sha256 and st.st_size == f.size \
            and entry.get("mtime_ns") == st.st_mtime_ns

    def installed(self, spec):
        """Every file is present and unchanged since it was verified (`verify` hashes them again
        before loading)."""
        record = self._record(spec)
        return all(self._kept(spec, f, record) for f in spec.files)

    def verify(self, spec, job=None):
        """Hash every file again; refuse the model unless each matches its pinned SHA-256."""
        folder = self.folder(spec)
        for i, f in enumerate(spec.files):
            path = folder / f.name
            if job is not None:
                job.report(i / len(spec.files), f"Checking {spec.label}")
            if not path.is_file() or path.stat().st_size != f.size or _sha256(path, job) != f.sha256:
                raise ModelError(f"{spec.label} is not installed or its file {f.name} has changed. Download it again.")
        return folder

    def download(self, spec, job, client_factory=None):
        """Stream each file to <name>.part, hashing as it comes; keep it only when the hash and
        size match. Files already verified are kept. A refused or cancelled download leaves no
        partial file."""
        import httpx
        folder = self.folder(spec)
        folder.mkdir(parents=True, exist_ok=True)
        # Keep each file still as verified (a retry after a later file failed or was cancelled
        # downloads, and needs disk space for, only the rest); forget every other record.
        old = self._record(spec)
        record = {f.name: old[f.name] for f in spec.files if self._kept(spec, f, old)}
        todo = [f for f in spec.files if f.name not in record]
        need = sum(f.size for f in todo)
        free = shutil.disk_usage(folder).free
        if need + FREE_SPACE_MARGIN > free:
            raise ModelError(f"{spec.label} needs {_mb(need)} of free disk space and {_mb(free)} is free.")
        done_bytes = 0
        client = (client_factory or (lambda: httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=120))))()
        try:
            for f in todo:
                part = folder / (f.name + ".part")
                try:
                    digest, got = hashlib.sha256(), 0
                    with client.stream("GET", f.url) as response, open(part, "wb") as out:
                        if response.status_code != 200:
                            raise ModelError(f"The download of {spec.label} failed: the server answered {response.status_code}.")
                        declared = response.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) != f.size:
                            raise ModelError(f"{spec.label}: {f.name} is not the pinned file (its size differs). Nothing was installed.")
                        for chunk in response.iter_bytes(CHUNK):
                            got += len(chunk)
                            if got > f.size:
                                raise ModelError(f"{spec.label}: {f.name} is larger than the pinned file. Nothing was installed.")
                            digest.update(chunk)
                            out.write(chunk)
                            job.report((done_bytes + got) / need, f"Downloading {spec.label}: {_mb(done_bytes + got)} of {_mb(need)}")
                    if got != f.size or digest.hexdigest() != f.sha256:
                        raise ModelError(f"{spec.label}: {f.name} did not match its pinned SHA-256. Nothing was installed.")
                    final = folder / f.name
                    os.replace(part, final)
                    st = final.stat()
                    record[f.name] = {"sha256": f.sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
                    tmp = folder / (RECORD + ".tmp")
                    tmp.write_text(json.dumps(record))
                    os.replace(tmp, folder / RECORD)
                    done_bytes += f.size
                except BaseException:
                    part.unlink(missing_ok=True)
                    raise
        except httpx.HTTPError as exc:
            raise ModelError(f"The download of {spec.label} failed: {type(exc).__name__}.") from exc
        finally:
            client.close()
        return {"installed": spec.id}

    def remove(self, spec):
        shutil.rmtree(self.folder(spec), ignore_errors=True)


def _mb(n):
    return f"{n / 1e6:.1f} MB" if n < 1e9 else f"{n / 1e9:.2f} GB"


def missing_packages(spec):
    return [p for p in spec.packages if importlib.util.find_spec(p) is None]


class ModelRuntime:
    """The catalog, the downloaded files and the jobs, and the /api/desktop/models and
    /api/desktop/jobs routes."""

    def __init__(self, home, catalog=CATALOG, client_factory=None):
        self.catalog = {spec.id: spec for spec in catalog}
        if len(self.catalog) != len(catalog):
            raise ValueError("two catalog entries share an id")
        self.store = ModelStore(home)
        self.jobs = Jobs()
        self._client_factory = client_factory
        self._lock = threading.Lock()

    def spec(self, model_id):
        spec = self.catalog.get(model_id)
        if spec is None:
            raise NoSuchModel(f"There is no model called {model_id!r}.")
        return spec

    def describe(self, spec):
        installed, missing = self.store.installed(spec), missing_packages(spec)
        downloading = self.jobs.running(kind="download", model=spec.id)
        return {"id": spec.id, "label": spec.label, "size": spec.size, "licence": spec.licence,
                "installed": installed, "missing_packages": missing, "ready": installed and not missing,
                "download_job": downloading[0].id if downloading else None}

    def status(self):
        return {"models": [self.describe(s) for s in self.catalog.values()]}

    def installed_ids(self):
        """For /api/config: the models that are downloaded, verified and have their packages."""
        return [s.id for s in self.catalog.values() if self.store.installed(s) and not missing_packages(s)]

    def start_download(self, model_id):
        spec = self.spec(model_id)
        with self._lock:
            running = self.jobs.running(kind="download", model=spec.id)
            if running:
                return running[0]
            if self.jobs.running(model=spec.id):
                raise ModelBusy(f"{spec.label} is in use; wait for it to finish.")
            if self.store.installed(spec):
                raise ModelBusy(f"{spec.label} is already installed.")
            return self.jobs.start("download", f"Download {spec.label} ({_mb(spec.size)})",
                                   lambda job: self.store.download(spec, job, self._client_factory), model=spec.id)

    def remove(self, model_id):
        spec = self.spec(model_id)
        with self._lock:
            if self.jobs.running(model=spec.id):
                raise ModelBusy(f"{spec.label} is in use; cancel or wait for it first.")
            self.store.remove(spec)
        return self.describe(spec)

    def run(self, model_id, label, work, busy=None):
        """Run `work(folder, job)` as a background job with the model's files, after checking its
        packages and hashing every file again. `work` reports progress with job.report(...).
        With `busy` (a message), a run of this model that is still going refuses the new one with
        ModelBusy(busy); the check and the new job's registration happen under one lock."""
        spec = self.spec(model_id)
        with self._lock:
            if self.jobs.running(kind="download", model=spec.id):
                raise ModelBusy(f"{spec.label} is still downloading.")
            if busy is not None and self.jobs.running(kind="run", model=spec.id):
                raise ModelBusy(busy)
            if not self.store.installed(spec):
                raise ModelError(f"Download {spec.label} first ({_mb(spec.size)}).")

            def go(job):
                missing = missing_packages(spec)
                if missing:
                    raise ModelError(f"{spec.label} needs the Python packages {', '.join(missing)}: "
                                     "python -m pip install -r requirements-models.txt")
                folder = self.store.verify(spec, job)
                job.report(0.0, label)
                return work(folder, job)
            return self.jobs.start("run", label, go, model=spec.id)

    async def __call__(self, scope, receive, send):
        path, method = scope.get("path", ""), scope.get("method", "")
        try:
            if path == MODELS_PATH:
                if method != "GET":
                    return await _reply(send, 405, {"error": "Method not allowed"})
                return await _reply(send, 200, await anyio.to_thread.run_sync(self.status))
            if path.startswith(MODELS_PATH + "/"):
                rest = path[len(MODELS_PATH) + 1:].split("/")
                if len(rest) == 2 and rest[1] == "download":
                    if method != "POST":
                        return await _reply(send, 405, {"error": "Method not allowed"})
                    job = await anyio.to_thread.run_sync(self.start_download, rest[0])
                    return await _reply(send, 202, job.public())
                if len(rest) == 1:
                    if method != "DELETE":
                        return await _reply(send, 405, {"error": "Method not allowed"})
                    return await _reply(send, 200, await anyio.to_thread.run_sync(self.remove, rest[0]))
            elif path.startswith(JOBS_PATH + "/") and path.count("/") == 4:
                job_id = path[len(JOBS_PATH) + 1:]
                if method == "GET":
                    job = self.jobs.get(job_id)
                elif method == "DELETE":
                    job = self.jobs.cancel(job_id)
                else:
                    return await _reply(send, 405, {"error": "Method not allowed"})
                if job is None:
                    return await _reply(send, 404, {"error": "No such job."})
                return await _reply(send, 200, job.public())
            return await _reply(send, 404, {"error": "Not found"})
        except ModelError as exc:
            status = 404 if isinstance(exc, NoSuchModel) else 409 if isinstance(exc, ModelBusy) else 400
            return await _reply(send, status, {"error": str(exc)})


async def _reply(send, status, body):
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": data})
