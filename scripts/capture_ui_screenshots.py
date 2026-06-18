#!/usr/bin/env python3
"""Capture genuine screenshots of the Streamlit explorer with Playwright.

Usage::

    python scripts/capture_ui_screenshots.py --url http://localhost:8599 \
        --out-dir docs/images

Requires a running Streamlit instance and the ``playwright`` package with
Chromium installed (``playwright install chromium``).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORT = {"width": 1600, "height": 1100}


def _settle(page, seconds: float = 4.0) -> None:
    """Wait for Streamlit to finish running (no 'Running' spinner)."""
    deadline = time.time() + 90
    while time.time() < deadline:
        running = page.locator('[data-testid="stStatusWidget"]').count()
        if running == 0:
            break
        time.sleep(1.0)
    page.wait_for_timeout(int(seconds * 1000))


def _shot(page, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), full_page=True)
    print(f"Wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8599")
    ap.add_argument("--out-dir", type=Path, default=Path("docs/images"))
    ap.add_argument("--prefix", default="ui")
    args = ap.parse_args()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
            page.goto(args.url, wait_until="networkidle", timeout=120_000)
            _settle(page)
            _shot(page, args.out_dir / f"{args.prefix}-real-lfp.png")

            for label, name in (("Model comparison", "model-comparison"),
                                ("Forecasts", "forecasts")):
                tab = page.get_by_role("tab", name=label)
                if tab.count() == 0:
                    print(f"WARNING: tab {label!r} not found", file=sys.stderr)
                    continue
                tab.first.click()
                _settle(page)
                _shot(page, args.out_dir / f"{args.prefix}-{name}.png")
            browser.close()
    except Exception as exc:  # pragma: no cover - developer tooling
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
