"""Kanten, Linien, Konturen, runde Oeffnungen; Abstand/Winkel zwischen zwei Merkmalen.

Merkmal = Dict mit mindestens "mitte": [x, y] (Pixel); Linien zusaetzlich "winkel_grad".
"""
import math
import cv2
import numpy as np


def _gray(bild):
    g = bild if bild.ndim == 2 else cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (5, 5), 0)


def kanten(bild, lo=50, hi=150):
    return cv2.Canny(_gray(bild), lo, hi)


def konturen(bild, min_flaeche=80, dunkel=True, max_anzahl=10, oeffnen_px=0, adaptiv=False):
    """Geschlossene Flaechen (dunkel auf hell, z. B. Buchsen-Oeffnung) - groesste zuerst.
    oeffnen_px: duenne Dinge (Stift, Kabel, Greiferfinger) vorher wegfiltern (morphologisches Oeffnen)."""
    g = _gray(bild)
    art = cv2.THRESH_BINARY_INV if dunkel else cv2.THRESH_BINARY
    if adaptiv:                                     # gegen Schatten/ungleiches Licht: Schwelle je Umgebung
        th = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, art, 61, 25)
    else:
        _, th = cv2.threshold(g, 0, 255, art + cv2.THRESH_OTSU)
    if oeffnen_px:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(oeffnen_px), int(oeffnen_px)))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, k)
    cs, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        a = cv2.contourArea(c)
        if a < min_flaeche:
            continue
        M = cv2.moments(c)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        per = cv2.arcLength(c, True)
        out.append({"mitte": [round(M["m10"] / M["m00"], 2), round(M["m01"] / M["m00"], 2)],
                    "flaeche_px": round(a, 1), "breite_px": round(max(rw, rh), 1), "hoehe_px": round(min(rw, rh), 1),
                    "winkel_grad": round(ang, 1), "rundheit": round(4 * math.pi * a / per ** 2, 3) if per else 0,
                    "rahmen": [int(v) for v in cv2.boundingRect(c)]})
    return sorted(out, key=lambda m: -m["flaeche_px"])[:max_anzahl]


def kreise(bild, min_r=4, max_r=120):
    """Runde Oeffnungen per Hough-Kreisen."""
    c = cv2.HoughCircles(_gray(bild), cv2.HOUGH_GRADIENT, dp=1.2, minDist=2 * min_r, param1=120, param2=25,
                         minRadius=min_r, maxRadius=max_r)
    if c is None:
        return []
    return [{"mitte": [round(float(x), 2), round(float(y), 2)], "radius_px": round(float(r), 2)} for x, y, r in c[0]]


def linien(bild, min_laenge=30, max_anzahl=20):
    """Gerade Kanten (z. B. Kabelende, Rand einer Halterung) - laengste zuerst."""
    ls = cv2.HoughLinesP(kanten(bild), 1, np.pi / 180, 40, minLineLength=min_laenge, maxLineGap=5)
    out = []
    for x1, y1, x2, y2 in ([] if ls is None else ls[:, 0]):
        out.append({"start": [int(x1), int(y1)], "ende": [int(x2), int(y2)],
                    "mitte": [(x1 + x2) / 2, (y1 + y2) / 2], "laenge_px": round(math.hypot(x2 - x1, y2 - y1), 1),
                    "winkel_grad": round(math.degrees(math.atan2(y2 - y1, x2 - x1)), 1)})
    return sorted(out, key=lambda l: -l["laenge_px"])[:max_anzahl]


def abstand(a, b, mm_pro_px=None):
    """Versatz b - a: dx, dy, Abstand (px und, wenn bekannt, mm) und Winkelunterschied (wenn beide einen haben)."""
    dx, dy = b["mitte"][0] - a["mitte"][0], b["mitte"][1] - a["mitte"][1]
    out = {"dx_px": round(dx, 2), "dy_px": round(dy, 2), "abstand_px": round(math.hypot(dx, dy), 2),
           "richtung_grad": round(math.degrees(math.atan2(dy, dx)), 1)}
    if "winkel_grad" in a and "winkel_grad" in b:
        d = (b["winkel_grad"] - a["winkel_grad"] + 180) % 360 - 180
        out["winkel_diff_grad"] = round(d, 2)
    if mm_pro_px:
        out.update(dx_mm=round(dx * mm_pro_px, 2), dy_mm=round(dy * mm_pro_px, 2),
                   abstand_mm=round(math.hypot(dx, dy) * mm_pro_px, 2))
    return out


def oeffnungen(bild, min_flaeche=30, max_flaeche=3000, min_rundheit=0.6, ausser=(), oeffnen_px=11):
    """Runde dunkle Oeffnungen (Loch, Buchse). 'ausser': Marker aus marker.finden - deren Flaeche wird ignoriert."""
    out = []
    for k in konturen(bild, min_flaeche=min_flaeche, max_anzahl=50, oeffnen_px=oeffnen_px, adaptiv=True):
        if k["flaeche_px"] > max_flaeche or k["rundheit"] < min_rundheit:
            continue
        x, y = k["mitte"]
        if any(cv2.pointPolygonTest(np.array(m["ecken"], np.float32), (float(x), float(y)), True) > -8 for m in ausser):
            continue
        out.append(k)
    return out
