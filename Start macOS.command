#!/bin/bash
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
