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
        self.profile = tempfile.mkdtemp(prefix="origin-chrome-")
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

        # Credit line: present, readable, and the heart is actually red.
        credit = ws.evaluate(
            """
            (() => {
              const el = document.querySelector('[data-testid=made-with-love]');
              if (!el) return null;
              const path = el.querySelector('svg path');
              return {
                text: el.innerText,
                label: el.querySelector('svg')?.getAttribute('aria-label'),
                fill: path ? getComputedStyle(path).fill : null,
              };
            })()
            """
        )
        check("auth screen shows the credit line", credit is not None)
        if credit:
            check("credit says 'Made with' and 'by Parth'",
                  "Made with" in credit["text"] and "by Parth" in credit["text"],
                  repr(credit["text"]))
            check("heart is labelled for screen readers", credit["label"] == "love")
            # rgb(239, 68, 68) is tailwind red-500.
            check("heart is red", credit["fill"] == "rgb(239, 68, 68)", str(credit["fill"]))
        chrome.screenshot(shots / "01-auth.png")

        check(
            "auth screen shows the new name",
            "Origin" in title,
            f"body={title[:160]!r}",
        )

        # ---- Logo ----
        def logo_gradient() -> str:
            return ws.evaluate(
                """
                (() => {
                  const el = document.querySelector('[data-testid=origin-logo]');
                  return el ? getComputedStyle(el).backgroundImage : '';
                })()
                """
            ) or ""

        dark_gradient = logo_gradient()
        check("logo renders on the auth screen", bool(dark_gradient), dark_gradient)
        check(
            "logo is a gradient tile, not a flat colour",
            "gradient" in dark_gradient,
            dark_gradient,
        )
        # The mark is a ring plus a filled centre, not the old four-point star.
        mark = ws.evaluate(
            """
            (() => {
              const svg = document.querySelector('[data-testid=origin-logo] svg');
              if (!svg) return null;
              return {
                circles: svg.querySelectorAll('circle').length,
                paths: svg.querySelectorAll('path').length,
              };
            })()
            """
        )
        check(
            "logo mark is built from circles (an O)",
            bool(mark) and mark["circles"] >= 2,
            str(mark),
        )
        check(
            "logo mark has the halo arcs, not a star",
            bool(mark) and mark["paths"] == 2,
            str(mark),
        )

        # ---- Ambient backdrop ----
        #
        # Headless Chrome reports prefers-reduced-motion: reduce by default, so
        # motion has to be asserted with the preference explicitly overridden.
        # Otherwise the global reduced-motion rule flattens every animation and a
        # static background passes a motion test.
        backdrop = ws.evaluate(
            """
            (() => {
              const root = document.querySelector('[data-testid=ambient-backdrop]');
              if (!root) return null;
              const layers = [...root.children];
              return {
                layers: layers.length,
                pointerEvents: getComputedStyle(root).pointerEvents,
                names: layers.map(l => getComputedStyle(l).animationName),
                durations: layers.map(l => getComputedStyle(l).animationDuration),
              };
            })()
            """
        )
        check("ambient backdrop renders", backdrop is not None, str(backdrop))
        if backdrop:
            check("backdrop has layered lights", backdrop["layers"] >= 4, str(backdrop))
            check(
                "backdrop never intercepts clicks",
                backdrop["pointerEvents"] == "none",
                str(backdrop["pointerEvents"]),
            )
            check(
                "backdrop layers declare animations",
                backdrop["names"].count("none") <= 1,
                str(backdrop["names"]),
            )

        # Reduced motion must flatten it.
        reduced = ws.evaluate(
            """
            (() => {
              const el = document.querySelector('[data-testid=ambient-backdrop] > div');
              const cs = getComputedStyle(el);
              return { duration: cs.animationDuration, iterations: cs.animationIterationCount };
            })()
            """
            if ws.evaluate(
                "matchMedia('(prefers-reduced-motion: reduce)').matches"
            )
            else None
        )
        check(
            "headless Chrome emulates reduced motion (test prerequisite)",
            reduced is not None,
            "motion assertions below need reduce overridden, not relied upon",
        )

        # Now allow motion and prove the layers actually move.
        ws.send(
            "Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]},
        )
        ws.send("Page.reload", {"ignoreCache": True})
        time.sleep(3)

        def drift_state():
            return ws.evaluate(
                """
                (() => {
                  const els = [...document.querySelectorAll('[data-testid=ambient-backdrop] > div')];
                  return els.map(el => {
                    const anims = el.getAnimations();
                    return {
                      t: anims.length ? Math.round(anims[0].currentTime || 0) : null,
                      transform: getComputedStyle(el).transform,
                    };
                  });
                })()
                """
            ) or []

        before = drift_state()
        check(
            "animations are live when motion is allowed",
            bool(before) and before[0]["t"] is not None,
            str(before[:1]),
        )
        time.sleep(2)
        after = drift_state()
        check(
            "the light actually drifts over time",
            bool(before) and bool(after) and before[0]["t"] != after[0]["t"],
            f"{before[:1]} -> {after[:1]}",
        )
        check(
            "drift is a transform animation (compositor-only)",
            bool(after) and "matrix" in after[0]["transform"],
            str(after[:1]),
        )
        chrome.screenshot(shots / "29-ambient-dark.png")

        # Restore defaults for the rest of the run.
        ws.send("Emulation.setEmulatedMedia", {"features": []})
        ws.send("Page.reload", {"ignoreCache": True})
        time.sleep(2.5)

        # Theme-aware: the same tile must not look identical in both themes.
        ws.evaluate("localStorage.setItem('origin.theme','light'); true")
        ws.send("Page.reload", {"ignoreCache": True})
        time.sleep(2.5)
        light_gradient = logo_gradient()
        check("logo renders in light mode too", bool(light_gradient))
        check(
            "logo adapts to the theme",
            light_gradient != dark_gradient,
            f"light={light_gradient} dark={dark_gradient}",
        )
        chrome.screenshot(shots / "27-logo-light.png")

        # Restore the dark default for the rest of the run.
        ws.evaluate("localStorage.setItem('origin.theme','dark'); true")
        ws.send("Page.reload", {"ignoreCache": True})
        time.sleep(2.5)
        check("old brand is gone from the auth screen", "DocMind" not in title, title[:160])

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
              // Read either key: the app migrated docmind.* -> origin.* on read.
              const t = localStorage.getItem('origin.token') || localStorage.getItem('docmind.token');
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

        # ---- Emotional tone of the question should surface on the bubble ----
        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              btns.find(b => b.textContent.trim().startsWith('Chat'))?.click();
              return true;
            })()
            """
        )
        time.sleep(1.2)
        ask(
            "This is the third time I have contacted support and nobody has fixed "
            "it. Absolutely unacceptable.",
            wait_s=60,
        )
        time.sleep(1.0)
        tone_shown = ws.evaluate(
            "[...document.querySelectorAll('span[title]')]"
            ".some(e => /reads as /i.test(e.getAttribute('title')||''))"
        )
        check("a frustrated question gets a tone badge", bool(tone_shown))
        chrome.screenshot(shots / "24-tone-badge.png")

        # A neutral technical question must NOT get one.
        before = ws.evaluate(
            "[...document.querySelectorAll('span[title]')]"
            ".filter(e => /reads as /i.test(e.getAttribute('title')||'')).length"
        )
        ask("What is the maximum efficiency of extracting wind energy?", wait_s=60)
        time.sleep(1.0)
        after = ws.evaluate(
            "[...document.querySelectorAll('span[title]')]"
            ".filter(e => /reads as /i.test(e.getAttribute('title')||'')).length"
        )
        check(
            "a neutral question does not get a tone badge",
            after == before,
            f"before={before} after={after}",
        )

        # ---- Emotion analysis tool on a document ----
        ws.evaluate(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              btns.find(b => b.textContent.trim().startsWith('Documents'))?.click();
              return true;
            })()
            """
        )
        time.sleep(1.5)
        ws.evaluate(
            """
            (() => {
              const boxes = [...document.querySelectorAll('input[type=checkbox]')];
              const n = boxes.find(b => (b.closest('[class*=card]') || b.parentElement || {textContent:''})
                .textContent.includes('Demo-Renewable-Energy'));
              if (n) n.click();
              return !!n;
            })()
            """
        )
        time.sleep(1.2)
        ran = ws.evaluate(
            """
            (() => {
              const b = [...document.querySelectorAll('button')]
                .find(x => x.textContent.trim() === 'Emotions');
              if (!b) return false;
              b.click();
              return true;
            })()
            """
        )
        check("Emotions tool button exists", bool(ran))
        for _ in range(45):
            time.sleep(1)
            if ws.evaluate("!!document.querySelector('[data-testid=emotion-panel]')"):
                break
        panel = ws.evaluate("!!document.querySelector('[data-testid=emotion-panel]')")
        check("emotion panel renders", bool(panel))
        if panel:
            panel_text = ws.evaluate(
                "document.querySelector('[data-testid=emotion-panel]').innerText"
            ) or ""
            check("panel shows a distribution", "EMOTION DISTRIBUTION" in panel_text.upper())
            check("panel reports intensity", "valence" in panel_text.lower())
            check(
                "panel states its own limits",
                "sarcasm" in panel_text.lower(),
                panel_text[-200:],
            )
        chrome.screenshot(shots / "23-emotion-panel.png")

        # ---- Sidebar credit: pinned below Light / Sign out ----
        sidebar_credit = ws.evaluate(
            """
            (() => {
              const credit = document.querySelector('[data-testid=made-with-love]');
              const out = [...document.querySelectorAll('button')]
                .find(b => (b.getAttribute('title') || '') === 'Sign out');
              if (!credit || !out) return null;
              const c = credit.getBoundingClientRect();
              const o = out.getBoundingClientRect();
              return {
                top: c.top,
                bottom: c.bottom,
                signOutTop: o.top,
                viewportH: window.innerHeight,
              };
            })()
            """
        )
        check("sidebar shows the credit line", sidebar_credit is not None)
        if sidebar_credit:
            check(
                "credit sits below the theme toggle and sign out",
                sidebar_credit["top"] >= sidebar_credit["signOutTop"],
                str(sidebar_credit),
            )
            check(
                "credit is pinned to the bottom of the viewport",
                sidebar_credit["viewportH"] - sidebar_credit["bottom"] < 24,
                str(sidebar_credit),
            )
        chrome.screenshot(shots / "26-sidebar-credit.png")

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