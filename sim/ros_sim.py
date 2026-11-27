"""Simulierter Harness fuer Code-Skills: dieselben Befehle wie ki/ros_skills.py (call(name, **args)),
aber gegen eine Simulation (Backend 'kinsim' = sim.welt.Welt, spaeter Isaac mit denselben Methoden).

So laufen skilllib-Skills (run(robot, ...)) unveraendert in der Simulation: RobotAPI(SimRos(...), "sim_follower").
Die Zeit ist Simulationszeit (warte() rechnet vor, statt zu schlafen) -> 20 Versuche dauern Sekunden.
"""
import base64, math
import cv2
import remote_kin as K
from regel import kartesisch, werkzeuge
from regel.kontakt import KontaktMelder
from .welt import Welt
from . import is_sim_arm

GRAD = 4096 / 360


def sim_posen(welt):
    """Gemerkte Posen der Simulation (aus der Szene gerechnet, wie 'pose.merken' am echten Arm)."""
    sz = welt.szene
    def p(x, y, z, phi=math.pi):
        j = K.ik((x, y, z, phi))
        return [int(round(j[1])), int(round(j[2])), int(round(j[3])), int(round(j[4])), 2047, 2000]
    sch, pal, lo = sz.schachtel, sz.palette, sz.loch
    return {"start": [2047, 1300, 2700, 2900, 2047, 2000],
            "ueber_schachtel": p(sch["x"], sch["y"], 0.07), "an_schachtel": p(sch["x"], sch["y"], 0.03),
            "ueber_palette": p(pal["x"], pal["y"], 0.07), "auf_palette": p(pal["x"], pal["y"], 0.035),
            "ueber_oeffnung": p(sz.halter["x"], sz.halter["y"], sz.halter["h"] + 0.012)}


