# Hinweise fuer Coding-Agents (Claude Code, Codex, Cursor ...)

Du arbeitest im **Team-Ordner** eines Teams beim *Physical AI Hackathon Karlsruhe* (28.11.2026) mit dem
**Physical AI Harness by RoboForge**. Sprache im Projekt: Deutsch, kurz und einfach.

## Die Aufgabe des Hackathons

Ein SO-101-Roboterarm legt drei Bauteile in die richtigen Faecher und prueft das Ergebnis per Kamera. Liegt die
Montageplatte schraeg oder ist ein Fach belegt, soll der Ablauf den Fehler erkennen, wenn moeglich korrigieren oder
begruendet stoppen. Drei Bausteine, ein Ablauf:

| Baustein | Was | Wo |
|---|---|---|
| **VLA** (Imitation Learning) | gelernte Bewegungen, z. B. "Teil greifen" | Abschnitt *VLA trainieren*; Aufnahmeplaene in `plaene/` |
| **Code-Skills** (Agentic Robotics) | Python-Funktionen, die Harness-Skills aufrufen, messen, pruefen | `skills/` |
| **Bildverarbeitung** | Kamerabild pruefen (Fach belegt? Platte schraeg?) | `skills/` (OpenCV, kleine Modelle) |
| **Orchestrator** | verbindet alles zu einem Ablauf | `orchestrator.py` |

## Was du hier tun darfst

- **Nur in diesem Ordner** arbeiten (`teams/<team>/`). Nur dieser Ordner wird geteilt (GitHub-Zweig des Teams);
  Aenderungen ausserhalb werden beim Hochladen ignoriert.
- `orchestrator.py`: der Ablauf. Startbar im Abschnitt *Orchestrator & Skills* (Knopf "starten").
- `skills/*.py`: eigene Code-Skills (Funktionen, die `ros.call(...)` benutzen).
- `plaene/<id>.json`: eigene **Aufnahmeplaene** (Trainingsplaene fuer VLAs). Anleitung: `plaene/README.md`.
  Die Plattform uebernimmt sie automatisch; sie erscheinen dann im Steuermodus zur Aufnahme.
- `ui/index.html`: das **eigene Interface** des Teams, angezeigt im Abschnitt *Euer Interface*.
- `vorstellung.md`: Text fuer die Abschlusspraesentation.

## Schnittstelle zum Roboter (Harness-Skills)

```python
from ros_client import RosClient          # liegt im Programmordner, PYTHONPATH ist gesetzt
ros = RosClient("team")
ros.call("skills.liste")                  # alle Skills mit Beschreibung und Parametern
ros.call("arme.liste")
ros.call("kamera.bild", arm="follower", kamera="arm")      # JPEG als Base64
ros.call("modelle.liste")
```

Wichtige Skills: `sitzung.anfragen`, `sitzung.status`, `sitzung.beenden`, `modell.vorladen`, `modell.ausfuehren`,
`pose.anfahren`, `greifer.setzen`, `greifer.pruefen`, `vision.messen`, `arm.ablegen`, `notablage`.

Im Interface (Browser) dasselbe per:

```js
fetch("/api/skill", {method: "POST", headers: {"Content-Type": "application/json", "X-RF": "1"},
                     body: JSON.stringify({name: "arme.liste", args: {}})})
```

## Sicherheit (verbindlich)

- **Keine Armbewegung ohne Mensch vor Ort und Zustimmung.** Bewegende Skills funktionieren nur in einer
  Arbeitssitzung, die ein Mensch am Harness-Fenster freigibt (`sitzung.anfragen` zeigt den Dialog vor Ort).
  Versuche nie, diese Freigabe zu umgehen.
- Bei Unklarheit: `arm.ablegen` (immer erlaubt) oder `notablage`.
- Keine Geheimnisse (Tokens, Passwoerter) in Dateien schreiben oder ausgeben.
- Nie 12 V an die Arme. Servo-EEPROM nicht veraendern.
- Bewegungen langsam testen (`grad_pro_s` klein), Hand am Stop-Knopf.

## Tipps

- Erst lesen (`arme.liste`, `kamera.bild`), dann bewegen.
- Gelernt wird nur, was Sehen braucht. Alles mit festem Ort wird fest programmiert (Posen im Steuermodus mit
  `pose.merken` einrichten und mit `pose.anfahren` nutzen).
- Erfolg pruefen ohne Kamera: `greifer.pruefen` (schliesst der Greifer ganz, ist nichts drin).
