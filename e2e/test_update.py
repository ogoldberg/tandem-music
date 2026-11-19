"""FIX.6: an update never leaves the studio with a page from one version and modules from another. The page and
the modules it imports are one set, installed whole by the new service worker and switched to on Update; until
then, and whenever an update cannot be fetched whole, the studio opens as it was, online and offline.

The server runs from a copy of the app, so the test deploys a new version by changing the copy's files."""
import json
import shutil
import zipfile
from contextlib import contextmanager

import pytest
from playwright.sync_api import expect

from conftest import ALL_CONTROLS, ROOT, Server
from test_midi import MOCK_MIDI
from test_studio import tone_wav
from test_capture import assert_server_down, ideas, open_capture, phone_page, wait_for_service_worker

GROOVE_IMPORT = "import {estimateTempo,quantizeProject,barOrigin} from './groove.js';"
STARTED = "document.getElementById('notecount').textContent !== ''"
SKIP = {".git", ".venv", ".claude", "node_modules", "__pycache__", ".pytest_cache"}


@pytest.fixture
def app_copy(tmp_path):
    """The app's top-level files copied (the server finds its files next to its own module) and its folders linked."""
    root = tmp_path / "app"
    root.mkdir()
    for entry in ROOT.iterdir():
        if entry.name in SKIP:
            continue
        if entry.is_dir():
            (root / entry.name).symlink_to(entry, target_is_directory=True)
        else:
            shutil.copy2(entry, root / entry.name)
    return root


@pytest.fixture
def copy_server(app_copy, tmp_path):
    server = Server(tmp_path / "uvicorn.log", root=app_copy)
    yield server
    server.stop()


@contextmanager
def studio_on(browser, server, script=None):
    """The studio, controlled by its service worker; fails the test on any page error or console error."""
    context = browser.new_context(base_url=server.url)
    context.add_init_script(ALL_CONTROLS)
    if script:
        context.add_init_script(script)
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.goto("/")
    page.wait_for_function(STARTED)
    wait_for_service_worker(page)
    page.reload()
    page.wait_for_function("!!navigator.serviceWorker.controller")
    page.wait_for_function(STARTED)
    yield page
    context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def deploy(root):
    """A new version: a page that imports a name only the new groove.js exports."""
    page = root / "index.html"
    html = page.read_text()
    assert html.count(GROOVE_IMPORT) == 1
    page.write_text(html.replace(GROOVE_IMPORT, GROOVE_IMPORT.replace("barOrigin}", "barOrigin,fix6Probe}")
                                 + "window.fix6Version=fix6Probe();"))
    groove = root / "groove.js"
    groove.write_text(groove.read_text() + "\nexport function fix6Probe() { return 'deploy 2'; }\n")


def update_settled(page):
    """Asks the browser to look for a new worker and waits until it has finished installing (or failed)."""
    return page.evaluate("""async () => { const reg = await navigator.serviceWorker.getRegistration();
      await reg.update().catch(() => {});
      for (let i = 0; i < 100 && reg.installing; i++) await new Promise(r => setTimeout(r, 100));
      return {installing: !!reg.installing, waiting: !!reg.waiting}; }""")


def go_offline(server):
    server.stop()
    assert_server_down(server)


