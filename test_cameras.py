"""Offline-Tests der Kamera-Plaetze (ohne echte Kameras)."""
import time, unittest
import cameras as C

A, B, D, E = (f"USB\\VID_0C45&PID_6366&MI_00\\9&{x}&0&0000" for x in ("AAAA", "BBBB", "DDDD", "EEEE"))


class FakeCam:
    def __init__(self, index, device=""):
        self.index, self.device = index, device
        self.alive_flag, self.stopped = True, False
        self.frame, self.t = None, None
        self.rate, self.error = 30.0, None

    def start(self):
        return self

    def stop(self, wait=True):
        self.stopped, self.alive_flag = True, False

    @property
    def alive(self):
        return self.alive_flag

    def latest(self):
        return self.frame, self.t


class AssignTests(unittest.TestCase):
    def test_device_id_from_symbolic_link(self):
        link = r"\\?\usb#vid_0c45&pid_6366&mi_00#9&183af011&0&0000#{e5323777-f976-4f5b-9b55-b94699c46e44}\global"
        self.assertEqual(C.device_id(link), r"USB\VID_0C45&PID_6366&MI_00\9&183AF011&0&0000")

    def test_fixed_slots_follow_device_not_index(self):
        slots = [{"name": "a", "device": B}, {"name": "b", "device": A}, {"name": "c", "device": ""},
                 {"name": "d", "device": ""}]
        plan = C.assign(slots, [(0, A, ""), (1, B, ""), (2, D, "")])
        self.assertEqual(plan[0], (1, B, True))
        self.assertEqual(plan[1], (0, A, True))
        self.assertEqual(plan[2], (2, D, False))     # unbekannt -> freier Platz, vorlaeufig
        self.assertEqual(plan[3], (None, "", False))

    def test_missing_fixed_camera_keeps_its_slot(self):
        slots = [{"name": "a", "device": A}, {"name": "b", "device": B}] + [{"name": "x", "device": ""}] * 2
        plan = C.assign(slots, [(0, B, "")])
        self.assertEqual(plan[0], (None, A, True))
        self.assertEqual(plan[1], (0, B, True))

    def test_load_slots_always_four(self):
        self.assertEqual(len(C.load_slots()), 4)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.devices = [(0, A, ""), (1, B, "")]
        slots = [{"name": "a", "device": A}, {"name": "b", "device": B}, {"name": "c", "device": D},
                 {"name": "d", "device": ""}]
        self.m = C.CameraManager(slots=slots, lister=lambda: list(self.devices), factory=FakeCam)

    def test_status_texts(self):
        self.m.poll()
        now = time.monotonic()
        self.assertEqual(self.m.status(0, now)[0], C.STARTING)
        self.m.cams[0].frame, self.m.cams[0].t = object(), now
        self.assertEqual(self.m.status(0, now)[0], C.LIVE)
        self.assertEqual(self.m.status(0, now + 5)[0], C.NO_SIGNAL)       # Bild veraltet
        self.assertEqual(self.m.status(2, now)[0], C.MISSING)             # zugeordnet, nicht da
        self.assertEqual(self.m.status(3, now)[0], C.UNASSIGNED)

    def test_unplug_and_replug(self):
        self.m.poll()
        first = self.m.cams[1]
        self.devices = [(0, B, "")]                     # A abgesteckt, B rutscht auf Nummer 0
        self.m.poll()
        self.assertIsNone(self.m.cams[0])
        self.assertIs(self.m.cams[1], first)            # laufende Aufnahme bleibt
        self.assertFalse(first.stopped)
        self.devices = [(0, B, ""), (1, A, "")]
        self.m.poll()
        self.assertEqual(self.m.cams[0].index, 1)

    def test_dead_capture_is_restarted(self):
        self.m.poll()
        old = self.m.cams[0]
        old.alive_flag = False
        self.m.poll()
        self.assertIsNot(self.m.cams[0], old)

    def test_unnamed_camera_is_shown(self):
        self.devices = [(0, A, ""), (1, B, ""), (2, E, "")]
        self.m.poll()
        now = time.monotonic()
        cam = self.m.cams[3]
        self.assertEqual(cam.device, E)
        cam.frame, cam.t = object(), now
        self.assertIn("noch nicht benannt", self.m.status(3, now)[0])


def scene():
    import numpy as np
    cv2 = C.cv2
    rng = np.random.default_rng(1)
    img = (rng.random((90, 160)) * 255).astype("uint8")
    img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_NEAREST)
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.putText(img, "RoboForge", (300, 400), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 0, 0), 8)
    return img


