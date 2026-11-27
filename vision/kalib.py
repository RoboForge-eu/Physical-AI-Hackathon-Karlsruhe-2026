"""Pixel -> Millimeter -> Bewegung fuer die Handgelenk-Kamera.

Einfachste robuste Kalibrierung ohne Kameramodell: zwei kleine Testbewegungen.
  1. Merkmal (Marker) messen -> p0 (Pixel)
  2. Werkzeug +s mm in x fahren, messen -> px;  zurueck
  3. Werkzeug +s mm in y fahren, messen -> py;  zurueck
  J = [(px - p0)/s, (py - p0)/s]  (2x2, Pixel je mm Werkzeugbewegung)
Damit ein Merkmal am Zielpixel z (wo die Werkzeugspitze hinzeigt) liegt, faehrt man m = J^-1 (z - p).
J gilt fuer die Hoehe, in der kalibriert wurde (Schwebehoehe ueber dem Teil); dort wird auch ausgerichtet.

Zielpixel ('werkzeugpunkt'): am echten Arm einmal bestimmen (Stiftspitze genau auf die Markermitte setzen,
auf Schwebehoehe anheben, Markermitte messen = Zielpixel). In der Simulation ist es aus dem Kameramodell bekannt.

Datei: calibration/handkamera_<arm>.json  {"J": [[..],[..]], "werkzeugpunkt": [x, y], "hoehe_mm": .., "mm_pro_px": ..}
"""
import json, os
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALDIR = os.path.join(HERE, "calibration")


class Kalibrierung:
    def __init__(self, J, werkzeugpunkt, hoehe_mm=None, mm_pro_px=None):
        self.J = np.asarray(J, float).reshape(2, 2)
        self.werkzeugpunkt = [float(v) for v in werkzeugpunkt]
        self.hoehe_mm, self.mm_pro_px = hoehe_mm, mm_pro_px

    @classmethod
    def aus_testbewegungen(cls, p0, px, py, schritt_mm, werkzeugpunkt, **kw):
        p0, px, py = (np.asarray(v, float) for v in (p0, px, py))
        J = np.column_stack([(px - p0) / schritt_mm, (py - p0) / schritt_mm])
        if abs(np.linalg.det(J)) < 1e-3:
            raise ValueError("Testbewegungen zu klein oder Merkmal nicht bewegt - Kalibrierung unbrauchbar")
        return cls(J, werkzeugpunkt, **kw)

    def korrektur_mm(self, merkmal_px):
        """Werkzeugbewegung (dx, dy) in mm, die das Merkmal auf den Werkzeugpunkt bringt."""
        d = np.asarray(self.werkzeugpunkt) - np.asarray(merkmal_px, float)
        m = np.linalg.solve(self.J, d)
        return float(m[0]), float(m[1])

    def to_dict(self):
        return {"J": self.J.round(5).tolist(), "werkzeugpunkt": [round(v, 2) for v in self.werkzeugpunkt],
                "hoehe_mm": self.hoehe_mm, "mm_pro_px": self.mm_pro_px}

    def speichern(self, arm, caldir=None):
        os.makedirs(caldir or CALDIR, exist_ok=True)
        path = os.path.join(caldir or CALDIR, f"handkamera_{arm}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def laden(cls, arm, caldir=None):
        path = os.path.join(caldir or CALDIR, f"handkamera_{arm}.json")
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        return cls(d["J"], d["werkzeugpunkt"], d.get("hoehe_mm"), d.get("mm_pro_px"))
