#!/usr/bin/env python3
"""Frontend static, build and small browser smoke tests."""
from __future__ import annotations

import re
import subprocess
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "src" / "App.jsx"
CSS = FRONTEND / "src" / "styles.css"

def check(name: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
    if not passed:
        raise AssertionError(name)

def main() -> int:
    source = APP.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    buttons = re.findall(r"<button\b([^>]*)>", source, flags=re.S)
    component_buttons = re.findall(r"<Button\b([^>]*)>", source, flags=re.S)
    wired_buttons = all("onClick=" in attributes for attributes in buttons)
    typed_buttons = all("type=" in attributes for attributes in buttons)
    wired_components = all("onClick=" in attributes or "type=\"submit\"" in attributes or "type='submit'" in attributes for attributes in component_buttons)
    checks = [
        ("all native frontend buttons have click handlers", bool(buttons) and wired_buttons),
        ("all native frontend buttons declare a button type", bool(buttons) and typed_buttons),
        ("all shared Button components perform an action or submit a form", bool(component_buttons) and wired_components),
        ("login screen includes customer demo ID", "setUserId('1')" in source),
        ("login screen includes admin demo ID", "setUserId('900001')" in source),
        ("login screen includes supervisor demo ID", "setUserId('900002')" in source),
        ("staff case actions are wired", "onUpdate({status:'closed'" in source and "intervention_required:" in source),
        ("staff reply action is wired", "onReply(reply)" in source),
        ("filter reset is wired", "onClearFilters" in source and "loadStaff(token,empty)" in source),
        ("customer chat refresh is wired", "setInterval(poll,3000)" in source),
        ("customer can create a support request without an order", "onContact(null)" in source and "Create a support request" in source),
        ("intervention action explains its effect", "Request human review" in source and "Clear human review" in source and "Flag this when the AI should stop handling the case" in source),
        ("voice uses browser WebRTC", "new RTCPeerConnection()" in source and "createDataChannel" in source),
        ("voice uses authenticated server endpoints", "/api/customer/voice-connect" in source and "/api/customer/voice-turn" in source),
        ("voice SDP is sent to the authenticated backend, not directly to OpenAI", "Content-Type':'application/sdp" in source and "api.openai.com/v1/realtime/calls" not in source),
        ("voice handles completed Realtime function calls", "response.output_item.done" in source and "function_call_output" in source),
        ("browser bundle does not contain a standard OpenAI API key", "OPENAI_API_KEY" not in source),
        ("voice controls have styling", ".voice-support-button" in css),
    ]
    for name, passed in checks:
        check(name, passed)

    if not (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        print("SKIP: Vite production build — run npm ci in frontend first")
        print("SKIP: Browser smoke test — frontend dependencies are not installed")
        return 0

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("SKIP: Vite production build — npm is not available on PATH")
        print("SKIP: Browser smoke test — npm is not available on PATH")
        return 0
    npm_cmd = (["cmd", "/c", npm] if os.name == "nt" else [npm])
    build = subprocess.run([*npm_cmd, "run", "build"], cwd=FRONTEND, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    check("Vite production build", build.returncode == 0, build.stdout[-1200:].strip().replace("\n", " | "))

    # Browser smoke test is optional when the Playwright browser binary is not installed.
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("SKIP: Browser smoke test — Python Playwright is not installed")
        return 0

    server = subprocess.Popen([*npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5178"],
                              cwd=FRONTEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ready = False
        for _ in range(40):
            try:
                with urlopen("http://127.0.0.1:5178", timeout=1) as response:
                    ready = response.status == 200
                if ready:
                    break
            except Exception:
                time.sleep(0.25)
        check("Vite development server starts", ready)
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                print(f"SKIP: Browser smoke test — Chromium unavailable ({type(exc).__name__})")
                return 0
            page = browser.new_page()
            page.goto("http://127.0.0.1:5178", wait_until="networkidle")
            page.get_by_text("Demo access").wait_for()
            field = page.locator("#user-id")
            for role, value in (("Customer", "1"), ("Admin", "900001"), ("Supervisor", "900002")):
                page.get_by_role("button", name=re.compile(role)).click()
                check(f"Browser can select {role} demo ID", field.input_value() == value)
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError:
        raise SystemExit(1)