def test_an_update_cut_off_before_a_module_leaves_the_studio_as_it_was(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        # The new page is on the server, and its groove.js cannot be fetched (as when the connection drops).
        (app_copy / "groove.js").unlink()
        page.reload()
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") is None
        # The new worker could not fetch the whole set, so it is not installed and nothing is offered.
        assert update_settled(page) == {"installing": False, "waiting": False}
        expect(page.locator("#swupdate")).to_be_hidden()
        go_offline(copy_server)
        page.reload()
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") is None


def test_an_update_fetched_whole_is_offered_and_opens_online_and_offline(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        page.reload()
        page.wait_for_function(STARTED)
        # The open version stays until the person takes the update.
        assert page.evaluate("window.fix6Version") is None
        assert update_settled(page) == {"installing": False, "waiting": True}
        expect(page.locator("#swupdate")).to_be_visible()
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"
        expect(page.locator("#swupdate")).to_be_hidden()
        go_offline(copy_server)
        page.reload()
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


def serve_stale_groove(root):
    """The server sends the groove.js of the version before (as a cache in the way could), under the new worker."""
    stale = root / "groove-stale.js"
    shutil.copy2(root / "groove.js", stale)
    backend = root / "tandem_backend.py"
    source = backend.read_text()
    route = 'Path(__file__).resolve().parent / "groove.js"'
    assert source.count(route) == 1
    backend.write_text(source.replace(route, 'Path(__file__).resolve().parent / "groove-stale.js"'))


def test_an_update_that_meets_an_older_module_is_not_installed(browser, app_copy, tmp_path):
    serve_stale_groove(app_copy)
    server = Server(tmp_path / "stale.log", root=app_copy)
    try:
        with studio_on(browser, server) as page:
            # The new worker names the new groove.js, but the server answers 200 with the old one.
            deploy(app_copy)
            assert update_settled(page) == {"installing": False, "waiting": False}
            expect(page.locator("#swupdate")).to_be_hidden()
            go_offline(server)
            page.reload()
            page.wait_for_function(STARTED)
            assert page.evaluate("window.fix6Version") is None
    finally:
        server.stop()


FIX6_MODULE = "\nexport const fix6Module = 'deploy 2';\n"
# Posted by a worker that runs the new tuneworker.js, or the new worldtune.js it imports.
FIX6_WORKER = "\nif (typeof WorkerGlobalScope !== 'undefined') postMessage('fix6 deploy 2');\n"
WORKER_SAYS = """() => new Promise(done => { const w = new Worker('./tuneworker.js', {type: 'module'}), said = [];
  w.onmessage = e => said.push(e.data); setTimeout(() => { w.terminate(); done(said.filter(m => typeof m === 'string')) }, 1500) })"""


def test_a_tab_left_open_keeps_its_own_version_when_another_takes_the_update(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as first:
        second = first.context.new_page()
        second.goto("/")
        second.wait_for_function(STARTED)
        deploy(app_copy)
        with open(app_copy / "polish.js", "a") as f:
            f.write(FIX6_MODULE)
        for name in ("tuneworker.js", "worldtune.js"):
            with open(app_copy / name, "a") as f:
                f.write(FIX6_WORKER)
        assert update_settled(first)["waiting"]
        with first.expect_navigation():
            first.click("#swupdate")
        first.wait_for_function(STARTED)
        assert first.evaluate("window.fix6Version") == "deploy 2"
        assert first.evaluate("async () => (await import('./polish.js')).fix6Module") == "deploy 2"
        assert first.evaluate(WORKER_SAYS) == ["fix6 deploy 2", "fix6 deploy 2"]
        # The other tab still runs the version it opened with: what it loads now (a module Polish imports
        # later, the tuning worker and what that worker imports) comes from that version, and it offers Update.
        assert second.evaluate("window.fix6Version") is None
        assert second.evaluate("async () => (await import('./polish.js')).fix6Module") is None
        assert second.evaluate(WORKER_SAYS) == []
        expect(second.locator("#swupdate")).to_be_visible()
        with second.expect_navigation():
            second.click("#swupdate")
        second.wait_for_function(STARTED)
        assert second.evaluate("window.fix6Version") == "deploy 2"


def test_a_module_the_next_version_drops_still_comes_from_an_open_tabs_version(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as first:
        second = first.context.new_page()
        second.goto("/")
        second.wait_for_function(STARTED)
        deploy(app_copy)
        # The next version no longer has polish.js in its shell, and the server now sends a different one.
        worker = app_copy / "sw.js"
        source = worker.read_text()
        assert source.count("'./polish.js',") == 1
        worker.write_text(source.replace("'./polish.js',", ""))
        with open(app_copy / "polish.js", "a") as f:
            f.write(FIX6_MODULE)
        assert update_settled(first)["waiting"]
        with first.expect_navigation():
            first.click("#swupdate")
        first.wait_for_function(STARTED)
        assert first.evaluate("window.fix6Version") == "deploy 2"
        # The tab left open is still on its own version, which has polish.js: it gets that one, with Polish's export.
        assert second.evaluate("async () => { const m = await import('./polish.js'); "
                               "return [m.fix6Module ?? null, typeof m.polishSamples]; }") == [None, "function"]


HOLD_RECORDINGS = """() => new Promise(held => navigator.locks.request('tandem-recordings', {mode: 'exclusive'},
  () => new Promise(release => { window.fix6Release = release; window.fix6Page = 'before'; held(); })))"""


@contextmanager
def capture_with_update(browser, browser_name, app_copy, copy_server):
    """The capture page, controlled by its worker, with a new version waiting and Update offered."""
    with phone_page(browser, browser_name, copy_server.url) as page:
        yield offer_update(page, app_copy)


def offer_update(page, app_copy):
    open_capture(page)
    wait_for_service_worker(page)
    page.reload()
    page.wait_for_function("!!navigator.serviceWorker.controller")
    expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
    deploy(app_copy)
    assert update_settled(page)["waiting"]
    expect(page.locator("#swupdate")).to_be_visible()
    return page


def test_update_waits_for_a_take_on_the_capture_page(browser, browser_name, app_copy, copy_server):
    with capture_with_update(browser, browser_name, app_copy, copy_server) as page:
        page.click("#record")
        expect(page.locator("#record")).to_have_attribute("aria-pressed", "true")
        page.wait_for_timeout(1200)
        page.click("#swupdate")
        expect(page.locator("#status")).to_have_text("Stop the recording first: Update reloads Tandem.")
        # Still recording on the same page. The take is stopped while its write cannot finish yet (as when another
        # tab holds the recordings), and Update is taken while it is being kept.
        expect(page.locator("#record")).to_have_attribute("aria-pressed", "true")
        page.evaluate(HOLD_RECORDINGS)
        page.click("#record")
        expect(page.locator("#status")).to_have_text("Keeping the idea…")
        page.click("#swupdate")
        # No new take starts once Update has begun, and the page waits for the write.
        page.evaluate("document.getElementById('record').onclick()")
        page.wait_for_timeout(1500)
        assert page.evaluate("window.fix6Page") == "before"
        expect(page.locator("#record")).to_have_attribute("aria-pressed", "false")
        with page.expect_navigation():
            page.evaluate("window.fix6Release()")
        expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
        expect(page.locator("#swupdate")).to_be_hidden()
        assert len(ideas(page)) == 1


def test_update_waits_for_a_take_the_device_did_not_keep_to_be_downloaded(browser, browser_name, app_copy,
                                                                          copy_server):
    with capture_with_update(browser, browser_name, app_copy, copy_server) as page:
        page.evaluate("""() => { FileSystemWritableFileStream.prototype.write = function () {
          return Promise.reject(new DOMException('full', 'QuotaExceededError')); }; }""")
        page.click("#record")
        expect(page.locator("#status")).to_contain_text("Recording…")
        page.wait_for_timeout(800)
        page.click("#record")
        expect(page.locator("#status")).to_contain_text("Could not keep the idea on this device")
        page.evaluate("window.fix6Page = 'before'")
        page.click("#swupdate")
        expect(page.locator("#status")).to_have_text(
            "Download the recording that was not kept first: Update reloads Tandem, and it is not saved on this device.")
        assert page.evaluate("window.fix6Page") == "before"
        expect(page.locator("#rescue")).to_be_visible()
        with page.expect_download():
            page.click("#rescue")
        with page.expect_navigation():
            page.click("#swupdate")
        expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")


ACTIVATE_FROM_ANOTHER_TAB = """async () => { const reg = await navigator.serviceWorker.getRegistration();
  const changed = new Promise(r => navigator.serviceWorker.addEventListener('controllerchange', r, {once: true}));
  reg.waiting.postMessage('activate'); await changed; }"""


def test_update_waits_for_a_take_when_another_tab_takes_the_update_first(browser, browser_name, app_copy,
                                                                        copy_server):
    with capture_with_update(browser, browser_name, app_copy, copy_server) as page:
        page.evaluate(HOLD_RECORDINGS)
        page.click("#record")
        expect(page.locator("#status")).to_contain_text("Recording…")
        page.wait_for_timeout(800)
        page.click("#record")
        expect(page.locator("#status")).to_have_text("Keeping the idea…")
        page.click("#swupdate")
        # While this page waits for its write, another tab takes the update: the new worker controls this page,
        # which still reloads only once the idea is kept.
        other = page.context.new_page()
        other.goto(copy_server.url + "/capture")
        other.evaluate(ACTIVATE_FROM_ANOTHER_TAB)
        page.wait_for_timeout(1500)
        assert page.evaluate("window.fix6Page") == "before"
        with page.expect_navigation():
            page.evaluate("window.fix6Release()")
        expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
        expect(page.locator("#swupdate")).to_be_hidden()
        assert len(ideas(page)) == 1


def test_studio_update_waits_for_its_write_when_another_tab_takes_the_update_first(browser, app_copy, copy_server,
                                                                                   tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        expect(page.locator("#swupdate")).to_be_visible()
        page.evaluate(HOLD_RECORDINGS)
        page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
        expect(page.locator("#status")).to_contain_text("Recorded")
        page.click("#swupdate")
        other = page.context.new_page()
        other.goto("/")
        other.wait_for_function(STARTED)
        other.evaluate(ACTIVATE_FROM_ANOTHER_TAB)
        page.wait_for_timeout(1500)
        assert page.evaluate("window.fix6Page") == "before"
        with page.expect_navigation():
            page.evaluate("window.fix6Release()")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"
        # The recording reached the device before the reload: the draft links it.
        assert page.evaluate("""async () => { const db = await new Promise((ok, no) => {
          const r = indexedDB.open('tandem'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
          const links = await new Promise((ok, no) => { const r = db.transaction('kv').objectStore('kv')
            .get('draft-audio'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
          db.close(); return !!links?.original; }""")


def test_studio_update_waits_for_a_take_from_the_keyboard(browser, app_copy, copy_server):
    with studio_on(browser, copy_server, MOCK_MIDI) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate("window.fix6Page = 'before'")
        page.click("#midiconnect")
        expect(page.locator("#midiinfo")).to_have_text("1 input, 1 output")
        page.click("#midirecord")
        expect(page.locator("#midirecord")).to_contain_text("Stop recording")
        page.click("#swupdate")
        expect(page.locator("#status")).to_have_text("Stop the recording first: Update reloads Tandem.")
        page.wait_for_timeout(1000)
        assert page.evaluate("window.fix6Page") == "before"
        expect(page.locator("#midirecord")).to_contain_text("Stop recording")
        page.click("#midirecord")
        expect(page.locator("#midirecord")).to_contain_text("Record from keyboard")
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


def test_studio_update_waits_for_a_recording_the_device_did_not_keep_to_be_downloaded(browser, app_copy, copy_server,
                                                                                       tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate("""() => { FileSystemWritableFileStream.prototype.write = function () {
          return Promise.reject(new DOMException('full', 'QuotaExceededError')); }; }""")
        page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
        expect(page.locator("#status")).to_contain_text("Could not keep the recording on this device")
        page.evaluate("window.fix6Page = 'before'")
        page.click("#swupdate")
        expect(page.locator("#status")).to_have_text(
            "Download the recording that was not kept first: Update reloads Tandem, and it is not saved on this device.")
        page.wait_for_timeout(1000)
        assert page.evaluate("window.fix6Page") == "before"
        expect(page.locator("#audiorescue")).to_be_visible()
        with page.expect_download() as got:
            page.click("#audiorescue")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        assert saved.name.endswith(".tandem.zip")
        with zipfile.ZipFile(saved) as z:
            assert {"project.json", "original.wav"} <= set(z.namelist())
        expect(page.locator("#audiorescue")).to_be_hidden()
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


# FIX.8: the draft's write is aborted while fix8FailDraft is set, as when the device's storage gives up mid-write.
FAIL_DRAFT = """() => { window.fix8FailDraft = true; const put = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (value, key) { const req = put.call(this, value, key);
    if (window.fix8FailDraft && key === 'draft') this.transaction.abort(); return req; }; }"""
DRAFT_UNKEPT = "Download the project first: Update reloads Tandem, and your latest changes are not saved on this device."


def change_tempo(page, bpm):
    page.fill("#bpm", str(bpm))
    page.dispatch_event("#bpm", "change")


def draft_bpm(page):
    return stored_draft(page)["bpm"]


def stored_draft(page):
    return page.evaluate("""async () => { const db = await new Promise((ok, no) => {
      const r = indexedDB.open('tandem'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
      const draft = await new Promise((ok, no) => { const r = db.transaction('kv').objectStore('kv')
        .get('draft'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
      db.close(); return draft; }""")


def update_is_refused(page, message, waiting=True):
    page.evaluate("window.fix6Page = 'before'")
    page.click("#swupdate")
    expect(page.locator("#status")).to_have_text(message)
    page.wait_for_timeout(1000)
    assert page.evaluate("window.fix6Page") == "before"
    if waiting:
        # Refused before the new version was told to take over: it is still waiting.
        assert page.evaluate("navigator.serviceWorker.getRegistration().then(r => !!r.waiting)")


def test_studio_update_waits_for_a_draft_the_device_did_not_keep_to_be_downloaded(browser, app_copy, copy_server,
                                                                                  tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(FAIL_DRAFT)
        change_tempo(page, 137)
        expect(page.locator("#status")).to_contain_text("Could not save the draft on this device")
        expect(page.locator("#audiorescue")).to_be_visible()
        update_is_refused(page, DRAFT_UNKEPT)
        with page.expect_download() as got:
            page.click("#audiorescue")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            assert json.loads(z.read("project.json"))["bpm"] == 137
        expect(page.locator("#audiorescue")).to_be_hidden()
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


def test_studio_update_goes_once_a_later_draft_write_is_kept(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(FAIL_DRAFT)
        change_tempo(page, 137)
        expect(page.locator("#audiorescue")).to_be_visible()
        update_is_refused(page, DRAFT_UNKEPT)
        page.evaluate("window.fix8FailDraft = false")
        change_tempo(page, 141)
        expect(page.locator("#audiorescue")).to_be_hidden()
        assert draft_bpm(page) == 141
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"
        expect(page.locator("#bpm")).to_have_value("141")


def test_a_rescue_download_leaves_out_a_take_recorded_while_it_is_prepared_and_says_so(browser, app_copy, copy_server,
                                                                                         tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate("""() => { FileSystemWritableFileStream.prototype.write = function () {
          return Promise.reject(new DOMException('full', 'QuotaExceededError')); }; }""")
        page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
        expect(page.locator("#status")).to_contain_text("Could not keep the recording on this device")
        expect(page.locator("#audiorescue")).to_be_visible()
        # The next recording read (the rescue's first) waits until fix8Release.
        page.evaluate("""() => { const read = Blob.prototype.arrayBuffer; window.fix8Hold = true;
          Blob.prototype.arrayBuffer = function () { if (!window.fix8Hold) return read.call(this);
            window.fix8Hold = false; window.fix8Held = true;
            return new Promise(go => { window.fix8Release = go; }).then(() => read.call(this)); }; }""")
        with page.expect_download() as got:
            page.click("#audiorescue")
            page.wait_for_function("window.fix8Held === true")
            page.set_input_files("#audiofile", str(tone_wav(tmp_path / "second.wav")))
            expect(page.locator("#takes")).to_contain_text("Take 2")
            page.evaluate("window.fix8Release()")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            assert len(json.loads(z.read("project.json")).get("takes", {}).get("list", [])) < 2
            first = set(z.namelist())
        expect(page.locator("#status")).to_contain_text("changed while the file was prepared")
        expect(page.locator("#audiorescue")).to_be_visible()
        update_is_refused(page,
            "Download the recording that was not kept first: Update reloads Tandem, and it is not saved on this device.")
        with page.expect_download() as got:
            page.click("#audiorescue")
        saved = tmp_path / ("again-" + got.value.suggested_filename)
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            takes = json.loads(z.read("project.json"))["takes"]["list"]
            assert len(takes) == 2
            # Every take's audio is in the second file; the take imported while the first was prepared is not in the first.
            assert {f"take-{t['id']}.wav" for t in takes} <= set(z.namelist())
            assert f"take-{takes[1]['id']}.wav" not in first
        expect(page.locator("#audiorescue")).to_be_hidden()
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


NO_STORAGE = "Object.defineProperty(window, 'indexedDB', {value: undefined, configurable: true})"
THROW_ON_WRITE = """() => { const put = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (value, key) {
    if (key === 'draft') throw new DOMException('The database connection is closing.', 'InvalidStateError');
    return put.call(this, value, key); }; }"""


@pytest.mark.parametrize("failure", ["no storage", "write throws"])
def test_studio_update_waits_for_a_draft_that_never_reached_the_device(browser, app_copy, copy_server, tmp_path,
                                                                       failure):
    with studio_on(browser, copy_server, NO_STORAGE if failure == "no storage" else None) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        if failure == "write throws":
            page.evaluate(THROW_ON_WRITE)
        # Nothing changed yet: nothing to download.
        expect(page.locator("#audiorescue")).to_be_hidden()
        change_tempo(page, 137)
        expect(page.locator("#audiorescue")).to_be_visible()
        update_is_refused(page, DRAFT_UNKEPT)
        with page.expect_download() as got:
            page.click("#audiorescue")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            assert json.loads(z.read("project.json"))["bpm"] == 137
        expect(page.locator("#audiorescue")).to_be_hidden()
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


# FIX.8: the activation message the Update button sends waits until fix8Activate().
HOLD_ACTIVATION = """() => { const post = ServiceWorker.prototype.postMessage;
  ServiceWorker.prototype.postMessage = function (msg) { if (msg !== 'activate') return post.call(this, msg);
    window.fix8ActivationHeld = true; window.fix8Activate = () => post.call(this, msg); }; }"""


def test_an_edit_not_kept_while_the_update_activates_stops_the_reload(browser, app_copy, copy_server, tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(HOLD_ACTIVATION)
        page.evaluate("window.fix6Page = 'before'")
        page.click("#swupdate")
        page.wait_for_function("window.fix8ActivationHeld === true")
        page.evaluate(FAIL_DRAFT)
        change_tempo(page, 137)
        expect(page.locator("#audiorescue")).to_be_visible()
        page.evaluate("window.fix8Activate()")
        expect(page.locator("#status")).to_have_text(DRAFT_UNKEPT)
        page.wait_for_timeout(1000)
        assert page.evaluate("window.fix6Page") == "before"
        expect(page.locator("#bpm")).to_have_value("137")
        update_is_refused(page, DRAFT_UNKEPT, waiting=False)
        with page.expect_download() as got:
            page.click("#audiorescue")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            assert json.loads(z.read("project.json"))["bpm"] == 137
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


# FIX.8: the outcome of every IndexedDB transaction started while fix8HoldWrites is set waits until fix8ReleaseWrites().
HOLD_WRITES = """() => { let release; const held = new Promise(go => { release = go; }); window.fix8ReleaseWrites = release;
  for (const name of ['oncomplete', 'onerror', 'onabort']) {
    const d = Object.getOwnPropertyDescriptor(IDBTransaction.prototype, name);
    Object.defineProperty(IDBTransaction.prototype, name, { configurable: true, get: d.get, set(fn) {
      d.set.call(this, fn && window.fix8HoldWrites ? e => { held.then(() => fn.call(this, e)); } : fn); } });
  } }"""


@pytest.mark.parametrize("older", ["kept", "failed"])
def test_an_older_draft_write_settling_late_does_not_overrule_a_newer_one(browser, app_copy, copy_server, older):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(HOLD_WRITES)
        if older == "failed":
            page.evaluate(FAIL_DRAFT)
        page.evaluate("window.fix8HoldWrites = true")
        change_tempo(page, 120)
        page.evaluate("window.fix8HoldWrites = false")
        if older == "kept":
            page.evaluate(THROW_ON_WRITE)
        else:
            page.evaluate("window.fix8FailDraft = false")
        change_tempo(page, 130)
        # The newer write has settled: thrown (warning up) or kept (no warning).
        if older == "kept":
            expect(page.locator("#audiorescue")).to_be_visible()
        else:
            page.wait_for_function("""async () => { const db = await new Promise(ok => {
              const r = indexedDB.open('tandem'); r.onsuccess = () => ok(r.result); });
              const d = await new Promise(ok => { const r = db.transaction('kv').objectStore('kv').get('draft');
                r.onsuccess = () => ok(r.result); }); db.close(); return d?.bpm === 130; }""")
            page.wait_for_timeout(300)
        page.evaluate("window.fix8ReleaseWrites()")
        page.wait_for_timeout(500)
        if older == "kept":
            expect(page.locator("#audiorescue")).to_be_visible()
            update_is_refused(page, DRAFT_UNKEPT)
        else:
            expect(page.locator("#audiorescue")).to_be_hidden()
            with page.expect_navigation():
                page.click("#swupdate")
            page.wait_for_function(STARTED)
            assert page.evaluate("window.fix6Version") == "deploy 2"


AUDIO_UNKEPT = "Download the recording that was not kept first: Update reloads Tandem, and it is not saved on this device."
FAIL_RECORDINGS = """() => { FileSystemWritableFileStream.prototype.write = function () {
  return Promise.reject(new DOMException('full', 'QuotaExceededError')); }; }"""


def press_update_with_activation_held(page):
    page.evaluate(HOLD_ACTIVATION)
    page.evaluate("window.fix6Page = 'before'")
    page.click("#swupdate")
    page.wait_for_function("window.fix8ActivationHeld === true")


def test_words_still_being_typed_when_the_update_activates_are_kept(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        press_update_with_activation_held(page)
        page.fill("#lyrics", "Twin-kle twin-kle")
        assert page.evaluate("document.activeElement.id") == "lyrics"
        with page.expect_navigation():
            page.evaluate("window.fix8Activate()")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"
        expect(page.locator("#lyrics")).to_have_value("Twin-kle twin-kle")


def test_a_draft_write_still_pending_when_the_update_activates_is_waited_for(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(HOLD_WRITES)
        press_update_with_activation_held(page)
        page.evaluate(FAIL_DRAFT)
        page.evaluate("window.fix8HoldWrites = true")
        change_tempo(page, 137)
        page.evaluate("window.fix8HoldWrites = false")
        expect(page.locator("#audiorescue")).to_be_hidden()
        page.evaluate("window.fix8Activate()")
        page.wait_for_timeout(1000)
        assert page.evaluate("window.fix6Page") == "before"
        page.evaluate("window.fix8ReleaseWrites()")
        expect(page.locator("#status")).to_have_text(DRAFT_UNKEPT)
        expect(page.locator("#audiorescue")).to_be_visible()
        page.wait_for_timeout(500)
        assert page.evaluate("window.fix6Page") == "before"


def test_a_recording_not_kept_while_the_update_activates_stops_the_reload(browser, app_copy, copy_server, tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(FAIL_RECORDINGS)
        press_update_with_activation_held(page)
        page.evaluate(HOLD_RECORDINGS)
        page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
        expect(page.locator("#status")).to_contain_text("Recorded")
        page.evaluate("window.fix8Activate()")
        page.wait_for_timeout(1000)
        assert page.evaluate("window.fix6Page") == "before"
        page.evaluate("window.fix6Release()")
        expect(page.locator("#status")).to_have_text(AUDIO_UNKEPT)
        expect(page.locator("#audiorescue")).to_be_visible()
        page.wait_for_timeout(500)
        assert page.evaluate("window.fix6Page") == "before"
        with page.expect_download():
            page.click("#audiorescue")
        expect(page.locator("#audiorescue")).to_be_hidden()
        with page.expect_navigation():
            page.click("#swupdate")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"


def test_a_project_edit_while_the_rescue_is_prepared_keeps_the_warning(browser, app_copy, copy_server, tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(FAIL_RECORDINGS)
        page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
        expect(page.locator("#status")).to_contain_text("Could not keep the recording on this device")
        change_tempo(page, 137)
        page.evaluate("""() => { const read = Blob.prototype.arrayBuffer; window.fix8Hold = true;
          Blob.prototype.arrayBuffer = function () { if (!window.fix8Hold) return read.call(this);
            window.fix8Hold = false; window.fix8Held = true;
            return new Promise(go => { window.fix8Release = go; }).then(() => read.call(this)); }; }""")
        with page.expect_download() as got:
            page.click("#audiorescue")
            page.wait_for_function("window.fix8Held === true")
            change_tempo(page, 141)
            page.evaluate("window.fix8Release()")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            assert json.loads(z.read("project.json"))["bpm"] == 137
        expect(page.locator("#status")).to_contain_text("changed while the file was prepared")
        expect(page.locator("#audiorescue")).to_be_visible()
        update_is_refused(page, AUDIO_UNKEPT)


def test_words_typed_while_the_update_waits_for_a_write_are_kept(browser, app_copy, copy_server):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(HOLD_WRITES)
        press_update_with_activation_held(page)
        page.evaluate("window.fix8HoldWrites = true")
        change_tempo(page, 137)
        page.evaluate("window.fix8HoldWrites = false")
        page.evaluate("window.fix8Activate()")
        page.wait_for_timeout(1000)
        assert page.evaluate("window.fix6Page") == "before"
        page.fill("#lyrics", "Twin-kle twin-kle")
        with page.expect_navigation():
            page.evaluate("window.fix8ReleaseWrites()")
        page.wait_for_function(STARTED)
        assert page.evaluate("window.fix6Version") == "deploy 2"
        expect(page.locator("#bpm")).to_have_value("137")
        expect(page.locator("#lyrics")).to_have_value("Twin-kle twin-kle")


def test_a_recording_made_while_the_rescue_is_prepared_keeps_the_warning(browser, app_copy, copy_server, tmp_path):
    with studio_on(browser, copy_server) as page:
        deploy(app_copy)
        assert update_settled(page)["waiting"]
        page.evaluate(FAIL_RECORDINGS)
        page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
        expect(page.locator("#status")).to_contain_text("Could not keep the recording on this device")
        page.evaluate("""() => { const read = Blob.prototype.arrayBuffer; window.fix8Hold = true;
          Blob.prototype.arrayBuffer = function () { if (!window.fix8Hold) return read.call(this);
            window.fix8Hold = false; window.fix8Held = true;
            return new Promise(go => { window.fix8Release = go; }).then(() => read.call(this)); }; }""")
        with page.expect_download() as got:
            page.click("#audiorescue")
            page.wait_for_function("window.fix8Held === true")
            project = stored_draft(page)
            page.click("#polish")
            expect(page.locator("#polished")).to_be_enabled(timeout=30000)
            # Only a recording changed: the project is as it was.
            page.wait_for_timeout(500)
            assert stored_draft(page) == project
            page.evaluate("window.fix8Release()")
        saved = tmp_path / got.value.suggested_filename
        got.value.save_as(saved)
        with zipfile.ZipFile(saved) as z:
            assert "polished.wav" not in z.namelist()
        expect(page.locator("#status")).to_contain_text("changed while the file was prepared")
        expect(page.locator("#audiorescue")).to_be_visible()
        update_is_refused(page, AUDIO_UNKEPT)
