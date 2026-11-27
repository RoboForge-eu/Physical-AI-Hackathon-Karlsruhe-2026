#!/bin/bash
# Physical AI Harness by RoboForge - macOS. The first start sets everything up (10-20 min, internet needed).
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3)
if [ -z "$PY" ]; then echo "Python 3.12 is missing: https://www.python.org/downloads/macos/"; read -n 1; exit 1; fi
if [ ! -x .venv/bin/python ]; then
  echo "[1/2] Setting up the app ..."
  "$PY" -m venv .venv || { read -n 1; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements-plattform.txt || { echo "Installation failed"; read -n 1; exit 1; }
  .venv/bin/python -m pip install depthai || echo "OAK-D Lite support not installed (optional)"
fi
if [ ! -x ki-env/bin/python ]; then
  echo "[2/2] Setting up the AI environment (LeRobot, PyTorch - large, please wait) ..."
  "$PY" -m venv ki-env || { read -n 1; exit 1; }
  ki-env/bin/python -m pip install --upgrade pip
  ki-env/bin/python -m pip install "lerobot[smolvla]==0.7.0" || { echo "AI installation failed"; read -n 1; exit 1; }
fi
.venv/bin/python physical_ai_harness.py --harness
