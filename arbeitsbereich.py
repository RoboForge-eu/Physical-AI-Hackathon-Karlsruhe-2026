"""Arbeitsbereich je Arm, in 3D: ein Plan von oben, an dessen Kanten senkrechte Waende stehen (unendlich hoch),
dazu Hindernisse als Koerper (Grundflaeche, optional Hoehe). Geprueft wird der ganze Arm aus dem echten
3D-Modell des SO-101 (so101_modell.py): Pruefpunkte auf allen beweglichen Teilen, auch Gestell-Teile, die beim
Einklappen nach hinten ragen. Kein Punkt darf einer Wand naeher kommen als 'abstand_m'.

Plan-Koordinaten in Metern, von oben gesehen: x nach rechts, y vom Nutzer weg (in den Tisch hinein).

Karte (karten/<arm>.json):
    {"arm": "follower", "aktiv": true, "abstand_m": 0.03,
     "erlaubt":  [[[x, y], ...], ...],     Flaechen, in denen sich der Arm bewegen darf (zusammengenommen)
     "verboten": [[[x, y], ...]  oder  {"punkte": [[x, y], ...], "hoehe_m": 0.4, "unten_m": 0}, ...],
                                           Hindernisse (ohne Hoehe: bis unendlich)
     "basis": {"x": 0, "y": 0.031,          Mitte der Basis-Platte im Plan (Ursprung des 3D-Modells)
               "basis_grad": 90,            wohin die Vorderseite der Basis zeigt (90 = +y, in den Tisch)
               "richtung_grad": 90,         wohin der Arm zeigt, wenn die Basis in der Mitte steht
               "drehsinn": -1}}             +1: groesserer Servowert dreht gegen den Uhrzeigersinn (von oben)

Was beim Folgen passiert (lab_worker.follow, Klasse Fence):
  - Jede Stellung, die der Follower anfahren soll, wird vorher im 3D-Modell geprueft.
  - Liegt das Leader-Ziel hinter einer Wand, faehrt der Follower nur so weit wie erlaubt und gleitet an der
    Wand entlang. Der Leader darf frei weiterbewegt werden.
  - Ist der Leader wieder im Bereich, holt der Follower mit begrenztem Tempo auf (jeder Zwischenschritt
    geprueft) und folgt dann wieder direkt. Kein Sprung, kein Versatz, kein Zurueckfuehren noetig.
"""
import json, math, os, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
KARTEN = os.path.join(HERE, "karten")
MID = 2047
STEP_RAD = 2 * math.pi / 4096
GEO = (1, 2, 3, 4, 5, 6)         # alle Gelenke: Drehung und Greifer bewegen Teile mit
NAMES = {1: "Basis", 2: "Schulter", 3: "Ellbogen", 4: "Handgelenk-Beugung", 5: "Handgelenk-Drehung", 6: "Greifer"}
CATCHUP_STEPS_S = 1500           # Aufholen nach der Wand: hoechstens so viele Schritte je Gelenk und Sekunde (~130 Grad/s)
DEFAULT_ABSTAND = 0.03



def path(arm):
    return os.path.join(KARTEN, f"{arm}.json")


def load(arm):
    try:
        with open(path(arm), encoding="utf-8") as f:
            k = json.load(f)
    except (OSError, ValueError):
        return None
    k["_grip"] = grip_range(k)
    return k


def save(karte, arm=None):
    os.makedirs(KARTEN, exist_ok=True)
    with open(path(arm or karte["arm"]), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in karte.items() if not k.startswith("_")}, f, indent=1)


# ---------------- Geometrie (3D-Modell des SO-101) ----------------
_MODEL = None


def model():
    global _MODEL
    if _MODEL is None:
        import so101_modell
        _MODEL = so101_modell.Modell()
    return _MODEL


def _pan_axis():
    j = next(j for j in model().order if j["name"] == "shoulder_pan")
    return np.array(j["xyz"][:2])


def to_plan(karte, pts_base):
    """Basis-Koordinaten (x vorn, y links, z oben) -> Plan (x, y, z)."""
    b = karte["basis"]
    a = math.radians(b.get("basis_grad", 90))
    c, s = math.cos(a), math.sin(a)
    x, y = pts_base[:, 0], pts_base[:, 1]
    return np.column_stack([b["x"] + c * x - s * y, b["y"] + s * x + c * y, pts_base[:, 2]])


