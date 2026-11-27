"""Karton in der Uebersichtskamera finden - relativ zum Roboter, egal wo der Turm steht.

Idee: ArUco-Marker kleben fest auf der Roboterbasis. Marker und Karton sind im selben Bild. Aus den vier Ecken
eines Markers folgt die Lage der Kamera relativ zum Marker (solvePnP) - und weil die Lage des Markers am Roboter
bekannt ist, auch relativ zum Roboter. Damit wird jedes Bildpixel auf die Ebene der Kartonoberkante (Hoehe bekannt)
zurueckgerechnet (und auf den Tisch; die Schnittmenge ist die Grundflaeche). Der Karton ist auf dem weissen Tisch die grosse dunkle Flaeche bekannter Groesse.
Die Kameraposition kuerzt sich heraus - der Turm darf frei stehen.

Plan-Koordinaten wie aufnahme/geometrie.py: cm, Ursprung = Drehachse der Basis auf Tischhoehe, x nach rechts,
y vom Roboter weg, z nach oben.

Marker (Eintrag je ID in 'marker'):
  mm        Kantenlaenge des schwarzen Quadrats
  x, y, z   Markermitte im Plan (cm)
  dreh      Drehung um die Senkrechte (Grad)
  kipp      0 = liegt flach (Bild nach oben), 90 = steht senkrecht. Bei kipp 90 und dreh 0 schaut der Marker
            nach hinten (zur Tischkante, -y), seine Oberkante zeigt nach oben.
Sieht die Kamera mehrere, zaehlt der im Bild groesste.

Einstellungen: calibration/uebersicht_<arm>.json (einmessen schreibt dreh/x/y des genutzten Markers und hfov).
"""
import copy, json, math, os
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALDIR = os.path.join(HERE, "calibration")
DEFAULT = {
    "marker": {"10": {"mm": 40.0, "x": 0.0, "y": -6.0, "z": 5.0, "dreh": 0.0, "kipp": 0.0},
               "11": {"mm": 60.0, "x": 0.0, "y": -6.0, "z": 5.0, "dreh": 0.0, "kipp": 0.0}},
    "karton_hoehe": 10.0, "hfov": 88.0, "hell_max": 0, "farbe_min": 25, "pappe_hell_min": 80,
    "laenge": 25.0, "breite": 15.5, "klappe": 7.0, "r_min": 10.0, "r_max": 55.0}
RASTER = 0.5                       # cm je Pixel in der Draufsicht


def pfad(arm):
    return os.path.join(CALDIR, f"uebersicht_{arm}.json")


def laden(arm="follower"):
    c = copy.deepcopy(DEFAULT)
    try:
        with open(pfad(arm), encoding="utf-8") as f:
            neu = json.load(f)
        for mid, m in (neu.pop("marker", None) or {}).items():
            c["marker"][mid] = dict(c["marker"].get(mid, {}), **m)
        c.update(neu)
    except (OSError, ValueError):
        pass
    from vision import kamerakalib
    c["kamera"] = kamerakalib.laden(arm, "turm")        # Verzerrung/Bildwinkel, falls kalibriert
    return c


def _vorbereiten(bild, cfg, cv2):
    """Mit Kamera-Kalibrierung: Bild entzerren und die echte Kameramatrix nutzen."""
    if cfg.get("kamera"):
        from vision import kamerakalib
        bild, K = kamerakalib.entzerren(bild, cfg["kamera"], cv2)
        cfg = dict(cfg, _K=K)
    return bild, cfg


def speichern(cfg, arm="follower"):
    os.makedirs(CALDIR, exist_ok=True)
    with open(pfad(arm), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in cfg.items() if (k in DEFAULT and k != "kamera")
                   or k in ("eingemessen_am", "eingemessen_mit")},
                  f, indent=1)


def kamera_matrix(w, h, hfov):
    f = (w / 2) / math.tan(math.radians(hfov) / 2)
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])


def marker_lage(m):
    """Marker -> Plan: (R 3x3, t 3) mit X_plan = R X_marker + t (Markerrahmen wie OpenCV: x rechts, y oben, z raus)."""
    a, k = math.radians(m["dreh"]), math.radians(m["kipp"])
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(k), -math.sin(k)], [0, math.sin(k), math.cos(k)]])
    return Rz @ Rx, np.array([m["x"], m["y"], m["z"]], float)


