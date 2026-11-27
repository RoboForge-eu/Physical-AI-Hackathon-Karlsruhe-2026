"""Mess-Werkzeug fuer Regelschleifen: Bild -> Versatz des Merkmals zum Werkzeugpunkt in mm (+ Messbild).

Gleiche Funktion im Harness (Kamerabild der echten Handgelenk-Kamera) und in der Simulation.
"""
import os, time
from vision import marker as M, merkmale as F, zeichnen as Z

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSBILDER = os.path.join(HERE, "ki_daten", "messbilder")
ZIELE = ("oeffnung", "marker", "kreis")


def messen(bild, ziel="oeffnung", kalib=None, groesse_mm=20.0, marker_id=None, pfad=None, name="messung"):
    """ziel: 'oeffnung' (runde dunkle Oeffnung), 'marker' (ArUco, optional marker_id), 'kreis' (Hough).
    Ohne Kalibrierung: nur Pixel und - ueber den Marker - mm im Bild (keine Werkzeugrichtung)."""
    if ziel not in ZIELE:
        raise ValueError(f"ziel muss eines von {ZIELE} sein")
    h, w = bild.shape[:2]
    marker = M.finden(bild, groesse_mm)
    mpp = marker[0]["mm_pro_px"] if marker else (kalib.mm_pro_px if kalib else None)
    kandidat = None
    zielpx = kalib.werkzeugpunkt if kalib else [w / 2, h / 2]
    def naechste(ks):     # das VLA hat das Teil grob hingebracht: das Merkmal nahe der Spitze ist gemeint
        return min(ks, key=lambda k: (k["mitte"][0] - zielpx[0]) ** 2 + (k["mitte"][1] - zielpx[1]) ** 2) if ks else None
    if ziel == "marker":
        ms = [m for m in marker if marker_id is None or m["id"] == int(marker_id)]
        kandidat = ms[0] if ms else None
    elif ziel == "oeffnung":
        kandidat = naechste([k for k in F.oeffnungen(bild, ausser=marker) if k["rundheit"] >= 0.75])
    else:
        kandidat = naechste(F.kreise(bild))
    out = {"gefunden": kandidat is not None, "ziel": ziel, "marker": marker, "mm_pro_px": mpp,
           "werkzeugpunkt_px": [round(v, 1) for v in zielpx], "kalibriert": kalib is not None}
    text = [f"{name}: {ziel}"]
    versatz = None
    if kandidat is not None:
        out["merkmal_px"] = kandidat["mitte"]
        a = F.abstand({"mitte": zielpx}, kandidat, mpp)
        out["abstand_px"] = a["abstand_px"]
        if mpp:
            out["abstand_mm"] = a["abstand_mm"]
        if kalib is not None:
            dx, dy = kalib.korrektur_mm(kandidat["mitte"])
            out["korrektur_mm"] = [round(dx, 2), round(dy, 2)]
            text.append(f"Korrektur dx {dx:+.2f} dy {dy:+.2f} mm")
        if "abstand_mm" in out:
            text.append(f"Abstand {out['abstand_mm']:.2f} mm")
        versatz = (kandidat["mitte"], zielpx, f"{out.get('abstand_mm', a['abstand_px']):.1f}")
    else:
        text.append("NICHT gefunden")
    pfad = pfad or os.path.join(MESSBILDER, time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}-{name}.jpg")
    img = Z.messbild(bild, marker, [kandidat] if kandidat else [], versatz, text, pfad)
    out["messbild"] = pfad
    out["_bild"] = img
    return out


def kalibrieren(messe_marker, korrigiere, schritt_mm, werkzeugpunkt, **kw):
    """Gemeinsamer Ablauf (Harness und Simulation): Marker messen, +x, zurueck, +y, zurueck.
    messe_marker() -> (pixel, mm_pro_px); korrigiere(dx, dy) faehrt klein (mm)."""
    from vision.kalib import Kalibrierung
    if abs(schritt_mm) > 5:
        raise ValueError("schritt_mm hoechstens 5")
    p0, mpp = messe_marker()
    korrigiere(schritt_mm, 0)
    try:
        px, _ = messe_marker()
    finally:
        korrigiere(-schritt_mm, 0)
    korrigiere(0, schritt_mm)
    try:
        py, _ = messe_marker()
    finally:
        korrigiere(0, -schritt_mm)
    return Kalibrierung.aus_testbewegungen(p0, px, py, schritt_mm, werkzeugpunkt, mm_pro_px=mpp, **kw)
