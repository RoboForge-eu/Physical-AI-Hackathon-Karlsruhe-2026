"""Stellt das Hackathon-Repo zusammen (Software + Team-Vorlage + Waechter + Installation fuer Windows/macOS).

Kopiert NUR Programmdateien. Nicht dabei: Kalibrierung, config.json, Aufnahmen, Modelle, Schluessel, Logs.
Die Kalibrierung und Arm-Zuordnung jeder Station kommt spaeter ueber das Team-Paket (stationspakete/).

  python -m plattform.repo_bauen [zielordner]       (Standard: <RoboForge>/hackathon_repo)

Danach im Zielordner:  git init -b main ; git add . ; git commit ; git remote add origin <url> ; git push
"""
import json, os, shutil, sys

from . import KIT, HIER

ROOT = os.path.dirname(os.path.dirname(KIT))
ZIEL = os.path.join(ROOT, "hackathon_repo")

ORDNER = ["ki", "aufnahme", "plattform", "skilllib", "vision", "workflow", "regel", "sim", "icons", "modell", "karten",
          "agent", "teams/_vorlage"]
NICHT = {"__pycache__", "plattform_daten", "stationspakete"}
DATEI_NICHT = {"config.json", "livekit.json", "agent.json", "fernzugriff.json", "NACHT_PROMPT.md", "BERICHT_NACHT.md",
               "PROMPT.md", "ucode.elf"}
PLAENE = ["elektrodose.json"]

CONFIG_BEISPIEL = {
    "follower": {"usb_serial": "", "port": None, "label": "Setup 1", "cameras": [1, 2]},
    "leader": {"usb_serial": "", "port": None},
    "baud": 1000000,
    "cameras": [{"name": "Setup 1 · Arm", "device": ""}, {"name": "Setup 1 · Turm", "device": ""},
                {"name": "Übersicht 2 · OAK-D Lite", "device": "OAK"}, {"name": "frei 4", "device": ""}],
}

GITIGNORE = """# Lokal, nie ins Repo
.venv/
ki-env/
__pycache__/
*.pyc
plattform_daten/
stationspakete/
ki_daten/
calibration/
config.json
logs/
*.log
livekit.json
agent.json
fernzugriff.json
build/
dist/
.DS_Store
# Modelle und Datensaetze gehoeren auf Hugging Face (Knopf "Modell veroeffentlichen")
*.safetensors
*.pt
*.pth
*.bin
*.ckpt
*.mp4
*.npz
"""

REQ_PLATTFORM = """# Physical AI Harness: Oberflaeche + Harness (Arm, Kameras). Python 3.12.
pyserial>=3.5
websockets>=13
opencv-python>=4.9
numpy>=1.26
psutil>=5.9
pillow>=10
scipy>=1.11
"""

START_WIN = r"""@echo off
rem Physical AI Harness by RoboForge - Windows. Beim ersten Start wird alles eingerichtet (10-20 min, Internet noetig).
cd /d "%~dp0"
set PY=py -3.12
%PY% --version >nul 2>nul || set PY=python
%PY% --version >nul 2>nul || (echo Python 3.12 fehlt. Bitte installieren: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo [1/2] Richte die Oberflaeche ein ...
  %PY% -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements-plattform.txt || (echo Installation fehlgeschlagen & pause & exit /b 1)
  .venv\Scripts\python -m pip install depthai || echo OAK-D-Lite-Unterstuetzung nicht installiert ^(optional^)
)
if not exist ki-env\Scripts\python.exe (
  echo [2/2] Richte die KI-Umgebung ein ^(LeRobot, PyTorch - gross, bitte warten^) ...
  %PY% -m venv ki-env || (pause & exit /b 1)
  ki-env\Scripts\python -m pip install --upgrade pip
  nvidia-smi >nul 2>nul && ki-env\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  ki-env\Scripts\python -m pip install "lerobot[smolvla]==0.7.0" || (echo KI-Installation fehlgeschlagen & pause & exit /b 1)
)
start "" .venv\Scripts\pythonw.exe physical_ai_harness.py --harness
"""