def _marker(bild, cfg):
    """Groesster bekannter Marker im Bild: (id-text, erkennung) oder (None, None)."""
    from vision import marker
    gefunden = [m for m in marker.finden(bild) if str(m["id"]) in cfg["marker"]]
    if not gefunden:
        return None, None
    m = max(gefunden, key=lambda m: m["seite_px"])
    return str(m["id"]), m


def projektionen(bild, cfg, cv2, mid, m):
    """Moegliche 3x4-Matrizen Plan-Punkt (cm, homogen) -> Bildpixel. Ein kleiner, schraeg gesehener Marker ist
    doppeldeutig (er kann 'umgeklappt' erscheinen) - darum beide Loesungen, die bessere waehlt die Kartonsuche."""
    h, w = bild.shape[:2]
    s = cfg["marker"][mid]["mm"] / 10.0
    obj = np.array([[-s / 2, s / 2, 0], [s / 2, s / 2, 0], [s / 2, -s / 2, 0], [-s / 2, -s / 2, 0]], np.float32)
    K = cfg["_K"] if cfg.get("_K") is not None else kamera_matrix(w, h, cfg["hfov"])
    n, rvecs, tvecs, fehler = cv2.solvePnPGeneric(obj, np.array(m["ecken"], np.float32), K, None,
                                                  flags=cv2.SOLVEPNP_IPPE_SQUARE)
    Rpm, tpm = marker_lage(cfg["marker"][mid])
    out = []
    for rvec, tvec in zip(rvecs, tvecs):
        Rcm, _ = cv2.Rodrigues(rvec)
        Rcp = Rcm @ Rpm.T
        tcp = tvec.ravel() - Rcp @ tpm
        if (-Rcp.T @ tcp)[2] <= 0:                     # Kamera unter dem Tisch: unmoeglich
            continue
        out.append(K @ np.hstack([Rcp, tcp[:, None]]))
    return out


def projektion(bild, cfg, cv2, mid, m):
    """Beste Projektion (die mit dem passendsten Karton), sonst die erste."""
    best = _suche(bild, cfg, cv2, mid, m)
    if best is not None:
        return best[4]
    ps = projektionen(bild, cfg, cv2, mid, m)
    return ps[0] if ps else None


def ebene(P, hoehe):
    """Homographie Plan (x, y, 1) auf Hoehe 'hoehe' -> Bild."""
    return np.stack([P[:, 0], P[:, 1], P[:, 2] * hoehe + P[:, 3]], axis=1)


_MODELL = None


def arm_maske(P, form, pose, cv2, rand_px=14):
    """Bildbereich, den der Arm verdeckt (aus dem 3D-Modell in der aktuellen Stellung), als 0/255-Bild."""
    global _MODELL
    import so101_modell
    if _MODELL is None:
        _MODELL = so101_modell.Modell()
    h, w = form[:2]
    maske = np.zeros((h, w), np.uint8)
    d = {i + 1: int(v) for i, v in enumerate(pose[:6])}
    fr = _MODELL.frames(_MODELL.angles(d))
    for k in _MODELL.links:
        R, t = fr[k]
        pts = _MODELL.links[k]["punkte"] @ R.T + t                # Meter, x vorn, y links, z oben
        plan = np.stack([-pts[:, 1] * 100, pts[:, 0] * 100, pts[:, 2] * 100, np.ones(len(pts))], axis=1)
        q = plan @ P.T
        ok = q[:, 2] > 1e-6
        if ok.sum() < 3:
            continue
        px = (q[ok, :2] / q[ok, 2:3]).astype(np.float32)
        cv2.fillConvexPoly(maske, cv2.convexHull(px).astype(np.int32), 255)
    if rand_px:
        maske = cv2.dilate(maske, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rand_px + 1, 2 * rand_px + 1)))
    return maske


