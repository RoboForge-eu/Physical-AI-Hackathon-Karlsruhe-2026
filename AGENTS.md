# Hinweise fuer Coding-Agents · Physical AI Harness by RoboForge

Dieser Ordner ist die **Software als Quellcode** (Python + HTML/JS, nichts kompiliert). Jede Installation (jeder
Ordner) hat ihre eigenen Daten: `config.json` (welches USB-Board ist welcher Arm, Kamera-Plaetze), `calibration/`,
`ki_daten/` (Datensaetze, Modelle, Aufnahmeplan-Fortschritt), `plattform_daten/`. Sprache: Deutsch, kurz und einfach.

## Aufbau

| Teil | Datei(en) | Hinweis |
|---|---|---|
| Start | `physical_ai_harness.py` | oeffnet die App (http://127.0.0.1:8780) und den Harness |
| Webseite + Server | `plattform/` | **KERN** – eine Seite mit Abschnitten 0–7 |
| Harness (Arm, Kameras, Sicherheit) | `ros.py`, `webstation.py`, `cameras.py`, `oak.py` | **KERN** |
| KI (Aufnahme, Training) | `ki/`, `aufnahme/` | **KERN** |
| Skills des Harness | `ki/ros_skills.py` | Liste: Skill `skills.liste` |
| Team-Arbeit | `teams/<team>/` | **hier wird gebaut**, siehe `teams/_vorlage/AGENTS.md` |
| Beispiel-Trainingsplan | `plaene/elektrodose.json` | Vorlage fuer eigene Plaene in `teams/<team>/plaene/` |

Teams erweitern nur Orchestrator, Code-Skills, Interface und Trainingsplaene in `teams/<team>/`. Den Kern nicht
umbauen; er ist mit `KERN-DATEI` markiert.

## Arme einrichten (Arme finden)

```
python -m plattform.station boards                                 # Boards mit Seriennummer (oeffnet keinen Port)
python -m plattform.station arme --follower <SN> --leader <SN> --name "Setup 1"
```
Leader-Board finden: Leader-USB kurz ziehen, `boards` erneut ausfuehren – das fehlende Board ist der Leader.
Danach den Harness neu starten (App: 1 · Roboter → Harness neu starten). Kameras: App → Kameras zuordnen.
Die OAK-D Lite (zweite Uebersichtskamera) liegt auf Platz 3 (`"device": "OAK"`, braucht `pip install depthai`).

## Sicherheit (verbindlich)

- Keine Armbewegung ohne Mensch vor Ort und dessen Zustimmung. Freigaben nie umgehen.
- Nie 12 V an die Arme. Servo-EEPROM nicht veraendern.
- Keine Geheimnisse (Tokens, Passwoerter) ausgeben oder committen.
- Stop: Skill `arm.ablegen` oder `notablage` (immer erlaubt), in der App F12.

## Tests

`python -m unittest` fuer jede `test_*.py` in diesem Ordner.
