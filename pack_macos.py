"""Stellt das macOS-Paket der Fernsteuerung zusammen: dist/RoboForge_Fernsteuerung_macOS.zip

Enthaelt nur, was die App braucht (kein Harness, keine KI), zwei Doppelklick-Skripte und eine Anleitung.
Die .command-Dateien bekommen im ZIP das Ausfuehrungsrecht, damit sie auf dem Mac direkt starten.

  python pack_macos.py
"""
import os, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "RoboForge Fernsteuerung (macOS)"
FILES = ["fernsteuerung.py", "fern_core.py", "fern_sim.py", "remote_access.py", "remote_kin.py", "so101.py",
         "fast_bus.py", "build_fernsteuerung.py", "icons/__init__.py", "icons/fernsteuerung.png", "icons/fernsteuerung.ico", "requirements-fernsteuerung.txt"]

START = """#!/bin/bash
# Startet die RoboForge Fernsteuerung. Beim ersten Mal wird eine eigene Python-Umgebung eingerichtet (~2 min).
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Richte die Fernsteuerung ein (einmalig) ..."
  python3 -m venv .venv || { echo "Python 3 fehlt - siehe ANLEITUNG.md"; read -n 1; exit 1; }
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements-fernsteuerung.txt || { echo "Installation fehlgeschlagen"; read -n 1; exit 1; }
fi
./.venv/bin/python fernsteuerung.py
"""

BUILD = """#!/bin/bash
# Baut die Fernsteuerung als echte Mac-App (dist/RoboForge Fernsteuerung.app), die ohne Python laeuft.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements-fernsteuerung.txt
fi
./.venv/bin/python -m pip install pyinstaller
./.venv/bin/python build_fernsteuerung.py
open dist
echo "Fertig. Die App liegt im Ordner dist. Fenster schliessen mit einer Taste."; read -n 1
"""

README = """# RoboForge Fernsteuerung – macOS

## Was du brauchst

1. **macOS 12 oder neuer** (Apple-Chip oder Intel).
2. **Python 3.10 oder neuer mit Tkinter** – am einfachsten vom offiziellen Installer:
   https://www.python.org/downloads/macos/ → „macOS 64-bit universal2 installer“ → installieren.
   Danach im Ordner „Programme/Python 3.x“ einmal **„Install Certificates.command“** doppelklicken.
   (Python aus Homebrew geht auch, braucht aber zusätzlich `brew install python-tk`.)
3. Einen **Zugangscode** (beginnt mit `RF1.`) – erstellt im RoboForge Harness mit „Fernzugang erstellen“.
4. Optional: einen **SO-101-Leader-Arm** per USB. Ohne Leader steuerst du mit der Tastatur.

## Starten (ohne etwas zu bauen)

1. ZIP entpacken, den Ordner z. B. in „Dokumente“ legen.
2. **`Fernsteuerung starten.command`** doppelklicken.
   - Beim ersten Mal fragt macOS evtl. „nicht verifizierter Entwickler“: **Rechtsklick → Öffnen → Öffnen**.
   - Beim ersten Start wird eine eigene Python-Umgebung eingerichtet (ca. 2 Minuten, Internet nötig).
3. Zugangscode einfügen → **Verbinden**.

## Als echte Mac-App bauen (optional)

**`App bauen.command`** doppelklicken → nach einigen Minuten liegt **`RoboForge Fernsteuerung.app`** im Ordner `dist`.
Diese App läuft auch auf anderen Macs ohne Python. Sie ist nicht von Apple signiert: beim ersten Start
**Rechtsklick → Öffnen**. (Eine App baut immer für den Prozessor des Macs, auf dem gebaut wird.)

## Leader-Arm am Mac

Der Anschluss heißt meist `/dev/cu.usbmodem…` oder `/dev/cu.usbserial…`. In der App unter „Eigener Leader-Arm“
auswählen → „Leader verbinden“. Die App liest den Leader nur, sie bewegt ihn nie.

## Steuern

- **Tastatur:** W/S vor/zurück · A/D links/rechts · R/F hoch/runter · Q/E Hand heben/senken · T/G Hand drehen ·
  O/L Greifer auf/zu · Umschalt = schneller · **Leertaste = Steuern an/aus · Esc = Stop**.
- **Übungsmodus:** nur die Mini-Simulation, nichts wird gesendet – zum Ausprobieren ohne Roboter.
- Bewegen kann der echte Arm nur, wenn vor Ort im Harness „Remote (Internet)“ gewählt und freigegeben ist.

## Wenn etwas nicht geht

| Problem | Lösung |
|---|---|
| „python3: command not found“ | Python wie oben installieren |
| Fenster öffnet nicht, Fehler mit „tkinter“ | Python vom offiziellen Installer nehmen (nicht das von Apple mitgelieferte) |
| Kein Leader-Anschluss in der Liste | USB-Kabel/Strom prüfen, dann „↻“ |
| „Zugangscode ist abgelaufen“ | im Harness neuen Code erstellen (gilt 12 h) |
"""


def main():
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    target = os.path.join(HERE, "dist", "RoboForge_Fernsteuerung_macOS.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(os.path.join(HERE, f), f"{NAME}/{f}")
        for name, text, mode in (("Fernsteuerung starten.command", START, 0o755), ("App bauen.command", BUILD, 0o755),
                                 ("ANLEITUNG.md", README, 0o644)):
            info = zipfile.ZipInfo(f"{NAME}/{name}")
            info.external_attr = (0o100000 | mode) << 16          # Unix-Rechte: ausfuehrbar fuer .command
            info.create_system = 3                                # 3 = Unix, sonst ignoriert macOS die Rechte
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.replace("\r\n", "\n"))
    print("Fertig:", target)


if __name__ == "__main__":
    main()