def _suche(bild, cfg, cv2, mid, m, Ps=None, pose=None):
    """Karton suchen (alle Marker-Loesungen, oder die gemerkte Kameralage Ps). pose: Armstellung -> verdeckte
    Bildteile werden ignoriert. Gibt (guete, (x, y), winkel, (laenge, breite), P) oder None."""
    best = None
    for P in (Ps if Ps is not None else projektionen(bild, cfg, cv2, mid, m)):
        verdeckt = arm_maske(P, bild.shape, pose, cv2) if pose is not None else None
        r = _suche_mit(bild, cfg, cv2, m, P, verdeckt)
        if r is not None and (best is None or r[0] < best[0]):
            best = r + (P,)
    return best


def _suche_mit(bild, cfg, cv2, m, P, verdeckt=None):
    R = cfg["r_max"]
    n = int(2 * R / RASTER)
    S = np.array([[RASTER, 0, -R], [0, RASTER, -R], [0, 0, 1.0]])           # Raster (u, v) -> Plan (x, y)
    gray = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY) if bild.ndim == 3 else bild
    dunkel = gray < cfg["hell_max"]
    if bild.ndim == 3:                               # Pappe ist farbig (braun), der Tisch grau-weiss
        hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
        dunkel |= (hsv[:, :, 1] > cfg.get("farbe_min", 25)) & (hsv[:, :, 2] > cfg.get("pappe_hell_min", 80))
    dunkel = dunkel.astype(np.uint8) * 255
    if m is not None:                                                        # Marker selbst ist kein Karton
        pts = np.array(m["ecken"], np.float32)
        c = pts.mean(axis=0)
        cv2.fillConvexPoly(dunkel, ((pts - c) * 1.6 + c).astype(np.int32), 0)
    # Dunkle Flaeche einmal auf die Ebene der Oberkante und einmal auf den Tisch zurueckrechnen. Die Waende
    # verschmieren in der oberen Ebene zur Kamera hin, in der Tischebene von ihr weg - die Schnittmenge ist genau
    # die Grundflaeche des Kartons (senkrechte Waende), egal von wo die Kamera schaut.
    top = rand = None
    for hoehe in (cfg["karton_hoehe"], 0.0):
        Hr = np.linalg.inv(ebene(P, hoehe) @ S)                                # Bild -> Raster
        t = cv2.warpPerspective(dunkel, Hr, (n, n), flags=cv2.INTER_NEAREST)
        rand = t if rand is None else rand
        top = t if top is None else cv2.bitwise_and(top, t)
    yy, xx = np.mgrid[0:n, 0:n]
    px, py = xx * RASTER - R, yy * RASTER - R
    rr = np.hypot(px, py)
    weg = (rr < cfg["r_min"]) | (rr > R)
    if cfg.get("nur_vorne", True):                   # beim Einmessen ist "vorn" noch unbekannt
        weg |= py < -2
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for t in (top, rand):
        t[weg] = 0
        t[:] = cv2.morphologyEx(cv2.morphologyEx(t, cv2.MORPH_CLOSE, k, iterations=2), cv2.MORPH_OPEN, k)
    # Offene Klappen (wie in den Aufnahmen): von oben ist der Karton ein "Plus" - Kasten mit vier flach
    # aufgeklappten Klappen. Diese Form (bekannte Groesse) wird direkt gesucht, auf halber Kartonhoehe.
    if cfg.get("kanten", True):
        Hr = np.linalg.inv(ebene(P, cfg["karton_hoehe"]) @ S)
        grau = cv2.warpPerspective(gray, Hr, (n, n), flags=cv2.INTER_LINEAR)
        vr = None
        if verdeckt is not None:
            vr = cv2.warpPerspective(verdeckt, Hr, (n, n), flags=cv2.INTER_NEAREST)
            # Bildrand: ausserhalb des Bildes ist auch "nicht gesehen"
            vr = np.maximum(vr, 255 - cv2.warpPerspective(np.full(gray.shape, 255, np.uint8), Hr, (n, n),
                                                          flags=cv2.INTER_NEAREST))
        kante = _kanten_suche(grau, rand, cfg, cv2, R, vr)
        if kante is not None:
            return kante
    if cfg.get("klappe", 0) > 0:
        Hr = np.linalg.inv(ebene(P, cfg["karton_hoehe"] / 2) @ S)
        mitte = cv2.warpPerspective(dunkel, Hr, (n, n), flags=cv2.INTER_NEAREST)
        mitte[weg] = 0
        mitte = cv2.morphologyEx(cv2.morphologyEx(mitte, cv2.MORPH_CLOSE, k, iterations=2), cv2.MORPH_OPEN, k)
        plus = _plus_suche(mitte, cfg, cv2, R)
        if plus is not None:
            return plus
    # Groesste dunkle Flaeche passender Groesse (offene Klappen machen sie groesser als den Karton)
    soll = cfg["laenge"] * cfg["breite"]
    nlab, lab, stats, _ = cv2.connectedComponentsWithStats(top)
    kand = [k for k in range(1, nlab) if 0.4 * soll <= stats[k, cv2.CC_STAT_AREA] * RASTER ** 2 <= 4.0 * soll]
    if not kand:
        return None
    k = max(kand, key=lambda k: stats[k, cv2.CC_STAT_AREA])
    blob = (lab == k).astype(np.float32)
    flaeche = float(blob.sum()) * RASTER ** 2
    # Rechteck in Kartongroesse so legen, dass es moeglichst ganz auf dunkler Flaeche liegt (alle Drehungen)
    from aufnahme import geometrie as G
    D = int(math.hypot(cfg["laenge"], cfg["breite"]) / RASTER) + 3
    beste = None

    def probe(ang):
        kern = np.zeros((D, D), np.float32)
        ecken = [(D / 2 + x / RASTER, D / 2 + y / RASTER)
                 for x, y in G.corners(0, 0, ang, cfg["laenge"], cfg["breite"])]
        cv2.fillConvexPoly(kern, np.array(ecken, np.int32), 1.0)
        kern /= kern.sum()
        cov = cv2.filter2D(blob, -1, kern, borderType=cv2.BORDER_CONSTANT)
        return float(cov.max()), ang, cov
    beste = max((probe(a) for a in range(0, 180, 6)), key=lambda t: t[0])          # grob, dann fein
    beste = max([beste] + [probe((beste[1] + d) % 180) for d in (-4, -2, 2, 4)], key=lambda t: t[0])
    mx, ang, cov = beste
    ys, xs = np.where(cov >= mx - 0.02)              # bei Klappen ist die Lage etwas offen: Mitte davon nehmen
    u, v = float(xs.mean()), float(ys.mean())
    (_, _), (a, b), _ = cv2.minAreaRect(cv2.findNonZero((blob > 0).astype(np.uint8)))
    L, B = max(a, b) * RASTER, min(a, b) * RASTER
    guete = (1 - mx) + 0.3 * min(1.0, abs(flaeche / soll - 1))
    return (guete, (u * RASTER - R, v * RASTER - R), float(ang), (L, B))


