"""Maske fuer die Startpose in der Wrist-Cam: zwei Fuehrungen an den Oberkanten der langen Kartonwaende.

Regel A (vorne): Die vordere Laengskante liegt an der Greiferspitze (Spitzen an der Kante oder knapp darunter),
                 ihre Mitte horizontal hoechstens +-vorne_dx (Anteil Bildbreite) neben der Spitze.
Regel B (hinten): Die hintere Laengskante liegt nahe dem oberen Bildrand (hinten_min..hinten_max der Bildhoehe)
                 und ist vollstaendig im Bild.
Beide:           Kanten ungefaehr waagerecht (+-winkel_tol Grad).
Regel C (von oben): Ziel ist, den ganzen Karton von oben zu sehen und hineinzuschauen. Darum sind die Baender
                 grosszuegig, und zwischen Hinter- und Vorderkante muessen mindestens 'draufsicht_min' der
                 Bildhoehe liegen (flach/seitlich geschaut wird der Karton gestaucht).
Die Hinterkante wird ueber fast die ganze Bildbreite gesucht, damit Teile im Karton sie nicht verdecken.

Erkannt wird mit Kantenfilter + Hough-Geraden, nur ungefaehr waagerechte Stuecke, zu Kanten zusammengefasst.
Gegen die Weitwinkelverzerrung wird jede Kante nur im mittleren Bereich ihres Verlaufs bewertet.
Nur die Oberflaeche bekommt Einblendungen - die aufgezeichneten Bilder bleiben unveraendert.
"""
import math

DEFAULT = {"tip_x": 0.47, "tip_y": 0.72, "vorne_ueber": 0.25, "vorne_unter": 0.04, "vorne_dx": 0.18,
           "hinten_min": 0.02, "hinten_max": 0.38, "winkel_tol": 12, "draufsicht_min": 0.30,
           "kante_min": 0.20, "pappe_min": 0.35, "parallel_tol": 8,
           "flaeche_min": 0.40}


def _edge_map(gray, cv2):
    """Waagerechte Kanten (Helligkeitswechsel von oben nach unten), als Ja/Nein-Bild."""
    # Lokaler Kontrast (CLAHE): schwache Kanten Pappe-an-Pappe (fast leerer Karton) gegen starke Kanten
    # von Teilen und Greiferfingern sichtbar machen
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    mag = abs(gy)
    thr = max(25.0, float(mag.max()) * 0.18)
    return (mag > thr) & (abs(gy) > 1.5 * abs(gx))


def _profile(edges, x0, x1, r0, r1):
    """Anteil der Spalten im Band [x0,x1), die in Zeile r (+-1) eine waagerechte Kante haben."""
    import numpy as np
    h = edges.shape[0]
    band = edges[:, x0:x1]
    near = band.copy()
    for k in range(1, 4):                       # +-3 Zeilen: Kanten sind durch das Weitwinkelobjektiv gebogen
        near[k:] |= band[:-k]
        near[:-k] |= band[k:]
    frac = near.mean(axis=1)
    return [(r, float(frac[r])) for r in range(max(0, r0), min(h, r1))]


def _edge_at(edges, row, x0, x1, tol=4, max_gap=0.05):
    """Kante um Zeile 'row' im Bereich x0..x1 genauer vermessen: Neigung aus linker/rechter Haelfte,
    Ausdehnung durch Verfolgen nach links und rechts."""
    import numpy as np
    h, w = edges.shape

    def row_in(xa, xb, r):
        best, br = -1, r
        for rr in range(max(0, r - tol), min(h, r + tol + 1)):
            c = edges[rr, xa:xb].mean() if xb > xa else 0
            if c > best:
                best, br = c, rr
        return br, best

    mid = (x0 + x1) // 2
    rl, cl = row_in(x0, mid, row)
    rr, cr = row_in(mid, x1, row)
    xl, xr = (x0 + mid) / 2, (mid + x1) / 2
    winkel = math.degrees(math.atan2(rr - rl, xr - xl)) if cl > 0.2 and cr > 0.2 else 0.0
    # Ausdehnung: entlang der Kante weiterlaufen, bis eine Luecke von 5 % der Breite kommt
    def follow(x, step):
        r, gap, last = row, 0, x
        while 0 <= x < w and gap < max_gap * w:
            col = edges[max(0, r - tol):min(h, r + tol + 1), x]
            if col.any():
                r = max(0, r - tol) + int(np.argmax(col))
                gap, last = 0, x
            else:
                gap += 1
            x += step
        return last
    return {"y": row / h, "winkel": winkel, "x0": follow(mid, -1) / w, "x1": follow(mid, 1) / w,
            "deckung": (cl + cr) / 2}


