"""Offline-Tests Arbeitsbereich in 3D (Waende/Hindernisse je Arm, echtes SO-101-Modell) - ohne Arme."""
import io, unittest
from unittest.mock import Mock, patch
import arbeitsbereich as A

C = 2047                                   # Basis-Mitte in diesen Tests
REST = {1: C, 2: 846, 3: 3095, 4: 902, 5: 2047, 6: 1418}


def karte(wall_y=0.30, abstand=0.03):
    """Tisch, Kante bei y = 0, Basis buendig daran, Arm zeigt in der Mitte nach +y. Wand quer bei y = wall_y."""
    return {"arm": "t", "aktiv": True, "abstand_m": abstand,
            "erlaubt": [[[-1, 0.0], [1, 0.0], [1, wall_y], [-1, wall_y]]], "verboten": [],
            "basis": {"x": 0.0, "y": A.base_back_offset(), "basis_grad": 90, "richtung_grad": 90, "drehsinn": -1}}


def pose(base=C, sh=2047, el=2047, wr=2047, roll=2047, grip=2047):
    return {1: base, 2: sh, 3: el, 4: wr, 5: roll, 6: grip}


class GeometryTests(unittest.TestCase):
    def test_base_flush_with_edge(self):
        self.assertAlmostEqual(A.base_clearance(karte()), 0.0, places=3)   # hintere Kante genau auf y = 0
        self.assertAlmostEqual(A.base_back_offset(), 0.031, places=3)

    def test_mid_pose_points_forward(self):
        P = A.arm_points(karte(), pose(), C)
        self.assertGreater(P[:, 1].max(), 0.35)                            # Greifer ~0,4 m vor der Kante
        self.assertLess(abs(P[:, 0].mean()), 0.05)

    def test_base_turn_direction_follows_drehsinn(self):
        k = karte()
        # Drehsinn -1: groesserer Servowert dreht im Uhrzeigersinn (von oben), also von +y nach +x
        self.assertGreater(A.arm_points(k, pose(base=C + 600), C)[:, 0].mean(), 0.05)
        self.assertLess(A.arm_points(k, pose(base=C - 600), C)[:, 0].mean(), -0.05)
        k["basis"]["drehsinn"] = 1
        self.assertLess(A.arm_points(k, pose(base=C + 600), C)[:, 0].mean(), -0.05)

    def test_folded_rest_pose_sticks_over_the_edge(self):
        """Echtes 3D-Modell: in der Ablage ragt der Oberarm-Motor ~3 cm hinter die Basis."""
        d, _ = A.clearance(karte(), REST, C)
        self.assertLess(d, -0.02)

    def test_obstacle_with_height_can_be_passed_over(self):
        k = karte(wall_y=0.8)
        box = [[-0.05, 0.30], [0.05, 0.30], [0.05, 0.36], [-0.05, 0.36]]
        k["verboten"] = [box]                                              # unendlich hoch: Greifer steckt drin
        self.assertLess(A.clearance(k, pose(), C)[0], 0)
        k["verboten"] = [{"punkte": box, "hoehe_m": 0.05}]                 # 5 cm hohe Kiste: Arm ist darueber
        with_box = A.clearance(k, pose(), C)[0]
        k["verboten"] = []
        self.assertAlmostEqual(with_box, A.clearance(k, pose(), C)[0])     # Kiste stoert nicht (engste Stelle: Tischkante)


