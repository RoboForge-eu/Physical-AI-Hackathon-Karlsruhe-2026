"""Feinarbeit in schneller Schleife (ohne Sprachmodell): kleine kartesische Korrekturen, Kontakt ohne
Kraftsensor, Mess-Werkzeuge als gemeinsame Funktionen fuer Harness und Simulation.

  kartesisch.korrektur(soll, dx, dy, dz)  -> neue Gelenkziele (max. 5 mm je Schritt)
  kontakt.KontaktMelder                   -> Ereignisse 'angestossen', 'abgesackt', 'frei' aus Soll/Ist/Last
  werkzeuge.messen(bild, ...)             -> Versatz Merkmal -> Werkzeugpunkt in mm + Messbild
"""
