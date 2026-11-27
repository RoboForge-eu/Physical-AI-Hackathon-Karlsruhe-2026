@echo off
rem Physical AI Harness by RoboForge - Windows. The first start sets everything up (10-20 min, internet needed).
cd /d "%~dp0"
set PY=py -3.12
%PY% --version >nul 2>nul || set PY=python
%PY% --version >nul 2>nul || (echo Python 3.12 is missing. Please install it: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo [1/2] Setting up the app ...
  %PY% -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements-plattform.txt || (echo Installation failed & pause & exit /b 1)
  .venv\Scripts\python -m pip install depthai || echo OAK-D Lite support not installed ^(optional^)
)
if not exist ki-env\Scripts\python.exe (
  echo [2/2] Setting up the AI environment ^(LeRobot, PyTorch - large, please wait^) ...
  %PY% -m venv ki-env || (pause & exit /b 1)
  ki-env\Scripts\python -m pip install --upgrade pip
  nvidia-smi >nul 2>nul && ki-env\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  ki-env\Scripts\python -m pip install "lerobot[smolvla]==0.7.0" || (echo AI installation failed & pause & exit /b 1)
)
start "" .venv\Scripts\pythonw.exe physical_ai_harness.py --harness
