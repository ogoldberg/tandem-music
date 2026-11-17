"""SEC.7: the studio and the capture page are sent with a Content-Security-Policy that blocks a
script injected into the page, an inline event handler and a javascript: URL, while the page's own
inline module script still runs (the rest of the e2e suite runs with the policy on)."""
import pytest

INJECT = """async () => {
  const seen = [];
  document.addEventListener('securitypolicyviolation', e => seen.push(e.violatedDirective + ' ' + e.blockedURI));
  window.__ran = [];
  const s = document.createElement('script');
  s.textContent = 'window.__ran.push("inline")';
  document.body.append(s);
  const m = document.createElement('script');
  m.type = 'module';
  m.textContent = 'window.__ran.push("module")';
  document.body.append(m);
  const d = document.createElement('div');
  d.innerHTML = '<img src="data:," onerror="window.__ran.push(\\'handler\\')">'
              + '<a id="__js" href="javascript:window.__ran.push(\\'url\\')">x</a>';
  document.body.append(d);
  document.getElementById('__js').click();
  await new Promise(r => setTimeout(r, 500));
  return {ran: window.__ran, seen};
}"""


@pytest.mark.parametrize("path,ready", [
    ("/", "document.getElementById('notecount').textContent !== ''"),
    ("/capture", "document.getElementById('record') && !document.getElementById('record').disabled"),
])
def test_an_injected_script_is_blocked_and_the_page_still_runs(page, server_url, path, ready):
    errors, csp = [], []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: (csp if "Content Security Policy" in msg.text else errors).append(msg.text)
            if msg.type == "error" else None)
    response = page.goto(server_url + path)
    assert "script-src 'self'" in response.headers["content-security-policy"]
    page.wait_for_function(ready)  # the page's own inline module script ran
    assert not csp, csp
    result = page.evaluate(INJECT)
    assert result["ran"] == [], result
    # the script element, the module script and the javascript: URL; then the event handler
    assert sum(v.startswith("script-src-elem") for v in result["seen"]) == 3, result
    assert sum(v.startswith("script-src-attr") for v in result["seen"]) == 1, result
    assert len(csp) >= 4, csp
    assert not errors, errors
