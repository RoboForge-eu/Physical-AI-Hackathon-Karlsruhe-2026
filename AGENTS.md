# Notes for coding agents · Physical AI Harness by RoboForge

This folder is the **software as source code** (Python + HTML/JS, nothing compiled). Every installation (every
folder) has its own data: `config.json` (which USB board is which arm, camera slots, language), `calibration/`,
`ki_daten/` (datasets, models, recording plan progress), `plattform_daten/`. The code uses German names; the app
shows English or German (profile → language; default per installation in `config.json` `"sprache"`).

## Structure

| Part | File(s) | Note |
|---|---|---|
| Start | `physical_ai_harness.py` | opens the app (http://127.0.0.1:8780) and the harness |
| Web page + server | `plattform/` | **CORE** – one page with sections 0–7, texts translated in `plattform/static/i18n.js` |
| Harness (arm, cameras, safety) | `ros.py`, `webstation.py`, `cameras.py`, `oak.py` | **CORE** |
| AI (recording, training) | `ki/`, `aufnahme/` | **CORE** |
| Harness skills | `ki/ros_skills.py` | list: skill `skills.liste` |
| Team work | `teams/<team>/` | **build here**, see `teams/_vorlage/AGENTS.md` |
| Example training plan | `plaene/elektrodose.json` | template for your own plans in `teams/<team>/plaene/` |

Teams only extend orchestrator, code skills, interface and training plans in `teams/<team>/`. Do not rebuild the
core; it is marked `KERN-DATEI` (core file).

## Setting up the arms (find arms)

```
python -m plattform.station boards                                 # boards with serial number (opens no port)
python -m plattform.station arme --follower <SN> --leader <SN> --name "Setup 1"
```
Find the leader board: unplug the leader USB for a moment and run `boards` again – the missing board is the leader.
Then restart the harness (app: 1 · Robot → Restart harness). Cameras: app → Assign cameras.
The OAK-D Lite (second overview camera) is on slot 3 (`"device": "OAK"`, needs `pip install depthai`).

## Safety (binding)

- No arm movement without a person on site and their consent. Never bypass approvals.
- Never 12 V to the arms. Do not change the servo EEPROM.
- Never print or commit secrets (tokens, passwords).
- Stop: skill `arm.ablegen` or `notablage` (always allowed), in the app F12.

## Tests

`python -m unittest` for every `test_*.py` in this folder.
