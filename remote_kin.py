"""Kinematik und Arbeitsraum fuer die Fernsteuerung (reine Mathematik, keine Hardware).

Roboter-Koordinaten: Ursprung am Fuss der Basis auf der Tischplatte, x nach vorn (Arbeitsseite),
y nach links, z nach oben, Meter. Werkzeugpose = Greiferspitze (x, y, z) plus Neigung phi
der Hand gegen die Senkrechte (pi/2 = waagerecht nach vorn, pi = senkrecht nach unten).
Der SO-101 hat 5 Achsen: die Gierrichtung des Greifers ist immer die der Basis.

Das Modell nutzt dieselben Winkel wie so101.heights (dort an Logdaten geprueft).
"Vorn = positive Schulterwinkel" folgt aus der Greifpose vom 13.11. 15:19
(2351/1917/2841: Spitze ~19 cm vorn, ~7 cm hoch, zeigt nach unten).
Am 14.11. am Leader nur lesend gemessen (Follower uebernimmt Gelenke 1-5 1:1):
- Basis von hinten gesehen nach links: 1949 -> 1363, also links = kleinere Ticks (BASE_SIGN = -1).
- Handgelenk von hinten Richtung Spitze gegen den Uhrzeigersinn: 1848 -> 494 (ROLL_SIGN = -1).
- Greifer ganz offen -> Follower 2895 (Anschlag 2903), ganz zu -> Follower 1419 (Anschlag 1418).
"""
import json, math, os
from so101 import MID, SHOULDER_H, UPPER, FORE, HAND, CALDIR, heights

TICKS_PER_RAD = 4096 / (2 * math.pi)
BASE_SIGN = -1        # links (+y) = kleinere Ticks, gemessen
ROLL_SIGN = -1        # gegen den Uhrzeigersinn (von hinten) = kleinere Ticks, gemessen
# Greifer: 0 = offen, 1 = zu (Follower-Ticks, gemessen; ganz zu = 1419, etwas Abstand zum Anschlag)
GRIP_CLOSED = 1430
GRIP_OPEN = 2880

JOINT_MARGIN = 40                       # Ticks Abstand zu den Endanschlaegen
BOX = {"x": (0.10, 0.32), "y": (-0.20, 0.20), "z": (0.03, 0.30)}
PHI_RANGE = (1.2, math.pi)              # von leicht nach oben bis senkrecht nach unten
MIN_LINK_Z = 0.04                       # Ellbogen und Handgelenk mindestens so hoch ueber dem Tisch
MIN_R = 0.10                            # Spitze nicht naeher an der Basis-Achse


def _load_limits():
    try:
        cal = json.load(open(os.path.join(CALDIR, "follower_calibration.json")))
        return {int(s): (v["min"], v["max"]) for s, v in cal.items()}
    except (OSError, ValueError, KeyError):
        return {1: (870, 3253), 2: (835, 3242), 3: (887, 3086), 4: (904, 3181), 5: (0, 4095), 6: (1418, 2903)}


LIMITS = _load_limits()


def ang(ticks):
    return (ticks - MID) / TICKS_PER_RAD


def ticks(rad):
    return MID + rad * TICKS_PER_RAD


def _wrap_phi(a):
    """Neigung in [-pi/2, 3pi/2), damit 'nach unten' (pi) nicht am Sprung liegt."""
    return (a + math.pi / 2) % (2 * math.pi) - math.pi / 2


def fk(j):
    """Gelenkwerte (Ticks, dict 1..4) -> Werkzeugpose (x, y, z, phi)."""
    a1 = ang(j[2])
    a2 = a1 + math.pi / 2 + ang(j[3])
    a3 = a2 + ang(j[4])
    r = UPPER * math.sin(a1) + FORE * math.sin(a2) + HAND * math.sin(a3)
    yaw = BASE_SIGN * ang(j[1])
    return (r * math.cos(yaw), r * math.sin(yaw), heights(j)[2], _wrap_phi(a3))


def ik(pose):
    """Werkzeugpose -> Ticks fuer Basis, Schulter, Ellbogen, Handgelenk (Ellbogen oben), oder None."""
    x, y, z, phi = pose
    r = math.hypot(x, y)
    yaw = math.atan2(y, x)
    rw = r - HAND * math.sin(phi)
    zw = z - HAND * math.cos(phi) - SHOULDER_H
    c = (rw * rw + zw * zw - UPPER ** 2 - FORE ** 2) / (2 * UPPER * FORE)
    if not -1.0 <= c <= 1.0:
        return None
    delta = math.acos(c)
    a1 = math.atan2(rw, zw) - math.atan2(FORE * math.sin(delta), UPPER + FORE * math.cos(delta))
    a2 = a1 + delta
    return {1: ticks(BASE_SIGN * yaw), 2: ticks(a1), 3: ticks(delta - math.pi / 2), 4: ticks(phi - a2)}


def in_box(pose):
    x, y, z, phi = pose
    return (BOX["x"][0] <= x <= BOX["x"][1] and BOX["y"][0] <= y <= BOX["y"][1]
            and BOX["z"][0] <= z <= BOX["z"][1] and PHI_RANGE[0] <= phi <= PHI_RANGE[1]
            and math.hypot(x, y) >= MIN_R)


def clamp_box(pose):
    x, y, z, phi = pose
    c = (min(max(x, BOX["x"][0]), BOX["x"][1]), min(max(y, BOX["y"][0]), BOX["y"][1]),
         min(max(z, BOX["z"][0]), BOX["z"][1]), min(max(phi, PHI_RANGE[0]), PHI_RANGE[1]))
    return c, c != tuple(pose)


def joints_ok(j):
    for s, v in j.items():
        lo, hi = LIMITS[s]
        if not lo + JOINT_MARGIN <= v <= hi - JOINT_MARGIN:
            return False
    elbow, wrist, _ = heights(j)
    return elbow >= MIN_LINK_Z and wrist >= MIN_LINK_Z


def solve(pose):
    """Gelenkwerte, wenn die Pose im Arbeitsraum liegt und sicher erreichbar ist, sonst None."""
    if not in_box(pose):
        return None
    j = ik(pose)
    return j if j is not None and joints_ok(j) else None


def safe_target(last, desired):
    """Naechste sichere Pose auf dem Weg von 'last' (sicher) nach 'desired'.
    Gibt (pose, begrenzt) zurueck. begrenzt=True heisst: Grenze erreicht (fuer Haptik)."""
    want, clamped = clamp_box(desired)
    if solve(want) is not None:
        return want, clamped
    lo, hi = 0.0, 1.0
    for _ in range(16):
        mid = (lo + hi) / 2
        p = tuple(a + (b - a) * mid for a, b in zip(last, want))
        if solve(p) is not None:
            lo = mid
        else:
            hi = mid
    return tuple(a + (b - a) * lo for a, b in zip(last, want)), True


def grip_ticks(g):
    g = min(max(g, 0.0), 1.0)
    return GRIP_OPEN + (GRIP_CLOSED - GRIP_OPEN) * g
