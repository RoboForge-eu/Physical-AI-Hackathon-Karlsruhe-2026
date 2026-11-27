# Simulation (SO-101 ohne Hardware)

Ein simulierter SO-101 mit derselben Schnittstelle wie der echte Arm. VLA-Modelle (über den KI-Fahrer),
Code-Skills und Orchestrator-Abläufe laufen damit ohne Hardware. **Kein COM-Port, keine echte Bewegung.**

## Zwei Backends, eine Schnittstelle

| Backend | Was | Status |
|---|---|---|
| `kinsim` (`sim/welt.py`) | Eigene leichte Simulation: Servo-Positionsregler, Kontakt mit Tisch/Halterung/Loch, Schachtel greifen, zwei Kameras (Handgelenk, Turm), Domain Randomization. Nur numpy/OpenCV, keine GPU. | **läuft, getestet** |
| `isaac` (`sim/isaac/`) | NVIDIA Isaac Sim 6.2 / Isaac Lab 3.0 mit der offiziellen Vorlage `isaaclab_assets.robots.so101.SO101_CFG` (TheRobotStudio-USD, SysID-Antriebe). Server läuft in `%USERPROFILE%\isaac-env`, spricht JSON-Zeilen mit dem Harness. | **läuft** (headless, 18.11. geprüft) |

Beide liefern dieselben Methoden (`setze_soll`, `schritt`, `stellung`, `last`, `bild`, `spitze`), deshalb laufen
Sim-Worker und Skill-Simulation mit beiden.

## Starten

```bash
python ros.py --sim
```
Harness im Simulationsmodus: Titel, orange Kopfzeile und jedes Arm-Feld zeigen **SIMULATION**; statt
`lab_worker.py` startet `sim_worker.py` (gleiches Protokoll: `start/stop/rec/target/ktarget`, `OBS`-, `LAST`-Zeilen).
Kamerabilder kommen aus der Simulation (`ki_daten/sim_kameras/`). „Neu starten“ behält `--sim` bei.
Isaac statt kinsim: Umgebungsvariable `ROBOFORGE_SIM_BACKEND=isaac`.

Weitere Einstiege (alle ohne Harness):
```bash
python -m sim.experiment_einstecken --n 20
```
```bash
python -m sim.episoden_aufnehmen --n 20
```
Code-Skill in der Simulation: `run_skill(name, modus="sim", sim={"szenario": "einstecken", "seed": 3})`;
im Agentic-Skill-Studio nutzt der SkillAuthor dafür das Werkzeug `simulationslauf`.

## Isaac: was erledigt ist, was du morgen tust

Erledigt in der Nacht:
1. Isaac Sim 6.2 (`isaacsim[all,extscache]==6.2.0.0`) in `isaac-env` – Log `%USERPROFILE%\isaac-install.log`, `EXIT 0`.
2. PyTorch **2.11.0+cu130** in `isaac-env` (die Isaac-Installation hatte nur die CPU-Version gezogen),
   `torch.cuda.is_available() == True` auf der RTX 3090. Log `%USERPROFILE%\isaac-torch.log`.
3. `isaaclab.bat -i` mit aktivierter Umgebung – Log `%USERPROFILE%\isaaclab-install.log` (siehe BERICHT_NACHT.md).
4. URDF + Meshes des SO-101 (TheRobotStudio) nach `modell/so101_roh/` (für eigene Importe; Isaac Lab bringt das USD schon mit).
5. `sim/isaac/server.py` (Szene: Tisch, Palette, Schachtel, Halterung mit Loch, Licht, Handgelenk- und Turmkamera),
   `sim/isaac/backend.py` (Client), `sim/isaac/umrechnung.py` (Ticks ↔ rad wie `so101_modell.py`).

**Nicht** gemacht: Isaac gestartet. Die NVIDIA-Omniverse-Lizenz (EULA) bestätigst du selbst; `OMNI_KIT_ACCEPT_EULA`
wird nirgends gesetzt. Erster Start (fragt die EULA ab, lädt Shader/Assets, dauert beim ersten Mal lange):

