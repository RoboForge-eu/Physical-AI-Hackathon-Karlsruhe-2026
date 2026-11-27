"""Tisch-Geometrie fuer Kartonplatzierungen (Draufsicht, Zentimeter).

Ursprung = Drehachse der Roboterbasis an der Tischkante; x nach rechts, y vom Roboter weg in den Tisch.
Erlaubt ist der Halbring vor dem Roboter (Innenradius r_innen, Aussenradius r_aussen, y >= 0).
Eine Platzierung: Kartonmitte (x, y), Drehung 'winkel' (Grad) der langen Kartonachse gegen die x-Achse,
und die Anflugseite (welche lange Seite der Greifer anfaehrt: +1 / -1 entlang der kurzen Achse).
"""
import math, random

# Ausrichtung: Winkel 'delta' zwischen langer Kartonachse und der Richtung Basis -> Kartonmitte
#   quer   = lange Seite zeigt zur Basis  -> delta nahe 90 Grad
#   laengs = kurze Seite zeigt zur Basis  -> delta nahe 0 Grad
#   schraeg dazwischen
# Gemessen (22.11.): Im Halbring 16-40 cm passt ein Karton 25 x 15,5 cm nur mit delta >= ~68 Grad. Laengs ist dort
# geometrisch unmoeglich, und "schraeg" kann nur bis etwa 30 Grad aus der Quer-Lage gedreht sein.
QUER_MIN, LAENGS_MAX = 80.0, 45.0


def corners(x, y, winkel, laenge, breite):
    a = math.radians(winkel)
    ux, uy = math.cos(a), math.sin(a)          # lange Achse
    vx, vy = -uy, ux                           # kurze Achse
    hl, hb = laenge / 2, breite / 2
    return [(x + sx * hl * ux + sy * hb * vx, y + sx * hl * uy + sy * hb * vy)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _point_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def inside_ring(pts, r_innen, r_aussen, rand=0.0):
    """Rechteck (4 Ecken) vollstaendig im Halbring? Mit Randabstand 'rand'."""
    if any(py < rand for _, py in pts):
        return False
    if any(math.hypot(px, py) > r_aussen - rand for px, py in pts):
        return False
    # Ursprung nicht im Rechteck und kein Punkt des Rechtecks naeher als r_innen + rand
    near = min(_point_seg_dist(0, 0, *pts[i], *pts[(i + 1) % 4]) for i in range(4))
    return near >= r_innen + rand and not _contains(pts, 0, 0)


def _contains(pts, px, py):
    sign = None
    for i in range(4):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % 4]
        c = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        s = c > 0
        if sign is None:
            sign = s
        elif s != sign:
            return False
    return True


def delta_deg(x, y, winkel):
    """Winkel 0..90 zwischen langer Achse und Radialrichtung."""
    radial = math.degrees(math.atan2(y, x))
    d = abs((winkel - radial) % 180)
    return min(d, 180 - d)


def classify(x, y, winkel):
    d = delta_deg(x, y, winkel)
    if d >= QUER_MIN:
        return "quer"
    if d <= LAENGS_MAX:
        return "laengs"
    return "schraeg"


def approach_side(x, y, winkel):
    """Lange Seite, die der Greifer anfaehrt (+1 oder -1 entlang der kurzen Achse).
    quer/schraeg: die Seite naeher an der Basis. laengs (kurze Seite zur Basis, beide langen Seiten fast gleich
    weit weg): immer die RECHTE lange Seite, von der Basis aus zum Karton geschaut (Festlegung 25.11.)."""
    a = math.radians(winkel)
    vx, vy = -math.sin(a), math.cos(a)
    if classify(x, y, winkel) == "laengs":
        rx, ry = y, -x                      # rechts von der Blickrichtung Basis -> Kartonmitte
        return 1 if (vx * rx + vy * ry) > 0 else -1
    # Seite +1 liegt bei Mitte + v*b/2: naeher an der Basis, wenn v von der Basis weg zeigt
    return -1 if (x * vx + y * vy) > 0 else 1


def side_points(p, laenge, breite):
    """Endpunkte der Anflugseite (fuer Pfeil und Karte)."""
    c = corners(p["x"], p["y"], p["winkel"], laenge, breite)
    return (c[0], c[1]) if p["seite"] == -1 else (c[3], c[2])


