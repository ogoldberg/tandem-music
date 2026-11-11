"""DESK.3: projects as folders on disk in the Mac app.

A project folder holds exactly the files of a Tandem file (bundle.js, MOB.3), unzipped:

    tandem.json   {"format":"tandem-bundle","version":1,"name","savedAt"}; the name is the folder's
    project.json  the portable project, as Save project writes it; never any audio
    original.wav  the recording; polished.wav and tuned.wav when the studio made them

The page and the local server pass a project as that zip, so the studio reuses bundle.js both ways:
Save to folder sends the zip it would share, the server unpacks it into the folder the person picks in
a native save dialog; Open folder asks for a folder in a native dialog and answers its files as a zip,
which the studio opens like a Tandem file. The routes exist only inside guarded_app (the launch secret,
the app's own origin and host), never on the hosted app, and they write and read only these five file
names in a folder the person chose in the dialog. Nothing here imports pywebview: the launcher passes
the window's dialogs in (WindowDialogs), and tests pass a stand-in.
"""
import io
import json
import os
import re
import secrets
import threading
import zipfile
from pathlib import Path

import anyio

FILES = {"meta": "tandem.json", "project": "project.json", "original": "original.wav",
         "polished": "polished.wav", "tuned": "tuned.wav"}
RECORDINGS = ("original.wav", "polished.wav", "tuned.wav")
NAMES = frozenset(FILES.values())
# The same cap as bundle.js MAX_BUNDLE_BYTES: more than any recording the studio handles.
MAX_BYTES = 512 * 1024 * 1024
MAX_NAME = 60
DEFAULT_NAME = "Tandem project"
# Files a folder may hold that do not make it "someone else's folder" when saving into it.
IGNORABLE = frozenset({".DS_Store", "Icon\r", ".localized"})


class ProjectError(ValueError):
    """A project or folder Tandem cannot use; the message says what is wrong."""


def _is_wav(data):
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _json(data, name):
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProjectError(f"{name} could not be read: {exc}") from exc


def _check(files):
    """Check a project's files (name -> bytes): a project.json that is a Tandem project, WAV
    recordings, and a tandem.json that is an object when present."""
    if FILES["project"] not in files:
        raise ProjectError("There is no project.json, so this is not a Tandem project.")
    project = _json(files[FILES["project"]], "project.json")
    if not (isinstance(project, dict) and isinstance(project.get("notes"), list) and isinstance(project.get("drums"), list)
            and project.get("format", "tandem-project") == "tandem-project"):
        raise ProjectError("project.json is not a Tandem project.")
    if FILES["meta"] in files and not isinstance(_json(files[FILES["meta"]], "tandem.json"), dict):
        raise ProjectError("tandem.json is not a Tandem file description.")
    for name in RECORDINGS:
        if name in files and not _is_wav(files[name]):
            raise ProjectError(f"{name} is not a WAV recording.")
    return files


def files_from_bundle(data):
    """The files of a Tandem file the studio sent (a zip at the top level, as bundle.js writes it)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProjectError("This is not a Tandem file.") from exc
    with archive:
        infos = archive.infolist()
        for info in infos:
            if info.filename not in NAMES:
                raise ProjectError(f"A Tandem file holds only {', '.join(sorted(NAMES))}, not {info.filename}.")
        if len({i.filename for i in infos}) != len(infos):
            raise ProjectError("The Tandem file names a file twice.")
        if sum(i.file_size for i in infos) > MAX_BYTES:
            raise ProjectError("The project is too large to save.")
        try:
            files = {i.filename: archive.read(i) for i in infos}
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
            raise ProjectError(f"The Tandem file is damaged: {exc}") from exc
    return _check(files)


def _meta(files, name):
    """tandem.json naming the project after its folder, keeping the time it was saved."""
    saved_at = None
    if FILES["meta"] in files:
        old = _json(files[FILES["meta"]], "tandem.json")
        if isinstance(old, dict) and isinstance(old.get("savedAt"), (int, float)) and not isinstance(old.get("savedAt"), bool):
            saved_at = old["savedAt"]
    meta = {"format": "tandem-bundle", "version": 1, "name": name[:MAX_NAME], "savedAt": saved_at}
    return json.dumps(meta, indent=2).encode()


def suggested_name(files):
    """The name the save dialog suggests: the project's own, made safe as a folder name."""
    name = ""
    if FILES["meta"] in files:
        meta = _json(files[FILES["meta"]], "tandem.json")
        if isinstance(meta, dict) and isinstance(meta.get("name"), str):
            name = meta["name"]
    # The same clean-up as bundle.js bundleFileName.
    clean = re.sub(r"-+", "-", re.sub(r'[/\\:*?"<>|\x00-\x1f]+', "-", name))
    clean = clean.strip(" .-\t\n")[:MAX_NAME].strip()
    return clean or DEFAULT_NAME


def prepare_save_folder(path):
    """The folder to save a project into: made when new; an existing one must be empty or a Tandem
    project folder, so a save never mixes a project into someone else's folder."""
    path = Path(path)
    if path.exists() and not path.is_dir():
        raise ProjectError(f"{path.name} is a file; choose a new name for the project folder.")
    if path.is_dir():
        others = [p.name for p in path.iterdir() if p.name not in IGNORABLE]
        if others and not (path / FILES["project"]).is_file():
            raise ProjectError(f"{path.name} already holds other files and is not a Tandem project folder; choose a new name.")
    else:
        path.mkdir()
    return path


