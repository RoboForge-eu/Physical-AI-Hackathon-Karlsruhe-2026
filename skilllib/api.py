"""'robot' fuer Code-Skills. Nur diese Methoden gibt es; alles geht ueber den Harness (Sicherheit dort).

  robot.pose(name)                    feste Pose anfahren (vor Ort gemerkt)
  robot.posen()                       Namen der gemerkten Posen
  robot.greifer(prozent)              0 = zu, 100 = ganz auf
  robot.greifer_haelt() -> bool       steckt etwas im Greifer? (aus der Greiferstellung)
  robot.faehigkeit(modell, sekunden)  gelernte VLA-Faehigkeit ausfuehren
  robot.skill(name, **params)         anderen Code-Skill ausfuehren (Bibliothek waechst)
  robot.kamera(name) -> str           Kamerabild (JPEG, Base64) - fuer robot.frage
  robot.frage(frage, optionen, kamera=None) -> str   Entscheidungspunkt: ein Sprachmodell waehlt eine Option
  robot.stellung() -> [6 Werte]       aktuelle Gelenkstellung
  robot.warte(sekunden)
  robot.log(text)

Agentic-Werkzeuge (Feinarbeit in schneller Schleife, siehe AGENTIC.md):
  robot.messen(ziel="oeffnung", kamera="arm", groesse_mm=20, marker_id=None) -> dict
        ziel: "oeffnung" | "marker" | "kreis". Liefert gefunden, abstand_mm, korrektur_mm [dx, dy]
        (Werkzeugbewegung, die das Merkmal unter die Spitze bringt; nur mit Kalibrierung), messbild (Pfad)
  robot.kalibrieren(schritt_mm=3)     Handgelenk-Kamera am Marker kalibrieren (zwei kleine Testbewegungen)
  robot.korrektur(dx=0, dy=0, dz=0)   kleine kartesische Korrektur der Spitze in mm (max. 5 mm je Achse, langsam)
  robot.kontakt() -> dict             zustand "frei"/"beruehrt", fehler_z_mm, last, ereignisse seit letztem Aufruf
        (je {"art": "angestossen"|"abgesackt"|"frei", "text", "t"}) - Kontakt ohne Kraftsensor
  robot.zeit() -> float               Sekunden seit Skill-Start (in der Simulation: Simulationszeit)
"""
import time


class SkillAbort(Exception):
    pass


class RobotAPI:
    def __init__(self, ros, arm, log=print, decide=None, run_skill=None, max_s=600):
        self.ros, self.arm, self._log = ros, arm, log
        self._decide, self._run_skill = decide, run_skill
        self._t0, self._max = time.monotonic(), max_s
        self.calls = []
        self._t_sim0 = float(ros.call("zeit")["t"]) if str(arm).startswith("sim_") else 0.0

    def _call(self, what, **args):
        if time.monotonic() - self._t0 > self._max:
            raise SkillAbort(f"Skill laeuft laenger als {self._max} s")
        self.calls.append((what, args))
        return self.ros.call(what, timeout=300, arm=self.arm, **args)

    def pose(self, name, grad_pro_s=30):
        r = self._call("pose.anfahren", name=name, grad_pro_s=grad_pro_s)
        self._log(f"pose {name}: {'erreicht' if r.get('erreicht') else 'NICHT erreicht'}")
        return bool(r.get("erreicht"))

    def posen(self):
        return sorted(self._call("pose.liste"))

    def greifer(self, prozent):
        self._call("greifer.setzen", prozent=max(0, min(100, float(prozent))))

    def greifer_haelt(self):
        r = self._call("greifer.pruefen")
        self._log(f"greifer haelt etwas: {r.get('haelt_etwas')}")
        return bool(r.get("haelt_etwas"))

    def faehigkeit(self, modell, sekunden=10, aufgabe=None):
        args = {"modell": modell, "sekunden": float(sekunden)}
        if aufgabe:
            args["aufgabe"] = aufgabe
        return self._call("modell.ausfuehren", **args)

    def skill(self, name, **params):
        if self._run_skill is None:
            raise SkillAbort("Andere Skills koennen hier nicht aufgerufen werden")
        return self._run_skill(name, params)

    def kamera(self, name="turm"):
        return self.ros.call("kamera.bild", arm=self.arm, kamera=name)["jpeg_base64"]

    def frage(self, frage, optionen, kamera=None):
        optionen = [str(o) for o in optionen]
        bild = self.kamera(kamera) if kamera else None
        if self._decide is None:
            raise SkillAbort("Kein Entscheider verfuegbar")
        antwort = self._decide(frage, optionen, bild)
        if antwort not in optionen:
            antwort = optionen[0]
        self._log(f"frage '{frage}' -> {antwort}")
        return antwort

    def stellung(self):
        return self._call("arm.stellung")["stellung"]

    def warte(self, sekunden):
        if self._ist_sim:
            self.ros.call("warte", sekunden=min(float(sekunden), 30))
        else:
            time.sleep(min(float(sekunden), 30))

    @property
    def _ist_sim(self):
        return str(self.arm).startswith("sim_")

    def messen(self, ziel="oeffnung", kamera="arm", groesse_mm=20, marker_id=None):
        args = {"kamera": kamera, "ziel": ziel, "groesse_mm": float(groesse_mm)}
        if marker_id is not None:
            args["marker_id"] = int(marker_id)
        r = self._call("vision.messen", **args)
        self._log(f"messen {ziel}: " + (f"{r.get('abstand_mm', r.get('abstand_px'))} mm/px, Korrektur {r.get('korrektur_mm')}"
                                        if r.get("gefunden") else "nicht gefunden"))
        return r

    def kalibrieren(self, schritt_mm=3):
        r = self._call("vision.kalibrieren", schritt_mm=float(schritt_mm))
        self._log("Handgelenk-Kamera kalibriert")
        return r

    def korrektur(self, dx=0.0, dy=0.0, dz=0.0):
        return self._call("arm.korrektur", dx_mm=float(dx), dy_mm=float(dy), dz_mm=float(dz))

    def kontakt(self):
        return self._call("arm.kontakt")

    def zeit(self):
        if self._ist_sim:
            return float(self.ros.call("zeit")["t"]) - self._t_sim0
        return round(time.monotonic() - self._t0, 2)

    def log(self, text):
        self._log(str(text)[:300])