def region(x, y):
    """Grobe Einordnung fuer die Verteilung: links/mitte/rechts und nah/fern."""
    ang = math.degrees(math.atan2(y, x))
    lr = "rechts" if ang < 60 else "links" if ang > 120 else "mitte"
    nf = "nah" if math.hypot(x, y) < 28 else "fern"
    return lr, nf


_CACHE = {}


def candidates(geo, schritt_r=1.0, schritt_ang=3.0, schritt_w=3.0):
    key = (tuple(sorted((k, v) for k, v in geo.items() if isinstance(v, (int, float)))), schritt_r, schritt_ang, schritt_w)
    if key not in _CACHE:
        _CACHE[key] = _candidates(geo, schritt_r, schritt_ang, schritt_w)
    return list(_CACHE[key])


def _candidates(geo, schritt_r=1.0, schritt_ang=3.0, schritt_w=3.0):
    """Alle gueltigen Platzierungen auf einem Raster (deterministisch, einmal berechnen).
    Laengs passt der Karton nur ganz knapp radial zwischen die Kreise: dafuer feineres Raster und eigener
    Randabstand 'rand_laengs' (Standard 0)."""
    L, B, ri, ra = geo["laenge"], geo["breite"], geo["r_innen"], geo["r_aussen"]
    rand, rand_l = geo.get("rand", 1.0), geo.get("rand_laengs", 0.0)
    out = []

    def scan(sr, sa, sw, klasse, margin):
        r = ri
        while r <= ra:
            ang = 5.0
            while ang <= 175.0:
                x, y = r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang))
                w = 0.0
                while w < 180.0:
                    k = classify(x, y, w)
                    if (k == "laengs") == (klasse == "laengs") and inside_ring(corners(x, y, w, L, B), ri, ra, margin):
                        out.append((round(x, 1), round(y, 1), round(w, 1), k))
                    w += sw
                ang += sa
            r += sr
    scan(schritt_r, schritt_ang, schritt_w, "andere", rand)
    scan(0.1, schritt_ang, 1.0, "laengs", rand_l)
    return out


def generate(klassen, geo, seed, schon=(), pool=None, abstand_min=0.0):
    """Waehlt fuer jede gewuenschte Ausrichtungsklasse eine gueltige, moeglichst verschiedene Platzierung.
    Gibt es eine Klasse geometrisch nicht (z. B. laengs), wird 'schraeg' (sonst 'quer') genommen und
    'ersatz_fuer' gesetzt. Reproduzierbar ueber 'seed'.
    abstand_min: jede neue Platzierung liegt mindestens so weit (cm, Drehung zaehlt 0.15 cm/Grad) von allen
    'schon'-Platzierungen entfernt (Folgeplan: wirklich neue Positionen), sofern es solche gibt."""
    alt = list(schon)
    rng = random.Random(seed)
    pool = pool if pool is not None else candidates(geo)
    by_class = {}
    for c in pool:
        by_class.setdefault(c[3], []).append(c)
    placed = list(schon)
    regions_used = {}
    for q in placed:
        regions_used[region(q["x"], q["y"])] = regions_used.get(region(q["x"], q["y"]), 0) + 1
    out = []
    for klasse in klassen:
        options = by_class.get(klasse) or by_class.get("schraeg") or by_class.get("quer")
        if not options:
            raise ValueError("Der Karton passt nirgends in den erlaubten Bereich")
        if abstand_min and alt:
            fern = [c for c in options if min(math.hypot(c[0] - q["x"], c[1] - q["y"]) + 0.15 * min(
                abs(c[2] - q["winkel"]) % 180, 180 - abs(c[2] - q["winkel"]) % 180) for q in alt) >= abstand_min]
            options = fern or options
        sample = rng.sample(options, min(len(options), 600))
        def score(c):
            x, y, w, _ = c
            d = min([math.hypot(x - q["x"], y - q["y"]) + 0.15 * min(abs(w - q["winkel"]) % 180,
                     180 - abs(w - q["winkel"]) % 180) for q in placed] or [99])
            return d - 4 * regions_used.get(region(x, y), 0)
        x, y, w, k = max(sample, key=score)
        p = {"x": x, "y": y, "winkel": w, "ausrichtung": k, "seite": approach_side(x, y, w)}
        if k != klasse:
            p["ersatz_fuer"] = klasse
        placed.append(p)
        regions_used[region(x, y)] = regions_used.get(region(x, y), 0) + 1
        out.append(p)
    return out
