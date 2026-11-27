# Physical AI Hackathon Karlsruhe · 28.11.2026

Software: **Physical AI Harness by RoboForge**. Eine Oberflaeche im Browser fuehrt durch den ganzen Tag:
Roboter einrichten → Daten aufnehmen → VLA trainieren → Orchestrator & Skills → eigenes Interface → Teilen → Vorstellen.

## Die Aufgabe

Ein SO-101-Roboterarm legt drei Bauteile in die richtigen Faecher und prueft das Ergebnis per Kamera. Liegt die
Montageplatte schraeg oder ist ein Fach belegt, soll der Ablauf den Fehler erkennen, wenn moeglich korrigieren oder
begruendet stoppen.

## Installation

Voraussetzung: **Python 3.12** von python.org (macOS: der "universal2 installer", danach einmal
"Install Certificates.command" im Python-Ordner doppelklicken).

| System | Starten (erster Start richtet alles ein, 10-20 min) |
|---|---|
| Windows | `Start Windows.cmd` doppelklicken |
| macOS | `Start macOS.command` doppelklicken (beim ersten Mal: Rechtsklick → Oeffnen) |

Die Oberflaeche oeffnet sich im Browser unter http://127.0.0.1:8780. Mit dem **Team-Code** von eurem Zettel anmelden.

### Welcher Rechner trainiert was?

| Rechner | ACT | SmolVLA |
|---|---|---|
| Windows/Linux mit NVIDIA-Grafikkarte | gut | gut |
| MacBook mit Apple-Chip (M1-M4) | gut (1-3 h) | sehr langsam |
| ohne passende Grafikkarte | langsam | nicht sinnvoll |

Die Software erkennt das selbst und schlaegt die passende Methode vor.

## Euer Team-Ordner

Alles, was ihr baut, liegt in `teams/<euer-team>/` (Vorlage: `teams/_vorlage/`). **Lest `AGENTS.md`** dort,
oder lasst es euren Coding-Agent lesen. Nur dieser Ordner wird geteilt.

## Teilen

- **Code:** Knopf *Team-Ordner hochladen*. Er landet im Zweig `team/<euer-team>`. Ein Waechter uebernimmt
  automatisch nur euren Ordner nach `main` (alle 5 Minuten).
- **Modelle und Datensaetze:** Knopf *Modell veroeffentlichen*. Sie landen auf Hugging Face bei
  [RoboForge](https://huggingface.co/RoboForge), mit Teamname und Beschreibung.

## Sicherheit

Keine Armbewegung ohne Mensch vor Ort und Zustimmung (jede Bewegung wird im Harness-Fenster bestaetigt).
Nie 12 V an die Arme. Im Zweifel: **STOP** oben rechts.
