"""Tests: Karton in der Uebersichtskamera (synthetische Szene), Anflug-Formel, Feinausrichten (Servo)."""
import copy, math, os, tempfile, unittest
import numpy as np
import cv2

from vision import karton as KA, marker as MK
from aufnahme import anflug as A


def look_at(cam, ziel):
    """Rotation Plan -> Kamera (OpenCV: z nach vorn, y nach unten)."""
    z = np.array(ziel, float) - cam
    z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.stack([x, y, z])


def szene(cfg, platz, cam=(45.0, -35.0, 70.0), ziel=(0, 22, 0), hfov=70.0, w=1280, h=720, kasten_grau=105, klappen=0.0, plus=0.0):
    cam = np.array(cam, float)
    R = look_at(cam, ziel)
    K = KA.kamera_matrix(w, h, hfov)
    P = K @ np.hstack([R, (-R @ cam)[:, None]])

    def proj(X):
        q = P @ np.append(X, 1.0)
        return q[:2] / q[2]
    img = np.full((h, w, 3), 225, np.uint8)
    # Karton: alle 8 Ecken, konvexe Huelle dunkel (Waende + Oberkante)
    from aufnahme import geometrie as G
    pts = []
    for zz in (0.0, cfg["karton_hoehe"]):
        for x, y in G.corners(platz["x"], platz["y"], platz["winkel"], cfg["laenge"], cfg["breite"]):
            pts.append(proj([x, y, zz]))
    hull = cv2.convexHull(np.array(pts, np.float32)).astype(np.int32)
    cv2.fillConvexPoly(img, hull, (kasten_grau,) * 3)
    if klappen:                                   # offene Klappen: flach nach aussen an den langen Seiten
        c4 = G.corners(platz["x"], platz["y"], platz["winkel"], cfg["laenge"], cfg["breite"])
        cx, cy = platz["x"], platz["y"]
        for i, j in ((0, 1), (2, 3)):
            (ax, ay), (bx, by) = c4[i], c4[j]
            mx, my = (ax + bx) / 2 - cx, (ay + by) / 2 - cy
            n = math.hypot(mx, my)
            ox, oy = mx / n * klappen, my / n * klappen
            poly = [proj([ax, ay, cfg["karton_hoehe"]]), proj([bx, by, cfg["karton_hoehe"]]),
                    proj([bx + ox, by + oy, cfg["karton_hoehe"] - 3]), proj([ax + ox, ay + oy, cfg["karton_hoehe"] - 3])]
            cv2.fillConvexPoly(img, np.array(poly, np.int32), (kasten_grau + 15,) * 3)
    if plus:                                      # alle vier Klappen flach aufgeklappt (wie in den Aufnahmen)
        c4 = G.corners(platz["x"], platz["y"], platz["winkel"], cfg["laenge"], cfg["breite"])
        for i in range(4):
            (ax, ay), (bx, by) = c4[i], c4[(i + 1) % 4]
            mx, my = (ax + bx) / 2 - platz["x"], (ay + by) / 2 - platz["y"]
            n = math.hypot(mx, my)
            ox, oy = mx / n * plus, my / n * plus
            poly = [proj([ax, ay, cfg["karton_hoehe"]]), proj([bx, by, cfg["karton_hoehe"]]),
                    proj([bx + ox, by + oy, 0.5]), proj([ax + ox, ay + oy, 0.5])]
            cv2.fillConvexPoly(img, np.array(poly, np.int32), (kasten_grau + 10,) * 3)
    for mid, m in cfg["marker"].items():
        Rpm, tpm = KA.marker_lage(m)
        s = m["mm"] / 10.0
        ecken = [proj(Rpm @ np.array(c) + tpm) for c in
                 ([-s / 2, s / 2, 0], [s / 2, s / 2, 0], [s / 2, -s / 2, 0], [-s / 2, -s / 2, 0])]
        # nur zeichnen, wenn die Vorderseite zur Kamera zeigt
        normal = Rpm @ np.array([0, 0, 1.0])
        if np.dot(normal, cam - tpm) <= 0:
            continue
        mk = cv2.cvtColor(MK.erzeugen(int(mid), seite_px=300, rand_px=50), cv2.COLOR_GRAY2BGR)
        n = mk.shape[0]
        src = np.array([[50, 50], [350, 50], [350, 350], [50, 350]], np.float32)
        H = cv2.getPerspectiveTransform(src, np.array(ecken, np.float32))
        warp = cv2.warpPerspective(mk, H, (w, h), borderValue=(0, 0, 0))
        maske = cv2.warpPerspective(np.full((n, n), 255, np.uint8), H, (w, h))
        img[maske > 0] = warp[maske > 0]
    return img


