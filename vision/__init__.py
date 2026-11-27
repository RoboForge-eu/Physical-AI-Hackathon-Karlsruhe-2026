"""Mess-Werkzeuge (reine Bildverarbeitung mit OpenCV, kein Sprachmodell).

  marker.finden(bild, groesse_mm)        ArUco-Marker: Mitte, Ecken, Winkel in Pixeln, mm/Pixel, Lage in mm
  merkmale.konturen(bild) / linien(bild) / kreise(bild)   Kanten, Linien, runde Oeffnungen
  merkmale.abstand(a, b, mm_pro_px)      Abstand und Winkel zwischen zwei Merkmalen in px und mm
  zeichnen.messbild(bild, messungen, pfad)  Bild mit eingezeichneten Messungen speichern
  kalib.Kalibrierung                     Pixel -> mm in der Handgelenk-Kamera aus einem Marker bekannter Groesse

Alle Funktionen geben einfache Dicts/Listen zurueck (JSON-faehig), damit Skills, Agent und Tests sie gleich nutzen.
"""
