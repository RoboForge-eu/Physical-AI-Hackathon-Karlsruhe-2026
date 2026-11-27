"""Harness-Seite des Isaac-Backends: gleiche Methoden wie sim.welt.Welt (setze_soll, schritt, stellung, last,
bild, spitze, soll, ist, t). Startet sim/isaac/server.py in der Isaac-Umgebung und spricht JSON-Zeilen.

Setzt NIE OMNI_KIT_ACCEPT_EULA: die Lizenz akzeptiert der Nutzer selbst beim ersten Start.
"""
import json, os, subprocess
import numpy as np
import remote_kin as K

ISAAC_PY = os.environ.get("ISAAC_PYTHON", os.path.join(os.path.expanduser("~"), "isaac-env", "Scripts", "python.exe"))
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ki_daten", "isaac_server.log")
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")


class IsaacBackend:
    def __init__(self, seed=0, zufall=False, headless=True, python=ISAAC_PY):
        env = {k: v for k, v in os.environ.items() if k != "OMNI_KIT_ACCEPT_EULA"}
        cmd = [python, "-u", SERVER, "--seed", str(seed)] + (["--zufall"] if zufall else []) + \
              ([] if headless else ["--visualizer", "kit"])   # Isaac Lab 3.0: ohne --visualizer = kein Fenster
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(LOG, "wb"), env=env)   # Fehler -> Log
        hallo = self._lesen()
        if not hallo.get("bereit"):
            raise RuntimeError(f"Isaac-Server nicht bereit: {hallo}")
        from sim.welt import Szene
        self.szene = Szene(np.random.default_rng(seed), zufall)   # gleiche Lage wie kinsim, Isaac baut sie nach
        sz = self.szene
        self._rufe("szene", palette=sz.palette, schachtel={k: v for k, v in sz.schachtel.items() if k != "farbe"},
                   farbe=[c / 255 for c in sz.schachtel["farbe"]], halter=sz.halter, loch=sz.loch, marker=sz.marker,
                   licht={"gain": float(sz.licht["gain"]), "tint": [float(v) for v in sz.licht["tint"]]},
                   turm_versatz=[float(v) for v in sz.turm_versatz])
        self.t, self.soll, self.ist, self._last = 0.0, [2047.0] * 6, [2047.0] * 6, [0] * 6
        self.greifer_zu, self.greifer_auf = 1430, 2880
        self._zustand(self._rufe("zustand"))

    def _lesen(self):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("Isaac-Server beendet")
            if line.startswith(b"{"):
                return json.loads(line)

    def _rufe(self, cmd, **a):
        self.p.stdin.write((json.dumps({"cmd": cmd, **a}) + "\n").encode())
        self.p.stdin.flush()
        r = self._lesen()
        if "fehler" in r:
            raise RuntimeError(r["fehler"])
        return r

    def _zustand(self, r):
        self.t, self.ist, self._last = r["t"], [float(v) for v in r["ist"]], r["last"]

    def setze_soll(self, ticks):
        self.soll = [float(v) for v in ticks]

    def schritt(self, n=1):
        self._zustand(self._rufe("schritt", soll=[int(round(v)) for v in self.soll], n=int(n)))

    def stellung(self):
        return [int(round(v)) for v in self.ist]

    def last(self):
        return list(self._last)

    def spitze(self, j=None):
        j = j or self.ist
        return K.fk({1: j[0], 2: j[1], 3: j[2], 4: j[3]})

    def bild(self, kamera="arm"):
        r = self._rufe("bild", kamera=kamera)
        n = r["bytes"]
        data = self.p.stdout.read(n)
        return np.frombuffer(data, np.uint8).reshape(r["h"], r["w"], 3)

    def werkzeugpunkt_px(self):
        return self._rufe("werkzeugpunkt")["px"]

    def schliessen(self):
        try:
            self._rufe("ende")
        except Exception:
            pass
        self.p.kill()
