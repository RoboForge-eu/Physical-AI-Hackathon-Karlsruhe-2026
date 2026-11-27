"""Tests: Simulation (kinsim, Sim-Worker, Isaac-Umrechnung) und Agentic Robotics (Messen, Korrektur, Kontakt,
Regelschleifen-Vorlagen). Alles offline: keine Hardware, kein COM-Port, keine GPU."""
import io, math, os, queue, tempfile, threading, time, types, unittest
import numpy as np
import cv2
import remote_kin as K


def ueber(x, y, z):
    j = K.ik((x, y, z, math.pi))
    return [j[1], j[2], j[3], j[4], 2047, 2000]


class VisionTests(unittest.TestCase):
    def bild_mit_marker(self, seite=80, pos=(200, 150), loch=(420, 180, 15)):
        img = np.full((360, 640, 3), 210, np.uint8)
        from vision import marker
        m = marker.erzeugen(3, seite, 10)
        img[pos[1]:pos[1] + m.shape[0], pos[0]:pos[0] + m.shape[1]] = m[:, :, None]
        cv2.circle(img, loch[:2], loch[2], (20, 20, 20), -1)
        return img

    def test_marker_mm_and_center(self):
        from vision import marker
        found = marker.finden(self.bild_mit_marker(), groesse_mm=20)
        self.assertEqual([m["id"] for m in found], [3])
        self.assertAlmostEqual(found[0]["seite_px"], 80, delta=2)
        self.assertAlmostEqual(found[0]["mm_pro_px"], 0.25, delta=0.01)
        self.assertAlmostEqual(found[0]["mitte"][0], 250, delta=1.5)

    def test_opening_ignores_marker_and_thin_pen(self):
        from vision import marker, merkmale
        img = self.bild_mit_marker()
        cv2.line(img, (420, 60), (420, 180), (90, 90, 90), 6)          # Stift ragt ins Loch
        found = merkmale.oeffnungen(img, ausser=marker.finden(img, 20))
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["mitte"][0], 420, delta=2)
        self.assertAlmostEqual(found[0]["mitte"][1], 180, delta=2)

    def test_distance_and_angle(self):
        from vision import merkmale
        a = merkmale.abstand({"mitte": [0, 0], "winkel_grad": 170}, {"mitte": [30, 40], "winkel_grad": -170}, 0.5)
        self.assertEqual(a["abstand_px"], 50)
        self.assertEqual(a["abstand_mm"], 25)
        self.assertEqual(a["winkel_diff_grad"], 20)

    def test_measurement_image_is_written(self):
        from regel import werkzeuge
        with tempfile.TemporaryDirectory() as d:
            r = werkzeuge.messen(self.bild_mit_marker(), "oeffnung", pfad=os.path.join(d, "m.jpg"))
            self.assertTrue(r["gefunden"])
            self.assertTrue(os.path.exists(r["messbild"]))
            self.assertIn("abstand_mm", r)

    def test_calibration_from_test_moves(self):
        from vision.kalib import Kalibrierung
        J = np.array([[0.0, -3.0], [-3.0, 0.0]])                     # 3 px je mm, Achsen vertauscht
        p0 = np.array([300.0, 100.0])
        k = Kalibrierung.aus_testbewegungen(p0, p0 + J[:, 0] * 2, p0 + J[:, 1] * 2, 2, [320, 90])
        dx, dy = k.korrektur_mm([326, 99])
        self.assertAlmostEqual(dx, 3.0, places=5)
        self.assertAlmostEqual(dy, 2.0, places=5)
        with tempfile.TemporaryDirectory() as d:
            k.speichern("sim_x", d)
            self.assertEqual(Kalibrierung.laden("sim_x", d).werkzeugpunkt, [320.0, 90.0])
        with self.assertRaises(ValueError):
            Kalibrierung.aus_testbewegungen(p0, p0, p0, 2, [0, 0])


