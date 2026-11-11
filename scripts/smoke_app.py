"""Start the Streamlit app headless, browse every tab, and fail if the server logs show errors.

Run from a fresh checkout to also exercise the first start (documentation download and index).
Prerequisites: pip install -e . playwright && python -m playwright install chromium
Usage: python scripts/smoke_app.py
"""

from __future__ import annotations

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
PORT = 8598
BASE = f"http://localhost:{PORT}"
# Compte de démonstration administrateur : il voit tous les écrans (E-01 à E-08).
LOGIN = "Alex Administrateur (Administrateur)"
TABS = [
    "Tableau de bord",
    "Projet",
    "Plan",
    "Fiche étape",
    "Assistant",
    "Livrables",
    "Administration",
    "Sources",
    "Référentiel",
]
BAD_LOG = re.compile(r"Traceback|Exception|Error|Warning|deprecat|Please replace", re.IGNORECASE)


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
    page.wait_for_function(
        "!document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=180000
    )
    time.sleep(1)


def main() -> int:
    log_path = Path(tempfile.mkstemp(prefix="streamlit-", suffix=".log")[1])
    # Base neuve, chargée avec les données de démonstration (comme sur Community Cloud).
    env = {**os.environ, "OCA_DB": str(Path(tempfile.mkdtemp()) / "smoke.db")}
    with log_path.open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py",
                "--server.headless", "true", "--server.port", str(PORT),
                "--browser.gatherUsageStats", "false",
            ],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
        )  # fmt: skip
        problems: list[str] = []
        try:
            wait_for_server()
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                page.goto(BASE)
                settle(page)  # le premier démarrage télécharge la doc et construit l'index
                page.get_by_role("button", name=LOGIN).click()
                settle(page)
                for tab in TABS:
                    page.get_by_role("tab", name=tab).click()
                    settle(page)
                    if page.locator('[data-testid="stException"]').count():
                        problems.append(f"exception affichée dans l'onglet {tab}")
                page.get_by_role("tab", name="Assistant").click()
                page.locator('[data-testid="stMain"]').get_by_label("Question", exact=True).fill(
                    "Comment imprimer des chèques ?"
                )
                page.locator('[data-testid="stMain"]').get_by_role(
                    "button", name="Demander"
                ).click()
                # Titre recomposé en français (F-003), en anglais si la traduction manque.
                page.locator('[data-testid="stMain"]').get_by_text(
                    re.compile("Émettre des chèques|Writing checks")
                ).first.wait_for(timeout=30000)
                body = page.inner_text("body")
                page.get_by_role("tab", name="Plan").click()
                settle(page)
                # Les métriques du plan ne s'affichent que si un projet est ouvert
                # (le nom du projet est dans un champ, absent de innerText).
                if "Faites ou validées" not in page.inner_text("body"):
                    problems.append("le projet exemple n'est pas ouvert")
                if "Index indisponible" in body:
                    problems.append("index indisponible")
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=20)
    output = log_path.read_text(encoding="utf-8")
    print("---- logs Streamlit ----")
    print(output)
    problems += [f"log : {line.strip()}" for line in output.splitlines() if BAD_LOG.search(line)]
    if problems:
        print("ÉCHEC :\n- " + "\n- ".join(problems))
        return 1
    print(f"OK : application démarrée, {len(TABS)} onglets parcourus, aucune erreur dans les logs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
