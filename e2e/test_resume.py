"""RESUME.1: Tandem opening on a song kept from last time says so, with Keep going and Start a new song, and the Sing
step says which song a take goes into and whether the song plays while it is recorded."""

from playwright.sync_api import expect

from test_guided import guided_page
from test_studio import wait_until

READY = "document.getElementById('notecount').textContent !== '' && !document.body.inert"

KV_GET = """async key => await new Promise((resolve, reject) => {
  const open = indexedDB.open('tandem');
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const db = open.result, get = db.transaction('kv').objectStore('kv').get(key);
    get.onsuccess = () => { db.close(); resolve(get.result ?? null); };
    get.onerror = () => reject(get.error);
  };
})"""


def kv(page, key):
    return page.evaluate(KV_GET, key)


def reopen(page):
    page.reload()
    page.wait_for_function(READY)


def faster(page):
    """Four beats a minute faster, as one edit (the studio's speed field, hidden in the guided view)."""
    return page.evaluate("() => { const b = document.getElementById('bpm'); b.value = String(Number(b.value) + 4); b.dispatchEvent(new Event('change')); return Number(b.value); }")


def with_example(page):
    page.click("#gdemo")
    page.wait_for_function("document.getElementById('notecount').textContent !== '0 notes'")
    wait_until(page, f"async () => ((await ({KV_GET})('draft'))?.notes?.length ?? 0) > 0", "the example is the stored draft")


def name_song(page, name):
    page.click('#steps [data-step="share"]')
    page.fill("#gsongname", name)
    page.locator("#gsongname").blur()
    page.click('#steps [data-step="sing"]')


def test_a_fresh_start_says_nothing_and_a_song_in_progress_says_where_a_take_goes(browser, server_url):
    with guided_page(browser, server_url) as page:
        expect(page.locator("#gresume")).to_be_hidden()
        expect(page.locator("#ginto")).to_be_hidden()
        reopen(page)
        expect(page.locator("#gresume")).to_be_hidden()
        with_example(page)
        # Loading a song in this visit is not a welcome back; the line over Record names the song.
        expect(page.locator("#gresume")).to_be_hidden()
        expect(page.locator("#ginto")).to_have_text("Recording into “Untitled song”: the song plays while you sing.")
        name_song(page, "Rain song")
        expect(page.locator("#ginto")).to_contain_text("“Rain song”")
        page.click("#grecopts summary")
        page.uncheck("#recsong")
        expect(page.locator("#ginto")).to_have_text("Recording into “Rain song”: the song stays quiet while you sing.")


def test_opening_on_a_song_in_progress_welcomes_it_back(browser, server_url):
    with guided_page(browser, server_url) as page:
        with_example(page)
        name_song(page, "Rain song")
        page.click('#steps [data-step="share"]')
        wait_until(page, f"async () => (await ({KV_GET})('song-name')) === 'Rain song'", "the name is kept")
        changed = kv(page, "draft-changed")
        assert isinstance(changed, (int, float)) and changed > 0
        reopen(page)
        # The card is on the Sing step, whichever step was open before.
        expect(page.locator('#steps [data-step="sing"]')).to_have_attribute("aria-current", "step")
        expect(page.locator("#gresume")).to_be_visible()
        expect(page.locator("#gresumetitle")).to_have_text("Rain song")
        # The example: its tune and its drums.
        expect(page.locator("#notecount")).to_have_text("8 notes")
        expect(page.locator("#gresumewhat")).to_have_text("8 notes and a beat")
        expect(page.locator("#gresumewhen")).to_have_text("Last changed just now")
        expect(page.locator("#ginto")).to_be_hidden()

        # Opening the same song again is not a change: the time it last changed stays.
        assert kv(page, "draft-changed") == changed

        page.click("#gresumekeep")
        expect(page.locator('#steps [data-step="song"]')).to_have_attribute("aria-current", "step")
        # Back on Sing, the card is put away and the line over Record says where a take goes.
        page.click('#steps [data-step="sing"]')
        expect(page.locator("#gresume")).to_be_hidden()
        expect(page.locator("#ginto")).to_have_text("Recording into \u201cRain song\u201d: the song plays while you sing.")


def test_an_edit_puts_the_card_away_and_changes_the_time(browser, server_url):
    with guided_page(browser, server_url) as page:
        with_example(page)
        before = kv(page, "draft-changed")
        reopen(page)
        expect(page.locator("#gresume")).to_be_visible()
        faster(page)
        expect(page.locator("#gresume")).to_be_hidden()
        expect(page.locator("#ginto")).to_be_visible()
        wait_until(page, f"async () => (await ({KV_GET})('draft-changed')) > {before}", "the change is timed")


def test_start_a_new_song_keeps_the_old_one_as_a_version(browser, server_url):
    with guided_page(browser, server_url) as page:
        with_example(page)
        # Changed, so it is more than the example (an unchanged example is not kept as a version).
        bpm = faster(page)
        wait_until(page, f"async () => (await ({KV_GET})('draft'))?.bpm === {bpm}", "the change is the stored draft")
        reopen(page)
        expect(page.locator("#gresume")).to_be_visible()
        page.click("#gresumenew")
        expect(page.locator("#gresume")).to_be_hidden()
        expect(page.locator("#notecount")).to_have_text("0 notes")
        expect(page.locator("#ginto")).to_be_hidden()
        page.click('#steps [data-step="share"]')
        expect(page.locator("#versionlist .version span")).to_have_count(1)
        expect(page.locator("#versionlist .version span")).to_contain_text("Before a new song")
        wait_until(page, f"async () => ((await ({KV_GET})('draft'))?.notes?.length ?? 1) === 0", "the empty song is the draft")
        reopen(page)
        expect(page.locator("#gresume")).to_be_hidden()


# A second of a quiet tone as a 16-bit mono WAV, built in the page, kept as a recording and listed as an idea, the way
# the capture page keeps one.
ADD_IDEA = """async () => {
  const {openKV}=await import('./storage.js');
  const {createIdeaStore}=await import('./ideas.js');
  const {openRecordings}=await import('./recordings.js');
  const rate=16000, n=rate, buf=new ArrayBuffer(44+n*2), v=new DataView(buf);
  const text=(o,s)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i))};
  text(0,'RIFF');v.setUint32(4,36+n*2,true);text(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);
  v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);
  text(36,'data');v.setUint32(40,n*2,true);
  for(let i=0;i<n;i++)v.setInt16(44+i*2,Math.round(3000*Math.sin(2*Math.PI*220*i/rate)),true);
  const store=await openRecordings(navigator.storage), kv=await openKV(indexedDB);
  const link=await store.hold(async()=>{const l=await store.put(new Blob([buf],{type:'audio/wav'}));return l});
  return (await createIdeaStore(kv).add({duration:1,audio:link})).id;
}"""


def test_opening_an_idea_from_the_phone_is_not_a_welcome_back(browser, server_url):
    with guided_page(browser, server_url) as page:
        with_example(page)
        bpm = faster(page)
        wait_until(page, f"async () => (await ({KV_GET})('draft'))?.bpm === {bpm}", "the change is the stored draft")
        idea = page.evaluate(ADD_IDEA)
        page.goto(f"/?idea={idea}")
        page.wait_for_function(READY)
        expect(page.locator("#status")).to_contain_text("Transcribe it to turn it into notes.")
        # The idea is the song now (it has a recording), yet it was just opened, not kept from last time.
        page.click('#steps [data-step="sing"]')
        expect(page.locator("#gresume")).to_be_hidden()
        expect(page.locator("#ginto")).to_be_visible()
        expect(page.locator("#ginto")).to_contain_text("Recording into")
