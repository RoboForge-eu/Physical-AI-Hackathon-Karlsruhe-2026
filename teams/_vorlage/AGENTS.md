# Notes for coding agents (Claude Code, Codex, Cursor ...)

You are working in the **team folder** of a team at the *Physical AI Hackathon Karlsruhe* (28 Nov 2026) with the
**Physical AI Harness by RoboForge**. Keep answers short and simple. The code base uses German names for skills,
functions and result keys (e.g. `greifer` = gripper, `sitzung` = session, `haelt_etwas` = is holding something);
`skills.liste` describes every skill.

## The hackathon task

An SO-101 robot arm places three parts into the right slots and checks the result with a camera. If the mounting
plate is tilted or a slot is occupied, the flow should detect the error, fix it if possible, or stop with a reason.
Three building blocks, one flow:

| Building block | What | Where |
|---|---|---|
| **VLA** (imitation learning) | learned movements, e.g. "grasp a part" | section *3 · Training*; recording plans in `plaene/` |
| **Code skills** (agentic robotics) | Python functions that call harness skills, measure, check | `skills/` |
| **Vision** | check the camera image (slot occupied? plate tilted?) | `skills/` (OpenCV, small models) |
| **Orchestrator** | connects everything into one flow | `orchestrator.py` |

## Where you build – and where not (important)

The platform is finished and made for beginners. **Do not rebuild it.** Only extend the team building blocks:

| Extend (your part) | File in the team folder | shows up in the app |
|---|---|---|
| Flow / orchestrator | `orchestrator.py` | 4 · Orchestrator |
| Code skills, vision | `skills/*.py` | 4 · Orchestrator (via `orchestrator.py`) |
| Your own interface | `ui/index.html` (+ your own .js/.css next to it) | 5 · Interface |
| Training plan (recording plan for a VLA) | `plaene/<id>.json` (guide: `plaene/README.md`, example `../../plaene/elektrodose.json`) | 2 · Data (control mode) and 3 · Training |
| Presentation | `vorstellung.md` | 7 · Demo |

**Do not change** (core, shared by all teams, files are marked `KERN-DATEI` = core file): `plattform/` (web page and
server), `ros.py` and `webstation.py` (harness, safety), `ki/` (recording, training), `cameras.py`, `oak.py`,
`calibration/`, `config.json`. If a harness function is missing, use the existing skills (`skills.liste`) or build
a code skill in `skills/`. If you really need a core change: give a short reason and ask the organizers.

## What you may do here

- Work **only in this folder** (`teams/<team>/`). Only this folder is shared (the team branch on GitHub); changes
  outside are ignored when uploading.
- `orchestrator.py`: the flow. Start it in section *4 · Orchestrator* (button "Start orchestrator.py").
- `skills/*.py`: your own code skills (functions that use `ros.call(...)`).
- `plaene/<id>.json`: your own **recording plans** (training plans for VLAs). Guide: `plaene/README.md`.
  The app picks them up automatically; they then appear in control mode for recording.
- `ui/index.html`: the team interface, shown in section *5 · Interface*.
- `vorstellung.md`: text for the final presentation.

## Interface to the robot (harness skills)

```python
from ros_client import RosClient          # lives in the program folder, PYTHONPATH is set
ros = RosClient("team")
ros.call("skills.liste")                  # all skills with description and parameters
ros.call("arme.liste")                    # arms
ros.call("kamera.bild", arm="follower", kamera="arm")      # JPEG as Base64
ros.call("modelle.liste")                 # trained models
```

Important skills: `sitzung.anfragen` (request work session), `sitzung.status`, `sitzung.beenden` (end session),
`modell.vorladen` (preload model), `modell.ausfuehren` (run model), `pose.anfahren` (move to saved pose),
`greifer.setzen` (set gripper), `greifer.pruefen` (check gripper), `vision.messen` (measure), `arm.ablegen` (put
down), `notablage` (emergency put-down).

Cameras: `kamera.bild` (the arm cameras), `kamera.plaetze` (all slots), `kamera.platz_bild` (e.g. the second
overview camera **OAK-D Lite** for experiments) and `kamera.tiefe` (OAK-D Lite: distance in mm at an image
position, optionally as a depth image).

Commands starting with `station.*`, `steuer.*`, `spiegel.*` and `web.*` belong to the app (operation on site).
**Never** call them from the orchestrator or skills.

In the interface (browser) the same via:

```js
fetch("/api/skill", {method: "POST", headers: {"Content-Type": "application/json", "X-RF": "1"},
                     body: JSON.stringify({name: "arme.liste", args: {}})})
```

## Safety (binding)

- **No arm movement without a person on site and their consent.** Moving skills only work in a work session that
  a person approves in the app (`sitzung.anfragen` shows the dialog on site). Never try to bypass this approval.
- When in doubt: `arm.ablegen` (always allowed) or `notablage`.
- Never write or print secrets (tokens, passwords).
- Never 12 V to the arms. Do not change the servo EEPROM.
- Test movements slowly (small `grad_pro_s`), hand on the stop button.

## Tips

- Read first (`arme.liste`, `kamera.bild`), then move.
- Only learn what needs vision. Everything with a fixed location is programmed (set up poses in control mode with
  `pose.merken` and use them with `pose.anfahren`).
- Check success without a camera: `greifer.pruefen` (if the gripper closes completely, nothing is inside).
