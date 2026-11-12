"""Capture demo screenshots of the Streamlit app with Playwright, on the example project.

Prerequisites: pip install -e . playwright, documentation fetched and index built.
Usage: python scripts/capture_screens.py [--out docs/img]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 8599
BASE = f"http://localhost:{PORT}"


def wait_for_server(timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/_stcore/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("Streamlit n'a pas démarré")


def settle(page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]')")
    time.sleep(1.5)


def open_tab(page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    settle(page)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "img")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app/streamlit_app.py",
            "--server.headless",
            "true",
            "--server.port",
            str(PORT),
            "--browser.gatherUsageStats",
            "false",
            "--theme.base",
            "light",
        ],
        cwd=ROOT,
        env={**os.environ, "OCA_DB": str(Path(tempfile.mkdtemp()) / "captures.db")},
    )
    try:
        wait_for_server()
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=2)

            # La fiche ouverte vient du paramètre ?step= ; la connexion garde l'adresse.
            page.goto(f"{BASE}/?step=fin_taxes")
            settle(page)
            page.get_by_role("button", name="Camille Consultante (Consultant)").click()
            settle(page)
            open_tab(page, "Plan")
            # Streamlit défile dans son propre conteneur : on agrandit la fenêtre pour que les
            # 36 étapes du plan tiennent sur la capture.
            page.set_viewport_size({"width": 1440, "height": 2150})
            settle(page)
            page.screenshot(path=args.out / "01-plan.png", full_page=True)
            page.set_viewport_size({"width": 1440, "height": 960})

            open_tab(page, "Fiche étape")
            page.screenshot(path=args.out / "02-fiche-etape.png", full_page=True)

            open_tab(page, "Assistant")
            page.locator('[data-testid="stMain"]').get_by_label("Question", exact=True).fill(
                "Comment configurer les positions fiscales au Québec ?"
            )
            page.locator('[data-testid="stMain"]').get_by_role("button", name="Demander").click()
            page.locator('[data-testid="stMain"]').get_by_text(
                re.compile("Positions fiscales|Fiscal positions")
            ).first.wait_for(timeout=30000)
            settle(page)
            page.screenshot(path=args.out / "03-assistant.png", full_page=True)

            open_tab(page, "Projet")
            page.screenshot(path=args.out / "04-profil.png", full_page=True)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=20)
    print(f"Captures écrites dans {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
