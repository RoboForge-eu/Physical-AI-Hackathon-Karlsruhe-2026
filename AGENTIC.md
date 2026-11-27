# Agentic Robotics: Präzision durch Werkzeuge und Regelschleife

**Prinzip:** Das VLA bringt das Teil grob hin. Danach sorgt ein Programm für die Präzision.
Das Sprachmodell **plant, wählt Werkzeuge und schreibt/verbessert den Code**. Die Feinarbeit macht der Code
selbst in einer schnellen Schleife: **messen → kleine Korrektur → messen**. Das Sprachmodell sitzt nicht in
jedem Regeltakt; es bekommt am Ende einen **Ereignis-Bericht in Sätzen** plus Messbild.

| Begriff | Was | Wer |
|---|---|---|
| Werkzeug | eine Fähigkeit des Harness: messen, korrigieren, Kontakt lesen (`vision.*`, `arm.*`) | fest programmiert, Sicherheit im Harness |
| Skill | Python-Code `run(robot, ...)`, der Werkzeuge in einer Schleife benutzt | Sprachmodell schreibt und verbessert |
| Ablauf | Orchestrator ruft VLA-Fähigkeiten und Skills nacheinander auf | Mensch / Orchestrator |

## Die Werkzeuge

| Im Skill (`robot.`) | Harness-Befehl | Was |
|---|---|---|
| `messen(ziel, kamera)` | `vision.messen` | ArUco-Marker, runde Öffnung oder Kreis finden (OpenCV, kein LLM). Abstand in mm (Markergröße), mit Kalibrierung die Korrektur `[dx, dy]` in mm, die das Merkmal unter die Spitze bringt. Speichert ein **Messbild** mit eingezeichneter Messung (`ki_daten/messbilder/`). |
| `kalibrieren()` | `vision.kalibrieren` | Pixel → mm → Bewegung: Marker messen, +3 mm x, zurück, +3 mm y, zurück → 2×2-Matrix. |
| – | `vision.werkzeugpunkt_merken` | einmal vor Ort (für den Agenten gesperrt): wo die Spitze im Kamerabild hinzeigt. |
| `korrektur(dx, dy, dz)` | `arm.korrektur` | kleine kartesische Korrektur über die Kinematik (`remote_kin`): **max. 5 mm je Achse**, langsam, Handneigung/Rolle/Greifer bleiben, Gelenkanschläge geprüft. Bewegt → nur in freigegebener Sitzung. |
| `kontakt()` | `arm.kontakt` | Kontakt **ohne Kraftsensor** aus Servo-Soll/Ist und Last: `zustand` frei/berührt, Höhenfehler, Ereignisse `angestossen`, `abgesackt` (Höhe fällt plötzlich = in die Öffnung gerutscht), `frei`. |
| `zeit()` | – | Sekunden seit Skill-Start (für Berichte). |

Neu im Worker: `lab_worker.py` gibt zusätzlich alle 0,1 s eine Zeile `LAST l1..l6` aus (Present Load der
STS3215, nur lesen – an Regelung und Sicherheitsschwellen ist nichts geändert).

### Kontakt: wie und welche Schwellen
Spitzenhöhe zweimal über die Kinematik: aus Soll und aus Ist. `fehler = z(Ist) − z(Soll) − Nulllinie`.
Die **Nulllinie** gleitet, solange kein Kontakt ist – nötig, weil der echte Arm ohne Kontakt im Mittel ~10 mm
unter dem Soll hängt (26 435 Proben aus euren Episoden, `python -m regel.schwellen`).
Schwellen (`regel/kontakt.py`): angestoßen > 1,5 mm über 3 Proben (oder Laständerung > 120 ‰),
abgesackt > 1,0 mm in 0,4 s mehr als befohlen, frei < 0,6 mm. In der Simulation bestätigt (0 Falschmeldungen
in 60 Versuchen). Aus den Teleop-Episoden lässt sich **keine** sichere Schwelle für den echten Arm ableiten
(dort ändert sich der Fehler in 0,3 s um bis zu 23 mm, weil schnell gefahren wird). → beim ersten Experiment
vor Ort prüfen (Schritt 5 unten).

## Die Regelschleifen-Vorlagen (`skilllib/vorlagen/`, als Skills in der Bibliothek)

- **visuelles_ausrichten**: messen → Korrektur → messen, bis Restversatz < 0,5 mm oder 8 Versuche.
- **spiralsuche**: absenken bis Kontakt, 2 mm andrücken, eckige Spirale (0,5 mm Schritte, bis 3 mm);
  Erfolg = `abgesackt`, danach einführen bis Anschlag; „verkantet“, wenn der Anschlag zu flach kommt.
- **zugtest**: 2 mm ziehen – bleibt die Spitze hinter dem Soll, sitzt das Teil.
- **stift_einstecken**: Pose `ueber_oeffnung` → (kalibrieren) → ausrichten → Spiralsuche → Zugtest.
- **schachtel_auf_palette**: greifen (mit Greifer-Prüfung und zweitem Versuch) und ablegen.

