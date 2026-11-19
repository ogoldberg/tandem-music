"""FIX.6: an update never leaves the studio with a page from one version and modules from another. The page and
the modules it imports are one set, installed whole by the new service worker and switched to on Update; until
then, and whenever an update cannot be fetched whole, the studio opens as it was, online and offline.

The server runs from a copy of the app, so the test deploys a new version by changing the copy's files."""
import shutil
from contextlib import contextmanager

import pytest
from playwright.sync_api import expect

from conftest import ALL_CONTROLS, ROOT, Server
from test_capture import assert_server_down, wait_for_service_worker

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
def studio_on(browser, server):
    """The studio, controlled by its service worker; fails the test on any page error or console error."""
    context = browser.new_context(base_url=server.url)
    context.add_init_script(ALL_CONTROLS)
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
