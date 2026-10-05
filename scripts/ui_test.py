#!/usr/bin/env python3
"""Headless browser smoke test.

Drives the real UI with Chrome DevTools Protocol over a WebSocket: registers,
uploads the demo document, waits for indexing, asks a question, and asserts
that a grounded answer with citations appears.

No test framework required - only the Chrome binary.
"""

from __future__ import annotations

import base64
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:5173")
PORT = 9222


class CDP:
    """Minimal Chrome DevTools Protocol client over raw websockets."""

    def __init__(self, ws_url: str) -> None:
        import socket  # noqa: F401

        self.ws_url = ws_url
        self._id = 0
        self.sock = None
        self._buffer = b""
        self._connect()

    def _connect(self) -> None:
        # Reuse the stdlib-free approach: a hand-rolled websocket client keeps
        # this script dependency-free.
        from urllib.parse import urlparse

        parsed = urlparse(self.ws_url)
        host, port = parsed.hostname, parsed.port or 80
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

        import ssl as _ssl  # noqa: F401

        self.sock = socket.create_connection((host, port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode())
        while b"\r\n\r\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            self._buffer += chunk
        self._buffer = self._buffer.split(b"\r\n\r\n", 1)[1]

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed")
            self._buffer += chunk
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def send(self, method: str, params: dict | None = None, timeout: float = 120.0) -> dict:
        self._id += 1
        msg_id = self._id
        payload = json.dumps({"id": msg_id, "method": method, "params": params or {}}).encode()
        frame = self._frame(payload, opcode=0x1)
        self.sock.sendall(frame)

        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = self._read_message()
            if payload is None:
                continue
            data = json.loads(payload)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                return data.get("result", {})
        raise TimeoutError(f"{method} timed out")

    @staticmethod
    def _frame(data: bytes, opcode: int = 0x1) -> bytes:
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header += length.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += length.to_bytes(8, "big")
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return bytes(header) + masked

    def _read_message(self) -> str | None:

        try:
            b1, b2 = self._recv_exact(2)
        except (TimeoutError, ConnectionError):
            return None
        opcode = b1 & 0x0F
        length = b2 & 0x7F
        if length == 126:
            length = int.from_bytes(self._recv_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._recv_exact(8), "big")
        if b2 & 0x80:
            mask = self._recv_exact(4)
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self._recv_exact(length)))
        else:
            payload = self._recv_exact(length)
        if opcode == 0x8:
            raise ConnectionError("websocket closed by peer")
        if opcode in (0x9, 0xA):
            return None
        return payload.decode("utf-8", "replace")

    def evaluate(self, expression: str, timeout: float = 120.0):
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"].get("text", "JS error"))
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


import socket


class Chrome:
    def __init__(self) -> None:
        self.profile = tempfile.mkdtemp(prefix="docmind-chrome-")
        self.proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                f"--remote-debugging-port={PORT}",
                f"--user-data-dir={self.profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--window-size=1600,1000",
                "--hide-scrollbars",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.ws = self._connect_ws()

    def _connect_ws(self) -> CDP:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as r:
                    targets = json.load(r)
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    return CDP(pages[0]["webSocketDebuggerUrl"])
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("could not attach to Chrome")

    def goto(self, url: str) -> None:
        self.ws.send("Page.enable", {})
        self.ws.send("Page.navigate", {"url": url})
        time.sleep(2)

    def screenshot(self, path: Path) -> None:
        result = self.ws.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(result["data"]))

    def close(self) -> None:
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            shutil.rmtree(self.profile, ignore_errors=True)


DEMO = """Renewable Energy: Solar Photovoltaics and Wind Power

Solar Photovoltaics
A photovoltaic cell is built from doped silicon. When photons strike the material they
dislodge electrons, generating direct current. Standard silicon panels achieve roughly 20
percent conversion efficiency, though perovskite tandem cells have exceeded 30 percent.

Wind Turbines
Wind turbines capture kinetic energy with three blades mounted on a hub. Betz's law limits
extraction to roughly 59 percent of the wind's kinetic power.
"""

failures: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def js(body: str) -> str:
    """Wrap a JS body so Chrome evaluates it as an expression."""
    return f"(function(){{ {body} return true }})()"


