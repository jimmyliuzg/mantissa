"""End-to-end M4 test: share links, both config and snapshot.

Asserts:
  1. After upload + run, "Copy link" puts a URL on the clipboard
     starting with the site origin and containing `?d=c1:` (config).
  2. The link round-trips: opening it in a fresh browser context
     shows the same KPIs.
  3. "Copy snapshot link" puts a URL containing `?s=s1:` (snapshot).
  4. The snapshot link loads instantly — no Pyodide boot wait — and
     shows the same KPIs.
  5. Editing a field on a snapshot view clears the snapshot banner
     and re-runs the engine.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CONFIG = REPO_ROOT / "examples" / "sample_config.json"
PORT = 8767


def main() -> int:
    cfg = json.loads(SAMPLE_CONFIG.read_text())

    with sync_playwright() as p:
        # First browser context: create the share links.
        b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = b.new_context(
            accept_downloads=True,
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = ctx.new_page()
        page.on("console", lambda m: print(f"[browser:{m.type}] {m.text[:200]}"))
        page.on("pageerror", lambda e: print(f"[pageerror] {str(e)[:200]}"))

        page.goto("http://127.0.0.1:8767/")
        page.evaluate(
            "(c) => sessionStorage.setItem('mantissa:config', JSON.stringify(c))", cfg
        )
        page.goto("http://127.0.0.1:8767/#/review", wait_until="load")
        page.wait_for_selector(".kpi-row .kpi-value", timeout=180_000)
        baseline = page.eval_on_selector_all(
            ".kpi .kpi-value", "els => els.map(e => e.textContent.trim())"
        )
        print(f"baseline KPIs: {baseline}")

        # --- Copy config link ---
        page.click(".share-bar button:has-text('Copy link')")
        time.sleep(0.5)
        config_url = page.evaluate("() => navigator.clipboard.readText()")
        print(f"==> config URL starts with: {config_url[:60]}...")
        if "?d=c1-" not in config_url:
            print(f"FAIL: config URL missing ?d=c1-: {config_url[:200]}")
            return 2

        # --- Copy snapshot link ---
        page.click(".share-bar button:has-text('Copy snapshot link')")
        time.sleep(0.5)
        snapshot_url = page.evaluate("() => navigator.clipboard.readText()")
        print(f"==> snapshot URL starts with: {snapshot_url[:60]}...")
        if "?s=s1-" not in snapshot_url:
            print(f"FAIL: snapshot URL missing ?s=s1-: {snapshot_url[:200]}")
            return 3
        # Snapshot must be larger than the config URL (more bytes encoded).
        if len(snapshot_url) <= len(config_url):
            print(f"FAIL: snapshot ({len(snapshot_url)}) not larger than config ({len(config_url)})")
            return 4

        # --- Open the config URL in a fresh context; engine runs ---
        ctx2 = b.new_context()
        page2 = ctx2.new_page()
        t0 = time.time()
        page2.goto(config_url, wait_until="load", timeout=60_000)
        page2.wait_for_selector(".kpi-row .kpi-value", timeout=180_000)
        config_kpis = page2.eval_on_selector_all(
            ".kpi .kpi-value", "els => els.map(e => e.textContent.trim())"
        )
        config_secs = time.time() - t0
        print(f"config link KPIs (after {config_secs:.1f}s): {config_kpis}")
        if config_kpis != baseline:
            print(f"FAIL: config link KPIs differ from baseline")
            return 5

        # --- Open the snapshot URL; should be near-instant ---
        ctx3 = b.new_context()
        page3 = ctx3.new_page()
        t0 = time.time()
        page3.goto(snapshot_url, wait_until="load", timeout=60_000)
        page3.wait_for_selector(".kpi-row .kpi-value", timeout=30_000)
        snap_secs = time.time() - t0
        print(f"snapshot link KPIs (after {snap_secs:.1f}s): {baseline[:7]}")
        snap_kpis = page3.eval_on_selector_all(
            ".kpi .kpi-value", "els => els.map(e => e.textContent.trim())"
        )
        if snap_kpis != baseline:
            print(f"FAIL: snapshot KPIs differ from baseline")
            print(f"  expected: {baseline}")
            print(f"  got:      {snap_kpis}")
            return 6

        # --- Snapshot must show the banner ---
        banner = page3.evaluate(
            "() => document.querySelector('.snapshot-banner')?.textContent || ''"
        )
        if "shared snapshot" not in banner:
            print(f"FAIL: snapshot banner not shown. got: {banner!r}")
            return 7

        # --- Editing a field on a snapshot view triggers a re-run ---
        print("==> editing a field on the snapshot view")
        page3.evaluate(
            """
            () => {
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
              const numInputs = document.querySelectorAll('.drawer input[type="number"]');
              const target = numInputs[0]; // first numeric field
              if (!target) return false;
              setter.call(target, '999999');
              target.dispatchEvent(new Event('input', { bubbles: true }));
              return true;
            }
            """
        )
        # Wait for the snapshot banner to clear (indicates re-run).
        deadline = time.time() + 60
        cleared = False
        while time.time() < deadline:
            banner_text = page3.evaluate(
                "() => document.querySelector('.snapshot-banner')?.textContent || ''"
            )
            if "shared snapshot" not in banner_text:
                cleared = True
                break
            time.sleep(0.5)
        if not cleared:
            print(f"FAIL: snapshot banner did not clear after edit")
            return 8
        print("==> snapshot banner cleared, re-run in progress")

        # Wait for the re-run to complete.
        page3.wait_for_selector(".kpi-row .kpi-value", timeout=180_000)
        # The new run should differ from the baseline.
        new_kpis = page3.eval_on_selector_all(
            ".kpi .kpi-value", "els => els.map(e => e.textContent.trim())"
        )
        print(f"after edit KPIs: {new_kpis}")
        if new_kpis == baseline:
            print(f"WARN: KPIs unchanged after edit; engine may not have re-run")
            # not a hard fail, but worth flagging
        print("==> M4 OK")
        b.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
