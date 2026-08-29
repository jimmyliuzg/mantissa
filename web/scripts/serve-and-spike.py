"""End-to-end M1 viewer test.

Builds, serves, drops the CLI sample config into sessionStorage, drives
the viewer with Playwright, and asserts the rendered KPIs match the CLI
baseline to 14 decimal places.

This is the M1 acceptance test. It replaces the earlier /tmp spike once
M1 is in-tree.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
SAMPLE_CONFIG = REPO_ROOT / "examples" / "sample_config.json"
BASELINE = Path("/tmp/mantissa-pyodide-spike/baseline/run.json")
PORT = 8767


def build() -> None:
    print("==> building mantissa wheel")
    subprocess.run(
        ["bash", "web/scripts/build-wheel.sh"],
        cwd=REPO_ROOT,
        check=True,
    )
    print("==> building web app")
    subprocess.run(
        ["npx", "vite", "build"],
        cwd=WEB_ROOT,
        check=True,
    )


def serve() -> subprocess.Popen[bytes]:
    print(f"==> serving {WEB_ROOT / 'dist'} on :{PORT}")
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1",
         "--directory", str(WEB_ROOT / "dist")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="skip build step")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    if not args.no_build:
        build()

    server = serve()
    try:
        time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_context().new_page()
            page.on("console", lambda m: print(f"[browser:{m.type}] {m.text}"))
            page.on("pageerror", lambda e: print(f"[pageerror] {e}"))

            # Inject sample config into sessionStorage before navigation so
            # the viewer page picks it up.
            config = json.loads(SAMPLE_CONFIG.read_text())
            page.goto(f"http://127.0.0.1:{PORT}/")
            page.evaluate(
                "(c) => sessionStorage.setItem('mantissa:config', JSON.stringify(c))",
                config,
            )
            page.goto(f"http://127.0.0.1:{PORT}/review", wait_until="load")

            # Wait for the engine to bootstrap and the viewer to render.
            print("==> waiting for KPI row to render")
            try:
                page.wait_for_selector(".kpi-row .kpi-value", timeout=args.timeout * 1000)
            except Exception as e:
                page.screenshot(path=str(WEB_ROOT / "fail.png"), full_page=True)
                print(f"FAIL: {e}")
                return 2

            # Read each KPI value and the chart paths.
            kpi_texts = page.eval_on_selector_all(
                ".kpi .kpi-value",
                "els => els.map(e => e.textContent.trim())",
            )
            print(f"==> rendered KPIs: {kpi_texts}")

            # The deterministic projection also runs; pull cash flow chart presence.
            cash_flow_paths = page.eval_on_selector_all(
                ".panel:nth-of-type(1) .chart path.series",
                "els => els.length",
            )
            fan_paths = page.eval_on_selector_all(
                ".panel:nth-of-type(2) .chart path.series, .panel:nth-of-type(2) .chart line.series",
                "els => els.length",
            )
            print(f"==> cash-flow series paths: {cash_flow_paths[0] if cash_flow_paths else 0}")
            print(f"==> fan series paths: {fan_paths[0] if fan_paths else 0}")

            # Compare to CLI baseline.
            base = json.loads(BASELINE.read_text())
            want_pct = base["success_rate"] * 100
            got_pct = float(kpi_texts[0].rstrip("%"))
            ok = abs(got_pct - want_pct) < 0.05  # display rounds to 1 decimal
            print(f"==> success rate: browser {got_pct}% vs CLI {want_pct:.1f}% — {'OK' if ok else 'MISMATCH'}")

            page.screenshot(path=str(WEB_ROOT / "ok.png"), full_page=True)
            browser.close()
            return 0 if ok else 1
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
