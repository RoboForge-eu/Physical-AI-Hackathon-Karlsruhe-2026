"""Tastatursteuerung und Mini-Simulation fuer die Fernsteuerungs-App (laeuft auf dem Bediener-PC).

  KeyTeleop  Tasten -> Zielpose der Greiferspitze (vor/zurueck, links/rechts, hoch/runter, Hand neigen/drehen,
             Greifer) -> Gelenkwerte ueber die Kinematik des SO-101 (remote_kin). Unerreichbares wird nicht
             angefahren; erreichbare Teilbewegungen und Rueckwege bleiben moeglich.
  chain      Gelenkwerte -> 3D-Punkte von Basis, Schulter, Ellbogen, Handgelenk, Spitze
  SimView    zeichnet Tisch, Arbeitsraum, Roboterarm (gemeldet) und Geister-Arm (dein Ziel) auf ein tk.Canvas;
             Maus ziehen dreht die Ansicht. Rein kinematisch (keine Physik) - sofort, ohne Netz-Verzoegerung.
"""
import itertools
import math
import remote_kin as K

# Taste -> (Groesse, Richtung). Deutsche und englische Tastaturen: keine Z/Y-Tasten.
KEYS = {
    "w": ("x", +1), "s": ("x", -1),          # vor / zurueck
    "a": ("y", +1), "d": ("y", -1),          # links / rechts (vom Roboter aus)
    "r": ("z", +1), "f": ("z", -1),          # hoch / runter
    "q": ("phi", -1), "e": ("phi", +1),      # Hand heben / senken
    "t": ("roll", +1), "g": ("roll", -1),    # Hand drehen
    "o": ("grip", -1), "l": ("grip", +1),    # Greifer auf / zu
}
HELP = ("W/S vor/zurueck · A/D links/rechts · R/F hoch/runter · Q/E Hand heben/senken\n"
        "T/G Hand drehen · O/L Greifer auf/zu · Umschalt = schneller · Leertaste = Steuern · Esc = Stop")
SPEED = {"x": 0.06, "y": 0.06, "z": 0.05, "phi": 0.8, "roll": 1.2, "grip": 1.2}   # m/s, rad/s, Anteil/s


def grip_fraction(ticks):
    """Greifer-Ticks -> 0 (offen) .. 1 (zu), Umkehrung von remote_kin.grip_ticks."""
    return min(1.0, max(0.0, (K.GRIP_OPEN - ticks) / (K.GRIP_OPEN - K.GRIP_CLOSED)))


class KeyTeleop:
    def __init__(self, joints=None):
        self.reset(joints or [K.MID] * 5 + [K.GRIP_CLOSED])

    def reset(self, joints):
        """Start an der aktuellen Roboterstellung (kein Sprung beim Kuppeln)."""
        j = {s: float(v) for s, v in zip(range(1, 7), joints)}
        self.pose = K.fk(j)
        self.roll = j[5]
        self.grip = grip_fraction(j[6])
        self.joints = [int(round(j[s])) for s in range(1, 6)]
        self.blocked = False

    def apply(self, keys, dt, fast=False):
        """keys: Menge gedrueckter Tasten (klein). Gibt True zurueck, wenn sich etwas geaendert hat."""
        self.blocked = False
        if not keys:
            return False
        k = (2.0 if fast else 1.0) * dt
        x, y, z, phi = self.pose
        d = {"x": 0.0, "y": 0.0, "z": 0.0, "phi": 0.0, "roll": 0.0, "grip": 0.0}
        for key in keys:
            if key in KEYS:
                what, sign = KEYS[key]
                d[what] += sign * SPEED[what] * k
        want = (x + d["x"], y + d["y"], z + d["z"], phi + d["phi"])
        if want != self.pose and not self._accept_pose(want):
            self.blocked = True
            # Nur die unzulaessige Richtung begrenzen. Eine zweite Taste darf
            # weiter entlang der Grenze oder zurueck in den Arbeitsraum fahren.
            for axis, delta in enumerate((d["x"], d["y"], d["z"], d["phi"])):
                if not delta:
                    continue
                start = self.pose
                candidate = list(start)
                candidate[axis] += delta
                if self._accept_pose(tuple(candidate)):
                    continue
                # Bis kurz vor die Grenze fahren, ohne ein unerreichbares
                # Ziel aufzusammeln, das spaeter erst zurueckgenommen werden muss.
                lo, hi = 0.0, 1.0
                for _ in range(12):
                    mid = (lo + hi) / 2
                    candidate[axis] = start[axis] + delta * mid
                    if self._accept_pose(tuple(candidate)):
                        lo = mid
                    else:
                        hi = mid
        lo, hi = K.LIMITS[5]
        self.roll = min(max(self.roll + K.ROLL_SIGN * d["roll"] * K.TICKS_PER_RAD, lo + K.JOINT_MARGIN), hi - K.JOINT_MARGIN)
        self.joints[4] = int(round(self.roll))
        self.grip = min(1.0, max(0.0, self.grip + d["grip"]))
        return True

    def _accept_pose(self, pose):
        """Nur erreichbare Ziele und auch nach Tick-Rundung sichere Gelenke uebernehmen."""
        sol = K.solve(pose)
        if sol is None:
            return False
        # Gesendet werden ganze Ticks. Auch deren reale Pose muss innerhalb
        # derselben Grenzen liegen (wichtig beim erneuten Kuppeln an einer Grenze).
        # An der Grenze kann einfaches Runden nach aussen zeigen. Dann den
        # naechsten sicheren Nachbar-Tick nehmen, statt seitliches Fahren zu sperren.
        options = itertools.product(*[(math.floor(sol[s]), math.ceil(sol[s])) for s in range(1, 5)])
        for values in sorted(set(options), key=lambda v: sum((v[s - 1] - sol[s]) ** 2 for s in range(1, 5))):
            rounded = dict(zip(range(1, 5), values))
            if K.joints_ok(rounded) and K.in_box(K.fk(rounded)) and K.heights(rounded)[2] >= 0.0:
                self.pose = pose
                self.joints[:4] = values
                return True
        return False

    def values(self):
        """(j1..j5, Greifer 0..1) wie vom Leader-Arm."""
        return list(self.joints), self.grip


