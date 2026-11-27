"""3D-Modell des SO-101 (Follower) aus dem offiziellen URDF: Gelenkkette + Huelle/Pruefpunkte je Teil.

    m = Modell()
    welt = m.punkte(pose)          # alle Pruefpunkte in Metern, Koordinaten der Basis (siehe unten)
    teile = m.teile(pose)          # je Teil: (name, Huellen-Ecken in Welt, Flaechen) zum Zeichnen

Basis-Koordinaten (wie das URDF): Ursprung unten in der Mitte der Basis-Platte auf dem Tisch, z nach oben.
Servo -> URDF-Winkel: (Servowert - Mitte) * 2*pi/4096 * Vorzeichen. Mitte ist 2047 (bzw. die Mitte der
Basis-Anschlaege fuer die Basis). Die Vorzeichen sind so gewaehlt, dass unsere Mittelstellung (Oberarm
senkrecht, Unterarm waagerecht nach vorn) und die Drehrichtungen zum echten Arm passen (siehe SIGN).
"""
import json, math, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(HERE, "modell", "so101.json")
STEP_RAD = 2 * math.pi / 4096
MID = 2047
SERVO = {"shoulder_pan": 1, "shoulder_lift": 2, "elbow_flex": 3, "wrist_flex": 4, "wrist_roll": 5, "gripper": 6}
SIGN = {"shoulder_pan": 1, "shoulder_lift": 1, "elbow_flex": 1, "wrist_flex": 1, "wrist_roll": 1, "gripper": 1}
ZERO = {}
GRIP_CLOSED_RAD = -0.19          # bei diesem Modell-Winkel liegen die Backenspitzen aneinander (nachgemessen)
GRIP_OPEN_RAD = 1.745             # Backe ganz auf (URDF-Grenze); ganz zu = 0                         # Winkel im URDF bei Servo-Mitte (rad), falls die Nullstellungen nicht passen


def _rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _axis_rot(axis, a):
    x, y, z = axis
    c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


class Modell:
    def __init__(self, path=MODEL_FILE):
        data = json.load(open(path))
        self.links = {}
        for k, v in data["links"].items():
            hv = np.array(v["huelle"])
            c = hv.mean(axis=0)
            faces = []
            for a, b, d in v["flaechen"]:                   # Flaechen nach aussen ausrichten (fuers Zeichnen)
                n = np.cross(hv[b] - hv[a], hv[d] - hv[a])
                faces.append([a, b, d] if np.dot(n, hv[a] - c) >= 0 else [a, d, b])
            self.links[k] = {"huelle": hv, "flaechen": faces, "punkte": np.array(v["punkte"])}
        self.joints = data["joints"]
        self.order = []                                    # Gelenke in Reihenfolge von der Basis aus
        done = {"base_link"}
        while len(self.order) < len(self.joints):
            for j in self.joints:
                if j["parent"] in done and j not in self.order:
                    self.order.append(j)
                    done.add(j["child"])
        for j in self.order:
            j["_R"] = _rpy(*j["rpy"])
            j["_t"] = np.array(j["xyz"])
        self.moving = [k for k in self.links if k != "base_link"]

    def angles(self, pose, base_center=MID, grip=None):
        """grip: (Servowert zu, Servowert auf) aus der Anschlag-Messung -> Backe 0 (zu) .. GRIP_OPEN_RAD (auf)."""
        out = {}
        for name, s in SERVO.items():
            if s in pose and pose[s] is not None:
                mid = base_center if s == 1 else MID
                out[name] = ZERO.get(name, 0.0) + SIGN[name] * (pose[s] - mid) * STEP_RAD
        if grip and 6 in pose and grip[1] != grip[0]:
            d = 1 if grip[1] > grip[0] else -1           # Servo treibt die Backe direkt: 1 Schritt = 1 Schritt Winkel
            out["gripper"] = max(-0.6, min(2.3, GRIP_CLOSED_RAD + d * (pose[6] - grip[0]) * STEP_RAD))
        return out

    def frames(self, angles):
        """Link -> (R, t) in Basis-Koordinaten."""
        fr = {"base_link": (np.eye(3), np.zeros(3))}
        for j in self.order:
            R0, t0 = fr[j["parent"]]
            R = R0 @ j["_R"]
            t = t0 + R0 @ j["_t"]
            if j["type"] == "revolute":
                R = R @ _axis_rot(j["axis"], angles.get(j["name"], 0.0))
            fr[j["child"]] = (R, t)
        for k in self.links:                                # Teil-Huellen (name#abschnitt) haengen am Teil
            if "#" in k:
                fr[k] = fr[k.split("#")[0]]
        return fr

    def punkte(self, pose, base_center=MID, links=None, grip=None):
        """Alle Pruefpunkte der beweglichen Teile (bzw. 'links') als (N, 3) in Basis-Koordinaten."""
        fr = self.frames(self.angles(pose, base_center, grip))
        parts = []
        for k in (links or self.moving):
            R, t = fr[k]
            parts.append(self.links[k]["punkte"] @ R.T + t)
        return np.vstack(parts)

    def teile(self, pose, base_center=MID, grip=None):
        fr = self.frames(self.angles(pose, base_center, grip))
        out = []
        for k, L in self.links.items():
            R, t = fr[k]
            out.append((k, L["huelle"] @ R.T + t, L["flaechen"]))
        return out

    def spitze(self, pose, base_center=MID):
        fr = self.frames(self.angles(pose, base_center))
        R, t = fr.get("gripper_frame_link", fr["gripper_link"])
        return t