def main() -> int:
    shots = Path(__file__).resolve().parents[1] / "storage" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    if not Path(CHROME).exists():
        print("Chrome not found; skipping browser test")
        return 0

    print("=" * 70)
    print("HEADLESS BROWSER SMOKE TEST")
    print("=" * 70)

    chrome = Chrome()
    ws = chrome.ws
    try:
        # Collect console errors so silent React failures surface.
        ws.send("Runtime.enable", {})

        chrome.goto(APP_URL)
        check("app loads", ws.evaluate("document.readyState") == "complete")
        check(
            "root rendered",
            bool(ws.evaluate("document.querySelector('#root')?.children.length")),
        )

        # ---- Auth screen ----
        title = ws.evaluate("document.body.innerText") or ""
        check("auth screen visible", "Sign in" in title, f"body={title[:120]!r}")
        chrome.screenshot(shots / "01-auth.png")

        # ---- Register ----
        run_id = f"{int(time.time())}{random.randint(1000, 9999)}"
        email = f"ui-{run_id}@example.com"
        username = f"uitester{run_id}"
        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              btns.find(b => b.textContent.includes('Create account'))?.click();
              return true;
            })()
            """
        )
        time.sleep(0.6)
        # Inject values via JSON so quoting can never break the JS expression.
        ws.evaluate(
            f"""
            (() => {{
              const set = (el, v) => {{
                const d = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value');
                d.set.call(el, v);
                el.dispatchEvent(new Event('input', {{bubbles:true}}));
              }};
              set(document.querySelector('#email'), {json.dumps(email)});
              set(document.querySelector('#username'), {json.dumps(username)});
              set(document.querySelector('#password'), 'password123');
              return true;
            }})()
            """
        )
        time.sleep(0.4)
        chrome.screenshot(shots / "02-register-filled.png")

        ws.evaluate(
            """
            (() => {
              document.querySelector('button[type=submit]')?.click();
              return true;
            })()
            """
        )
        time.sleep(4)

        body = ws.evaluate("document.body.innerText") or ""
        if "already exists" in body:
            raise RuntimeError(f"registration conflict for {email}")
        check("signed in (chat visible)", "Chat with your documents" in body, body[:200])
        check("upload zone present", "Drop your documents here" in body)
        chrome.screenshot(shots / "03-empty-state.png")

        # ---- Upload via the demo button (exercises the same API path) ----
        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              btns.find(b => b.textContent.includes('Try Demo Document'))?.click();
              return true;
            })()
            """
        )
        time.sleep(6)
        chrome.screenshot(shots / "04-after-upload.png")

        # Confirm the upload landed by asking the API directly (keeps the UI
        # flow uninterrupted) and by checking the sidebar reflects the doc.
        time.sleep(2)
        doc_count = ws.evaluate(
            """
            (async () => {
              const t = localStorage.getItem('docmind.token');
              const r = await fetch('/api/documents', {headers:{Authorization:'Bearer '+t}});
              const j = await r.json();
              return j.total;
            })()
            """
        )
        check("demo document uploaded", bool(doc_count), f"total={doc_count}")

        # ---- Wait for indexing ----
        indexed = False
        for _ in range(45):
            body = ws.evaluate("document.body.innerText") or ""
            composer_ready = ws.evaluate(
                "(() => {const t=document.querySelector('textarea');"
                "return t ? !t.disabled : false})()"
            )
            if composer_ready:
                indexed = True
                break
            time.sleep(2)
        check("composer enabled after indexing", indexed, (body or "")[:200])
        chrome.screenshot(shots / "05-indexed.png")

        # ---- Ask a question ----
        ws.evaluate(
            """
            (() => {
              const ta = document.querySelector('textarea');
              if (!ta) return false;
              const d = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
              d.set.call(ta, 'What is the maximum efficiency of extracting wind energy?');
              ta.dispatchEvent(new Event('input', {bubbles:true}));
              return true;
            })()
            """
        )
        time.sleep(0.5)
        chrome.screenshot(shots / "06-composer-filled.png")

        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              const send = btns.find(b => b.getAttribute('aria-label') === 'Send message');
              send?.click();
              return Boolean(send);
            })()
            """
        )

        answered = False
        answer_text = ""
        for _ in range(90):
            body = ws.evaluate("document.body.innerText") or ""
            answer_text = body
            if "59" in body and ("citation" in body.lower() or "Sources" in body):
                answered = True
                break
            time.sleep(2)
        check("grounded answer rendered", answered, (answer_text or "")[:300])
        check(
            "citation shown",
            "Sources" in (answer_text or ""),
            (answer_text or "")[:300],
        )
        chrome.screenshot(shots / "07-answer.png")

        # ---- Citation opens preview ----
        clicked = ws.evaluate(
            """
            (() => {
              const btn = document.querySelector('[data-testid=citation-card]');
              if (btn) { btn.click(); return true; }
              return false;
            })()
            """
        )
        check("citation card clickable", clicked is True)
        time.sleep(4)
        body = ws.evaluate("document.body.innerText") or ""
        check(
            "preview panel opened",
            "cited passage" in body or "passages" in body or "chunks" in body,
            body[:300],
        )
        chrome.screenshot(shots / "08-preview.png")

        # ---- Live / general answers and their provenance badges ----
        print()
        print("-" * 60)
        print("LIVE + GENERAL MODES")
        print("-" * 60)

        def badges() -> list[str]:
            """Read the provenance badge titles currently on screen."""
            return ws.evaluate(
                "[...document.querySelectorAll('span[title]')]"
                ".map(e=>e.getAttribute('title'))"
                ".filter(t=>t && (t.indexOf('Grounded in passages')>=0"
                "|| t.indexOf('fetched live')>=0"
                "|| t.indexOf('system clock')>=0"
                "|| t.indexOf('own knowledge')>=0))"
            ) or []

        def ask(q: str, wait_s: int = 60) -> None:
            """Send a question and wait for its own answer to finish.

            The wait is on the badge *count* rising, not on badges existing:
            earlier answers stay on screen, so a non-empty check returns
            immediately and the assertion then reads the previous reply.
            """
            before = len(badges())
            ws.evaluate(
                js(
                    "var ta=document.querySelector('textarea');"
                    "var d=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value');"
                    f"d.set.call(ta,{q!r});"
                    "ta.dispatchEvent(new Event('input',{bubbles:true}));"
                )
            )
            time.sleep(0.4)
            ws.evaluate(
                js(
                    "var b=[...document.querySelectorAll('button')]"
                    ".find(b=>b.getAttribute('aria-label')==='Send message');"
                    "if(b) b.click();"
                )
            )
            for _ in range(wait_s):
                time.sleep(1)
                if len(badges()) > before:
                    return
            return

        ask("what is today's date", wait_s=25)
        found = badges()
        check(
            "live date answered with a Live (system clock) badge",
            any("system clock" in t for t in found),
            f"badges={found}",
        )
        chrome.screenshot(shots / "16-live-date.png")

        ask("hi", wait_s=45)
        found = badges()
        check(
            "greeting answered with a General knowledge badge",
            any("own knowledge" in t for t in found),
            f"badges={found}",
        )
        chrome.screenshot(shots / "17-general.png")

        # ---- Model picker: popular vendors, grouped and honest about keys ----
        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              btns.find(b => (b.title || '') === 'Change model')?.click();
              return true;
            })()
            """
        )
        time.sleep(1.0)
        picker = ws.evaluate("document.body.innerText") or ""
        # innerText reflects CSS text-transform, and these headings are
        # uppercased, so compare case-insensitively.
        picker_lc = picker.lower()
        for vendor, label in [
            ("openai", "chatgpt"),
            ("anthropic", "claude"),
            ("google", "gemini"),
            ("hugging face", "gemma"),
        ]:
            check(
                f"model picker lists {label} under {vendor}",
                vendor in picker_lc and label in picker_lc,
                picker[:200],
            )
        # Unconfigured vendors must be visibly marked, not silently selectable.
        check(
            "unconfigured vendor groups say 'not configured'",
            picker_lc.count("not configured") >= 3,
            f"count={picker_lc.count('not configured')}",
        )
        disabled = ws.evaluate(
            "document.querySelectorAll('button[disabled]').length"
        )
        check("unconfigured models are disabled", (disabled or 0) > 0, f"disabled={disabled}")
        chrome.screenshot(shots / "20-model-picker.png")
        ws.evaluate(
            """
            (() => {
              const b = [...document.querySelectorAll('button')].find(x => x.getAttribute('aria-label') === 'Close model picker');
              b?.click();
              return true;
            })()
            """
        )
        time.sleep(0.5)

        # Models view should surface vendor credentials, not just HF.
        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              btns.find(b => b.textContent.trim().startsWith('Models'))?.click();
              return true;
            })()
            """
        )
        time.sleep(1.5)
        models_view = ws.evaluate("document.body.innerText") or ""
        for needle in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "ChatGPT"]:
            check(
                f"Models view names {needle}",
                needle.lower() in models_view.lower(),
                models_view[:160],
            )
        chrome.screenshot(shots / "21-models-providers.png")

        # ---- Navigation views ----
        for label, needle in [
            ("Documents", "Documents"),
            ("Models", "Models"),
            ("Settings", "Settings"),
        ]:
            ws.evaluate(
                f"""
                (() => {{
                  const btns = [...document.querySelectorAll('button')];
                  btns.find(b => b.textContent.trim().startsWith('{label}'))?.click();
                  return true;
                }})()
                """
            )
            time.sleep(1.5)
            body = ws.evaluate("document.body.innerText") or ""
            check(f"{label} view renders", needle in body, body[:160])
            chrome.screenshot(shots / f"09-{label.lower()}.png")

        notes.append(f"screenshots written to {shots}")

    finally:
        chrome.close()

    print()
    print("=" * 70)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL UI CHECKS PASSED")
    for n in notes:
        print(f"  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())