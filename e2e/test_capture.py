"""MOB.1: the phone capture page records ideas from a (fake) microphone, keeps them on the device and
opens them in the studio. Runs in a phone-sized, touch context."""
import json
from contextlib import contextmanager

import httpx
import pytest
from playwright.sync_api import expect

from test_studio import IDB_GET, OPFS_FILES, count

PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 3, "has_touch": True}


@contextmanager
def phone_page(browser, browser_name, base_url):
    """A phone-sized page that fails the test on any page error or console error."""
    options = dict(PHONE)
    if browser_name == "chromium":
        options.update(is_mobile=True, permissions=["microphone"])
    context = browser.new_context(base_url=base_url, **options)
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text} @ {msg.location.get('url')}") if msg.type == "error" else None)
    yield page
    context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


@pytest.fixture
def phone(browser, browser_name, server_url):
    with phone_page(browser, browser_name, server_url) as page:
        yield page


@pytest.fixture
def phone_on_own_server(browser, browser_name, own_server):
    """A phone page on a server the test can stop, for real offline checks (MOB.2)."""
    with phone_page(browser, browser_name, own_server.url) as page:
        yield page, own_server


def open_capture(page):
    page.goto("/capture")
    expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")


def record(page, seconds=1.2):
    page.click("#record")
    expect(page.locator("#record")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(seconds * 1000)
    page.click("#record")
    expect(page.locator("#status")).to_contain_text("Kept a 0:0")


def ideas(page):
    return page.evaluate(IDB_GET, "ideas") or []


def test_record_keep_rename_play_and_delete_an_idea(phone):
    page = phone
    open_capture(page)
    expect(page.locator("#ideas")).to_contain_text("No ideas yet")
    # The record button is in view on a phone without scrolling, and the page does not scroll sideways.
    box = page.locator("#record").bounding_box()
    assert box["y"] + box["height"] <= 844 and box["width"] >= 150
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    record(page)
    expect(page.locator(".idea")).to_have_count(1)
    stored = ideas(page)
    assert len(stored) == 1 and stored[0]["duration"] >= 1 and stored[0]["name"] == ""
    assert page.evaluate(OPFS_FILES) == [stored[0]["audio"]["id"]]
    expect(page.locator(".idea .title")).to_contain_text("Idea · ")

    # Kept across a reload.
    page.reload()
    expect(page.locator(".idea")).to_have_count(1)

    page.click(".idea >> text=Rename")
    page.fill(".idea input", "  Chorus hook  ")
    page.keyboard.press("Enter")
    expect(page.locator(".idea .title")).to_have_text("Chorus hook")
    assert ideas(page)[0]["name"] == "Chorus hook"

    page.click(".idea .play")
    expect(page.locator("#status")).to_have_text("Playing Chorus hook.")

    record(page)
    expect(page.locator(".idea")).to_have_count(2)
    # Newest first.
    expect(page.locator(".idea").first.locator(".title")).to_contain_text("Idea · ")

    # Delete needs a second tap; the recording file goes with the idea.
    hook = page.locator(".idea", has_text="Chorus hook")
    hook.locator("text=Delete").click()
    expect(hook.locator("button.danger")).to_have_text("Tap again to delete")
    assert len(ideas(page)) == 2
    hook.locator("button.danger").click()
    expect(page.locator("#status")).to_have_text("Deleted Chorus hook.")
    expect(page.locator(".idea")).to_have_count(1)
    left = ideas(page)[0]["audio"]["id"]
    page.wait_for_function(f"async () => JSON.stringify(await ({OPFS_FILES})()) === '{json.dumps([left])}'")


def test_a_take_ends_and_is_kept_when_the_page_is_hidden(phone):
    page = phone
    open_capture(page)
    page.click("#record")
    expect(page.locator("#record")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(800)
    page.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
                             document.dispatchEvent(new Event('visibilitychange')); }""")
    expect(page.locator("#status")).to_contain_text("Kept a 0:0")
    expect(page.locator("#record")).to_have_attribute("aria-pressed", "false")
    expect(page.locator(".idea")).to_have_count(1)


def test_an_idea_that_cannot_be_kept_is_offered_as_a_download(phone, tmp_path):
    page = phone
    page.add_init_script("""FileSystemWritableFileStream.prototype.write = function () {
      return Promise.reject(new DOMException('full', 'QuotaExceededError'));
    };""")
    open_capture(page)
    page.click("#record")
    page.wait_for_timeout(800)
    page.click("#record")
    expect(page.locator("#status")).to_contain_text("Could not keep the idea on this device: Browser storage is full.")
    assert ideas(page) == []
    with page.expect_download() as info:
        page.click("#rescue")
    target = tmp_path / info.value.suggested_filename
    info.value.save_as(target)
    assert target.name.startswith("tandem-idea.") and target.stat().st_size > 0


def test_opening_an_idea_in_the_studio_keeps_the_previous_draft_as_a_version(phone):
    page = phone
    page.goto("/")
    page.wait_for_function("!document.body.inert")
    page.click("#demo")
    expect(page.locator("#notecount")).to_have_text("8 notes")

    page.click("#capturelink")
    expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
    record(page)
    page.click(".idea >> text=Rename")
    page.fill(".idea input", "Bus stop")
    page.keyboard.press("Enter")
    expect(page.locator(".idea .title")).to_have_text("Bus stop")

    page.click(".idea >> text=Open in studio")
    expect(page.locator("#status")).to_have_text('Opened Bus stop. Transcribe it to turn it into notes. Your previous draft was saved as the version "Before Bus stop".')
    assert page.evaluate("location.search") == ""
    expect(page.locator("#notecount")).to_have_text("0 notes")
    for button in ["#original", "#analyze", "#tune"]:
        expect(page.locator(button)).to_be_enabled()
    idea_audio = ideas(page)[0]["audio"]["id"]
    assert page.evaluate(IDB_GET, "draft-audio")["original"]["id"] == idea_audio

    page.click("#versionlist .version:has-text('Before Bus stop') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Before Bus stop")
    assert count(page, "notecount") == 8

    # The studio's recording clean-up keeps the idea's recording even when no draft or version links it.
    page.click("#clearnotes")
    page.evaluate("""() => new Promise((resolve, reject) => {
      const open = indexedDB.open('tandem');
      open.onsuccess = () => { const tx = open.result.transaction('kv', 'readwrite');
        tx.objectStore('kv').put([], 'versions'); tx.objectStore('kv').put({}, 'draft-audio');
        tx.oncomplete = () => { open.result.close(); resolve(); }; tx.onerror = () => reject(tx.error); };
    })""")
    page.reload()
    page.wait_for_function("!document.body.inert")
    page.wait_for_timeout(500)
    assert idea_audio in page.evaluate(OPFS_FILES)
    page.goto("/capture")
    page.click(".idea .play")
    expect(page.locator("#status")).to_have_text("Playing Bus stop.")


def test_opening_an_idea_into_an_empty_draft_saves_no_version(phone):
    page = phone
    open_capture(page)
    record(page)
    page.click(".idea >> text=Open in studio")
    expect(page.locator("#status")).to_contain_text("Transcribe it to turn it into notes.")
    expect(page.locator("#status")).not_to_contain_text("previous draft")
    expect(page.locator("#versionlist")).to_have_text("No saved versions yet.")


def test_opening_a_missing_idea_is_reported(phone):
    page = phone
    page.goto("/?idea=nope")
    expect(page.locator("#status")).to_have_text("That idea is no longer on this device.")


def test_without_device_storage_capture_says_so_and_does_not_record(phone):
    """Safari's private windows (and Playwright's WebKit) refuse the Origin Private File System."""
    page = phone
    page.add_init_script("StorageManager.prototype.getDirectory = () => Promise.reject(new DOMException('no', 'UnknownError'));")
    page.goto("/capture")
    expect(page.locator("#status")).to_contain_text("Ideas cannot be kept in this browser: no A private window cannot keep them")
    expect(page.locator("#record")).to_be_disabled()


def wait_for_service_worker(page):
    # The worker precaches the app on install; ready means it is active and the cache is filled.
    # Waited for with a timeout: a worker whose install fails never becomes ready.
    page.evaluate("() => { window.__swReady = false; navigator.serviceWorker.ready.then(() => { window.__swReady = true }) }")
    page.wait_for_function("window.__swReady === true")


FETCH_SIZES = "async files => Promise.all(files.map(async f => (await (await fetch(f)).arrayBuffer()).byteLength))"


def assert_server_down(server):
    with pytest.raises(httpx.ConnectError):
        httpx.get(server.url + "/api/health", timeout=2)


def test_capture_opens_records_and_keeps_an_idea_offline(phone_on_own_server):
    # MOB.2: once the app has been opened, capture works with the server gone.
    page, server = phone_on_own_server
    page.goto("/capture?from=homescreen")
    expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
    wait_for_service_worker(page)
    page.reload()
    page.wait_for_function("!!navigator.serviceWorker.controller")
    # A page opened with a query string is cached once, under its address without the query.
    keys = page.evaluate("async () => (await Promise.all((await caches.keys()).map(async n => (await (await caches.open(n)).keys()).map(r => r.url)))).flat()")
    assert not [k for k in keys if "?" in k], keys
    server.stop()
    assert_server_down(server)
    page.reload()
    expect(page.locator("#status")).to_have_text("Ready. Tap Record and sing.")
    record(page)
    expect(page.locator(".idea")).to_have_count(1)
    assert len(ideas(page)) == 1
    # The studio opens offline too, from its cached page and precached modules (never loaded online in
    # this test), with the idea's query string.
    page.click(".idea >> text=Open in studio")
    expect(page.locator("#status")).to_contain_text("Opened Idea · ")


def test_both_manifests_pass_chromium_installability(phone, browser_name):
    if browser_name != "chromium":
        pytest.skip("installability errors come from the Chrome DevTools Protocol")
    page = phone
    cdp = page.context.new_cdp_session(page)
    for path in ("/capture", "/"):
        page.goto(path)
        wait_for_service_worker(page)
        errors = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
        assert errors == [], (path, errors)


PERSIST_STUB = """(() => {
  window.__persistCalls = 0;
  const granted = %s;
  let persisted = false;
  navigator.storage.persisted = async () => persisted;
  navigator.storage.persist = async () => { window.__persistCalls++; persisted = granted; return granted; };
})()"""


@pytest.mark.parametrize("granted", [True, False])
def test_persistent_storage_is_requested_when_the_first_idea_is_kept(phone, granted):
    page = phone
    page.add_init_script(PERSIST_STUB % ("true" if granted else "false"))
    open_capture(page)
    expect(page.locator("#storageinfo")).to_contain_text("may clear saved work")
    assert page.evaluate("window.__persistCalls") == 0
    record(page)
    if granted:
        expect(page.locator("#storageinfo")).to_contain_text("will keep saved work until you clear it")
    else:
        expect(page.locator("#storageinfo")).to_contain_text("may clear saved work")
    assert page.evaluate("window.__persistCalls") == 1
    # Asked once per visit, not on every take.
    record(page)
    assert page.evaluate("window.__persistCalls") == 1


VENDOR_CACHED = """async files => {
  for (let i = 0; i < 50; i++) {
    const c = await caches.open('tandem-vendor-1');
    if ((await Promise.all(files.map(f => c.match(f)))).every(Boolean)) return true;
    await new Promise(r => setTimeout(r, 100));
  }
  return false;
}"""


def test_vendor_files_are_cached_on_first_use_and_served_offline(phone_on_own_server):
    # MOB.2: Basic Pitch's model and the instrument samples are not precached (megabytes), but once
    # fetched they are kept in their own cache, which survives app updates, and load with the server gone.
    page, server = phone_on_own_server
    open_capture(page)
    wait_for_service_worker(page)
    page.reload()  # now the worker controls the page
    page.wait_for_function("!!navigator.serviceWorker.controller")
    files = ["/vendor/basic-pitch-1.0.1/model/model.json", "/vendor/gm-samples-1/bass/24.mp3"]
    sizes = page.evaluate(FETCH_SIZES, files)
    assert all(size > 0 for size in sizes)
    assert page.evaluate(VENDOR_CACHED, files)
    server.stop()
    assert_server_down(server)
    assert page.evaluate(FETCH_SIZES, files) == sizes
