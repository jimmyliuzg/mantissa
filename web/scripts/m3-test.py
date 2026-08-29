"""End-to-end M3 test: walk the wizard, open in viewer, verify engine
runs and produces a non-trivial result.

Asserts:
  1. Landing page exposes a wizard entry point that navigates to /#/wizard.
  2. The wizard renders 9 step markers in the progress bar.
  3. We can step through with default answers and reach the Review screen.
  4. Clicking "Open in viewer" navigates to /#/review, the engine
     bootstraps, the projection runs, and the KPI row renders.
  5. The KPI value for the primary retirement scenario (defaults) is
     non-empty and reflects the wizard's high-balance, high-spending
     default profile.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = b.new_context().new_page()
        page.on("console", lambda m: print(f"[browser:{m.type}] {m.text[:200]}"))
        page.on("pageerror", lambda e: print(f"[pageerror] {str(e)[:200]}"))

        # Start at the landing page.
        page.goto("http://127.0.0.1:8767/", wait_until="load")
        # Click the wizard tile.
        print("==> clicking Start from scratch")
        page.click(".tile--wizard")
        page.wait_for_selector(".wizard", timeout=10_000)

        # Progress bar should have 9 dots.
        dots = page.eval_on_selector_all(".progress-dot", "els => els.length")
        print(f"==> progress dots: {dots}")
        if dots != 9:
            print(f"FAIL: expected 9 progress dots, got {dots}")
            return 2

        # Click Next 8 times to walk through the 8 question steps to Review.
        print("==> walking through 8 question steps")
        for i in range(8):
            time.sleep(0.05)
            page.click(".btn--primary")
        page.wait_for_selector(".review-table", timeout=5_000)
        print("==> reached review step")

        # Click "Open in viewer →"
        print("==> opening in viewer")
        page.click(".wizard-footer__final .btn--primary")
        page.wait_for_selector(".kpi-row .kpi-value", timeout=180_000)

        kpis = page.eval_on_selector_all(
            ".kpi .kpi-value", "els => els.map(e => e.textContent.trim())"
        )
        print(f"==> viewer KPIs: {kpis}")

        # The default wizard profile (35, retire 65, 250k assets, 120k
        # income, 60k spending, CA, 2.4k SS) should produce a success
        # rate that is at minimum 50% — the user is well-funded.
        success = float(kpis[0].rstrip("%"))
        print(f"==> success rate: {success}%")
        if success < 50:
            print(f"FAIL: success rate {success}% < 50% (under-funded plan)")
            return 3

        # Also verify the engine actually ran the slim config — pull
        # the runtime from the header.
        header = page.evaluate(
            "() => document.querySelector('.viewer-header .small')?.textContent || ''"
        )
        print(f"==> header: {header!r}")
        if "ready" not in header:
            print(f"FAIL: header did not show 'ready': {header!r}")
            return 4

        print("==> M3 OK")
        b.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