def pan_fk(karte, pose, base_center):
    """Servo-Stellung -> Stellung fuers Modell: Basis-Winkel aus Drehsinn und Richtung der Karte."""
    b = karte["basis"]
    ccw = b.get("drehsinn", -1) * (pose[1] - base_center) * STEP_RAD + math.radians(
        b.get("richtung_grad", 90) - b.get("basis_grad", 90))
    out = dict(pose)
    out[1] = base_center - ccw / STEP_RAD            # Modell: groesserer Wert dreht im Uhrzeigersinn
    return out


def grip_range(karte):
    """(zu, auf) des Greifers aus der Anschlag-Messung dieses Arms, sonst None."""
    import stopcal
    j = ((stopcal.load(stopcal.stops_path(karte.get("arm") or "")) or {}).get("joints") or {}).get("6")
    return (j["lo"], j["hi"]) if j else None


def arm_points(karte, pose, base_center):
    """Pruefpunkte aller beweglichen Teile im Plan, (N, 3)."""
    return to_plan(karte, model().punkte(pan_fk(karte, pose, base_center), base_center, grip=karte.get("_grip")))


def base_points(karte):
    m = model()
    return to_plan(karte, m.links["base_link"]["punkte"])


def base_back_offset():
    """Abstand Basis-Ursprung -> hintere Kante der Basis (Meter)."""
    return float(-model().links["base_link"]["huelle"][:, 0].min())


def _sdist(xy, poly):
    """Vorzeichenbehafteter Abstand (positiv = innen) von Punkten (N, 2) zu einem Polygon."""
    P = np.asarray(poly, dtype=float)
    A, B = P, np.roll(P, -1, axis=0)
    d = B - A
    L = np.maximum((d * d).sum(1), 1e-12)
    t = np.clip(((xy[:, None, :] - A[None]) * d[None]).sum(2) / L[None], 0, 1)
    proj = A[None] + t[..., None] * d[None]
    dist = np.sqrt(((xy[:, None, :] - proj) ** 2).sum(2)).min(1)
    x, y = xy[:, 0:1], xy[:, 1:2]
    y1, y2, x1, x2 = A[None, :, 1], B[None, :, 1], A[None, :, 0], B[None, :, 0]
    cross = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / np.where(y2 == y1, 1e-12, y2 - y1) + x1)
    inside = cross.sum(1) % 2 == 1
    return np.where(inside, dist, -dist)


def _obstacles(karte):
    for o in karte.get("verboten") or []:
        if isinstance(o, dict):
            yield o["punkte"], o.get("unten_m", -1.0), o.get("hoehe_m")
        else:
            yield o, -1.0, None


_EDGES = {}


def _edges(karte):
    """Alle Kanten aller Flaechen einmal vorbereitet (je Karte zwischengespeichert)."""
    key = (id(karte), id(karte.get("erlaubt")), id(karte.get("verboten")),
           len(karte.get("erlaubt") or []), len(karte.get("verboten") or []))
    hit = _EDGES.get(key[0])
    if hit and hit[0] == key[1:]:
        return hit[1]
    polys = [(np.asarray(p, float), "erlaubt", None, None) for p in karte.get("erlaubt") or []]
    polys += [(np.asarray(p, float), "verboten", lo, hi) for p, lo, hi in _obstacles(karte)]
    A_ = np.vstack([p for p, *_ in polys]) if polys else np.zeros((0, 2))
    B_ = np.vstack([np.roll(p, -1, axis=0) for p, *_ in polys]) if polys else np.zeros((0, 2))
    starts = np.cumsum([0] + [len(p) for p, *_ in polys[:-1]]) if polys else np.zeros(0, int)
    d = B_ - A_
    data = {"ax": A_[:, 0], "ay": A_[:, 1], "dx": d[:, 0], "dy": d[:, 1], "L": np.maximum((d * d).sum(1), 1e-12),
            "by": B_[:, 1], "starts": starts, "kinds": [k for _, k, _, _ in polys],
            "ranges": [(lo, hi) for _, _, lo, hi in polys]}
    _EDGES[key[0]] = (key[1:], data)
    return data


def forget(karte):
    """Nach Aenderungen an den Flaechen einer Karte aufrufen (Kanten neu vorbereiten)."""
    _EDGES.pop(id(karte), None)