class SimRos:
    def __init__(self, welt=None, arm="sim_follower", backend=None, posen=None, kalib=None):
        if not is_sim_arm(arm):
            raise ValueError(f"Simulierte Arme heissen sim_...; {arm!r} sieht aus wie ein echter Arm")
        self.welt = welt or backend or Welt()
        self.arm = arm
        self.posen = posen if posen is not None else sim_posen(self.welt)
        self.melder = KontaktMelder()
        self.kalib = kalib
        self.messungen = []
        self.greifer = {"zu": self.welt.greifer_zu, "auf": self.welt.greifer_auf}

    # --- Zeit und Fahren ---
    def laufen(self, sekunden):
        n = max(1, int(round(sekunden * 100)))
        for _ in range(n):
            self.welt.schritt(1)
            self.melder.probe(self.welt.t, self.welt.soll, self.welt.ist, self.welt.last())

    def fahre(self, ziel, grad_pro_s=30, joints=range(6), tol=8):
        start = list(self.welt.soll)
        weg = max(abs(ziel[i] - start[i]) for i in joints) or 1
        n = max(1, int(weg / (grad_pro_s * GRAD) * 100))
        for k in range(1, n + 1):
            self.welt.setze_soll([start[i] + (ziel[i] - start[i]) * k / n if i in joints else start[i] for i in range(6)])
            self.laufen(0.01)
        self.laufen(0.3)
        st = self.welt.stellung()
        return all(abs(st[i] - ziel[i]) <= tol for i in joints if i != 5), st

    def _check(self, arm):
        if arm != self.arm:
            raise ValueError(f"Unbekannter Arm {arm!r} (Simulation: {self.arm})")

    # --- Befehle wie im Harness ---
    def call(self, befehl, timeout=None, **a):
        fn = getattr(self, "_" + befehl.replace(".", "_"), None)
        if fn is None:
            raise RuntimeError(f"{befehl} gibt es in der Simulation nicht")
        if "arm" in a:
            self._check(a.pop("arm"))
        return fn(**a)

    def _pose_liste(self):
        return dict(self.posen)

    def _pose_anfahren(self, name, grad_pro_s=30):
        if name not in self.posen:
            raise RuntimeError(f"Pose {name!r} gibt es nicht")
        ziel = list(self.posen[name][:5]) + [self.welt.soll[5]]
        ok, st = self.fahre(ziel, min(60, grad_pro_s), joints=range(5))
        return {"erreicht": ok, "pose": name, "ist": st}

    def _greifer_setzen(self, prozent):
        v = self.greifer["zu"] + (self.greifer["auf"] - self.greifer["zu"]) * float(prozent) / 100
        ziel = list(self.welt.soll)
        ziel[5] = v
        _, st = self.fahre(ziel, 40, joints=[5], tol=10 ** 6)
        return {"ziel": int(v), "ist": st[5], "prozent": prozent}

    def _greifer_pruefen(self):
        zu = abs(self.welt.soll[5] - self.greifer["zu"]) <= 30
        gap = abs(self.welt.ist[5] - self.greifer["zu"])
        return {"haelt_etwas": bool(zu and gap > 40), "greifer_geschlossen_befohlen": zu}

    def _arm_stellung(self):
        return {"stellung": self.welt.stellung()}

    def _kamera_bild(self, kamera="arm"):
        ok, jpg = cv2.imencode(".jpg", cv2.resize(self.welt.bild(kamera), (480, 270)))
        return {"jpeg_base64": base64.b64encode(jpg.tobytes()).decode()}

    def _modell_ausfuehren(self, modell, sekunden, aufgabe=None):
        raise RuntimeError("VLA-Modelle laufen in der Simulation ueber sim_worker.py + KI-Fahrer, nicht im Skill-Trockenlauf")

    # --- Agentic-Werkzeuge ---
    def _vision_messen(self, kamera="arm", ziel="oeffnung", groesse_mm=20.0, marker_id=None):
        r = werkzeuge.messen(self.welt.bild(kamera), ziel, self.kalib, groesse_mm, marker_id, name=f"sim-{ziel}")
        r.pop("_bild", None)
        self.messungen.append(r["messbild"])
        return r

    def _vision_kalibrieren(self, schritt_mm=3.0, groesse_mm=20.0):
        """Kalibrierung der Handgelenk-Kamera mit zwei Testbewegungen am Marker (siehe vision/kalib.py).
        Werkzeugpunkt ist in der Simulation aus dem Kameramodell bekannt."""
        def mitte():
            r = werkzeuge.messen(self.welt.bild("arm"), "marker", None, groesse_mm, name="kalib")
            if not r["gefunden"]:
                raise RuntimeError("Kein Marker im Bild der Handgelenk-Kamera")
            return r["merkmal_px"], r["mm_pro_px"]
        self.kalib = werkzeuge.kalibrieren(mitte, lambda dx, dy: self._arm_korrektur(dx_mm=dx, dy_mm=dy), schritt_mm,
                                           self.welt.werkzeugpunkt_px(), hoehe_mm=round(self.welt.spitze()[2] * 1000, 1))
        return self.kalib.to_dict()

    def _arm_korrektur(self, dx_mm=0.0, dy_mm=0.0, dz_mm=0.0):
        neu, sp = kartesisch.korrektur([int(round(v)) for v in self.welt.soll], dx_mm, dy_mm, dz_mm)
        ok, st = self.fahre(neu, 10, joints=range(5), tol=10 ** 6)
        x, y, z, _ = self.welt.spitze()
        return {"spitze_soll_mm": [round(v * 1000, 1) for v in sp[:3]], "spitze_ist_mm": [round(v * 1000, 1) for v in (x, y, z)]}

    def _arm_kontakt(self):
        return self.melder.abholen()

    def _zeit(self):
        return {"t": round(self.welt.t, 3)}

    def _warte(self, sekunden):
        self.laufen(float(sekunden))
        return {}


def szenario(name="standard", seed=0, zufall=True, spiel_mm=0.5, versatz_mm=4.0):
    """Fertige Simulationslage fuer Skill-Tests:
      'standard'   Szene mit Domain Randomization (zufall), Posen aus der Szene
      'einstecken' zusaetzlich: Lochspiel spiel_mm, Pose 'ueber_oeffnung' liegt zufaellig bis versatz_mm daneben
                   (wie ein VLA, das das Teil nur grob hinbringt)."""
    import numpy as np
    w = Welt(seed=seed, zufall=zufall)
    ros = SimRos(w)
    if name == "einstecken":
        w.szene.loch["r"] = w.szene.stift_r + spiel_mm / 1000
        w.szene._tex = None
        off = np.random.default_rng(seed + 1000).uniform(-versatz_mm, versatz_mm, 2) / 1000
        h = w.szene.halter
        j = K.ik((h["x"] + off[0], h["y"] + off[1], h["h"] + 0.012, math.pi))
        ros.posen["ueber_oeffnung"] = [int(round(j[s])) for s in (1, 2, 3, 4)] + [2047, 2000]
        ros.startversatz_mm = [round(float(v) * 1000, 2) for v in off]
    elif name != "standard":
        raise ValueError(f"Unbekanntes Szenario {name!r} (standard, einstecken)")
    return ros
