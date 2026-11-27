# Physical AI Hackathon Karlsruhe · 28 Nov 2026

Software: **Physical AI Harness by RoboForge**. One app guides you through the whole day:
set up the robot → record data → train a VLA → orchestrator & skills → your own interface → share → present.
The app is in English (switch to German in the profile menu, top right).

## The task

An SO-101 robot arm places three parts into the right slots and checks the result with a camera. If the mounting
plate is tilted or a slot is occupied, the flow should detect the error, fix it if possible, or stop with a reason.

## Installation

Requirement: **Python 3.12** from python.org (macOS: the "universal2 installer", then double-click
"Install Certificates.command" in the Python folder once).

| System | Start (the first start sets everything up, 10-20 min) |
|---|---|
| Windows | double-click `Start Windows.cmd` |
| macOS | double-click `Start macOS.command` (first time: right-click → Open) |

The app opens in its own window (http://127.0.0.1:8780). Sign in with the **team code** from your note.
Windows: `icons/plattform_verknuepfung.ps1` creates a desktop/taskbar shortcut.

### Training

At the hackathon every team trains its VLA with **ACT** (small, fast, runs on Windows, Mac and Linux;
with an NVIDIA graphics card it is fastest). Other models can be enabled in `plattform/server.py`
(`ERLAUBTE_METHODEN`), see the hint "Other models?" in section 3 of the app.

## Your team folder

Everything you build lives in `teams/<your-team>/` (template: `teams/_vorlage/`). **Read `AGENTS.md`** there,
or let your coding agent read it. Only this folder is shared. The software is plain source code: you and your
coding agent can read everything, but please only change your team folder.

## Sharing

- **Code:** button *Upload team folder*. It goes to the branch `team/<your-team>`. A guard workflow automatically
  copies only your folder to `main` (every 5 minutes).
- **Models and datasets:** button *Publish model*. They go to Hugging Face under
  [RoboForge](https://huggingface.co/RoboForge), with team name and description.

## Safety

No arm movement without a person on site and their consent (every movement is approved in the app).
Never connect 12 V to the arms. When in doubt: **STOP** at the top right, or F12.
