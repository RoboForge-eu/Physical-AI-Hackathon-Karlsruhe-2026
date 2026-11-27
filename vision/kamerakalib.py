"""Kamera-Kalibrierung (Bildwinkel und Weitwinkel-Verzerrung) mit einem gedruckten Schachbrett.

Ablauf: Schachbrett (vision/druck/schachbrett.pdf, 9 x 6 innere Ecken, 25 mm Felder) vor die Kamera halten und
langsam bewegen - schraeg, nah, fern, in alle Bildecken. Gesammelt werden Bilder, in denen das Brett ganz
erkannt wird und die sich von den bisherigen unterscheiden. Danach cv2.calibrateCamera.

Datei: calibration/kamera_<arm>_<kamera>.json  {"K": 3x3, "dist": [..], "groesse": [w, h], "fehler_px": .., "bilder": n}
"""
import json, os, time
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALDIR = os.path.join(HERE, "calibration")
MUSTER = (9, 6)                      # innere Ecken
FELD_MM = 25.0


def pfad(arm, kamera):
    return os.path.join(CALDIR, f"kamera_{arm}_{kamera}.json")


def laden(arm, kamera):
    try:
        with open(pfad(arm, kamera), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ecken(bild, cv2):
    """Schachbrettecken (N x 2, Pixel) oder None."""
    gray = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY) if bild.ndim == 3 else bild
    ok, c = cv2.findChessboardCornersSB(gray, MUSTER, flags=cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE)
    if not ok:
        return None
    return c.reshape(-1, 2)


def neu_genug(c, gesammelt, w):
    """Brett liegt anders als in allen bisherigen Bildern (Mitte, Groesse oder Neigung)."""
    m, s = c.mean(axis=0), np.ptp(c, axis=0)
    for g in gesammelt:
        if np.linalg.norm(m - g.mean(axis=0)) < 0.06 * w and np.all(np.abs(s - np.ptp(g, axis=0)) < 0.06 * w):
            return False
    return True


def rechnen(gesammelt, groesse, cv2):
    obj = np.zeros((MUSTER[0] * MUSTER[1], 3), np.float32)
    obj[:, :2] = np.mgrid[0:MUSTER[0], 0:MUSTER[1]].T.reshape(-1, 2) * FELD_MM
    w, h = groesse
    rms, K, dist, _, _ = cv2.calibrateCamera([obj] * len(gesammelt), [g.astype(np.float32) for g in gesammelt],
                                             (w, h), None, None)
    return {"K": K.round(3).tolist(), "dist": dist.ravel().round(6).tolist(), "groesse": [w, h],
            "fehler_px": round(float(rms), 3), "bilder": len(gesammelt),
            "hfov": round(float(np.degrees(2 * np.arctan(w / 2 / K[0, 0]))), 1),
            "datum": time.strftime("%Y-%m-%d %H:%M:%S")}


def sammeln(bild_holen, cv2, sekunden=45, ziel=20, takt=0.4, log=print):
    """Bilder sammeln. bild_holen() -> Bild oder None. Gibt (liste der ecken, groesse) zurueck."""
    gesammelt, groesse = [], None
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende and len(gesammelt) < ziel:
        img = bild_holen()
        if img is not None:
            groesse = (img.shape[1], img.shape[0])
            c = ecken(img, cv2)
            if c is not None and neu_genug(c, gesammelt, img.shape[1]):
                gesammelt.append(c)
                log(f"Bild {len(gesammelt)} von {ziel}")
        time.sleep(takt)
    return gesammelt, groesse


def speichern(arm, kamera, daten):
    os.makedirs(CALDIR, exist_ok=True)
    with open(pfad(arm, kamera), "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=1)


def entzerren(bild, kalib, cv2):
    """Bild ohne Verzerrung und die passende Kameramatrix (auf die Bildgroesse umgerechnet)."""
    h, w = bild.shape[:2]
    K = np.array(kalib["K"], float)
    gw, gh = kalib["groesse"]
    K[0] *= w / gw
    K[1] *= h / gh
    return cv2.undistort(bild, K, np.array(kalib["dist"], float)), K
