# Marker und Kamera-Kalibrierung – Infos zum Einbauen

## Marker (ArUco, keine AprilTags)
- Typ: **ArUco, Wörterbuch `DICT_4X4_50`** (OpenCV `cv2.aruco`, ab 4.7 `ArucoDetector`). IDs 0–49 möglich.
- Erkennung im Code: `vision/marker.py` (`DICT = "DICT_4X4_50"`, `finden(bild)` → Liste mit `id`, Ecken).
- Bisher benutzt (Roboterbasis, `vision/druck/basis_marker.pdf`):
  - **ID 10**: schwarz 40 mm, Zuschnitt 45 mm, oben auf die feste Basis.
  - **ID 11**: schwarz 60 mm, Zuschnitt 70 mm, senkrecht hinten auf die Basis.
- Neu: `vision/druck/marker_bogen.pdf` mit 12 großen Markern, schwarz **60 mm**, Zuschnitt 70 mm, je 4× **ID 11, 12, 13**.
  Andere IDs: `python vision/druck/marker_bogen.py 14 15 16`.
- **Wichtig:** Die **Kantenlänge des schwarzen Quadrats (60 mm)** muss die Software kennen. Daraus berechnet sie
  Abstand und Lage. Der weiße Rand zählt nicht mit.
- Die Software muss die **ID kennen**: Der Detektor findet zwar alle IDs aus `DICT_4X4_50` von selbst, nichts wird
  „eintrainiert“. Was eine ID bedeutet (welcher Arm, wo sie klebt, wie groß sie ist), steht aber in der
  Konfiguration. In `vision/karton.py` sind das die Einträge `cfg["marker"][<id>]` mit `mm` (Kantenlänge) und Lage.
  Eine neue ID wird also erkannt, aber erst benutzt, wenn sie dort eingetragen ist.
- Dieselbe ID zweimal im selben Kamerabild ist schlecht: Die Software kann sie dann nicht auseinanderhalten.
  Pro Station bzw. Arm also verschiedene IDs.
- Drucken: A4, **100 % / „Tatsächliche Größe“**, matt (glänzend spiegelt). Die 100-mm-Linie nachmessen.

## Kamera-Kalibrierung (Schachbrett)
- Vorlage: `vision/druck/schachbrett.pdf` (Skript `schachbrett.py`), A4 quer.
- **10 × 7 Felder = 9 × 6 innere Ecken**, Feld **25 mm**. Flach auf Pappe kleben.
- Code: `vision/kamerakalib.py`: `MUSTER = (9, 6)`, `FELD_MM = 25.0`, Erkennung `cv2.findChessboardCornersSB`,
  dann `cv2.calibrateCamera`.
- Ablauf: Brett vor die Kamera halten und langsam bewegen (schräg, nah, fern, in alle Bildecken), etwa 45 s.
  Gesammelt werden verschiedene Bilder mit ganz erkanntem Brett.
- Ergebnis: `calibration/kamera_<arm>_<kamera>.json` mit `K` (3×3), `dist`, `groesse` [w, h], `fehler_px`, `bilder`.
  Ein `fehler_px` unter ca. 0,5 ist gut.
- Nur nötig je Kameramodell und Auflösung. Ändert sich die Kamera oder ihre Auflösung, neu kalibrieren.