def _sdist_all(xy, E):
    """Vorzeichenbehaftete Abstaende (positiv = innen) aller Punkte zu allen Flaechen: (N, Flaechen)."""
    px, py = xy[:, 0:1], xy[:, 1:2]
    rx, ry = px - E["ax"], py - E["ay"]
    t = np.clip((rx * E["dx"] + ry * E["dy"]) / E["L"], 0.0, 1.0)
    ex, ey = rx - t * E["dx"], ry - t * E["dy"]
    dist2 = ex * ex + ey * ey
    dy = np.where(E["dy"] == 0, 1e-12, E["dy"])
    cross = ((E["ay"] > py) != (E["by"] > py)) & (px < E["dx"] * (py - E["ay"]) / dy + E["ax"])
    dmin = np.sqrt(np.minimum.reduceat(dist2, E["starts"], axis=1))
    inside = np.add.reduceat(cross.astype(np.int8), E["starts"], axis=1) % 2 == 1
    return np.where(inside, dmin, -dmin)


def clearance_points(karte, pts):
    """Kleinster Abstand der Punkte (N, 3) zu Waenden/Hindernissen. Positiv = frei."""
    E = _edges(karte)
    if not E["kinds"]:
        return np.full(len(pts), np.inf)
    S = _sdist_all(pts[:, :2], E)
    z = pts[:, 2]
    allowed = [i for i, k in enumerate(E["kinds"]) if k == "erlaubt"]
    d = S[:, allowed].max(axis=1) if allowed else np.full(len(pts), np.inf)
    for i, k in enumerate(E["kinds"]):
        if k != "verboten":
            continue
        lo, hi = E["ranges"][i]
        o = -S[:, i]                                   # waagerecht: positiv = ausserhalb der Grundflaeche
        top = np.inf if hi is None else hi
        vz = np.where(z > top, z - top, np.where(z < lo, lo - z, -np.inf))   # senkrecht: >0 = ueber/unter
        free = np.where(vz == -np.inf, o, np.where(o < 0, vz, np.maximum(o, vz)))
        d = np.minimum(d, free)
    return d


_SPHERES = {}


def _sphere(link):
    """Mittelpunkt und Radius der Pruefpunkte eines Teils (im Teil-Koordinatensystem)."""
    if link not in _SPHERES:
        P = model().links[link]["punkte"]
        c = P.mean(axis=0)
        _SPHERES[link] = (c, float(np.sqrt(((P - c) ** 2).sum(1)).max()))
    return _SPHERES[link]


def clearance(karte, pose, base_center, exact=False):
    """Kleinster Wandabstand des Arms (Meter) und Index des engsten Teils.
    Schnell: Teile, deren Huellkugel weit genug von allen Waenden ist, werden nicht Punkt fuer Punkt gerechnet;
    fuer sie zaehlt die (kleinere, also vorsichtige) Kugel-Abschaetzung. exact=True rechnet alle Punkte."""
    m = model()
    fr = m.frames(m.angles(pan_fk(karte, pose, base_center), base_center, karte.get("_grip")))
    links = m.moving
    centers, radii = [], []
    for k in links:
        c, r = _sphere(k)
        R, t = fr[k]
        centers.append(R @ c + t)
        radii.append(r)
    lb = clearance_points(karte, to_plan(karte, np.array(centers))) - np.array(radii)
    need = karte.get("abstand_m", DEFAULT_ABSTAND) + 0.01
    worst, which = float("inf"), None
    for i, k in enumerate(links):
        if exact or lb[i] < need:
            R, t = fr[k]
            d = float(clearance_points(karte, to_plan(karte, m.links[k]["punkte"] @ R.T + t)).min())
        else:
            d = float(lb[i])
        if d < worst:
            worst, which = d, i
    return worst, which


def base_clearance(karte):
    return float(clearance_points(karte, base_points(karte)).min())


def is_safe(karte, pose, base_center):
    return clearance(karte, pose, base_center)[0] >= karte.get("abstand_m", DEFAULT_ABSTAND)