def _kanten_suche(grau, maske, cfg, cv2, R, verdeckt=None):
    """Oberkante des Kartons: die Klappen haengen genau an den Kanten der Oeffnung. Auf Hoehe der Oberkante
    liegt dort ein Rechteck bekannter Groesse aus geraden Kanten - egal, wie die Klappen liegen. Gesucht wird das
    Rechteck, dessen Umriss am besten auf Bildkanten liegt und das auf Pappe liegt.
    verdeckt: Teile, die die Kamera nicht sieht (Arm davor, Bildrand) - dort zaehlt nur, was sichtbar ist. So wird
    der Karton auch gefunden, wenn ein Viertel bis drei Viertel davon verdeckt sind.
    Gibt (guete, (x, y), winkel, (laenge, breite)) oder None."""
    from aufnahme import geometrie as G
    soll = cfg["laenge"] * cfg["breite"]
    frei = np.ones(grau.shape, np.float32) if verdeckt is None else (verdeckt == 0).astype(np.float32)
    if float((maske > 0).sum()) * RASTER ** 2 < (0.4 if verdeckt is None else 0.12) * soll:
        return None
    kanten = cv2.Canny(cv2.GaussianBlur(grau, (5, 5), 0), 30, 90)
    kanten[maske == 0] = 0
    kanten = cv2.dilate(kanten, np.ones((2, 2), np.uint8))
    MAXD = 6.0
    dt = np.minimum(cv2.distanceTransform(255 - kanten, cv2.DIST_L2, 3), MAXD).astype(np.float32)
    dtf = dt * frei                                           # Abstand zur naechsten Kante, nur Sichtbares
    pappe = (maske > 0).astype(np.float32) * frei
    L, B = cfg["laenge"], cfg["breite"]
    D = int(math.hypot(L, B) / RASTER) + 5
    MIN_SICHT = 0.25                                          # mindestens ein Viertel des Umrisses sichtbar
    # Kartonmitte nur dort, wo ein Karton im Arbeitsbereich ueberhaupt liegen kann (Halbring vor dem Roboter)
    yy, xx = np.mgrid[0:grau.shape[0], 0:grau.shape[1]]
    rm = np.hypot(xx * RASTER - R, yy * RASTER - R)
    mitte_ok = (rm >= cfg.get("mitte_r_min", 17.0)) & (rm <= cfg.get("mitte_r_max", 40.0)) & (yy * RASTER - R > 0)

    def probe(ang):
        ecken = np.array([(D / 2 + x / RASTER, D / 2 + y / RASTER) for x, y in G.corners(0, 0, ang, L, B)], np.int32)
        umriss = np.zeros((D, D), np.float32)
        cv2.polylines(umriss, [ecken], True, 1.0, 1)
        flaeche = np.zeros((D, D), np.float32)
        cv2.fillConvexPoly(flaeche, ecken, 1.0)
        f = lambda img, k: cv2.filter2D(img, -1, k, borderType=cv2.BORDER_CONSTANT)
        sicht = f(frei, umriss) / umriss.sum()                       # Anteil des Umrisses, der sichtbar ist
        abst = f(dtf, umriss) / np.maximum(f(frei, umriss), 1e-3)     # mittlerer Kantenabstand (sichtbar)
        fs = f(frei, flaeche)
        cov = f(pappe, flaeche) / np.maximum(fs, 1e-3)               # sichtbare Innenflaeche ist Pappe
        wert = (1 - abst / MAXD) * sicht                             # nur gesehene, passende Kanten zaehlen
        wert[(sicht < MIN_SICHT) | (cov < 0.8) | (fs < 0.15 * flaeche.sum()) | ~mitte_ok] = 0
        _, mx, _, (u, v) = cv2.minMaxLoc(wert)
        return float(mx), ang, (u, v), float(sicht[v, u])
    beste = max((probe(a) for a in range(0, 180, 3)), key=lambda t: t[0])            # grob, dann fein
    beste = max([beste] + [probe((beste[1] + d) % 180) for d in (-2, -1, 1, 2)], key=lambda t: t[0])
    mx, ang, (u, v), sicht = beste
    if mx <= 0.15:
        return None
    guete = 1 - mx
    if sicht < 0.6:                 # weniger als 60 % des Umrisses gesehen: Lage zu unsicher (lieber "nicht gefunden")
        guete = max(guete, 0.61)
    return (guete, (u * RASTER - R, v * RASTER - R), float(ang), (L, B))