Beispiel-Bericht (Simulation): „Nach 1 Korrekturen ausgerichtet, Restversatz 0.14 mm (0.3 s). Kontakt bei
50.0 mm Höhe nach 14 mm Absenken und 4.6 s. Drücke 2.0 mm an und suche in einer Spirale bis 3.0 mm. Nach 9
Spiralschritten und 8.4 s um 3.8 mm abgesackt … Weitere 13 mm eingeführt, sitzt unten auf. Zugtest mit 2.0 mm:
Teil hält.“

## Ergebnis in der Simulation (20 zufällige Startlagen, Pose bis ±4 mm daneben, Licht zufällig)

| Variante | Erfolg | Falschmeldungen |
|---|---|---|
| Spiel 0,5 mm, mit Ausrichten + Spirale | **19/20** | 0 |
| Spiel 0,5 mm, ohne Ausrichten (nur Spirale) | 10/20 | 0 |
| Spiel 0,2 mm, mit Ausrichten + Spirale | 16/20 | 0 |

`python -m sim.experiment_einstecken --n 20 [--ohne-ausrichten] [--spiel-mm 0.2]`; Details in
`ki_daten/sim_experiment_einstecken.json`. Der eine Fehlschlag bei 0,5 mm: Öffnung unter Schatten nicht erkannt
(der Skill meldet das ehrlich).

## SkillAuthor (Agentic-Skill-Studio)

Der Agent kennt jetzt die neuen `robot`-Methoden (Werkzeug `doku`), die Vorlagen (Werkzeug `vorlagen`) und kann
**ohne Freigabe in der Simulation testen** (Werkzeug `simulationslauf`, mehrere zufällige Startlagen, Messbild
zurück). Echte Versuche weiterhin nur mit deiner Freigabe. Die Harness-Befehle stehen über `agent/tools.py`
automatisch auch dem Orchestrator-Agenten zur Verfügung (bewegende nur in freigegebener Sitzung).

## Tipp: Mechanik schlägt Sensor

**Fasen und Trichter an gedruckten Halterungen vergrößern die Toleranz – billiger als jeder Sensor.**
Eine 1-mm-Fase am Loch macht aus „0,2 mm treffen“ ein „1,2 mm treffen“; die Spiralsuche findet das Loch dann
fast immer im ersten Umlauf. Gleiches gilt für Führungsschrägen am Kabel-Stecker-Halter.

## Dein erstes echtes Experiment (Schritt für Schritt)

Ziel: Stift (z. B. 6-mm-Rundstab im Greifer) in ein gedrucktes Loch (7 mm, mit Fase) stecken.

1. **Marker drucken:** ArUco `DICT_4X4_50`, **ID 7**, Kantenlänge **genau 20 mm** (mit weißem Rand ≥ 4 mm).
   Erzeugen: `python -c "import cv2; from vision import marker; cv2.imwrite('marker7.png', marker.erzeugen(7, 400, 80))"`
   und so drucken, dass das schwarze Quadrat 20 mm misst (nachmessen!).
2. **Aufkleben:** flach auf die Halterung, **2 cm neben** dem Loch, so dass Marker und Loch zusammen im Bild der
   Handgelenk-Kamera sind, wenn die Spitze ~12 mm über dem Loch steht. Matt, nicht spiegelnd.
3. **Posen merken (Harness, vor Ort):** Arbeitssitzung freigeben, Arm per Leader so führen, dass die Stiftspitze
   ~12 mm über dem Loch steht, Hand senkrecht nach unten → `pose.merken` „ueber_oeffnung“. Greifer `auf`/`zu` merken.
4. **Werkzeugpunkt:** Stiftspitze genau auf die Markermitte setzen, auf ~12 mm anheben (gleiche Höhe wie die Pose),
   dann `vision.werkzeugpunkt_merken`. Danach `vision.kalibrieren` (fährt 2× 3 mm hin und zurück).
5. **Kontakt prüfen, bevor etwas eingesteckt wird:** Stift über flache Stelle, `arm.korrektur` dz = −1 mm in
   Schritten, nach jedem Schritt `arm.kontakt`. Erwartung: `angestossen` innerhalb 1–3 mm nach Berührung, nicht
   vorher. Kommt es zu früh/zu spät → Werte notieren (Fehler und Last stehen in der Antwort) und mir geben.
6. **Ausrichten allein:** Skill `visuelles_ausrichten` – schau dir das Messbild an (rote Linie = gemessener Versatz).
7. **Ganz:** Skill `stift_einstecken`. Danach Bericht und Messbild lesen.

Worauf achten: Hand in Reichweite des Stop-Knopfs; Licht gleichmäßig (kein harter Schatten über dem Loch);
Spitze nie mehr als ein paar mm in die Halterung drücken lassen (die Korrektur fährt nur 5 mm je Schritt, aber
der Servo drückt mit voller Kraft); erst mit Fase üben, dann ohne.
