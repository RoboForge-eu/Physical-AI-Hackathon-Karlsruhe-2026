"""ArUco-Marker finden (OpenCV >= 4.7, cv2.aruco.ArucoDetector). Standard-Woerterbuch DICT_4X4_50.

finden(bild, groesse_mm=None) -> [{"id", "mitte": [x, y], "ecken": [[x, y]*4], "winkel_grad", "seite_px",
                                   "mm_pro_px", "mitte_mm": [x, y] (Bildmitte = 0, x nach rechts, y nach unten)}]
"""
import math
import cv2
import numpy as np

DICT = "DICT_4X4_50"


def _detector(dictionary=DICT):
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(d, p)


def erzeugen(marker_id, seite_px=200, rand_px=40, dictionary=DICT):
    """Markerbild (weiss umrandet) zum Ausdrucken oder fuer die Simulation."""
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
    m = cv2.aruco.generateImageMarker(d, int(marker_id), int(seite_px))
    return cv2.copyMakeBorder(m, rand_px, rand_px, rand_px, rand_px, cv2.BORDER_CONSTANT, value=255)


def finden(bild, groesse_mm=None, dictionary=DICT):
    gray = bild if bild.ndim == 2 else cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _detector(dictionary).detectMarkers(gray)
    out = []
    if ids is None:
        return out
    h, w = gray.shape[:2]
    for c, i in zip(corners, ids.flatten()):
        c = c.reshape(4, 2)
        mitte = c.mean(axis=0)
        seite = float(np.mean([np.linalg.norm(c[k] - c[(k + 1) % 4]) for k in range(4)]))
        top = c[1] - c[0]
        m = {"id": int(i), "mitte": [round(float(mitte[0]), 2), round(float(mitte[1]), 2)],
             "ecken": [[round(float(x), 2), round(float(y), 2)] for x, y in c],
             "winkel_grad": round(math.degrees(math.atan2(top[1], top[0])), 2), "seite_px": round(seite, 2)}
        if groesse_mm:
            mpp = float(groesse_mm) / seite
            m["mm_pro_px"] = round(mpp, 5)
            m["mitte_mm"] = [round((mitte[0] - w / 2) * mpp, 2), round((mitte[1] - h / 2) * mpp, 2)]
        out.append(m)
    return sorted(out, key=lambda m: m["id"])