START_MAC = """#!/bin/bash
# Physical AI Harness by RoboForge - macOS. Beim ersten Start wird alles eingerichtet (10-20 min, Internet noetig).
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3)
if [ -z "$PY" ]; then echo "Python 3.12 fehlt: https://www.python.org/downloads/macos/"; read -n 1; exit 1; fi
if [ ! -x .venv/bin/python ]; then
  echo "[1/2] Richte die Oberflaeche ein ..."
  "$PY" -m venv .venv || { read -n 1; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements-plattform.txt || { echo "Installation fehlgeschlagen"; read -n 1; exit 1; }
  .venv/bin/python -m pip install depthai || echo "OAK-D-Lite-Unterstuetzung nicht installiert (optional)"
fi
if [ ! -x ki-env/bin/python ]; then
  echo "[2/2] Richte die KI-Umgebung ein (LeRobot, PyTorch - gross, bitte warten) ..."
  "$PY" -m venv ki-env || { read -n 1; exit 1; }
  ki-env/bin/python -m pip install --upgrade pip
  ki-env/bin/python -m pip install "lerobot[smolvla]==0.7.0" || { echo "KI-Installation fehlgeschlagen"; read -n 1; exit 1; }
fi
.venv/bin/python physical_ai_harness.py --harness
"""

WAECHTER_YML = """# Ordner-Waechter: uebernimmt aus jedem Team-Zweig (team/<name>) NUR den Ordner teams/<name>/ nach main.
# Laeuft zeitgesteuert vom Hauptzweig aus - Aenderungen der Teams an diesem Workflow wirken also nie.
name: Ordner-Waechter
on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: ordner-waechter
  cancel-in-progress: false
jobs:
  uebernehmen:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0
          ssh-key: ${{ secrets.WAECHTER_DEPLOY_KEY }}
      - name: Team-Ordner uebernehmen
        run: python3 .github/waechter.py
      - name: Nach main schieben
        run: |
          git config user.name "Ordner-Waechter"
          git config user.email "waechter@hackathon.roboforge.eu"
          if ! git diff --cached --quiet; then
            git commit -m "Waechter: Team-Ordner aktualisiert"
            git push origin HEAD:main
          else
            echo "Nichts Neues."
          fi
"""

WAECHTER_PY = '''"""Ordner-Waechter (laeuft auf GitHub, nur vom Hauptzweig aus).

Fuer jeden Zweig origin/team/<name>: Ordner teams/<name>/ in main durch den Stand im Team-Zweig ersetzen.
Alles andere aus dem Team-Zweig wird ignoriert. Grosse Dateien und Modell-/Videodateien werden uebersprungen
(die gehoeren auf Hugging Face).
"""
import os, re, shutil, subprocess

MAX_BYTES = 20 * 2**20
SPERRE = (".safetensors", ".pt", ".pth", ".bin", ".ckpt", ".mp4", ".npz", ".onnx")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main():
    branches = [b.strip() for b in git("branch", "-r", "--format=%(refname:short)").splitlines()]
    for b in branches:
        if not b.startswith("origin/team/"):
            continue
        name = b[len("origin/team/"):]
        if not NAME.match(name) or name.startswith("_"):
            print("uebersprungen (Name):", b)
            continue
        ziel = os.path.join("teams", name)
        files = []
        for line in git("ls-tree", "-r", "-l", b, "--", f"teams/{name}/").splitlines():
            meta, path = line.split("\\t", 1)
            mode, typ, sha, size = meta.split()
            if typ != "blob" or mode == "120000":
                continue
            if size != "-" and int(size) > MAX_BYTES or path.lower().endswith(SPERRE):
                print("  zu gross / nicht erlaubt:", path)
                continue
            files.append((path, sha))
        if os.path.isdir(ziel):
            shutil.rmtree(ziel)
        for path, sha in files:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = subprocess.run(["git", "cat-file", "blob", sha], check=True, capture_output=True).stdout
            with open(path, "wb") as f:
                f.write(data)
        subprocess.run(["git", "add", "-A", "--", ziel], check=True)
        print(f"{name}: {len(files)} Dateien")


if __name__ == "__main__":
    main()
'''