```bash
%USERPROFILE%\isaac-env\Scripts\activate.bat && cd %USERPROFILE%\IsaacLab && isaaclab.bat -p scripts\tutorials\00_sim\create_empty.py --viz kit
```
Danach den SO-101-Server einmal von Hand prüfen (Fenster sichtbar):
```bash
%USERPROFILE%\isaac-env\Scripts\python.exe sim\isaac\server.py
```
**Stand 18.11. (EULA bestätigt, erster Start ok):** Server läuft ohne Fenster (Isaac Lab 3.0: kein `--headless`
mehr, Fenster mit `--visualizer kit`). Erster Start ~5 min (Shader). Gelenke folgen dem Soll (Durchhang 7–22 Ticks wie
echt), Vorzeichen aller 4 Armgelenke gleich wie `remote_kin`. Die USD zeigt nach −y → Basis um +90° gedreht.
Turmkamera per Blickpunkt wie kinsim, Handkamera aus Lage/Drehung des Greifers (Fingerachse = −z). Fehler: `ki_daten/isaac_server.log`.
Noch offen:
- Vorzeichen/Nullstellung der Gelenke (`sim/isaac/umrechnung.py: SIGN`) gegen `remote_kin.fk` – Spitze bei
  gleicher Tick-Stellung an derselben Stelle?
- Pfad der Handgelenk-Kamera (`/World/Robot/gripper/...`) und Lage der Turmkamera (Quaternion grob gesetzt).
- `werkzeugpunkt` im Server ist ein Platzhalter – wie am echten Arm einmal bestimmen (AGENTIC.md).
- Nur starten, wenn die Grafikkarte frei ist (`nvidia-smi`), nicht während eines Trainings.

## Domain Randomization (gegen das Licht-Problem)

Je Szene zufällig: Helligkeit (×0,55–1,35), Farbstich je Kanal, weicher Schatten, Bildrauschen, Tisch- und
Schachtelfarbe, Schachtel-/Palettenlage, Turmkamera-Position (±3 cm) und -Richtung. 20 Episoden „Schachtel auf
Palette“ liegen in `ki_daten/datensaetze/sim_schachtel_auf_palette/` (eigenes Format, Arm `sim_follower`,
Kameras `arm` + `turm`, 640×360, 30 Hz) – Log `ki_daten/sim_episoden.log`.

## Grenzen (Simulation ≠ echt)

- kinsim ist **kinematisch**: kein Drehmoment-Modell, keine Reibung, kein Durchbiegen. Der echte Arm hängt
  ohne Kontakt im Mittel ~10 mm unter dem Soll (aus 26 000 Proben echter Episoden, `python -m regel.schwellen`) –
  kinsim nicht. Der Kontaktmelder arbeitet deshalb mit gleitender Nulllinie.
- Last in kinsim = Schwerkraft-Grundwert + k·Abweichung (grob), nicht gemessen.
- Gerendert wird vereinfacht (Ebenen + Quader, Arm als Linienzug in der Turmkamera). Für VLA-Training sind die
  Bilder nur ein Hilfsmittel (Licht-Robustheit), kein Ersatz für echte Aufnahmen. Sim-Datensätze heißen `sim_*`
  und gehören dem Arm `sim_follower` – sie lassen sich nicht mit echten mischen (`open_dataset` prüft den Arm).
- Handgelenk-Rolle wird in der Kamera nicht berücksichtigt; Lochwand nur seitlich blockierend.
- Ein Joint-Sprung über große Wege kann in kinsim durch Kanten „hängen“ – Regelschleifen fahren in ≤ 5-mm-Schritten.

## Nächste Schritte

1. EULA bestätigen, Isaac-Beispiel headless laufen lassen, `server.py` prüfen (siehe oben).
2. `sim/isaac/pruefen.py` schreiben: FK-Vergleich Isaac ↔ remote_kin bei 20 Stellungen.
3. Einsteck-Experiment und Episoden-Aufnahme mit `--backend isaac` wiederholen (echte Kontaktphysik).
4. VLA mit gemischten Daten (echt + sim_*) als Experiment trainieren – nur, wenn die GPU frei ist.