class KorrekturKontaktTests(unittest.TestCase):
    def test_small_cartesian_correction(self):
        from regel import kartesisch
        soll = ueber(0.20, 0.03, 0.07)
        neu, sp = kartesisch.korrektur(soll, 2, -1, -3)
        x, y, z, phi = kartesisch.spitze(neu)
        self.assertAlmostEqual(x, 0.202, delta=0.0006)
        self.assertAlmostEqual(y, 0.029, delta=0.0006)
        self.assertAlmostEqual(z, 0.067, delta=0.0006)
        self.assertEqual(neu[4:], soll[4:])

    def test_correction_limits(self):
        from regel import kartesisch
        soll = ueber(0.20, 0.03, 0.07)
        for bad in ((6, 0, 0), (0, 0, -5.5), (float("nan"), 0, 0)):
            with self.assertRaises(kartesisch.KorrekturFehler):
                kartesisch.korrektur(soll, *bad)

    def test_contact_events_with_baseline(self):
        from regel.kontakt import KontaktMelder
        m = KontaktMelder()
        soll = ueber(0.20, 0.03, 0.06)
        sag = ueber(0.20, 0.03, 0.05)              # echter Arm haengt 10 mm unter dem Soll: kein Kontakt
        t = 0
        for _ in range(50):
            t += 0.01
            m.probe(t, soll, sag)
        self.assertEqual(m.abholen()["ereignisse"], [])
        tiefer = ueber(0.20, 0.03, 0.055)          # Soll 5 mm tiefer, Ist bleibt stehen -> angestossen
        for _ in range(10):
            t += 0.01
            m.probe(t, tiefer, sag)
        ev = m.abholen()["ereignisse"]
        self.assertEqual([e["art"] for e in ev], ["angestossen"])
        tief = ueber(0.20, 0.03, 0.040)            # Ist faellt ploetzlich 6 mm (Soll unveraendert) -> abgesackt
        for _ in range(5):
            t += 0.01
            m.probe(t, tiefer, tief)
        arten = [e["art"] for e in m.abholen()["ereignisse"]]
        self.assertIn("abgesackt", arten)


class WeltTests(unittest.TestCase):
    def test_tip_blocked_by_holder_and_load_rises(self):
        from sim.welt import Welt
        w = Welt()
        h = w.szene.halter
        w.setze_soll(ueber(h["x"] + 0.02, h["y"], h["h"] + 0.01))
        w.schritt(300)
        frei = sum(w.last()[1:4])
        w.setze_soll(ueber(h["x"] + 0.02, h["y"], h["h"] - 0.004))
        w.schritt(200)
        self.assertGreater(w.spitze()[2], h["h"] - 0.0006)
        self.assertGreater(sum(w.last()[1:4]), frei)

    def test_peg_drops_into_hole(self):
        from sim.welt import Welt
        w = Welt()
        L = w.szene.loch
        w.setze_soll(ueber(L["x"], L["y"], 0.065))
        w.schritt(300)
        for z in range(60, 29, -5):              # in kleinen Schritten absenken (wie arm.korrektur)
            w.setze_soll(ueber(L["x"], L["y"], z / 1000))
            w.schritt(50)
        self.assertLess(w.spitze()[2], w.szene.halter["h"] - 0.010)

    def test_cameras_render_and_marker_visible(self):
        from sim.welt import Welt
        from vision import marker
        w = Welt(seed=2, zufall=True)
        h = w.szene.halter
        w.setze_soll(ueber(h["x"], h["y"], h["h"] + 0.012))
        w.schritt(300)
        a, t = w.bild("arm"), w.bild("turm")
        self.assertEqual(a.shape, (360, 640, 3))
        self.assertEqual(t.shape, (360, 640, 3))
        self.assertTrue(marker.finden(a, 20))


class SimSkillTests(unittest.TestCase):
    def robot(self, ros):
        from skilllib.api import RobotAPI
        from skilllib.runner import execute
        from skilllib.vorlagen import code
        r = RobotAPI(ros, ros.arm, log=lambda t: None, run_skill=lambda n, p: execute(code(n), p, r))
        return r

    def test_sim_arm_names_cannot_be_real(self):
        from sim.ros_sim import SimRos
        with self.assertRaises(ValueError):
            SimRos(arm="follower")

    def test_templates_pass_check(self):
        from skilllib.check import check
        from skilllib.vorlagen import VORLAGEN, code
        for n in VORLAGEN:
            self.assertEqual(check(code(n)), [], n)

    def test_insert_peg_in_simulation(self):
        from sim.ros_sim import szenario
        from skilllib.runner import execute
        from skilllib.vorlagen import code
        ok = 0
        for seed in (0, 1, 4):
            ros = szenario("einstecken", seed)
            res = execute(code("stift_einstecken"), {}, self.robot(ros))
            w, L = ros.welt, ros.welt.szene.loch
            x, y, z, _ = w.spitze()
            drin = math.hypot(x - L["x"], y - L["y"]) <= L["r"] and z < w.szene.halter["h"] - 0.005
            self.assertEqual(bool(res["erfolg"]), drin, res.get("bericht"))   # ehrlich: keine Falschmeldung
            self.assertIn("bericht", res)
            ok += drin
        self.assertGreaterEqual(ok, 2)

    def test_pick_and_place_in_simulation(self):
        from sim.ros_sim import szenario
        from skilllib.runner import execute
        from skilllib.vorlagen import code
        ros = szenario("standard", 5)
        res = execute(code("schachtel_auf_palette"), {}, self.robot(ros))
        self.assertTrue(res["erfolg"], res)
        sch, pal = ros.welt.szene.schachtel, ros.welt.szene.palette
        self.assertLess(abs(sch["x"] - pal["x"]), pal["b"] / 2)
        self.assertLess(abs(sch["y"] - pal["y"]), pal["t"] / 2)

    def test_dry_run_api_has_agentic_methods(self):
        from skilllib.api import DryRunAPI
        from skilllib.runner import execute
        from skilllib.vorlagen import code
        r = DryRunAPI(None, "follower", log=lambda t: None, posen=["ueber_oeffnung"])
        res = execute(code("spiralsuche"), {}, r)
        self.assertIn("erfolg", res)