class DryRunAPI(RobotAPI):
    """Trockenlauf: kein Arm bewegt sich. Prueft, ob es Posen und Modelle gibt, und spielt Antworten vor.
    greifer_haelt / frage folgen einem Drehbuch, damit der Agent auch Fehlerpfade testen kann."""
    def __init__(self, ros, arm, log=print, posen=None, modelle=None, haelt=(True,), antworten=None, **kw):
        super().__init__(ros, arm, log, **kw)
        self._posen, self._modelle = set(posen or []), set(modelle or [])
        self._haelt, self._antworten = list(haelt), list(antworten or [])
        self._greifer = 0

    def _sim(self, what, **args):
        self.calls.append((what, args))

    def pose(self, name, grad_pro_s=30):
        self._sim("pose.anfahren", name=name)
        if name not in self._posen:
            raise SkillAbort(f"Pose {name!r} gibt es nicht. Vorhanden: {sorted(self._posen)}")
        self._log(f"[trocken] pose {name}")
        return True

    def posen(self):
        return sorted(self._posen)

    def greifer(self, prozent):
        self._sim("greifer.setzen", prozent=prozent)
        self._greifer = float(prozent)

    def greifer_haelt(self):
        self._sim("greifer.pruefen")
        value = self._haelt.pop(0) if len(self._haelt) > 1 else self._haelt[0]
        self._log(f"[trocken] greifer haelt etwas: {value}")
        return bool(value)

    def faehigkeit(self, modell, sekunden=10, aufgabe=None):
        self._sim("modell.ausfuehren", modell=modell, sekunden=sekunden)
        if modell not in self._modelle:
            raise SkillAbort(f"Modell {modell!r} gibt es nicht. Vorhanden: {sorted(self._modelle)}")
        self._log(f"[trocken] faehigkeit {modell} {sekunden} s")
        return {"schritte": int(30 * float(sekunden))}

    def kamera(self, name="turm"):
        self._sim("kamera.bild", kamera=name)
        return ""

    def frage(self, frage, optionen, kamera=None):
        self._sim("frage", frage=frage)
        optionen = [str(o) for o in optionen]
        antwort = self._antworten.pop(0) if self._antworten else optionen[0]
        self._log(f"[trocken] frage '{frage}' -> {antwort}")
        return antwort if antwort in optionen else optionen[0]

    def stellung(self):
        return [2047] * 6

    def warte(self, sekunden):
        self._sim("warte", sekunden=sekunden)

    def messen(self, ziel="oeffnung", kamera="arm", groesse_mm=20, marker_id=None):
        self._sim("vision.messen", ziel=ziel)
        return {"gefunden": True, "abstand_mm": 0.2, "korrektur_mm": [0.0, 0.0], "messbild": None}

    def kalibrieren(self, schritt_mm=3):
        self._sim("vision.kalibrieren")
        return {}

    def korrektur(self, dx=0.0, dy=0.0, dz=0.0):
        self._sim("arm.korrektur", dx_mm=dx, dy_mm=dy, dz_mm=dz)
        return {}

    def kontakt(self):
        self._sim("arm.kontakt")
        self._k = getattr(self, "_k", 0) + 1
        ev = [{"art": "angestossen", "text": "[trocken] angestossen", "t": 0}] if self._k == 3 else              [{"art": "abgesackt", "text": "[trocken] abgesackt", "t": 0}] if self._k == 6 else []
        return {"zustand": "beruehrt" if 3 <= self._k else "frei", "fehler_z_mm": 0, "ereignisse": ev}

    def zeit(self):
        return 0.1 * len(self.calls)