def chain(joints):
    """Gelenkwerte [j1..j5(,j6)] -> Punkte (x, y, z) in Metern: Fuss, Schulter, Ellbogen, Handgelenk, Spitze."""
    j = {s: float(v) for s, v in zip(range(1, 6), joints)}
    a1 = K.ang(j[2])
    a2 = a1 + math.pi / 2 + K.ang(j[3])
    a3 = a2 + K.ang(j[4])
    yaw = K.BASE_SIGN * K.ang(j[1])
    pts, r, z = [(0.0, 0.0, 0.0), (0.0, 0.0, K.SHOULDER_H)], 0.0, K.SHOULDER_H
    for length, a in ((K.UPPER, a1), (K.FORE, a2), (K.HAND, a3)):
        r += length * math.sin(a)
        z += length * math.cos(a)
        pts.append((r * math.cos(yaw), r * math.sin(yaw), z))
    return pts


class SimView:
    """Kleine 3D-Ansicht auf einem tk.Canvas. draw(ziel, roboter) mit Gelenklisten (oder None)."""
    def __init__(self, canvas):
        self.c = canvas
        self.az, self.el = math.radians(-40), math.radians(25)
        self._drag = None
        canvas.bind("<ButtonPress-1>", lambda e: setattr(self, "_drag", (e.x, e.y, self.az, self.el)))
        canvas.bind("<B1-Motion>", self._move)
        self.last = (None, None, "")

    def _move(self, e):
        if self._drag:
            x0, y0, az, el = self._drag
            self.az = az + (e.x - x0) * 0.01
            self.el = min(max(el + (e.y - y0) * 0.01, math.radians(5)), math.radians(85))
            self.draw(*self.last)

    def project(self, p):
        w, h = int(self.c.winfo_width() or 320), int(self.c.winfo_height() or 260)
        x, y, z = p
        ca, sa = math.cos(self.az), math.sin(self.az)
        u = x * sa + y * ca
        v = x * ca - y * sa
        s = min(w, h) * 2.2
        return w / 2 + u * s, h * 0.72 - (z * math.cos(self.el) - v * math.sin(self.el)) * s

    def _line(self, pts, **kw):
        flat = [c for p in pts for c in self.project(p)]
        self.c.create_line(*flat, **kw)

    def draw(self, target=None, robot=None, note=""):
        self.last = (target, robot, note)
        c = self.c
        c.delete("all")
        for i in range(-3, 4):                                     # Tisch: Raster 10 cm
            self._line([(i * 0.1, -0.3, 0), (i * 0.1, 0.3, 0)], fill="#d8d8d8")
            self._line([(-0.3, i * 0.1, 0), (0.4, i * 0.1, 0)], fill="#d8d8d8")
        bx, by, bz = K.BOX["x"], K.BOX["y"], K.BOX["z"]            # Arbeitsraum-Kasten
        for z in bz:
            self._line([(bx[0], by[0], z), (bx[1], by[0], z), (bx[1], by[1], z), (bx[0], by[1], z), (bx[0], by[0], z)],
                       fill="#9fc5e8", dash=(3, 3))
        self._line([(0, 0, 0), (0.08, 0, 0)], fill="#b3261e", width=2)   # x = vorn
        if robot is not None:
            self._line(chain(robot), fill="#555555", width=7, capstyle="round")
        if target is not None:
            self._line(chain(target), fill="#2f6fb5", width=3, capstyle="round", dash=(6, 3))
        c.create_text(6, 6, anchor="nw", fill="#333", font=("Segoe UI", 8),
                      text="grau = Roboter (gemeldet) · blau = dein Ziel · Maus ziehen = drehen")
        if note:
            c.create_text(6, 22, anchor="nw", fill="#b3261e", font=("Segoe UI", 9, "bold"), text=note)