class SimWorkerTests(unittest.TestCase):
    def test_protocol_like_lab_worker(self):
        import sim_worker
        q = queue.Queue()

        class Cmds:
            def __iter__(self):
                while True:
                    line = q.get()
                    if line is None:
                        return
                    yield line
        out = io.StringIO()
        t = threading.Thread(target=sim_worker.main, args=(["--seed", "1"], Cmds(), out))
        t.start()
        q.put("start follower ki\n")
        time.sleep(0.4)
        q.put("ktarget follower 2047 1500 2600 2800 2047 2000\n")
        time.sleep(0.6)
        q.put("stop follower\n")
        time.sleep(1.5)
        q.put("quit\n")
        q.put(None)
        t.join(20)
        text = out.getvalue()
        self.assertIn("BEREIT: SIMULATION", text)
        self.assertIn("[follower] OBS ", text)
        self.assertIn("[follower] LAST ", text)
        self.assertIn("[follower] ARMENDE 0", text)
        self.assertIn("WORKER ENDE", text)
        from ki.recorder import parse_obs
        obs = [l.split("] ", 1)[1] for l in text.splitlines() if "] OBS " in l]
        self.assertIsNotNone(parse_obs(obs[-1]))

    def test_worker_never_imports_serial_bus(self):
        with open(os.path.join(os.path.dirname(__file__), "sim_worker.py"), encoding="utf-8") as f:
            src = f.read()
        for bad in ("import serial", "fast_bus", "from so101 import", "find_port"):
            self.assertNotIn(bad, src)


class IsaacUmrechnungTests(unittest.TestCase):
    def test_roundtrip(self):
        from sim.isaac import umrechnung as U
        t = [2047, 1000, 3000, 2500, 1500, 2100]
        self.assertEqual(U.rad_zu_ticks(U.ticks_zu_rad(t)), t)

    def test_backend_never_sets_eula(self):
        for f in ("backend.py", "server.py"):
            with open(os.path.join(os.path.dirname(__file__), "sim", "isaac", f), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn('OMNI_KIT_ACCEPT_EULA"] =', src)
            self.assertNotIn("OMNI_KIT_ACCEPT_EULA=", src)


class HarnessSkillTests(unittest.TestCase):
    def test_new_skills_registered_and_guarded(self):
        from ki import ros_skills, skills as S
        panel = types.SimpleNamespace(label="Setup 1")
        lab = types.SimpleNamespace(panels={"follower": panel}, session_ok=lambda arm: False)
        reg = ros_skills.build(lab)
        names = [t["name"] for t in reg.tool_schemas()]
        for n in ("vision.messen", "vision.kalibrieren", "arm.korrektur", "arm.kontakt"):
            self.assertIn(n, names)
        with self.assertRaises(S.SkillError):           # bewegt -> ohne freigegebene Sitzung gesperrt
            reg.call("arm.korrektur", {"arm": "follower", "dz_mm": -1}, source="agent")
        with self.assertRaises(S.SkillError):
            reg.call("arm.korrektur", {"arm": "follower", "dz_mm": -1}, source="remote")

    def test_agent_tools_hide_on_site_setup(self):
        from agent import tools
        ros_tools = [{"name": "vision.werkzeugpunkt_merken", "description": "", "input_schema": {}},
                     {"name": "arm.kontakt", "description": "", "input_schema": {}}]
        t, _ = tools.build(ros_tools, [], ["follower"])
        names = [x["name"] for x in t]
        self.assertIn("arm__kontakt", names)
        self.assertNotIn("vision__werkzeugpunkt_merken", names)

    def test_skill_author_knows_new_tools(self):
        from agent import author
        names = [t["name"] for t in author.TOOLS]
        self.assertIn("simulationslauf", names)
        self.assertIn("vorlagen", names)
        self.assertIn("robot.korrektur", __import__("skilllib.api", fromlist=["x"]).__doc__)


if __name__ == "__main__":
    unittest.main()