def _plus_suche(maske, cfg, cv2, R):
    """Karton mit offenen Klappen: Plus-Form (Kasten + vier Klappen der Tiefe 'klappe') moeglichst ganz auf dunkler
    Flaeche, die vier Ecken-Kerben moeglichst hell. Gibt (guete, (x, y), winkel, (laenge, breite)) oder None."""
    soll = cfg["laenge"] * cfg["breite"]
    if float(maske.sum()) / 255 * RASTER ** 2 < 0.4 * soll:
        return None
    from aufnahme import geometrie as G
    L, B, f = cfg["laenge"], cfg["breite"], cfg["klappe"]
    D = int(math.hypot(L + 2 * f, B + 2 * f) / RASTER) + 3
    blob = maske.astype(np.float32) / 255

    def poly(ang, l, b):
        return np.array([(D / 2 + x / RASTER, D / 2 + y / RASTER) for x, y in G.corners(0, 0, ang, l, b)], np.int32)

    def probe(ang):
        plus = np.zeros((D, D), np.uint8)
        cv2.fillConvexPoly(plus, poly(ang, L, B + 2 * f), 1)
        cv2.fillConvexPoly(plus, poly(ang, L + 2 * f, B), 1)
        box = np.zeros((D, D), np.uint8)
        cv2.fillConvexPoly(box, poly(ang, L + 2 * f, B + 2 * f), 1)
        kerben = (box > 0) & (plus == 0)
        kern = plus.astype(np.float32) / plus.sum() - kerben.astype(np.float32) / max(1, kerben.sum())
        wert = cv2.filter2D(blob, -1, kern, borderType=cv2.BORDER_CONSTANT)
        _, mx, _, (u, v) = cv2.minMaxLoc(wert)
        return mx, ang, (u, v)
    beste = max((probe(a) for a in range(0, 180, 6)), key=lambda t: t[0])           # grob, dann fein
    beste = max([beste] + [probe((beste[1] + d) % 180) for d in (-4, -2, 2, 4)], key=lambda t: t[0])
    mx, ang, (u, v) = beste
    return (1 - mx, (u * RASTER - R, v * RASTER - R), float(ang), (L, B))