README = """# Physical AI Hackathon Karlsruhe · 28.11.2026

Software: **Physical AI Harness by RoboForge**. Eine Oberflaeche im Browser fuehrt durch den ganzen Tag:
Roboter einrichten → Daten aufnehmen → VLA trainieren → Orchestrator & Skills → eigenes Interface → Teilen → Vorstellen.

## Die Aufgabe

Ein SO-101-Roboterarm legt drei Bauteile in die richtigen Faecher und prueft das Ergebnis per Kamera. Liegt die
Montageplatte schraeg oder ist ein Fach belegt, soll der Ablauf den Fehler erkennen, wenn moeglich korrigieren oder
begruendet stoppen.

## Installation

Voraussetzung: **Python 3.12** von python.org (macOS: der "universal2 installer", danach einmal
"Install Certificates.command" im Python-Ordner doppelklicken).

| System | Starten (erster Start richtet alles ein, 10-20 min) |
|---|---|
| Windows | `Start Windows.cmd` doppelklicken |
| macOS | `Start macOS.command` doppelklicken (beim ersten Mal: Rechtsklick → Oeffnen) |

Die Oberflaeche oeffnet sich im Browser unter http://127.0.0.1:8780. Mit dem **Team-Code** von eurem Zettel anmelden.

### Welcher Rechner trainiert was?

| Rechner | ACT | SmolVLA |
|---|---|---|
| Windows/Linux mit NVIDIA-Grafikkarte | gut | gut |
| MacBook mit Apple-Chip (M1-M4) | gut (1-3 h) | sehr langsam |
| ohne passende Grafikkarte | langsam | nicht sinnvoll |

Die Software erkennt das selbst und schlaegt die passende Methode vor.

## Euer Team-Ordner

Alles, was ihr baut, liegt in `teams/<euer-team>/` (Vorlage: `teams/_vorlage/`). **Lest `AGENTS.md`** dort,
oder lasst es euren Coding-Agent lesen. Nur dieser Ordner wird geteilt.

## Teilen

- **Code:** Knopf *Team-Ordner hochladen*. Er landet im Zweig `team/<euer-team>`. Ein Waechter uebernimmt
  automatisch nur euren Ordner nach `main` (alle 5 Minuten).
- **Modelle und Datensaetze:** Knopf *Modell veroeffentlichen*. Sie landen auf Hugging Face bei
  [RoboForge](https://huggingface.co/RoboForge), mit Teamname und Beschreibung.

## Sicherheit

Keine Armbewegung ohne Mensch vor Ort und Zustimmung (jede Bewegung wird im Harness-Fenster bestaetigt).
Nie 12 V an die Arme. Im Zweifel: **STOP** oben rechts.
"""

ADMIN = """# Fuer Veranstalter: Einrichtung des Repos (einmalig)

1. **Ruleset fuer `main`** (Settings → Rules → Rulesets → New branch ruleset):
   - Ziel: Standardzweig `main`
   - *Restrict updates*, *Restrict deletions*, *Block force pushes* einschalten
   - Bypass: nur **Deploy keys**
2. **Deploy-Key fuer den Waechter:** lokal `ssh-keygen -t ed25519 -f waechter -N ""`.
   - `waechter.pub` → Settings → Deploy keys → *Allow write access*
   - Inhalt von `waechter` (privat) → Settings → Secrets → Actions → `WAECHTER_DEPLOY_KEY`
   - Danach beide Dateien lokal loeschen.
3. **Token fuer die Teams:** Fine-grained Personal Access Token, nur dieses Repo, Berechtigung
   *Contents: Read and write* (NICHT *Workflows*, NICHT *Administration*). Er kommt in die Team-Pakete
   (`github.token`). Wegen des Rulesets kann damit niemand nach `main` schreiben, nur in die Team-Zweige.
4. **Actions** muessen erlaubt sein (Settings → Actions → General). Test: Actions → Ordner-Waechter → *Run workflow*.
5. Nach dem Hackathon: Token loeschen (Settings → Developer settings → Tokens).
"""