DREHUNGEN = (0, -6, 6, -12, 12)     # Karton darf im Bild gedreht liegen: so viele Grad probieren


def detect(frame, cfg=None, cv2=None):
    """Bewertet ein Wrist-Bild (BGR). Liegt der Karton schraeg im Bild, wird das Bild um die Greiferspitze
    gedreht nachgeprueft (DREHUNGEN). Gibt dict mit vorne/hinten (Kante oder None), ok_a/b/c, ok, werte."""
    if cv2 is None:
        import cv2
    import numpy as np
    c = dict(DEFAULT, **(cfg or {}))
    h, w = frame.shape[:2]
    cx, cy = c["tip_x"] * w, c["tip_y"] * h
    first = None
    for ang in DREHUNGEN:
        if ang:
            M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
            img = cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
        else:
            img = frame
        res = _detect_once(img, c, cv2)
        if ang:
            Mi = cv2.invertAffineTransform(M)
            for g in (res["vorne"], res["hinten"]):
                if g is None:
                    continue
                xm, ym = (g["x0"] + g["x1"]) / 2, g["y"]
                t = math.tan(math.radians(g["winkel"]))
                pts = []
                for x in (g["x0"], g["x1"]):
                    px, py = x * w, (ym + (x - xm) * t * w / h) * h
                    q = Mi @ np.array([px, py, 1.0])
                    pts.append((q[0] / w, q[1] / h))
                g["pa"], g["pb"] = pts
            res["werte"]["drehung"] = ang
        if res["ok"]:
            return res
        first = first or res
    return first


def _cardboard(small, cv2):
    """Ja/Nein-Bild: nicht weisser Tisch (Karton oder Inhalt). Die Kamera hat einen Farbstich, darum nur
    ueber die Helligkeit: der weisse Tisch ist deutlich heller als Pappe und Teile."""
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return gray < 180


def _plausible(g, pappe, below, c):
    """Kante gehoert zum Karton: lang genug und auf der Kartonseite (unter Hinterkante / ueber Vorderkante)
    liegt ueberwiegend Pappe oder Inhalt - nicht weisser Tisch."""
    h, w = pappe.shape
    if g is None or g["x1"] - g["x0"] < c["kante_min"]:
        return False
    x0, x1 = int(g["x0"] * w), int(g["x1"] * w)
    y = int(g["y"] * h)
    d = max(4, int(0.06 * h))
    ys = slice(y + 3, min(h, y + 3 + d)) if below else slice(max(0, y - 3 - d), max(1, y - 3))
    region = pappe[ys, x0:x1]
    return region.size > 0 and float(region.mean()) >= c["pappe_min"]