def kamera_lage(bild, cfg=None, cv2=None):
    """Nur die Lage der Kamera (aus dem Basis-Marker): Liste moeglicher 3x4-Matrizen, oder None (Marker verdeckt).
    Steht der Turm still, gilt sie auch fuer spaetere Bilder - dann darf der Arm den Marker verdecken."""
    if cv2 is None:
        import cv2
    cfg = cfg or laden()
    bild, cfg = _vorbereiten(bild, cfg, cv2)
    mid, m = _marker(bild, cfg)
    if m is None:
        return None
    return [P.tolist() for P in projektionen(bild, cfg, cv2, mid, m)]


def finden(bild, cfg=None, cv2=None, lage=None, pose=None, verdeckt=None):
    """Karton suchen. lage: gemerkte Kameralage (aus kamera_lage), falls der Marker gerade verdeckt ist.
    pose: Armstellung [j1..j6] - was der Arm verdeckt, wird nicht bewertet. verdeckt: weitere verdeckte Bildteile.
    Gibt {"gefunden", "platzierung": {x, y, winkel, seite}, "guete", "marker", "lage", "grund"} zurueck."""
    if cv2 is None:
        import cv2
    cfg = cfg or laden()
    roh = bild
    bild, cfg = _vorbereiten(bild, cfg, cv2)
    if verdeckt is not None and cfg.get("kamera"):
        from vision import kamerakalib
        verdeckt = cv2.undistort(verdeckt, *[np.asarray(v, float) for v in
                                             (kamerakalib.entzerren(roh, cfg["kamera"], cv2)[1], cfg["kamera"]["dist"])])
    mid, m = _marker(bild, cfg)
    Ps = None
    if m is None:
        if not lage:
            return {"gefunden": False, "grund": f"Kein Basis-Marker ({', '.join(cfg['marker'])}) im Uebersichtsbild"}
        Ps = [np.asarray(P, float) for P in lage]
    best = None
    for P in (Ps if Ps is not None else projektionen(bild, cfg, cv2, mid, m)):
        v = arm_maske(P, bild.shape, pose, cv2) if pose is not None else None
        if verdeckt is not None:
            v = verdeckt if v is None else np.maximum(v, verdeckt)
        r = _suche_mit(bild, cfg, cv2, m, P, v)
        if r is not None and (best is None or r[0] < best[0]):
            best = r + (P,)
    if best is None:
        return {"gefunden": False, "marker": None if m is None else int(mid),
                "grund": "Kein Karton gefunden (zu viel verdeckt oder nicht im Bild)"}
    guete, (x, y), winkel, (L, B), P = best
    from aufnahme import geometrie as G
    p = {"x": round(x, 1), "y": round(y, 1), "winkel": round(winkel, 1)}
    p["seite"] = G.approach_side(p["x"], p["y"], p["winkel"])
    ok = guete < cfg.get("guete_max", 0.45)
    return {"gefunden": ok, "platzierung": p, "groesse_cm": [round(L, 1), round(B, 1)], "guete": round(guete, 3),
            "marker": None if m is None else int(mid), "lage": [P.tolist()],
            "lage_gemerkt": m is None, "grund": None if ok else "Karton nur unsicher erkannt"}


