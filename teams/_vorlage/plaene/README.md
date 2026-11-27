# Eigene Aufnahmeplaene

Ein Aufnahmeplan sagt fuer jede Runde, **wo** ein Gegenstand stehen soll. Beispiel: `plaene/elektrodose.json` im
Programmordner (50 Runden, Dose an wechselnden Stellen im Halbring vor dem Arm).

Eigenen Plan anlegen: die Beispieldatei hierher kopieren, `id` aendern (gleich dem Dateinamen ohne `.json`),
dann `name`, `datensatz`, `objekt`, `bauteile` und `geometrie` (Groesse in cm, Radien um die Armbasis) anpassen.
Die Plattform uebernimmt den Plan automatisch; im Steuermodus erscheint er dann zur Aufnahme.

Tipp fuer den Coding-Agent: "Schreibe einen Aufnahmeplan fuer <Gegenstand>, <n> Runden, Radius 16-38 cm."