def _detect_once(frame, c, cv2):
    small = cv2.resize(frame, (640, int(640 * frame.shape[0] / frame.shape[1])))
    pappe = _cardboard(small, cv2)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = _edge_map(gray, cv2)
    h, w = edges.shape
    tx, ty = c["tip_x"], c["tip_y"]
    # vorne: im Band um die Greiferspitze (ohne die Greiferfinger selbst: oberhalb der Spitze suchen)
    bx0, bx1 = int((tx - 0.22) * w), int((tx + 0.22) * w)
    prof = _profile(edges, bx0, bx1, int((ty - c["vorne_ueber"] - 0.03) * h), int((ty + c["vorne_unter"] + 0.02) * h))
    cand = [(r, f) for r, f in prof if f >= 0.33]
    front = None
    if cand:
        for r, _f in sorted(cand, key=lambda rf: -rf[1]):        # kraeftigste plausible Kante im Band
            g = _edge_at(edges, r, bx0, bx1, max_gap=0.15)       # Greiferfinger verdecken die Kante teilweise
            if _plausible(g, pappe, False, c):
                front = g
                break
    # hinten: erste kraeftige Kante von oben im mittleren Bereich
    # Weitwinkel biegt die Kante: Zeile im fast geraden Mittelteil suchen, Laenge per Verfolgen messen.
    # Teile im Karton verdecken die Mitte manchmal: deshalb links und rechts der Mitte getrennt.
    back = None
    for r in range(int(0.02 * h) + 2, int((c["hinten_max"] + 0.04) * h)):   # oberste Zeilen = Bildrand
        for xa, xb in ((0.30, 0.70), (0.15, 0.45), (0.55, 0.85)):
            cov = _profile(edges, int(xa * w), int(xb * w), r, r + 1)
            if cov and cov[0][1] >= 0.45:
                g = _edge_at(edges, r, int(xa * w), int(xb * w), max_gap=0.08)
                if _plausible(g, pappe, True, c):
                    back = g
                    break
        if back is not None:
            break
    werte = {}
    ok_a = ok_b = False
    if front is not None:
        xm = (front["x0"] + front["x1"]) / 2
        werte.update(vorne_y=round(front["y"], 3), vorne_dx=round(xm - tx, 3), vorne_winkel=round(front["winkel"], 1))
        ok_a = (ty - c["vorne_ueber"] <= front["y"] <= ty + c["vorne_unter"] and abs(xm - tx) <= c["vorne_dx"]
                and abs(front["winkel"]) <= c["winkel_tol"])
    if back is not None:
        werte.update(hinten_y=round(back["y"], 3), hinten_winkel=round(back["winkel"], 1))
        ok_b = (c["hinten_min"] <= back["y"] <= c["hinten_max"] and abs(back["winkel"]) <= c["winkel_tol"])
    # Flaeche: zwischen den Kanten muss ein Karton liegen, nicht nur ein einzelnes Teil auf dem Tisch
    dunkel = _cardboard(small, cv2)[:int(c["tip_y"] * h)]
    flaeche = float(dunkel.mean()) if dunkel.size else 0.0
    werte["flaeche"] = round(flaeche, 3)
    ok_c = (front is not None and back is not None and front["y"] - back["y"] >= c["draufsicht_min"]
            and abs(front["winkel"] - back["winkel"]) <= c["parallel_tol"]   # Kanten eines Kartons: parallel
            and flaeche >= c["flaeche_min"])
    if front is not None and back is not None:
        werte["abstand"] = round(front["y"] - back["y"], 3)
    return {"vorne": front, "hinten": back, "ok_a": ok_a, "ok_b": ok_b, "ok_c": ok_c, "ok": ok_a and ok_b and ok_c,
            "werte": werte}


