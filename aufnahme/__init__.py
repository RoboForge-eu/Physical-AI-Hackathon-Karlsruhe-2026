"""Planbasierte Aufnahmen: der Steuermodus fuehrt den Bediener anhand eines Aufnahmeplans durch Sessions,
Runden und einzelne Griffe.

  geometrie.py   Tisch, Halbring, Kartonplatzierungen erzeugen und pruefen
  plan.py        Plan-Definition laden (plaene/*.json), Plan anlegen (Platzierungen, Auftraege), Fortschritt
  maske.py       Startpose-Maske in der Wrist-Cam (Kanten erkennen, Regeln A/B)
  automatik.py   automatischer Aufnahmestart und -stopp

Plaene liegen als JSON in plaene/ (Definition). Ein angelegter Plan mit Platzierungen, Auftraegen und
Fortschritt liegt in ki_daten/aufnahmeplaene/<plan>/. Ein weiterer kompatibler Plan = weitere JSON-Datei.
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAENE = os.path.join(HERE, "plaene")