class FenceTests(unittest.TestCase):
    """Wand: Follower bleibt im Bereich und gleitet an der Wand; zurueck im Bereich holt er von selbst auf."""
    def setUp(self):
        self.logs = []
        self.k = karte(wall_y=0.50)
        self.f = A.Fence(self.k, C, log=self.logs.append)
        self.assertTrue(self.f.start(pose())[0])
        self.t = 0.0

    def send(self, p, n=1):
        out = None
        for _ in range(n):
            self.t += 0.002
            out = self.f.filter(p, self.t)
        return out

    def test_inside_passes_through(self):
        self.assertEqual(self.send(pose(sh=2100)), pose(sh=2100))

    def test_never_behind_wall_and_catches_up_anywhere(self):
        for sh in range(2047, 3000, 10):                                   # Arm nach vorn -> Wand
            out = self.send(pose(sh=sh, el=1700))
            self.assertGreaterEqual(A.clearance(self.k, out, C)[0], 0.03 - 1e-6)
        self.assertTrue(self.f.limiting)
        for p in (pose(sh=3000, el=1700, base=C + 400), pose(sh=2800, el=1500)):   # Leader draussen frei
            out = self.send(p, 50)
            self.assertGreaterEqual(A.clearance(self.k, out, C)[0], 0.03 - 1e-6)
        target = pose(base=C + 600, sh=1900)                               # zurueck an ANDERER Stelle
        out = self.send(target, 2000)
        self.assertEqual(out, target)                                      # holt auf, folgt wieder direkt
        self.assertFalse(self.f.limiting)
        self.assertTrue(any("folgt direkt" in m for m in self.logs))

    def test_catch_up_is_speed_limited(self):
        self.send(pose(sh=2500, el=1700), 300)                             # Ziel hinter der Wand
        self.assertTrue(self.f.limiting)
        before = dict(self.f.cur)
        out = self.send(pose(base=C + 900), 1)                             # Ziel weit weg, aber sicher
        self.assertLessEqual(max(abs(out[s] - before[s]) for s in A.GEO), 4)   # kein Sprung

    def test_never_safe_start_returns_none(self):
        f = A.Fence(karte(wall_y=0.20), C, log=lambda m: None)
        self.assertFalse(f.start(pose())[0])
        self.assertIsNone(f.filter(pose(), 0.0))


class ImportTests(unittest.TestCase):
    def test_svg_mm_units_rect_path_and_y_up(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1000mm" height="500mm" viewBox="0 0 1000 500">'
               '<rect x="0" y="0" width="1000" height="500"/>'
               '<path d="M 100 100 l 50 0 l 0 50 Z"/>'
               '<polygon points="300,300 350,300 350,350"/></svg>')
        polys = A.import_svg(svg)
        self.assertEqual(len(polys), 3)
        self.assertIn((1.0, -0.5), polys[0])                                # 1000 mm, y nach oben gedreht
        self.assertEqual(polys[1], [(0.1, -0.1), (0.15, -0.1), (0.15, -0.15)])
        k = A.from_polygons("follower", polys)
        self.assertEqual(len(k["erlaubt"]), 1)
        self.assertEqual(len(k["verboten"]), 2)

    def test_dxf_lwpolyline(self):
        dxf = "\n".join(["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
                         "0", "SECTION", "2", "ENTITIES",
                         "0", "LWPOLYLINE", "90", "4", "70", "1",
                         "10", "0", "20", "0", "10", "1000", "20", "0", "10", "1000", "20", "500", "10", "0", "20", "500",
                         "0", "ENDSEC", "0", "EOF"])
        self.assertEqual(A.import_dxf(dxf), [[(0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.0, 0.5)]])


class WorkerTests(unittest.TestCase):
    def attach(self, k):
        import lab_worker
        f = Mock()
        f.name = "t"
        with patch("lab_worker.arbeitsbereich.load", return_value=k), \
             patch("sys.stdout", new_callable=io.StringIO) as log:
            try:
                return lab_worker.attach_fence(f, C, REST, [2, 3, 4, 1, 5, 6]), log.getvalue()
            except lab_worker.Abort as exc:
                return exc, log.getvalue()

    def test_raise_path_into_wall_aborts_before_moving(self):
        import lab_worker
        res, _ = self.attach(karte(wall_y=0.25))                           # Mittelstellung reicht ~0,4 m nach vorn
        self.assertIsInstance(res, lab_worker.Abort)

    def test_no_active_map_means_no_fence(self):
        k = karte()
        k["aktiv"] = False
        self.assertIsNone(self.attach(k)[0])

    def test_rest_over_edge_is_tolerated_but_path_may_not_go_deeper(self):
        res, log = self.attach(karte(wall_y=0.8))
        self.assertIsInstance(res, A.Fence)
        self.assertIn("ZAUN-WARNUNG", log)

    def test_base_over_wall_aborts(self):
        import lab_worker
        k = karte(wall_y=0.8)
        k["basis"]["y"] = 0.0                                              # Basis haengt 3 cm ueber die Kante
        self.assertIsInstance(self.attach(k)[0], lab_worker.Abort)


if __name__ == "__main__":
    unittest.main()