def draw(img, res, cfg=None, cv2=None, greifer_zu=None, countdown=None):
    """Einblendung fuer die Oberflaeche (Kopie!), als Einstellhilfe fuer den Bediener:
    - Bereiche, in denen keine Kante liegen soll, sind ausgegraut (hell bleiben nur die beiden Zielbaender),
    - feste Fuehrungslinien wie in der Vorlage: Kreuz im oberen Band (Hinterkante) und Kreuz an der
      Greiferspitze (Vorderkante) mit senkrechter Mittellinie durch die Spitze,
    - die erkannten Kanten als Linien, jede Regel unabhaengig rot oder gruen."""
    if cv2 is None:
        import cv2
    import numpy as np
    c = dict(DEFAULT, **(cfg or {}))
    out = img.copy()
    h, w = out.shape[:2]
    green, red, white = (60, 190, 80), (40, 40, 230), (235, 235, 235)
    col_a = green if res["ok_a"] else red
    col_b = green if res["ok_b"] else red
    tx, ty = int(c["tip_x"] * w), int(c["tip_y"] * h)
    b0, b1 = int(c["hinten_min"] * h), int(c["hinten_max"] * h)
    a0, a1 = int((c["tip_y"] - c["vorne_ueber"]) * h), int((c["tip_y"] + c["vorne_unter"]) * h)
    # ausgrauen: alles ausser den beiden Zielbaendern
    keep = np.zeros((h, w), bool)
    keep[max(0, b0 - 4):b1 + 4, :] = True
    keep[max(0, a0 - 4):a1 + 4, :] = True
    grey = (out * 0.45 + 70).astype(out.dtype)
    out[~keep] = grey[~keep]
    # Zielbaender mit Kreuz (Fuehrung)
    for (y0, y1, col) in ((b0, b1, col_b), (a0, a1, col_a)):
        cv2.rectangle(out, (0, y0), (w - 1, y1), col, 2)
        cv2.line(out, (int(0.02 * w), y0), (int(0.98 * w), y1), col, 1, cv2.LINE_AA)
        cv2.line(out, (int(0.02 * w), y1), (int(0.98 * w), y0), col, 1, cv2.LINE_AA)
    # Greiferspitze: Mittellinie und erlaubte seitliche Abweichung der Kantenmitte
    dx = int(c["vorne_dx"] * w)
    cv2.line(out, (tx, a0 - int(0.05 * h)), (tx, h - 1), col_a, 2, cv2.LINE_AA)
    cv2.line(out, (tx - dx, a0), (tx - dx, a1), col_a, 1)
    cv2.line(out, (tx + dx, a0), (tx + dx, a1), col_a, 1)
    cv2.drawMarker(out, (tx, ty), white, cv2.MARKER_CROSS, 18, 2)
    # erkannte Kanten
    for g, col in ((res.get("vorne"), col_a), (res.get("hinten"), col_b)):
        if g is not None:
            xm, ym = (g["x0"] + g["x1"]) / 2, g["y"]
            t = math.tan(math.radians(g["winkel"]))
            pa = (int(g["x0"] * w), int((ym + (g["x0"] - xm) * t * w / h) * h))
            pb = (int(g["x1"] * w), int((ym + (g["x1"] - xm) * t * w / h) * h))
            if "pa" in g:                                  # im gedrehten Bild gefunden: zurueckgedreht zeichnen
                pa = (int(g["pa"][0] * w), int(g["pa"][1] * h))
                pb = (int(g["pb"][0] * w), int(g["pb"][1] * h))
            cv2.line(out, pa, pb, col, 4, cv2.LINE_AA)
    fs = max(0.6, w / 900)                              # Schrift mit der Bildbreite skalieren
    txt = lambda s, y, col: cv2.putText(out, s, (10, y), cv2.FONT_HERSHEY_SIMPLEX, fs, col, max(2, int(fs * 2)),
                                        cv2.LINE_AA)
    ok_c = res.get("ok_c", True)
    step = int(34 * fs)                                 # Statuszeilen untereinander unten links (keine Ueberlappung)
    txt("Hinterkante oben im Bild " + ("OK" if res["ok_b"] else "--"), h - 3 * step + 8, col_b)
    txt("Vorderkante nahe Greiferspitze " + ("OK" if res["ok_a"] else "--"), h - 2 * step + 8, col_a)
    txt("Ganzer Karton von oben " + ("OK" if ok_c else "-- (hoeher / steiler von oben)"),
        h - step + 8, green if ok_c else red)
    fs = max(0.5, w / 1150)
    th = max(1, round(fs * 2))

    def badge(text, y, bg):
        (tw, ht), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        x = max(8, w - tw - 14)
        cv2.rectangle(out, (x - 7, y - ht - 6), (x + tw + 7, y + base + 4), bg, -1)
        cv2.putText(out, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th, cv2.LINE_AA)
        return y + ht + base + 16

    badge_green, amber = (38, 130, 61), (30, 96, 165)
    y = max(22, round(34 * fs))
    if greifer_zu is not None:
        y = badge("Greifer geschlossen" if greifer_zu else "Greifer offen", y,
                  badge_green if greifer_zu else amber)
    if countdown is not None:
        badge(f"Start in {countdown:.1f} s", y, amber)
    return out
