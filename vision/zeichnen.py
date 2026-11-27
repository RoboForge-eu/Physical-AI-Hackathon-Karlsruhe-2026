"""Messbild: Bild mit eingezeichneten Messungen, damit Mensch und Sprachmodell sehen, was gemessen wurde."""
import base64, os
import cv2
import numpy as np

GRUEN, ROT, GELB, BLAU = (60, 200, 60), (40, 40, 230), (0, 220, 255), (230, 140, 40)


def messbild(bild, marker=(), merkmale=(), versatz=None, text=(), pfad=None):
    """marker: aus marker.finden; merkmale: Dicts mit 'mitte' (und 'radius_px' / 'rahmen' / 'start','ende');
    versatz: (von_xy, nach_xy, beschriftung); text: Zeilen oben links. Gibt das Bild zurueck, speichert es bei pfad."""
    img = bild.copy() if bild.ndim == 3 else cv2.cvtColor(bild, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    cv2.drawMarker(img, (w // 2, h // 2), BLAU, cv2.MARKER_CROSS, 24, 1)          # Bildmitte = Werkzeugachse
    for m in marker:
        pts = np.array(m["ecken"], np.int32)
        cv2.polylines(img, [pts], True, GRUEN, 2)
        c = tuple(int(v) for v in m["mitte"])
        cv2.circle(img, c, 3, GRUEN, -1)
        lab = f"id {m['id']}" + (f" {m['mitte_mm'][0]:+.1f}/{m['mitte_mm'][1]:+.1f} mm" if "mitte_mm" in m else "")
        cv2.putText(img, lab, (c[0] + 6, c[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, GRUEN, 1, cv2.LINE_AA)
    for f in merkmale:
        c = tuple(int(v) for v in f["mitte"])
        if "radius_px" in f:
            cv2.circle(img, c, int(f["radius_px"]), GELB, 2)
        if "rahmen" in f:
            x, y, rw, rh = f["rahmen"]
            cv2.rectangle(img, (x, y), (x + rw, y + rh), GELB, 1)
        if "start" in f:
            cv2.line(img, tuple(f["start"]), tuple(f["ende"]), GELB, 2)
        cv2.circle(img, c, 3, GELB, -1)
    if versatz:
        a, b, lab = versatz
        a, b = tuple(int(v) for v in a), tuple(int(v) for v in b)
        cv2.arrowedLine(img, a, b, ROT, 2, tipLength=0.15)
        cv2.putText(img, lab, (b[0] + 6, b[1] + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ROT, 1, cv2.LINE_AA)
    for k, t in enumerate(text):
        cv2.putText(img, str(t), (8, 18 + 18 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, str(t), (8, 18 + 18 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    if pfad:
        os.makedirs(os.path.dirname(os.path.abspath(pfad)), exist_ok=True)
        cv2.imwrite(pfad, img)
    return img


def jpeg_base64(img, breite=480):
    h, w = img.shape[:2]
    if w > breite:
        img = cv2.resize(img, (breite, int(h * breite / w)))
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(jpg.tobytes()).decode()
