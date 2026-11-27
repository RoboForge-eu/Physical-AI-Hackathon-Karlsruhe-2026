"""Leichte SO-101-Simulation ("kinsim"): Gelenke, Kontakt, Objekte, Kameras. Reines numpy/OpenCV.

Koordinaten wie remote_kin: Meter, Ursprung am Fuss der Basis, x nach vorn, y nach links, z nach oben.
Gelenkwerte in Servo-Schritten (Mitte 2047) wie am echten Arm; Kinematik aus remote_kin (fk/ik).

Modell der Antriebe (STS3215, positionsgeregelt): jedes Gelenk faehrt mit begrenzter Geschwindigkeit zum
Soll. Die Greiferspitze kann nicht in feste Flaechen eindringen (Tisch, Palette, Halterung); wird das Soll
tiefer befohlen, bleibt das Ist stehen -> Soll/Ist-Abweichung und Last steigen wie am echten Arm.
Last in Promille (0..1000) wie das STS-Register 'Present Load': Grundlast durch Schwerkraft + k * Abweichung.

Szene: Tisch, Palette, Kabel-Schachtel (greifbar), Halterung mit Oeffnung (Stift einstecken) und
ArUco-Marker daneben. Der Stift steckt fest im Greifer; seine Spitze ist die Werkzeugspitze.
"""
import math
import numpy as np
import cv2
import remote_kin as K
from vision import marker as M

STEP_HZ = 100
MAX_SPEED = 2200            # Ticks/s (STS3215 ohne Last ~ 0,2 s / 60 Grad)
LOAD_GAIN = 6.0             # Promille Last je Tick Abweichung (grob, siehe SIMULATION.md)
LOAD_GRAVITY = (0, 180, 140, 60, 0, 0)
W, H = 640, 360             # wie ki.episodes.SIZE


