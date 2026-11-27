"""RoboForge KI: Aufnahme, Training und Ausfuehren von Robotermodellen.

Aufbau (von unten nach oben, damit spaeter ein Agent darauf aufsetzen kann):
  episodes  - eigenes, einfaches Aufnahmeformat (laeuft im ROS-Prozess, ohne LeRobot)
  methods   - Steckplaetze fuer Lernverfahren (ACT, SmolVLA, spaeter eigene)
  skills    - benannte Befehle mit Beschreibung und Parametern; Oberflaeche, Fernzugriff
              und spaeter ein Agent rufen dieselben Befehle auf
  jobs      - Training als eigener Prozess in der KI-Umgebung (ki-env), Warteschlange
  driver    - KI-Fahrer: laedt ein Modell und liefert Gelenkziele (eigener Prozess)

Sicherheit bleibt immer im Worker (Grenzen, Tempo, Stop, Ablegen), egal wer Ziele liefert.
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "ki_daten")
DATASETS = os.path.join(DATA, "datensaetze")
MODELS = os.path.join(DATA, "modelle")
from .geraet import ki_python as _ki_python
KI_PYTHON = _ki_python(HERE)