class Fence:
    """Haelt den Follower im Arbeitsbereich. Methode (nachvollziehbar, ohne Zustands-Fallen):

    Der Follower hat eine eigene Stellung 'cur' (das, was zuletzt gesendet wurde). In jedem Takt:
      1. Ist das Leader-Ziel sicher und laeuft kein Aufholen -> direkt folgen (cur = Ziel).
      2. Sonst geht cur einen kleinen Schritt Richtung Ziel (hoechstens CATCHUP_STEPS_S je Gelenk und Sekunde).
         Der Schritt wird im 3D-Modell geprueft. Ist er unsicher, wird jedes Gelenk einzeln versucht:
         so gleitet der Arm an der Wand entlang, statt einzufrieren.
      3. Ist cur beim Ziel angekommen (und das Ziel sicher), wird wieder direkt gefolgt.
    Es gibt kein 'Zurueckfuehren an die Halte-Stellung': sobald der Leader wieder im Bereich ist, holt der
    Follower auf. Kein Sprung (Tempo begrenzt), kein Durchfahren einer Wand (jeder Zwischenschritt geprueft)."""

    def __init__(self, karte, base_center, log=print):
        self.karte, self.base_center, self.log = karte, base_center, log
        self.margin = karte.get("abstand_m", DEFAULT_ABSTAND)
        self.cur = None                  # zuletzt gesendete (sichere) Stellung
        self.limiting = False            # True: Follower weicht gerade vom Leader ab (Wand oder Aufholen)
        self._cache = {}
        self._last_t = None
        self._last_hint = 0.0

    def _safe(self, pose):
        key = tuple(int(round(pose[s])) for s in GEO)
        hit = self._cache.get(key)
        if hit is None:
            hit = clearance(self.karte, pose, self.base_center)[0] >= self.margin
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = hit
        return hit

    def start(self, pose):
        """Ausgangsstellung pruefen (z. B. nach dem Hochfahren). -> (ok, abstand)."""
        d, _ = clearance(self.karte, pose, self.base_center)
        self.cur = {s: int(pose[s]) for s in GEO} if d >= self.margin else None
        self.limiting = False
        return d >= self.margin, d

    @property
    def holding(self):
        return self.limiting

    @property
    def held(self):
        return dict(self.cur) if self.limiting and self.cur else None

    def filter(self, cmd, now=None):
        """cmd: Gelenk -> Leader-Ziel. Gibt die zu sendenden Ziele zurueck (None: noch nie sicher gewesen)."""
        import time as _t
        now = _t.monotonic() if now is None else now
        dt = 0.02 if self._last_t is None else max(0.0, min(0.05, now - self._last_t))
        self._last_t = now
        target = {s: int(cmd[s]) for s in GEO}
        if self.cur is None:
            if self._safe(target):
                self.cur = dict(target)
                return cmd
            return None
        if not self.limiting and self._safe(target):
            self.cur = dict(target)
            return cmd
        if not self.limiting:
            self.limiting = True
            self._last_hint = now
            self.log("ZAUN: Wand erreicht - Follower bleibt im Bereich (gleitet an der Wand entlang). "
                     "Sobald der Leader wieder im Bereich ist, holt der Follower von selbst auf.")
        maxd = max(1, int(CATCHUP_STEPS_S * dt))
        step = {s: max(-maxd, min(maxd, target[s] - self.cur[s])) for s in GEO}
        cand = {s: self.cur[s] + step[s] for s in GEO}
        if self._safe(cand):
            self.cur = cand
        else:                                          # an der Wand entlang: Gelenke einzeln
            for s in GEO:
                if step[s] == 0:
                    continue
                trial = dict(self.cur)
                trial[s] += step[s]
                if self._safe(trial):
                    self.cur = trial
        if all(self.cur[s] == target[s] for s in GEO) and self._safe(target):
            self.limiting = False
            self.log("ZAUN: Follower wieder beim Leader - folgt direkt.")
            return cmd
        if now - self._last_hint >= 2.0:
            self._last_hint = now
            off = max(abs(target[s] - self.cur[s]) for s in GEO) * 360 / 4096
            self.log(f"ZAUN: Leader-Ziel liegt hinter einer Wand (groesste Abweichung {off:.0f} Grad). "
                     "Follower wartet am Rand.")
        out = dict(cmd)
        out.update(self.cur)
        return out


# ---------------- Import ----------------
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "pt": 0.0254 / 72, "px": 0.0254 / 96, "": 0.0254 / 96}


def _length(v):
    m = re.match(r"\s*(" + _NUM + r")\s*([a-z]*)", v or "")
    return (float(m.group(1)), m.group(2)) if m else (None, "")


def _path_polys(d):
    """SVG-Pfad -> Liste von Polygonen (Kurven nur ueber ihre Endpunkte angenaehert)."""
    toks = re.findall(r"[MmLlHhVvZzCcSsQqTtAa]|" + _NUM, d)
    polys, cur, i, cmd = [], [], 0, None
    x = y = sx = sy = 0.0
    args = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
    while i < len(toks):
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if len(cur) >= 3:
                    polys.append(cur)
                cur, x, y = [], sx, sy
                continue
        if cmd is None:
            break
        n = args[cmd.upper()]
        vals = [float(v) for v in toks[i:i + n]]
        if len(vals) < n:
            break
        i += n
        rel = cmd.islower()
        C = cmd.upper()
        if C == "H":
            x = x + vals[0] if rel else vals[0]
        elif C == "V":
            y = y + vals[0] if rel else vals[0]
        else:
            nx, ny = vals[-2], vals[-1]
            x, y = (x + nx, y + ny) if rel else (nx, ny)
        if C == "M":
            if len(cur) >= 3:
                polys.append(cur)
            cur, sx, sy = [(x, y)], x, y
            cmd = "l" if rel else "L"            # weitere Zahlenpaare nach M sind Linien
        else:
            cur.append((x, y))
    if len(cur) >= 3:
        polys.append(cur)
    return polys


