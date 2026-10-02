#!/usr/bin/env python3
"""Capture light-mode and responsive screenshots for visual review.

Not part of the pass/fail suite - this is a manual inspection helper.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui_test import APP_URL, Chrome  # noqa: E402


def js(body: str) -> str:
    """Wrap a JS body so Chrome evaluates it as an expression.

    The semicolon matters: without it a body that does not end in one would
    splice into `...click() return true`, which is a syntax error.
    """
    return f"(function(){{ {body.rstrip().rstrip(';')}; return true }})()"


def click_button(ws, text: str, exact: bool = False) -> bool:
    matcher = f"b.textContent.trim()==={text!r}" if exact else f"b.textContent.trim().startsWith({text!r})"
    return bool(
        ws.evaluate(
            js(
                f"var b=[...document.querySelectorAll('button')].find(b=>{matcher});"
                f"if(b){{b.click();}}"
            )
        )
    )


def main() -> int:
    shots = Path(__file__).resolve().parents[1] / "storage" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    chrome = Chrome()
    ws = chrome.ws
    try:
        chrome.goto(APP_URL)
        rid = f"{int(time.time())}{random.randint(1000, 9999)}"

        click_button(ws, "Create account")
        time.sleep(0.8)
        ws.evaluate(
            js(
                "var set=function(el,v){var d=Object.getOwnPropertyDescriptor("
                "el.constructor.prototype,'value');d.set.call(el,v);"
                "el.dispatchEvent(new Event('input',{bubbles:true}));};"
                f"set(document.querySelector('#email'), {f'vis-{rid}@example.com'!r});"
                f"set(document.querySelector('#username'), {f'vis{rid}'!r});"
                "set(document.querySelector('#password'), 'password123');"
            )
        )
        time.sleep(0.4)
        ws.evaluate(js("document.querySelector('button[type=submit]').click();"))
        time.sleep(5)

        body = ws.evaluate("document.body.innerText") or ""
        if "Chat with your documents" not in body:
            print(f"registration failed: {body[:200]}")
            return 1
        print("signed in")

        # Upload the demo so the chat view has real content.
        click_button(ws, "Try Demo Document")
        # Indexing plus suggestion generation takes a few seconds on CPU.
        time.sleep(14)
        print("demo uploaded")

        # ---- Light mode: use the sidebar toggle (aria-label is unambiguous) ----
        ws.evaluate(
            js(
                "var b=[...document.querySelectorAll('button')]"
                ".find(b=>(b.getAttribute('aria-label')||'').indexOf('mode')>=0);"
                "if(b) b.click();"
            )
        )
        time.sleep(1.5)
        theme_now = ws.evaluate("document.documentElement.className")
        print(f"theme after toggle: {theme_now!r}")

        click_button(ws, "Chat")
        time.sleep(1.5)
        chrome.screenshot(shots / "11-light-chat.png")

        # ---- Documents view (light) ----
        click_button(ws, "Documents")
        time.sleep(2)
        chrome.screenshot(shots / "12-light-documents.png")

        click_button(ws, "Chat")
        time.sleep(1.5)

        # ---- Back to dark for the responsive shots ----
        ws.evaluate(
            js(
                "var b=[...document.querySelectorAll('button')]"
                ".find(b=>(b.getAttribute('aria-label')||'').indexOf('mode')>=0);"
                "if(b) b.click();"
            )
        )
        time.sleep(1.5)

        # ---- Tablet ----
        ws.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 900, "height": 800, "deviceScaleFactor": 2, "mobile": False},
        )
        time.sleep(1.5)
        chrome.screenshot(shots / "13-tablet.png")

        # ---- Mobile + slide-out nav ----
        ws.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True},
        )
        time.sleep(1.5)
        chrome.screenshot(shots / "14-mobile.png")

        ws.evaluate(js("document.querySelector('[aria-label=\"Open navigation\"]')?.click();"))
        time.sleep(1.5)
        chrome.screenshot(shots / "15-mobile-nav.png")

        print(f"screenshots written to {shots}")
        return 0
    finally:
        chrome.close()


if __name__ == "__main__":
    sys.exit(main())