class Szene:
    def __init__(self, rng=None, zufall=False):
        r = rng or np.random.default_rng(0)
        j = (lambda s: r.uniform(-s, s)) if zufall else (lambda s: 0.0)
        self.tisch_farbe = np.array([150, 170, 185]) + (r.integers(-40, 40, 3) if zufall else 0)
        self.palette = {"x": 0.16 + j(0.01), "y": 0.15 + j(0.01), "b": 0.12, "t": 0.10, "h": 0.012}
        self.schachtel = {"x": 0.20 + j(0.015), "y": -0.08 + j(0.015), "b": 0.035, "t": 0.03, "h": 0.045,
                          "farbe": (60, 60, 200) if not zufall else tuple(int(v) for v in r.integers(30, 230, 3))}
        self.halter = {"x": 0.20, "y": 0.03, "b": 0.08, "t": 0.08, "h": 0.05}
        self.loch = {"x": 0.20 + j(0.002), "y": 0.03 + j(0.002), "r": 0.0035, "tiefe": 0.015, "fase": 0.0}
        self.stift_r = 0.003
        self.marker = {"id": 7, "x": self.halter["x"] - 0.02, "y": self.halter["y"] + 0.022, "seite": 0.020}
        self.licht = {"gain": 1.0, "tint": np.ones(3), "schatten": None, "rauschen": 2.0}
        self.turm_versatz = np.zeros(3)
        self.turm_dreh = np.zeros(2)
        if zufall:
            self.licht = {"gain": r.uniform(0.55, 1.35), "tint": r.uniform(0.8, 1.2, 3),
                          "schatten": (r.uniform(0, W), r.uniform(0, H), r.uniform(80, 260), r.uniform(0.3, 0.7)),
                          "rauschen": r.uniform(1, 8)}
            self.turm_versatz = r.uniform(-0.03, 0.03, 3)
            self.turm_dreh = r.uniform(-0.05, 0.05, 2)
        self._tex = None

    # --- Geometrie ---
    def _in(self, o, x, y, rand=0.0):
        return abs(x - o["x"]) <= o["b"] / 2 + rand and abs(y - o["y"]) <= o["t"] / 2 + rand

    def boden(self, x, y):
        """Hoehe der festen Flaeche unter der Stiftspitze."""
        if self._in(self.halter, x, y):
            L = self.loch
            d = math.hypot(x - L["x"], y - L["y"])
            spiel = L["r"] - self.stift_r
            if d <= spiel:
                return self.halter["h"] - L["tiefe"]
            if d <= spiel + L["fase"]:                     # Fase: Flaeche faellt zum Loch hin ab
                return self.halter["h"] - L["fase"] * (1 - (d - spiel) / L["fase"])
            return self.halter["h"]
        if self._in(self.palette, x, y):
            return self.palette["h"]
        return 0.0

    # --- Bild der Tischflaeche (1 mm je Pixel) ---
    X0, X1, Y0, Y1 = -0.10, 0.50, -0.35, 0.35

    def textur(self):
        if self._tex is not None:
            return self._tex
        w, h = int((self.Y1 - self.Y0) * 1000), int((self.X1 - self.X0) * 1000)
        tex = np.empty((h, w, 3), np.uint8)
        tex[:] = self.tisch_farbe.clip(0, 255)
        rng = np.random.default_rng(1)
        tex = (tex + rng.normal(0, 6, tex.shape)).clip(0, 255).astype(np.uint8)       # Holzmaserung light
        def rect(o, farbe):
            u0, v0 = self.uv(o["x"] + o["b"] / 2, o["y"] + o["t"] / 2)
            u1, v1 = self.uv(o["x"] - o["b"] / 2, o["y"] - o["t"] / 2)
            cv2.rectangle(tex, (int(u0), int(v0)), (int(u1), int(v1)), farbe, -1)
        rect(self.palette, (40, 90, 140))
        rect(self.halter, (215, 215, 210))
        L = self.loch
        cv2.circle(tex, tuple(int(v) for v in self.uv(L["x"], L["y"])), int(round(L["r"] * 1000)), (25, 25, 25), -1)
        mk = self.marker
        s = int(round(mk["seite"] * 1000))
        img = cv2.resize(M.erzeugen(mk["id"], 200, 0), (s, s), interpolation=cv2.INTER_NEAREST)
        img = cv2.copyMakeBorder(img, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        u, v = self.uv(mk["x"], mk["y"])
        u0, v0 = int(round(u - s / 2 - 4)), int(round(v - s / 2 - 4))
        tex[v0:v0 + s + 8, u0:u0 + s + 8] = img[:, :, None]
        self._tex = tex
        return tex

    def uv(self, x, y):
        """Welt -> Texturpixel (u nach rechts = -y, v nach unten = -x; Draufsicht von vorn)."""
        return (self.Y1 - y) * 1000, (self.X1 - x) * 1000


def kamera_handgelenk(pose):
    """Kamera am Handgelenk: sitzt 9 cm hinter der Spitze auf der Werkzeugachse, 3 cm zur Basis hin versetzt,
    blickt entlang der Hand. Rueckgabe (R welt->kamera, Position, f)."""
    x, y, z, phi = pose
    yaw = math.atan2(y, x)
    d = np.array([math.sin(phi) * math.cos(yaw), math.sin(phi) * math.sin(yaw), math.cos(phi)])
    left = np.array([-math.sin(yaw), math.cos(yaw), 0.0])
    xr = -left
    yd = np.cross(d, xr)
    pos = np.array([x, y, z]) - 0.09 * d + 0.03 * yd
    return np.vstack([xr, yd, d]), pos, 330.0


def kamera_turm(szene):
    pos = np.array([0.18, -0.38, 0.42]) + szene.turm_versatz
    ziel = np.array([0.18, 0.02, 0.02])
    d = ziel - pos
    d /= np.linalg.norm(d)
    a, b = szene.turm_dreh
    d = d + np.array([a, 0, b])
    d /= np.linalg.norm(d)
    xr = np.cross(d, [0, 0, 1.0])
    xr /= np.linalg.norm(xr)
    yd = np.cross(d, xr)
    return np.vstack([xr, yd, d]), pos, 480.0


def projizieren(R, pos, f, pts):
    pc = (np.asarray(pts, float) - pos) @ R.T
    z = pc[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.stack([W / 2 + f * pc[:, 0] / z, H / 2 + f * pc[:, 1] / z], 1), z


class Welt:
    def __init__(self, seed=0, zufall=False, start=None):
        self.rng = np.random.default_rng(seed)
        self.szene = Szene(self.rng, zufall)
        self.t = 0.0
        start = start or [2047, 1300, 2700, 2900, 2047, 2000]
        self.soll = [float(v) for v in start]
        self.ist = [float(v) for v in start]
        self.gehalten = False             # Schachtel im Greifer
        self.greifer_zu = 1430
        self.greifer_auf = 2880
        self.zeichne_stift = True

    # --- Gelenke ---
    def setze_soll(self, ticks):
        for i, v in enumerate(ticks):
            lo, hi = K.LIMITS.get(i + 1, (0, 4095))
            self.soll[i] = float(min(max(v, lo), hi))

    def spitze(self, j=None):
        j = j or self.ist
        return K.fk({1: j[0], 2: j[1], 3: j[2], 4: j[3]})

    def _greifer_grenze(self):
        """Mit Schachtel im Greifer schliesst er nicht weiter als die Schachtelbreite."""
        if self.gehalten:
            return self.greifer_zu + 0.55 * (self.greifer_auf - self.greifer_zu)
        return None

    def schritt(self, n=1):
        dt = 1.0 / STEP_HZ
        for _ in range(n):
            self.t += dt
            alt = list(self.ist)
            for i in range(6):
                d = self.soll[i] - self.ist[i]
                self.ist[i] += max(-MAX_SPEED * dt, min(MAX_SPEED * dt, d))
            g = self._greifer_grenze()
            if g is not None and self.ist[5] < g:
                self.ist[5] = g
            x, y, z, phi = self.spitze()
            L, hz = self.szene.loch, self.szene.halter["h"]
            ox, oy, oz, _ = self.spitze(alt)
            if (oz < hz - 0.0005 and math.hypot(ox - L["x"], oy - L["y"]) <= L["r"]
                    and math.hypot(x - L["x"], y - L["y"]) > L["r"] - self.szene.stift_r):
                j = K.ik((ox, oy, z, phi))                 # Lochwand: seitlich blockiert, senkrecht frei
                for s in range(4):
                    self.ist[s] = j[s + 1] if j is not None else alt[s]
                x, y, z, phi = self.spitze()
            floor = self.szene.boden(x, y)
            if z < floor - 1e-5:                           # Spitze darf nicht in feste Flaechen
                j = None
                ox, oy, oz, ophi = self.spitze(alt)
                if oz >= floor - 1e-4:
                    j = K.ik((x, y, floor, phi))
                if j is None:
                    j = K.ik((ox, oy, max(oz, floor), ophi))
                if j is not None:
                    for s in range(4):
                        self.ist[s] = j[s + 1]
            self._rasten()
            self._greifen()

    def _rasten(self):
        """Stift ganz eingesteckt -> rastet ein (wie ein Stecker): Zug nach oben wird bis RAST_MM festgehalten."""
        L, hz = self.szene.loch, self.szene.halter["h"]
        x, y, z, phi = self.spitze()
        unten = hz - L["tiefe"]
        if L.get("rastet", True) and math.hypot(x - L["x"], y - L["y"]) <= L["r"] and z <= unten + 0.003:
            self.eingesteckt = True
        if getattr(self, "eingesteckt", False):
            if z > unten + 0.004:                     # mehr als 4 mm gezogen: ausgerastet (nur mit Gewalt)
                self.eingesteckt = False
            elif z > unten + 0.0005:
                j = K.ik((x, y, unten + 0.0005, phi))
                if j is not None:
                    for s in range(4):
                        self.ist[s] = j[s + 1]

    def _greifen(self):
        sch = self.szene.schachtel
        x, y, z, _ = self.spitze()
        nahe = math.hypot(x - sch["x"], y - sch["y"]) < 0.015 and z < sch["h"] + 0.005
        zu = self.soll[5] < self.greifer_zu + 0.6 * (self.greifer_auf - self.greifer_zu)
        if not self.gehalten and nahe and zu and self.ist[5] < self.greifer_zu + 0.6 * (self.greifer_auf - self.greifer_zu):
            self.gehalten = True
        if self.gehalten and not zu:
            self.gehalten = False
            sch["z"] = self.szene.boden(x, y)
        if self.gehalten:
            sch["x"], sch["y"], sch["z"] = x, y, max(0.0, z - sch["h"] / 2)

    def last(self):
        return [int(min(1000, LOAD_GRAVITY[i] + LOAD_GAIN * abs(self.soll[i] - self.ist[i]))) for i in range(6)]

    def stellung(self):
        return [int(round(v)) for v in self.ist]

    # --- Kameras ---
    def bild(self, kamera="arm"):
        sz = self.szene
        if kamera == "arm":
            R, pos, f = kamera_handgelenk(self.spitze())
        else:
            R, pos, f = kamera_turm(sz)
        tex = sz.textur()
        uu, vv = np.meshgrid(np.arange(W), np.arange(H))
        rays = np.stack([(uu - W / 2) / f, (vv - H / 2) / f, np.ones_like(uu, float)], -1) @ R
        img = np.zeros((H, W, 3), np.float32)
        mapx = np.full((H, W), -1, np.float32)
        mapy = np.full((H, W), -1, np.float32)
        hit = np.zeros((H, W), bool)
        for zplane, obj in ((sz.halter["h"], sz.halter), (sz.palette["h"], sz.palette), (0.0, None)):
            with np.errstate(divide="ignore", invalid="ignore"):
                s = (zplane - pos[2]) / rays[..., 2]
            px, py = pos[0] + s * rays[..., 0], pos[1] + s * rays[..., 1]
            ok = (s > 0) & ~hit
            if obj is not None:
                ok &= (np.abs(px - obj["x"]) <= obj["b"] / 2) & (np.abs(py - obj["y"]) <= obj["t"] / 2)
            if obj is None:                           # Seitenwand der Halterung statt Textur darunter
                wand = ok & (np.abs(px - sz.halter["x"]) <= sz.halter["b"] / 2) & (np.abs(py - sz.halter["y"]) <= sz.halter["t"] / 2)
                ok &= ~wand
                wand_px = wand
            mapx[ok] = ((sz.Y1 - py) * 1000)[ok]
            mapy[ok] = ((sz.X1 - px) * 1000)[ok]
            hit |= ok
        img = cv2.remap(tex, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(90, 90, 90))
        img[~hit] = (200, 200, 200)
        img[wand_px] = (170, 170, 165)
        self._objekte(img, R, pos, f, kamera)
        return self._licht(img)

    def _quader(self, img, R, pos, f, cx, cy, z0, b, t, h, farbe):
        ecken = np.array([[cx + sx * b / 2, cy + sy * t / 2, z0 + sz_ * h] for sz_ in (0, 1)
                          for sy in (-1, 1) for sx in (-1, 1)])
        p, z = projizieren(R, pos, f, ecken)
        if (z <= 0.01).any():
            return
        flaechen = [(4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
        for k, fl in sorted(enumerate(flaechen), key=lambda kf: -z[list(kf[1])].mean()):
            shade = 1.0 if k == 0 else 0.75
            cv2.fillConvexPoly(img, p[list(fl)].astype(np.int32), tuple(int(c * shade) for c in farbe), cv2.LINE_AA)

    def _objekte(self, img, R, pos, f, kamera):
        sch = self.szene.schachtel
        self._quader(img, R, pos, f, sch["x"], sch["y"], sch.get("z", 0.0), sch["b"], sch["t"], sch["h"], sch["farbe"])
        if kamera != "arm":                               # Arm als Linienzug in der Turmkamera
            j = self.ist
            a1 = K.ang(j[1]); a2 = a1 + math.pi / 2 + K.ang(j[2]); a3 = a2 + K.ang(j[3])
            yaw = K.BASE_SIGN * K.ang(j[0])
            pts, r, z = [(0, 0, 0)], 0.0, 0.0
            from so101 import SHOULDER_H, UPPER, FORE, HAND
            z = SHOULDER_H; pts.append((0, 0, z))
            for L, a in ((UPPER, a1), (FORE, a2), (HAND, a3)):
                r += L * math.sin(a); z += L * math.cos(a)
                pts.append((r * math.cos(yaw), r * math.sin(yaw), z))
            p, zz = projizieren(R, pos, f, pts)
            if (zz > 0).all():
                cv2.polylines(img, [p.astype(np.int32)], False, (40, 120, 230), 9, cv2.LINE_AA)
        else:                                             # Stift von oben: Spitze unten im Bild
            x, y, z, phi = self.spitze()
            p, zz = projizieren(R, pos, f, [(x, y, z), (x, y, z + 0.03)])
            if (zz > 0).all() and self.zeichne_stift:
                cv2.line(img, tuple(p[1].astype(int)), tuple(p[0].astype(int)), (160, 160, 160), 7, cv2.LINE_AA)

    def _licht(self, img):
        L = self.szene.licht
        out = img.astype(np.float32) * L["gain"] * L["tint"]
        if L["schatten"] is not None:
            cx, cy, r, k = L["schatten"]
            uu, vv = np.meshgrid(np.arange(W), np.arange(H))
            m = np.clip(1 - np.hypot(uu - cx, vv - cy) / r, 0, 1)
            out *= (1 - k * m)[..., None]
        out += self.rng.normal(0, L["rauschen"], out.shape)
        return out.clip(0, 255).astype(np.uint8)

    def werkzeugpunkt_px(self):
        """Wo die Stiftspitze in der Handgelenk-Kamera auf Hoehe der Halterungsflaeche liegt (Zielpixel)."""
        x, y, z, phi = self.spitze()
        R, pos, f = kamera_handgelenk((x, y, z, phi))
        p, _ = projizieren(R, pos, f, [(x, y, self.szene.halter["h"])])
        return [float(p[0][0]), float(p[0][1])]
