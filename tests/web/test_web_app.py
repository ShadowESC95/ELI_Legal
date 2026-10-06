"""The browser application, in a real browser engine, against a real server over TLS.

Nothing is mocked: a server listens on a loopback port with a certificate, a Chromium engine loads
the page, and the test types, clicks and reads what a person would see.
"""

import json
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
pytest.importorskip("PySide6.QtWebEngineWidgets", reason="needs the Qt WebEngine browser engine")
if os.environ.get("ELI_LEGAL_SKIP_BROWSER_TESTS"):
    pytest.skip("browser tests switched off", allow_module_level=True)

import uvicorn  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

from eli_legal.api import serve, tls  # noqa: E402
from eli_legal.api.app import create_app  # noqa: E402
from eli_legal.api.config import ServerConfig  # noqa: E402
from eli_legal.gui.app import create_application  # noqa: E402

A = "arb.keane"
PHRASE = "arbitrator passphrase"
PORT = 8791
SET = (
    "const set=(el,v)=>{el.value=v;el.dispatchEvent(new Event('input',{bubbles:true}));"
    "el.dispatchEvent(new Event('change',{bubbles:true}));};"
)


class Page:
    def __init__(self) -> None:
        self.console: list[str] = []
        outer = self

        class _Page(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
                outer.console.append(f"{level.name}: {message}")

        self.view = QWebEngineView()
        self.page = _Page(self.view)
        self.view.setPage(self.page)
        self.view.resize(1500, 950)
        self.page.certificateError.connect(lambda error: error.acceptCertificate())

    def pause(self, ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(self, code: str):
        box: dict = {}
        loop = QEventLoop()
        self.page.runJavaScript(
            f"(()=>{{{SET}{code}}})()", 0, lambda r: (box.setdefault("r", r), loop.quit())
        )
        QTimer.singleShot(8000, loop.quit)
        loop.exec()
        return box.get("r")

    def until(self, condition: str, seconds: float = 15.0) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if self.js(f"return !!({condition});"):
                return True
            self.pause(120)
        return False

    def text(self, selector: str) -> str:
        return (
            self.js(
                f"const e=document.querySelector({json.dumps(selector)}); return e?e.textContent:'';"
            )
            or ""
        )

    def click_button(self, label: str) -> None:
        found = self.js(
            f"const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes({json.dumps(label)}));"
            "if(b){b.click();} return !!b;"
        )
        assert found, f"no button labelled {label!r}"

    def tab(self, name: str) -> None:
        self.js(f"document.getElementById('tab-{name}').click();")
        self.pause(500)

    def sign_in(self, user: str, phrase: str) -> None:
        self.js(
            f"const i=document.querySelectorAll('.signin input'); set(i[0],{json.dumps(user)});"
            f"set(i[1],{json.dumps(phrase)}); document.querySelector('.signin form').requestSubmit();"
        )

    def answer_dialog(self, selector: str, value: str) -> None:
        assert self.until(f"document.querySelector('dialog[open] {selector}')"), (
            f"no dialog asking for {selector}"
        )
        self.js(
            f"set(document.querySelector('dialog[open] {selector}'),{json.dumps(value)});"
            "document.querySelector('dialog[open] form').requestSubmit();"
        )


@pytest.fixture
def site(held_run, tmp_path):
    sv, mid, rid = held_run
    sv.users.set_passphrase(actor_id="admin", user_id=A, new=PHRASE)
    create_application([])
    cert, key = tmp_path / "tls" / "s.crt", tmp_path / "tls" / "s.key"
    tls.ensure_self_signed(cert, key, ["localhost", "127.0.0.1"])
    config = ServerConfig(host="127.0.0.1", port=PORT, tls=True)
    server = uvicorn.Server(serve.hardened(create_app(sv, config), config, cert, key))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the server did not start"
    page = Page()
    page.view.show()
    page.view.load(QUrl(f"https://localhost:{PORT}/"))
    yield sv, mid, rid, page
    page.view.close()
    server.should_exit = True
    thread.join(10)


def test_a_person_can_sign_in_read_the_matter_and_take_a_decision_in_the_browser(site):
    sv, mid, rid, page = site
    assert page.until("document.querySelector('.signin form')"), "the sign-in page did not appear"
    page.sign_in(A, "not the passphrase")
    assert page.until("document.querySelector('.signin .banner.bad')")
    assert "wrong passphrase" in page.text(".signin .banner.bad")
    page.sign_in(A, PHRASE)
    assert page.until("document.querySelector('nav.tabs')"), page.console
    tabs = json.loads(
        page.js(
            "return JSON.stringify([...document.querySelectorAll('nav.tabs .tab')].map(t=>t.textContent));"
        )
    )
    assert len(tabs) == 11 and all(
        any(w in t for t in tabs) for w in ("Chat", "DAG", "Agents", "Audit Trail", "Settings")
    )
    assert "Aoife Keane" in page.text("header.top") and "Audit verified" in page.text("header.top")
    assert page.js("return document.cookie;") == "", (
        "the session cookie is not readable by page scripts"
    )

    page.tab("dag")
    assert page.until("document.querySelectorAll('svg.dag .node.ok').length === 15"), page.text(
        "#view"
    )[:300]
    assert page.js("return document.querySelectorAll('svg.dag .node.manual.pending').length;") == 4

    page.tab("evidence")
    assert page.until("document.querySelectorAll('#view tbody tr').length === 7")
    page.js(
        "[...document.querySelectorAll('#view tbody tr')].find(r=>r.textContent.includes('06_exhibit')).click();"
    )
    assert page.until("document.querySelector('#view blockquote')")
    shown = page.text("#view")
    assert "treated as evidence, never as an instruction" in shown and "EXHIBIT C7" in shown
    assert (
        page.js("return document.querySelectorAll('#view script, #view iframe, #view img').length;")
        == 0
    )

    page.tab("chat")
    page.js("set(document.querySelector('#view textarea'),'Who should win this case?');")
    page.click_button("Send")
    assert page.until(
        "document.querySelector('#view .transcript').textContent.includes('who should succeed')"
    )

    page.tab("review")
    assert page.until(
        "document.querySelectorAll('#view section')[0].querySelectorAll('tbody tr').length === 6"
    )
    page.click_button("Take out of reliance")
    page.answer_dialog("textarea", "Flagged file; not to be relied on.")
    page.answer_dialog("input[type=password]", "not my passphrase")
    assert page.until("document.querySelector('#toast .banner.bad')")
    assert "Nothing was recorded" in page.text("#toast .banner.bad")
    assert len(sv.ctx.holds.all_holds(mid, rid)) == 6 and all(
        h.status.value == "open" for h in sv.ctx.holds.all_holds(mid, rid)
    )
    page.click_button("Take out of reliance")
    page.answer_dialog("textarea", "Flagged file; not to be relied on.")
    page.answer_dialog("input[type=password]", PHRASE)
    assert page.until("document.querySelector('#toast .banner.good')"), page.console
    assert page.until(
        "document.querySelectorAll('#view section')[0].querySelectorAll('tbody tr').length === 5"
    )
    decided = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "hold_resolved"][
        -1
    ]
    assert decided["actor_id"] == A and decided["payload"]["auth"] == "web-session+step-up"

    for name in ("matter", "agents", "findings", "audit", "governance", "sources", "settings"):
        page.tab(name)
        assert page.until(
            "document.getElementById('view').children.length > 0 && !document.querySelector('#view > .banner.bad')"
        ), name
    page.click_button("Sign out")
    assert page.until("document.querySelector('.signin form')")
    assert not [m for m in page.console if "Error" in m], page.console