class KartonSucheTest(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(KA.DEFAULT)
        self.cfg["hfov"] = 70.0                       # wie szene()
        self.cfg["klappe"] = 0.0                      # Szenen ohne flach offene Klappen
        self.cfg["kanten"] = False                    # synthetische Szene hat keine Kartonkanten im Inneren
        self.cfg["hell_max"] = 170                    # synthetische Szene: grauer Karton, keine Farbe

    def pruefe(self, cfg, platz, **kw):
        img = szene(cfg, platz, **kw)
        r = KA.finden(img, cfg)
        self.assertTrue(r["gefunden"], r)
        p = r["platzierung"]
        self.assertLess(math.hypot(p["x"] - platz["x"], p["y"] - platz["y"]), 3.0, (p, platz))
        dw = abs((p["winkel"] - platz["winkel"] + 90) % 180 - 90)
        self.assertLess(dw, 5.0, (p, platz))
        return r

    def test_flacher_marker(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["marker"]["11"]
        for platz in ({"x": -12.5, "y": 25.6, "winkel": 116.0}, {"x": 10.0, "y": 28.0, "winkel": 20.0},
                      {"x": 0.0, "y": 30.0, "winkel": 0.0}):
            self.pruefe(cfg, platz)

    def test_senkrechter_marker_hinten(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["marker"]["10"]
        r = self.pruefe(cfg, {"x": 8.0, "y": 27.0, "winkel": 160.0}, cam=(30.0, -55.0, 60.0))
        self.assertEqual(r["marker"], 11)

    def test_turm_woanders(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["marker"]["11"]
        for cam in ((-50.0, -20.0, 75.0), (60.0, 10.0, 80.0)):
            self.pruefe(cfg, {"x": 5.0, "y": 26.0, "winkel": 100.0}, cam=cam)

    def test_offene_klappen(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["marker"]["11"]
        for platz in ({"x": 0.0, "y": 28.0, "winkel": 0.0}, {"x": -8.0, "y": 27.0, "winkel": 120.0}):
            img = szene(cfg, platz, klappen=5.0)        # bis etwa 5 cm Klappen eindeutig
            r = KA.finden(img, cfg)
            self.assertTrue(r["gefunden"], r)
            p = r["platzierung"]
            self.assertLess(math.hypot(p["x"] - platz["x"], p["y"] - platz["y"]), 4.0, (p, platz))
            self.assertLess(abs((p["winkel"] - platz["winkel"] + 90) % 180 - 90), 8.0, (p, platz))

    def test_ohne_marker(self):
        img = np.full((720, 1280, 3), 225, np.uint8)
        self.assertFalse(KA.finden(img, self.cfg)["gefunden"])

    def test_einmessen(self):
        wahr = copy.deepcopy(self.cfg)
        del wahr["marker"]["11"]
        wahr["marker"]["10"].update(x=3.0, y=-7.5, dreh=12.0)
        wahr["hfov"] = 78.0
        soll = {"x": 0.0, "y": 28.0, "winkel": 90.0}
        img = szene(wahr, soll, hfov=78.0)
        start = copy.deepcopy(self.cfg)
        start["hfov_suchen"] = True
        del start["marker"]["11"]
        neu, guete, mid = KA.einmessen(img, soll, start)
        self.assertEqual(mid, 10)
        self.assertLess(abs(neu["hfov"] - 78.0), 6)
        m = neu["marker"]["10"]
        self.assertLess(math.hypot(m["x"] - 3.0, m["y"] + 7.5), 2.0, m)
        self.assertLess(abs(m["dreh"] - 12.0), 4.0, m)
        # danach eine andere Platzierung richtig finden
        platz = {"x": -10.0, "y": 27.0, "winkel": 130.0}
        r = KA.finden(szene(wahr, platz, hfov=78.0), neu)
        self.assertTrue(r["gefunden"], r)
        self.assertLess(math.hypot(r["platzierung"]["x"] + 10, r["platzierung"]["y"] - 27), 3.0, r)


class KameraKalibTest(unittest.TestCase):
    def test_brennweite_aus_schachbrett(self):
        from vision import kamerakalib as KK
        w, h, f = 1280, 720, 600.0
        K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
        sq = 60
        brett = np.full((9 * sq, 12 * sq), 255, np.uint8)
        for i in range(10):
            for j in range(7):
                if (i + j) % 2 == 0:
                    brett[sq + j * sq:sq + (j + 1) * sq, sq + i * sq:sq + (i + 1) * sq] = 0
        src = np.array([[sq, sq], [11 * sq, sq], [11 * sq, 8 * sq], [sq, 8 * sq]], np.float32)
        obj = np.array([[0, 0, 0], [250, 0, 0], [250, 175, 0], [0, 175, 0]], np.float32)
        rng = np.random.default_rng(0)
        bilder = []
        for _ in range(25):
            rv = rng.uniform(-0.5, 0.5, 3)
            tv = np.array([rng.uniform(-150, 0), rng.uniform(-120, 0), rng.uniform(500, 900)])
            ip, _ = cv2.projectPoints(obj, rv, tv, K, None)
            H = cv2.getPerspectiveTransform(src, ip.reshape(-1, 2).astype(np.float32))
            bilder.append(cv2.cvtColor(cv2.warpPerspective(brett, H, (w, h), borderValue=200), cv2.COLOR_GRAY2BGR))
        it = iter(bilder)
        gesammelt, groesse = KK.sammeln(lambda: next(it, None), cv2, sekunden=5, takt=0.0, log=lambda t: None)
        self.assertGreaterEqual(len(gesammelt), 5)
        r = KK.rechnen(gesammelt, groesse, cv2)
        self.assertLess(abs(r["K"][0][0] - f) / f, 0.03, r)


class FluessigeFahrtTest(unittest.TestCase):
    def test_gleichzeitig_und_weich(self):
        from ki.session import ArmSession
        gesendet = []
        box = {}
        sess = ArmSession("t", "test", lambda t: None, lambda: box["s"].hold if "s" in box else None, period=0.002)
        box["s"] = sess
        sess.hold = [1000, 1000, 1000, 1000, 1000, 1400]

        def merke():
            gesendet.append(list(sess.hold))
            return sess.hold
        sess.get_state = merke
        ok, st = sess.move_smooth([2000, 1500, 1000, 1200, 1000, 1400], 0.2, settle=0)
        sess.halt.set()
        self.assertTrue(ok)
        self.assertEqual(st[:5], [2000, 1500, 1000, 1200, 1000])
        # Gelenke laufen synchron: Basis und Schulter haben jederzeit denselben Anteil des Weges zurueckgelegt
        for z in gesendet:
            self.assertLess(abs((z[0] - 1000) / 1000 - (z[1] - 1000) / 500), 0.01)
        # weich: kleine Schritte am Anfang, groesste in der Mitte
        d = [b[0] - a[0] for a, b in zip(gesendet, gesendet[1:])]
        self.assertLess(d[0], max(d) / 4)

    def test_bleibt_zurueck(self):
        from ki.session import ArmSession
        sess = ArmSession("t", "test", lambda t: None, lambda: [1000] * 6, period=0.002)
        sess.hold = [1000] * 6
        ok, st = sess.move_smooth([3000, 1000, 1000, 1000, 1000, 1000], 0.2, settle=0)
        sess.halt.set()
        self.assertFalse(ok)                    # Arm haengt fest (z. B. Tisch) -> Fahrt bricht ab

    def test_haelt_bis_modell_sendet(self):
        """Erste Modellantwort dauert ~1 s: die Sitzung muss so lange weiter halten (sonst legt der Worker ab)."""
        import threading, time
        from ki.session import ArmSession

        class Fahrer:                                # Modell geladen, rechnet aber noch
            def __init__(self):
                self.halt, self.paused, self.ready = threading.Event(), threading.Event(), threading.Event()
                self.error, self.last_sent, self.sent_at = None, None, None
                self.ready.set()
            def stop(self):
                self.halt.set()

        gesendet = []
        sess = ArmSession("t", "test", lambda t: gesendet.append((time.monotonic(), list(t))),
                          lambda: [1000] * 6, period=0.01)
        time.sleep(0.05)
        c = Fahrer()
        sess.client = c
        gesendet.clear()
        time.sleep(0.3)
        self.assertGreater(len(gesendet), 10)        # noch keine Modellziele -> Sitzung haelt weiter
        c.last_sent, c.sent_at = [1100] * 6, time.monotonic()
        time.sleep(0.05)
        n = len(gesendet)
        time.sleep(0.1)
        self.assertEqual(len(gesendet), n)           # Modell sendet selbst -> Sitzung schweigt
        time.sleep(0.4)
        self.assertGreater(len(gesendet), n)         # Modell stockt -> Sitzung haelt dessen letztes Ziel
        self.assertEqual(gesendet[-1][1], [1100] * 6)
        sess.halt.set()


class AnflugFormelTest(unittest.TestCase):
    def test_lerne_und_grobziel(self):
        import json
        rng = np.random.default_rng(1)
        with tempfile.TemporaryDirectory() as d:
            for k in range(40):
                p = {"x": float(rng.uniform(-25, 25)), "y": float(rng.uniform(18, 35)), "winkel": float(rng.uniform(0, 180))}
                f = A.merkmale(p)
                j = [2011 - 12.2 * f[0], 1720 + 79 * f[1], 1971 - 78.6 * f[1], 3173, (1070 + 11.9 * f[2]) % 2048,
                     1400]
                ep = os.path.join(d, f"ep_{k:04d}")
                os.makedirs(ep)
                with open(os.path.join(ep, "info.json"), "w") as fh:
                    json.dump({"startpose": [int(round(v)) for v in j], "platzierung_soll": p, "split": "train",
                               "maske_werte": {"vorne_y": 0.7, "vorne_dx": 0.0, "vorne_winkel": 0.0}}, fh)
            m = A.lerne([d], speichern=False)
        self.assertLess(max(m["rest_ticks"]), 3)
        z = A.grobziel(m, {"x": 0.0, "y": 28.0, "winkel": 0.0})
        self.assertLess(abs(z[0] - 2011), 3)
        self.assertEqual(z[5], 1400)
        self.assertLess(abs(z[4] - 1070), 5)          # quer (rel 0)


class ServoTest(unittest.TestCase):
    def test_konvergiert(self):
        """Simulierte Bildwirkung (unbekannt fuer den Regler), Start daneben -> Maske gruen."""
        Jw = np.array([[0.04, 0.0, 0.0], [0.005, -0.05, 0.0], [0.3, 0.0, 0.09]])
        zust = {"u": np.array([3.0, -2.5, -80.0])}           # Abweichung von der Zielstellung

        def messe():
            e = Jw @ zust["u"]
            return e, bool(np.all(np.abs(e) <= A.SKALA))

        def bewege(u):
            zust["u"] = zust["u"] + u
        r = A.ausrichten(messe, bewege, log=lambda t: None)
        self.assertTrue(r["ok"], r)
        self.assertLess(r["schritte"], 8)

    def test_ohne_kante(self):
        r = A.ausrichten(lambda: (None, False), lambda u: None, log=lambda t: None)
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()


class OrchestratorFreigabeTest(unittest.TestCase):
    def _ablauf(self):
        from workflow import engine as E
        N = {"k1": E.new_node("start", "k1"), "k2": E.new_node("sitzung", "k2"), "k3": E.new_node("faehigkeit", "k3")}
        N["k1"]["next"], N["k2"]["next"] = "k2", "k3"
        N["k3"]["params"].update(modell="m1", sekunden=1, aufgabe="Pick up a red circuit board")
        return {"name": "t", "start": "k1", "nodes": N}

    class Ros:
        def __init__(self):
            self.calls, self.frei = [], False

        def call(self, name, timeout=None, **a):
            self.calls.append(name)
            if name == "sitzung.status":
                return {"bereit": self.frei, "freigegeben": self.frei}
            if name == "sitzung.hinweis":
                return {"titel": "T", "text": "Hinweis"}
            if name == "sitzung.freigeben":
                self.frei = True
            return {}

    def test_zustimmung_im_orchestrator(self):
        from workflow import engine as E
        ros = self.Ros()
        gefragt = []
        r = E.Runner(self._ablauf(), ros, log=lambda t: None, sleep=lambda s: None,
                     confirm=lambda t, x: gefragt.append(x) or True)
        r.run()
        self.assertEqual(gefragt, ["Hinweis"])
        self.assertIn("sitzung.freigeben", ros.calls)
        self.assertNotIn("sitzung.anfragen", ros.calls)
        self.assertLess(ros.calls.index("modell.vorladen"), ros.calls.index("sitzung.freigeben"))   # frueh laden
        self.assertIn("modell.ausfuehren", ros.calls)

    def test_abgelehnt(self):
        from workflow import engine as E
        ros = self.Ros()
        r = E.Runner(self._ablauf(), ros, log=lambda t: None, sleep=lambda s: None, confirm=lambda t, x: False)
        with self.assertRaises(E.PipelineError):
            r.run()
        self.assertNotIn("sitzung.freigeben", ros.calls)

    def test_agent_darf_nicht_zustimmen(self):
        from unittest import mock
        from ki import ros_skills
        from ki.skills import SkillError
        lab = mock.MagicMock()
        lab.panels = {"follower": mock.MagicMock()}
        reg = ros_skills.build(lab)
        for quelle in ("agent", "remote"):
            with self.assertRaises(SkillError):
                reg.call("sitzung.freigeben", {"arm": "follower", "zustimmung": True}, source=quelle)