def kopieren(src, dst):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in NICHT]
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".log")) or f in DATEI_NICHT:
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))


def schreiben(path, text, exe=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n" if path.endswith(".cmd") else "\n") as f:
        f.write(text)
    if exe:
        os.chmod(path, 0o755)


CLAUDE_MD = """# Hinweise fuer KI-Assistenten

Siehe [AGENTS.md](AGENTS.md). Teams arbeiten nur in `teams/<team>/` (siehe `teams/_vorlage/AGENTS.md`).
"""


def entpersonalisieren(ziel):
    """Eigenen Benutzerpfad (z. B. C:/Users/<name>) in Texten durch %USERPROFILE% ersetzen."""
    home = os.path.expanduser("~")
    muster = [home.replace(os.sep, os.sep * 2), home]
    for root, dirs, files in os.walk(ziel):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            if not f.endswith((".py", ".md", ".txt", ".html", ".json", ".cmd")):
                continue
            p = os.path.join(root, f)
            with open(p, encoding="utf-8", errors="surrogateescape", newline="") as fh:
                s = fh.read()
            t = s
            for m in muster:
                t = t.replace(m, "%USERPROFILE%")
            if t != s:
                with open(p, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
                    fh.write(t)


def bauen(ziel=ZIEL):
    os.makedirs(ziel, exist_ok=True)
    for f in os.listdir(ziel):                   # alles ausser .git neu
        if f == ".git":
            continue
        p = os.path.join(ziel, f)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for f in os.listdir(KIT):
        p = os.path.join(KIT, f)
        if os.path.isfile(p) and f not in DATEI_NICHT and (f.endswith((".py", ".txt", ".md", ".html"))
                                                           or f.endswith(".example.json")):
            shutil.copy2(p, os.path.join(ziel, f))
    for d in ORDNER:
        if os.path.isdir(os.path.join(KIT, d)):
            kopieren(os.path.join(KIT, d), os.path.join(ziel, d))
    os.makedirs(os.path.join(ziel, "plaene"), exist_ok=True)
    for f in PLAENE:
        shutil.copy2(os.path.join(KIT, "plaene", f), os.path.join(ziel, "plaene", f))
    os.makedirs(os.path.join(ziel, "calibration"), exist_ok=True)
    schreiben(os.path.join(ziel, "config.example.json"), json.dumps(CONFIG_BEISPIEL, indent=1, ensure_ascii=False))
    schreiben(os.path.join(ziel, "README.md"), README)
    schreiben(os.path.join(ziel, "VERANSTALTER.md"), ADMIN)
    schreiben(os.path.join(ziel, "CLAUDE.md"), CLAUDE_MD)
    schreiben(os.path.join(ziel, ".gitignore"), GITIGNORE)
    schreiben(os.path.join(ziel, "requirements-plattform.txt"), REQ_PLATTFORM)
    schreiben(os.path.join(ziel, "Start Windows.cmd"), START_WIN)
    schreiben(os.path.join(ziel, "Start macOS.command"), START_MAC, exe=True)
    schreiben(os.path.join(ziel, ".github", "workflows", "ordner-waechter.yml"), WAECHTER_YML)
    schreiben(os.path.join(ziel, ".github", "waechter.py"), WAECHTER_PY)
    schreiben(os.path.join(ziel, "teams", "README.md"),
              "# Team-Ordner\n\nJedes Team arbeitet nur in `teams/<team>/`. Vorlage: `_vorlage/`.\n")
    entpersonalisieren(ziel)
    n = sum(len(f) for _, _, f in os.walk(ziel) if ".git" not in _)
    return ziel, n


if __name__ == "__main__":
    ziel, n = bauen(sys.argv[1] if len(sys.argv) > 1 else ZIEL)
    print(f"Hackathon-Repo in {ziel} ({n} Dateien).")