def blur(img, k):
    return img if k == 0 else C.cv2.GaussianBlur(img, (k, k), 0)


class FocusTests(unittest.TestCase):
    def test_sharper_image_scores_higher(self):
        img = scene()
        values = [C.sharpness(blur(img, k)) for k in (41, 21, 11, 5, 0)]
        self.assertEqual(values, sorted(values))

    def test_turning_through_focus_gives_check_only_near_best(self):
        img = scene()
        m = C.FocusMeter(alpha=1.0)
        self.assertFalse(m.update(blur(img, 31))["ok"])                 # unscharf, noch nicht gedreht
        for k in (21, 11, 5):
            m.update(blur(img, k))
        self.assertTrue(m.update(blur(img, 5))["ok"])                   # am besten Punkt
        res = m.update(blur(img, 21))                                    # zu weit gedreht
        self.assertFalse(res["ok"])
        self.assertIn("weiterdrehen", res["hint"])
        self.assertTrue(m.update(blur(img, 5))["ok"])                   # zurueck

    def test_blank_wall_gives_no_verdict(self):
        import numpy as np
        m = C.FocusMeter(alpha=1.0)
        res = m.update(np.full((720, 1280, 3), 200, np.uint8))
        self.assertFalse(res["ok"])
        self.assertIn("Struktur", res["hint"])

    def test_overlay_keeps_size(self):
        small = C.cv2.resize(scene(), (320, 180))
        out = C.draw_focus(small.copy(), C.FocusMeter().update(scene()))
        self.assertEqual(out.shape, small.shape)


class CoverTests(unittest.TestCase):
    def test_finds_the_one_covered_camera_after_hold_time(self):
        d = C.CoverDetector({A: 180, B: 150, D: 200})
        self.assertIsNone(d.update({A: 180, B: 20, D: 200}, 0.0))
        self.assertIsNone(d.update({A: 180, B: 18, D: 200}, 0.5))
        self.assertEqual(d.update({A: 180, B: 15, D: 200}, 0.8), B)

    def test_ambiguous_or_brief_darkness_is_ignored(self):
        d = C.CoverDetector({A: 180, B: 150})
        d.update({A: 10, B: 10}, 0.0)
        self.assertIsNone(d.update({A: 10, B: 10}, 1.0))          # zwei dunkel -> unklar
        d = C.CoverDetector({A: 180, B: 150})
        d.update({A: 180, B: 10}, 0.0)
        d.update({A: 180, B: 150}, 0.3)                            # Hand kurz drueber
        self.assertIsNone(d.update({A: 180, B: 10}, 0.8))

    def test_already_assigned_and_dark_scenes_are_ignored(self):
        d = C.CoverDetector({A: 180, B: 30}, ignore=[A])
        d.update({A: 5, B: 25}, 0.0)
        self.assertIsNone(d.update({A: 5, B: 25}, 1.0))            # A schon vergeben, B nicht deutlich dunkler

    def test_save_assignment_keeps_names(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text(json.dumps({"baud": 1, "cameras": [{"name": f"n{i}", "device": "x"} for i in range(4)]}), encoding="utf-8")
            C.save_assignment({0: B, 3: A}, p)
            cfg = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual([c["device"] for c in cfg["cameras"]], [B, "x", "x", A])
        self.assertEqual(cfg["cameras"][0]["name"], "n0")
        self.assertEqual(cfg["baud"], 1)


class CompleteAssignmentTests(unittest.TestCase):
    def test_partial_assignment_swaps_and_fills(self):
        old = [A, B, D, E]
        self.assertEqual(C.complete_assignment(old, {0: B, 1: A}, old), {0: B, 1: A, 2: D, 3: E})
        self.assertEqual(C.complete_assignment(old, {2: B}, old), {0: A, 1: D, 2: B, 3: E})   # Tausch
        x = "USB\VID_0C45&PID_6366&MI_00\9&XXXX&0&0000"
        # eine Kamera an neuem Anschluss, nichts zugeordnet: wird automatisch ergaenzt
        self.assertEqual(C.complete_assignment(old, {}, [x, B, D, E]), {0: x, 1: B, 2: D, 3: E})
        # unklar (zwei neue, zwei fehlende): nichts raten
        self.assertEqual(C.complete_assignment(old, {}, [x, x + "2", D, E])[0], A)


if __name__ == "__main__":
    unittest.main()