def import_svg(text):
    """SVG-Text -> Liste von Polygonen in Metern (y nach oben gedreht: im Plan zeigt y vom Nutzer weg).
    Einheit aus width/height + viewBox (mm, cm, m, in, px). Ohne Angabe: 1 px = 1/96 Zoll.
    Nicht unterstuetzt: Transformationen (transform=...)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    w, wu = _length(root.get("width"))
    vb = [float(v) for v in re.findall(_NUM, root.get("viewBox") or "")]
    scale = _UNITS.get(wu, _UNITS[""])
    if w and len(vb) == 4 and vb[2]:
        scale = w * _UNITS.get(wu, _UNITS[""]) / vb[2]
    polys = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        g = lambda k: float(el.get(k) or 0)
        if tag == "rect":
            x0, y0, ww, hh = g("x"), g("y"), g("width"), g("height")
            polys.append([(x0, y0), (x0 + ww, y0), (x0 + ww, y0 + hh), (x0, y0 + hh)])
        elif tag in ("polygon", "polyline"):
            v = [float(n) for n in re.findall(_NUM, el.get("points") or "")]
            polys.append(list(zip(v[0::2], v[1::2])))
        elif tag in ("circle", "ellipse"):
            cx, cy = g("cx"), g("cy")
            rx = g("r") or g("rx")
            ry = g("r") or g("ry")
            polys.append([(cx + rx * math.cos(a * math.pi / 12), cy + ry * math.sin(a * math.pi / 12)) for a in range(24)])
        elif tag == "path":
            polys.extend(_path_polys(el.get("d") or ""))
    return [[(round(px * scale, 4), round(-py * scale, 4)) for px, py in p] for p in polys if len(p) >= 3]


def import_dxf(text):
    """DXF (ASCII) -> Polygone in Metern: geschlossene LWPOLYLINE / POLYLINE. Einheit aus $INSUNITS (Standard mm)."""
    lines = [l.strip() for l in text.splitlines()]
    pairs = list(zip(lines[0::2], lines[1::2]))
    units = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
    scale = 0.001
    for i, (c, v) in enumerate(pairs):
        if v == "$INSUNITS" and i + 1 < len(pairs):
            scale = units.get(int(pairs[i + 1][1]), 0.001)
            break
    polys, cur, mode, take = [], None, None, False

    def flush():
        if cur and len(cur) >= 3 and all(p[1] is not None for p in cur):
            polys.append(cur)
    for c, v in pairs:
        if c == "0":
            if v == "LWPOLYLINE":
                flush()
                cur, mode, take = [], "lw", True
            elif v == "POLYLINE":
                flush()
                cur, mode, take = [], "pl", False      # Kopf-Koordinaten sind keine Ecke
            elif v == "VERTEX" and mode == "pl":
                take = True
            else:
                if mode is not None:
                    flush()
                cur, mode, take = None, None, False
        elif cur is not None and take and c == "10":
            cur.append([float(v), None])
        elif cur is not None and take and c == "20" and cur and cur[-1][1] is None:
            cur[-1][1] = float(v)
    flush()
    return [[(round(x * scale, 4), round(y * scale, 4)) for x, y in p] for p in polys if len(p) >= 3]


def from_polygons(arm, polys, basis=None, abstand=DEFAULT_ABSTAND):
    """Groesstes Polygon = erlaubte Flaeche, alle anderen = Hindernisse."""
    def area(p):
        return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))) / 2
    polys = sorted(polys, key=area, reverse=True)
    return {"arm": arm, "aktiv": True, "abstand_m": abstand,
            "erlaubt": [list(map(list, polys[0]))] if polys else [],
            "verboten": [list(map(list, p)) for p in polys[1:]],
            "basis": basis or {"x": 0.0, "y": 0.0, "basis_grad": 90, "richtung_grad": 90, "drehsinn": -1}}