def write_folder(folder, files):
    """Write a project's files into its folder. Each file is written beside its final name and moved
    into place, recordings first and the project last; Tandem's files the project no longer has (a
    tuned take that was dropped) are removed, and every other file in the folder is left alone."""
    folder = Path(folder)
    files = dict(files)
    files[FILES["meta"]] = _meta(files, folder.name)
    order = [n for n in RECORDINGS if n in files] + [FILES["project"], FILES["meta"]]
    for name in order:
        tmp = folder / f".{name}.{secrets.token_hex(4)}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(files[name])
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, folder / name)
        finally:
            tmp.unlink(missing_ok=True)
    for name in RECORDINGS:
        if name not in files:
            (folder / name).unlink(missing_ok=True)


def read_folder(folder):
    """A project folder's files, checked as a project, with tandem.json naming it after the folder."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ProjectError(f"{folder.name} is not a folder.")
    files = {}
    total = 0
    for name in sorted(NAMES):
        path = folder / name
        if not path.exists():
            # An iCloud Drive file not downloaded to this Mac is a placeholder named .<name>.icloud.
            if (folder / f".{name}.icloud").exists():
                raise ProjectError(f"{name} is still in iCloud and not on this Mac yet; download the folder in Finder, then open it again.")
            continue
        if not path.is_file():
            raise ProjectError(f"{name} in {folder.name} is not a file.")
        total += path.stat().st_size
        if total > MAX_BYTES:
            raise ProjectError("The project is too large to open.")
        files[name] = path.read_bytes()
    if FILES["project"] not in files:
        raise ProjectError(f"{folder.name} has no project.json, so it is not a Tandem project folder.")
    _check(files)
    files[FILES["meta"]] = _meta(files, folder.name)
    return files


def bundle_from_files(files):
    """A Tandem file (stored zip, as bundle.js writes it) of a project's files."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for name in [FILES["meta"], FILES["project"], *RECORDINGS]:
            if name in files:
                z.writestr(name, files[name])
    return out.getvalue()


class WindowDialogs:
    """The native dialogs of the launcher's pywebview window. `window` is set once the window exists;
    the kinds are pywebview's FileDialog.SAVE and FileDialog.FOLDER. pywebview runs the panel on the
    main thread and waits for it, so these are called from a worker thread."""

    def __init__(self, save_kind, folder_kind):
        self.save_kind, self.folder_kind, self.window = save_kind, folder_kind, None

    def _window(self):
        if self.window is None:
            raise ProjectError("The Tandem window is not open yet.")
        return self.window

    def choose_save(self, directory, name):
        answer = self._window().create_file_dialog(self.save_kind, directory=directory, save_filename=name)
        if isinstance(answer, (tuple, list)):
            answer = answer[0] if answer else None
        return answer or None

    def choose_folder(self, directory):
        answer = self._window().create_file_dialog(self.folder_kind, directory=directory)
        if isinstance(answer, (tuple, list)):
            answer = answer[0] if answer else None
        return answer or None


SAVE_PATH = "/api/desktop/project/save"
OPEN_PATH = "/api/desktop/project/open"


class ProjectFolders:
    """ASGI app for the two folder routes; guarded_app calls it for /api/desktop/ requests that passed
    its checks. One dialog at a time; the next dialog starts in the folder around the last project."""

    def __init__(self, dialogs):
        self.dialogs = dialogs
        self.last = None
        self._busy = threading.Lock()

    def _start_dir(self):
        return str(self.last.parent) if self.last is not None else ""

    def _save(self, data):
        files = files_from_bundle(data)
        chosen = self.dialogs.choose_save(self._start_dir(), suggested_name(files))
        if not chosen:
            return None
        folder = prepare_save_folder(chosen)
        write_folder(folder, files)
        self.last = folder
        return {"folder": folder.name, "path": str(folder)}

    def _open(self):
        chosen = self.dialogs.choose_folder(self._start_dir())
        if not chosen:
            return None
        files = read_folder(chosen)
        self.last = Path(chosen)
        return bundle_from_files(files)

    async def __call__(self, scope, receive, send):
        path, method = scope.get("path", ""), scope.get("method", "")
        if path not in (SAVE_PATH, OPEN_PATH):
            return await _reply(send, 404, b"Not found")
        if method != "POST":
            return await _reply(send, 405, b"Use POST")
        try:
            body = await _read_body(scope, receive)
        except ProjectError as exc:
            return await _reply(send, 413, str(exc).encode())
        if not self._busy.acquire(blocking=False):
            return await _reply(send, 409, b"A file dialog is already open in Tandem; finish it first.")
        try:
            if path == SAVE_PATH:
                result = await anyio.to_thread.run_sync(self._save, body)
                if result is None:
                    return await _reply(send, 204, b"")
                return await _reply(send, 200, json.dumps(result).encode(), b"application/json")
            result = await anyio.to_thread.run_sync(self._open)
            if result is None:
                return await _reply(send, 204, b"")
            return await _reply(send, 200, result, b"application/zip")
        except ProjectError as exc:
            return await _reply(send, 400, str(exc).encode())
        except OSError as exc:
            what = "save the project folder" if path == SAVE_PATH else "read the project folder"
            return await _reply(send, 500, f"Could not {what}: {exc.strerror or exc}".encode())
        finally:
            self._busy.release()


async def _read_body(scope, receive):
    declared = [v for k, v in scope.get("headers", []) if k == b"content-length"]
    if declared and declared[0].isdigit() and int(declared[0]) > MAX_BYTES:
        raise ProjectError("The project is too large to save.")
    parts, size = [], 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BYTES:
            raise ProjectError("The project is too large to save.")
        parts.append(chunk)
        if not message.get("more_body"):
            break
    return b"".join(parts)


async def _reply(send, status, body, content_type=b"text/plain; charset=utf-8"):
    headers = [] if status == 204 else [(b"content-type", content_type), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b"" if status == 204 else body})
