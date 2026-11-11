"""DESK.3: projects as folders on disk in the Mac app (tandem_desktop/projects.py).

The page and the local server pass a project as the Tandem file of bundle.js (a zip); on disk it is
the same files as a folder. These tests cover the folder format, the two routes behind the launch
secret, and the native dialogs through a stand-in for pywebview's window."""
import asyncio
import io
import json
import socket
import wave
import zipfile

import httpx
import pytest

import tandem_desktop as desk
from tandem_desktop import projects as pj

PORT = 47999
SECRET = "s" * 43


def wav_bytes(seconds=0.1, rate=8000):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return out.getvalue()


PROJECT = {"format": "tandem-project", "version": 1, "bpm": 96, "instrument": "piano", "melody_locked": True,
           "notes": [{"m": 60, "t": 0, "d": 0.5}], "drums": [{"k": "kick", "t": 0}], "harmony": [], "harmony_instrument": "piano"}


def bundle(files=None, *, meta=None, project=PROJECT, compress=zipfile.ZIP_STORED):
    """A zip like bundle.js writeBundle makes."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compress) as z:
        z.writestr("tandem.json", json.dumps(meta if meta is not None else {"format": "tandem-bundle", "version": 1, "name": "Song", "savedAt": 1700000000000}))
        if project is not None:
            z.writestr("project.json", json.dumps(project, indent=2))  # JSON.stringify(project, null, 2)
        for name, data in (files if files is not None else {"original.wav": wav_bytes()}).items():
            z.writestr(name, data)
    return out.getvalue()


def zip_names(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


# The folder format

def test_a_bundle_becomes_a_folder_and_the_folder_becomes_the_same_bundle(tmp_path):
    recs = {"original.wav": wav_bytes(0.2), "polished.wav": wav_bytes(0.3), "tuned.wav": wav_bytes(0.4)}
    files = pj.files_from_bundle(bundle(recs))
    folder = tmp_path / "My song"
    folder.mkdir()
    pj.write_folder(folder, files)
    assert sorted(p.name for p in folder.iterdir()) == ["original.wav", "polished.wav", "project.json", "tandem.json", "tuned.wav"]
    for name, data in recs.items():
        assert (folder / name).read_bytes() == data
    assert json.loads((folder / "project.json").read_text())["notes"] == PROJECT["notes"]
    back = zip_names(pj.bundle_from_files(pj.read_folder(folder)))
    assert {k: v for k, v in back.items() if k.endswith(".wav")} == recs
    assert json.loads(back["project.json"]) == PROJECT
    meta = json.loads(back["tandem.json"])
    # The folder's name is the project's name; the time it was saved is kept.
    assert meta == {"format": "tandem-bundle", "version": 1, "name": "My song", "savedAt": 1700000000000}


def test_the_folder_is_plain_files_a_person_can_read(tmp_path):
    folder = tmp_path / "Plain"
    folder.mkdir()
    pj.write_folder(folder, pj.files_from_bundle(bundle()))
    # project.json is kept as the studio wrote it (indented, like Save project), so it reads well in a synced folder.
    assert (folder / "project.json").read_text().startswith('{\n  "format": "tandem-project"')
    with wave.open(str(folder / "original.wav")) as w:
        assert w.getframerate() == 8000


def test_saving_again_replaces_the_recordings_and_drops_the_ones_no_longer_there(tmp_path):
    folder = tmp_path / "Song"
    folder.mkdir()
    pj.write_folder(folder, pj.files_from_bundle(bundle({"original.wav": wav_bytes(), "tuned.wav": wav_bytes(0.5)})))
    (folder / "notes.txt").write_text("mine")
    pj.write_folder(folder, pj.files_from_bundle(bundle({"original.wav": wav_bytes(0.7)})))
    assert not (folder / "tuned.wav").exists()
    assert (folder / "original.wav").read_bytes() == wav_bytes(0.7)
    # Files that are not Tandem's are never touched, and no temporary files are left.
    assert (folder / "notes.txt").read_text() == "mine"
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt", "original.wav", "project.json", "tandem.json"]


def test_a_project_without_a_recording_is_a_folder_with_only_the_project(tmp_path):
    folder = tmp_path / "Notes only"
    folder.mkdir()
    pj.write_folder(folder, pj.files_from_bundle(bundle({})))
    assert sorted(p.name for p in folder.iterdir()) == ["project.json", "tandem.json"]
    assert "original.wav" not in zip_names(pj.bundle_from_files(pj.read_folder(folder)))


def test_a_folder_without_tandem_json_opens_named_after_the_folder(tmp_path):
    folder = tmp_path / "From Finder"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps(PROJECT))
    (folder / "original.wav").write_bytes(wav_bytes())
    meta = json.loads(pj.read_folder(folder)["tandem.json"])
    assert meta["name"] == "From Finder" and meta["savedAt"] is None


def test_a_deflated_bundle_is_read_too():
    files = pj.files_from_bundle(bundle(compress=zipfile.ZIP_DEFLATED))
    assert files["original.wav"] == wav_bytes()


@pytest.mark.parametrize("make, message", [
    (lambda: b"not a zip", "not a Tandem"),
    (lambda: bundle(project=None), "no project.json"),
    (lambda: bundle(project={"notes": []}), "not a Tandem project"),
    (lambda: bundle(project=[1]), "not a Tandem project"),
    (lambda: bundle({"original.wav": b"RIFF....WAVX"}), "original.wav is not a WAV"),
    (lambda: bundle({"../escape.wav": wav_bytes()}), "../escape.wav"),
    (lambda: bundle({"Song/original.wav": wav_bytes()}), "Song/original.wav"),
    (lambda: bundle({"run.sh": b"#!/bin/sh"}), "run.sh"),
    (lambda: bundle(meta=[]), "tandem.json"),
])
def test_anything_but_a_tandem_project_is_refused(make, message):
    with pytest.raises(pj.ProjectError, match=message.replace(".", r"\.").replace("/", "/")):
        pj.files_from_bundle(make())


def test_an_oversized_bundle_is_refused_before_it_is_read(monkeypatch):
    monkeypatch.setattr(pj, "MAX_BYTES", 1000)
    with pytest.raises(pj.ProjectError, match="too large"):
        pj.files_from_bundle(bundle({"original.wav": wav_bytes(1)}))


def test_a_folder_that_is_not_a_project_is_refused(tmp_path):
    with pytest.raises(pj.ProjectError, match="no project.json"):
        pj.read_folder(tmp_path)
    (tmp_path / "project.json").write_text("{broken")
    with pytest.raises(pj.ProjectError, match="project.json"):
        pj.read_folder(tmp_path)


def test_a_recording_still_in_icloud_is_named_instead_of_silently_left_out(tmp_path):
    (tmp_path / "project.json").write_text(json.dumps(PROJECT))
    (tmp_path / ".original.wav.icloud").write_bytes(b"placeholder")
    with pytest.raises(pj.ProjectError, match="original.wav is still in iCloud"):
        pj.read_folder(tmp_path)


@pytest.mark.parametrize("name", ["project.json", "original.wav", "tandem.json"])
def test_a_link_in_place_of_a_project_file_is_refused(tmp_path, name):
    """#61: a folder's files are read only when they are plain files in it, never through a link,
    even when the link points at a valid file elsewhere or at nothing."""
    folder, elsewhere = tmp_path / "Song", tmp_path / "elsewhere"
    folder.mkdir(); elsewhere.mkdir()
    (folder / "project.json").write_text(json.dumps(PROJECT))
    (folder / "original.wav").write_bytes(wav_bytes())
    target = elsewhere / name
    target.write_bytes((folder / name).read_bytes() if (folder / name).exists() else json.dumps({"format": "tandem-bundle", "version": 1}).encode())
    (folder / name).unlink(missing_ok=True)
    (folder / name).symlink_to(target)
    with pytest.raises(pj.ProjectError, match=f"{name} in Song is a link"):
        pj.read_folder(folder)
    target.unlink()
    with pytest.raises(pj.ProjectError, match=f"{name} in Song is a link"):
        pj.read_folder(folder)


def test_saving_into_a_folder_that_holds_other_things_is_refused(tmp_path):
    (tmp_path / "taxes.pdf").write_text("x")
    with pytest.raises(pj.ProjectError, match="not a Tandem project folder"):
        pj.prepare_save_folder(tmp_path)
    a_file = tmp_path / "taxes.pdf"
    with pytest.raises(pj.ProjectError, match="is a file"):
        pj.prepare_save_folder(a_file)
    new = tmp_path / "New song"
    assert pj.prepare_save_folder(new) == new and new.is_dir()
    empty = tmp_path / "Empty"
    empty.mkdir()
    (empty / ".DS_Store").write_bytes(b"")
    assert pj.prepare_save_folder(empty) == empty
    pj.write_folder(new, pj.files_from_bundle(bundle()))
    assert pj.prepare_save_folder(new) == new  # an existing project folder is saved over


@pytest.mark.parametrize("content", ['{"name": "web-app", "targets": {}}', "{broken", '{"notes": [], "drums": [], "format": "other"}'])
def test_another_apps_project_json_does_not_make_a_folder_tandems(tmp_path, content):
    # An Nx, Angular or other tool's project.json must not let a save overwrite it and its folder.
    (tmp_path / "project.json").write_text(content)
    (tmp_path / "original.wav").write_bytes(wav_bytes())
    with pytest.raises(pj.ProjectError, match="not a Tandem project folder"):
        pj.prepare_save_folder(tmp_path)
    assert (tmp_path / "project.json").read_text() == content


# The routes behind the launch secret, with the dialogs stood in for

class FakeDialogs:
    def __init__(self, save=None, folder=None):
        self.save, self.folder, self.calls = save, folder, []

    def choose_save(self, directory, name):
        self.calls.append(("save", directory, name))
        return self.save

    def choose_folder(self, directory):
        self.calls.append(("folder", directory))
        return self.folder


def client(dialogs):
    app = desk.guarded_app(PORT, SECRET, desktop_api=pj.ProjectFolders(dialogs))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}")


def call(dialogs, method, path, secret=SECRET, **kw):
    headers = {desk.LAUNCH_HEADER: secret} if secret else {}
    async def go():
        async with client(dialogs) as c:
            return await c.request(method, path, headers=headers, **kw)
    return asyncio.run(go())


def test_save_writes_the_folder_the_person_chose_and_open_reads_it_back(tmp_path):
    dialogs = FakeDialogs(save=str(tmp_path / "Chorus idea"), folder=str(tmp_path / "Chorus idea"))
    folders = pj.ProjectFolders(dialogs)
    app = desk.guarded_app(PORT, SECRET, desktop_api=folders)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            h = {desk.LAUNCH_HEADER: SECRET}
            saved = await c.post("/api/desktop/project/save", headers=h, content=bundle(), )
            opened = await c.post("/api/desktop/project/open", headers=h)
            return saved, opened
    saved, opened = asyncio.run(go())
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"folder": "Chorus idea", "path": str(tmp_path / "Chorus idea")}
    assert (tmp_path / "Chorus idea" / "original.wav").read_bytes() == wav_bytes()
    assert opened.status_code == 200 and opened.headers["content-type"] == "application/zip"
    files = zip_names(opened.content)
    assert files["original.wav"] == wav_bytes() and json.loads(files["tandem.json"])["name"] == "Chorus idea"
    # The save dialog suggested the project's name; the next dialog starts where the last folder is.
    assert dialogs.calls == [("save", "", "Song"), ("folder", str(tmp_path))]


def test_a_cancelled_dialog_writes_and_reads_nothing(tmp_path):
    dialogs = FakeDialogs()
    assert call(dialogs, "POST", "/api/desktop/project/save", content=bundle()).status_code == 204
    assert call(dialogs, "POST", "/api/desktop/project/open").status_code == 204
    assert list(tmp_path.iterdir()) == []


def test_a_project_without_a_name_is_suggested_as_tandem_project(tmp_path):
    dialogs = FakeDialogs()
    call(dialogs, "POST", "/api/desktop/project/save", content=bundle(meta={"format": "tandem-bundle", "version": 1, "name": " / ", "savedAt": None}))
    assert dialogs.calls == [("save", "", "Tandem project")]


def test_a_bad_bundle_is_refused_before_any_dialog_opens(tmp_path):
    dialogs = FakeDialogs(save=str(tmp_path / "x"))
    r = call(dialogs, "POST", "/api/desktop/project/save", content=b"junk")
    assert r.status_code == 400 and "not a Tandem" in r.text
    assert dialogs.calls == [] and not (tmp_path / "x").exists()


def test_problems_with_the_chosen_folder_are_explained(tmp_path):
    (tmp_path / "taxes.pdf").write_text("x")
    r = call(FakeDialogs(save=str(tmp_path)), "POST", "/api/desktop/project/save", content=bundle())
    assert r.status_code == 400 and "not a Tandem project folder" in r.text
    r = call(FakeDialogs(folder=str(tmp_path)), "POST", "/api/desktop/project/open")
    assert r.status_code == 400 and "no project.json" in r.text


def test_the_routes_need_the_launch_secret_and_post(tmp_path):
    dialogs = FakeDialogs(save=str(tmp_path / "x"), folder=str(tmp_path))
    assert call(dialogs, "POST", "/api/desktop/project/save", secret=None, content=bundle()).status_code == 403
    assert call(dialogs, "POST", "/api/desktop/project/open", secret="t" * 43).status_code == 403
    assert call(dialogs, "GET", "/api/desktop/project/open").status_code == 405
    assert call(dialogs, "POST", "/api/desktop/nothing").status_code == 404
    assert dialogs.calls == []


def test_the_hosted_app_has_no_folder_routes():
    from tandem_backend import app

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
            return await c.post("/api/desktop/project/open")
    assert asyncio.run(go()).status_code == 404


def test_a_body_over_the_limit_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(pj, "MAX_BYTES", 1000)
    dialogs = FakeDialogs(save=str(tmp_path / "x"))
    r = call(dialogs, "POST", "/api/desktop/project/save", content=bundle({"original.wav": wav_bytes(1)}))
    assert r.status_code == 413 and dialogs.calls == []


def test_a_body_sent_without_its_length_is_cut_off_at_the_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(pj, "MAX_BYTES", 1000)
    dialogs = FakeDialogs(save=str(tmp_path / "x"))
    chunks = [b"\0" * 600, b"\0" * 600, b"\0" * 600]
    sent = []

    async def receive():
        return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)
    scope = {"type": "http", "method": "POST", "path": pj.SAVE_PATH, "headers": []}
    asyncio.run(pj.ProjectFolders(dialogs)(scope, receive, send))
    assert sent[0]["status"] == 413 and dialogs.calls == []
    assert len(chunks) == 1  # it stopped reading once the limit was passed


def test_only_one_dialog_at_a_time(tmp_path):
    import threading
    entered, release = threading.Event(), threading.Event()

    class Slow(FakeDialogs):
        def choose_folder(self, directory):
            entered.set()
            release.wait(5)
            return None

    app = desk.guarded_app(PORT, SECRET, desktop_api=pj.ProjectFolders(Slow()))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://127.0.0.1:{PORT}") as c:
            h = {desk.LAUNCH_HEADER: SECRET}
            first = asyncio.create_task(c.post("/api/desktop/project/open", headers=h))
            await asyncio.get_running_loop().run_in_executor(None, entered.wait, 5)
            second = await c.post("/api/desktop/project/open", headers=h)
            release.set()
            return await first, second
    first, second = asyncio.run(go())
    assert first.status_code == 204
    assert second.status_code == 409 and "already open" in second.text


def test_window_dialogs_use_pywebviews_save_and_folder_dialogs():
    class Window:
        def __init__(self, answer):
            self.answer, self.calls = answer, []

        def create_file_dialog(self, kind, directory="", allow_multiple=False, save_filename=""):
            self.calls.append((kind, directory, save_filename))
            return self.answer

    d = pj.WindowDialogs(save_kind=30, folder_kind=20)
    with pytest.raises(pj.ProjectError, match="window"):
        d.choose_folder("")
    d.window = Window("/Users/me/Song")  # the save dialog answers a path
    assert d.choose_save("/Users/me", "Song") == "/Users/me/Song"
    d.window = Window(("/Users/me/Song",))  # the folder dialog answers a tuple (and so might another platform's save dialog)
    assert d.choose_save("/Users/me", "Song") == "/Users/me/Song"
    d.window = Window(("/Users/me/Song",))
    assert d.choose_folder("/Users/me") == "/Users/me/Song"
    assert d.window.calls == [(20, "/Users/me", "")]
    d.window = Window(None)
    assert d.choose_save("", "x") is None and d.choose_folder("") is None


def test_start_server_serves_the_folder_routes(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    secret = desk.new_launch_secret()
    server, thread = desk.start_server(port, secret, desktop_api=pj.ProjectFolders(FakeDialogs(save=str(tmp_path / "Live"))))
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/api/desktop/project/save", content=bundle(), headers={desk.LAUNCH_HEADER: secret})
        assert r.status_code == 200 and (tmp_path / "Live" / "project.json").exists()
    finally:
        desk.stop_server(server, thread)