def einmessen(bild, platz_soll, cfg=None, cv2=None):
    """Karton liegt an einer bekannten Stelle (platz_soll {x, y, winkel}, z. B. eine Testplatzierung von der Karte).
    Bestimmt den Bildwinkel der Kamera und dreh/x/y des sichtbaren Markers (Hoehe z und kipp bleiben, die kommen
    aus der Skizze). Gibt (neue Einstellungen, guete, marker-id) zurueck - noch nicht gespeichert."""
    if cv2 is None:
        import cv2
    cfg = copy.deepcopy(cfg or laden())
    bild, cfg = _vorbereiten(bild, cfg, cv2)
    mid, m = _marker(bild, cfg)
    if m is None:
        raise RuntimeError(f"Kein Basis-Marker ({', '.join(cfg['marker'])}) im Uebersichtsbild")
    roh = copy.deepcopy(cfg)
    roh["nur_vorne"] = False
    roh["marker"][mid].update(x=0.0, y=0.0, dreh=0.0)          # erst im Markerrahmen messen
    beste = None
    # Bildwinkel nur auf Wunsch schaetzen (aus der Kartongroesse; bei offenen Klappen unsicher)
    for hfov in (range(40, 121) if cfg.get("hfov_suchen") else [int(round(cfg["hfov"]))]):
        roh["hfov"] = float(hfov)
        r = _suche(bild, roh, cv2, mid, m)
        if r is not None and (beste is None or r[0] < beste[1][0]):
            beste = (hfov, r)
    if beste is None:
        raise RuntimeError("Karton im Uebersichtsbild nicht gefunden")
    hfov, (guete, (mx, my), wm, _, _) = beste
    # 180 Grad doppeldeutig (Karton ist symmetrisch): die Loesung nehmen, die naeher an der Skizze liegt
    alt = cfg["marker"][mid]
    loes = []
    for extra in (0, 180):
        dreh = (platz_soll["winkel"] - wm + extra) % 360
        a = math.radians(dreh)
        ox = platz_soll["x"] - (mx * math.cos(a) - my * math.sin(a))
        oy = platz_soll["y"] - (mx * math.sin(a) + my * math.cos(a))
        loes.append((math.hypot(ox - alt["x"], oy - alt["y"]), ox, oy, dreh))
    _, ox, oy, dreh = min(loes)
    cfg["hfov"] = float(hfov)
    cfg["marker"][mid].update(x=round(ox, 2), y=round(oy, 2), dreh=round(dreh if dreh <= 180 else dreh - 360, 2))
    return cfg, round(guete, 3), int(mid)


def messbild(bild, ergebnis, cfg=None, cv2=None, lage=None):
    """Uebersichtsbild mit eingezeichnetem Karton (Plan-Rechteck auf Kartonhoehe projiziert) und Roboterachse."""
    if cv2 is None:
        import cv2
    cfg = cfg or laden()
    bild, cfg = _vorbereiten(bild, cfg, cv2)
    img = bild.copy()
    mid, m = _marker(bild, cfg)
    if m is not None:
        cv2.polylines(img, [np.array(m["ecken"], np.int32)], True, (60, 200, 60), 2)
        P = projektion(bild, cfg, cv2, mid, m)
    elif lage:
        P = np.asarray(lage[0], float)                     # Marker verdeckt: gemerkte Kameralage
        cv2.putText(img, "Marker verdeckt - gemerkte Kameralage", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 200, 255), 2, cv2.LINE_AA)
    else:
        return img
    if P is None:
        return img

    def bildpunkt(x, y, z):
        q = P @ np.array([x, y, z, 1.0])
        return int(q[0] / q[2]), int(q[1] / q[2])
    cv2.line(img, bildpunkt(0, 0, 0), bildpunkt(0, 0, 15), (230, 140, 40), 3)          # Drehachse der Basis
    p = ergebnis.get("platzierung")
    if p:
        from aufnahme import geometrie as G
        pts = [bildpunkt(x, y, cfg["karton_hoehe"])
               for x, y in G.corners(p["x"], p["y"], p["winkel"], cfg["laenge"], cfg["breite"])]
        farbe = (60, 200, 60) if ergebnis.get("gefunden") else (40, 40, 230)
        cv2.polylines(img, [np.array(pts, np.int32)], True, farbe, 3)
        cv2.putText(img, f"x {p['x']} y {p['y']} cm  {p['winkel']} Grad", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    farbe, 2, cv2.LINE_AA)
    return img
