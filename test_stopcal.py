"""Offline-Tests der Anschlag-Kalibrierung (ohne Arme)."""
import tempfile, unittest
import stopcal as K


def hold(cap, pos, t, seconds=1.0, dt=0.02, jitter=0):
    """Haelt pos fuer seconds; gibt (erkannter Wert oder None, neue Zeit) zurueck."""
    got = None
    n = int(seconds / dt)
    for i in range(n):
        r = cap.feed(pos + (jitter if i % 2 else 0), t)
        got = got if r is None else r
        t += dt
    return got, t


def move(cap, a, b, t, steps=30, dt=0.02):
    for i in range(steps + 1):
        cap.feed(int(a + (b - a) * i / steps), t)
        t += dt
    return t


class CaptureTests(unittest.TestCase):
    def test_four_stops_back_and_forth(self):
        cap = K.JointCapture((900, 3100))
        t = 0.0
        v, t = hold(cap, 902, t, jitter=2)         # Ablage: sofort A
        self.assertIn(v, (902, 903, 904))
        t = move(cap, 902, 3095, t)
        v, t = hold(cap, 3095, t)
        self.assertEqual(v, 3095)
        t = move(cap, 3095, 905, t)
        v, t = hold(cap, 905, t)
        self.assertEqual(v, 905)
        t = move(cap, 905, 3092, t)
        v, t = hold(cap, 3092, t)
        self.assertTrue(cap.done)
        r = cap.result()
        self.assertAlmostEqual(r["lo"], (902 + 905) / 2, delta=1.5)
        self.assertAlmostEqual(r["hi"], (3095 + 3092) / 2)
        self.assertTrue(r["ok"])

    def test_pause_in_the_middle_is_not_a_stop(self):
        cap = K.JointCapture((900, 3100))
        v, _ = hold(cap, 2000, 0.0, seconds=3)
        self.assertIsNone(v)
        self.assertEqual(cap.values, [])

    def test_short_hold_or_wobble_is_not_captured(self):
        cap = K.JointCapture((900, 3100))
        v, t = hold(cap, 905, 0.0, seconds=0.5)
        self.assertIsNone(v)
        v, t = hold(cap, 905, t, seconds=1.5, jitter=12)     # wackelt zu stark
        self.assertIsNone(v)

    def test_same_end_twice_needs_other_end_first(self):
        cap = K.JointCapture((900, 3100))
        v, t = hold(cap, 905, 0.0)
        self.assertIsNotNone(v)
        t = move(cap, 905, 1500, t)
        t = move(cap, 1500, 905, t)
        v, t = hold(cap, 905, t)                   # wieder Ablage-Seite: noch nicht dran
        self.assertIsNone(v)
        self.assertEqual(len(cap.values), 1)

    def test_bad_repeatability_is_flagged(self):
        cap = K.JointCapture((900, 3100))
        t = 0.0
        for pos in (930, 3095, 905, 3095):            # erst zu sanft, dann fester gedrueckt
            t = move(cap, cap.values[-1] if cap.values else 1500, pos, t)
            _, t = hold(cap, pos, t)
        self.assertFalse(cap.result()["ok"])
        self.assertEqual(cap.result()["repeat"], 25)

    def test_stopping_short_of_a_known_stop_is_not_taken(self):
        cap = K.JointCapture((900, 3100))
        t = move(cap, 1500, 905, 0.0)
        _, t = hold(cap, 905, t)
        t = move(cap, 905, 3095, t)
        _, t = hold(cap, 3095, t)
        t = move(cap, 3095, 940, t)                   # 35 Schritte vor dem Anschlag stehen geblieben
        v, t = hold(cap, 940, t, seconds=2)
        self.assertIsNone(v)
        self.assertTrue(cap.short)
        t = move(cap, 940, 906, t)                    # weiter gedrueckt
        v, t = hold(cap, 906, t)
        self.assertEqual(v, 906)

    def test_brief_overpush_does_not_block(self):
        """Beim Anschlagen kurz fester gedrueckt (federt nach) -> danach normal halten zaehlt trotzdem."""
        cap = K.JointCapture((900, 3100))
        t = move(cap, 1500, 905, 0.0)
        _, t = hold(cap, 905, t)
        t = move(cap, 905, 3060, t)
        _, t = hold(cap, 3060, t, seconds=0.1)        # nur kurz ueberdrueckt
        t = move(cap, 3060, 3040, t, steps=5)
        v, t = hold(cap, 3040, t)
        self.assertEqual(v, 3040)

    def test_gripper_has_more_tolerance(self):
        def run(joint):
            cap = K.JointCapture((1350, 2950), joint=joint)
            t = move(cap, 2000, 1400, 0.0)
            _, t = hold(cap, 1400, t)
            t = move(cap, 1400, 2920, t)
            _, t = hold(cap, 2920, t, seconds=0.5)    # fest zugedrueckt gehalten
            t = move(cap, 2920, 2905, t, steps=5)
            v, t = hold(cap, 2905, t)                 # etwas lockerer gehalten
            return v, cap
        v, _ = run(6)
        self.assertEqual(v, 2905)
        v, cap = run(1)
        self.assertIsNone(v)
        self.assertTrue(cap.short)
        self.assertEqual(cap.missing(), 15)

    def test_single_glitch_reading_does_not_block(self):
        cap = K.JointCapture((900, 3100))
        t = move(cap, 1500, 905, 0.0)
        cap.feed(700, t)                              # ein Fehlwert
        v, t = hold(cap, 905, t + 0.02)
        self.assertEqual(v, 905)


class FreeJointTests(unittest.TestCase):
    """Handgelenk-Drehung: im EEPROM 0..4095, Enden kommen aus der Bewegung."""
    def test_wrist_roll_four_stops(self):
        cap = K.JointCapture((0, 4095))
        t = 0.0
        v, t = hold(cap, 2100, t)                     # Ruhe in der Mitte: kein Anschlag
        self.assertIsNone(v)
        for a, b in ((2100, 700), (700, 3400), (3400, 703), (703, 3398)):
            t = move(cap, a, b, t)
            v, t = hold(cap, b, t)
            self.assertEqual(v, b)
        r = cap.result()
        self.assertTrue(cap.done)
        self.assertAlmostEqual(r["lo"], 701.5)
        self.assertTrue(r["ok"])

    def test_small_turn_is_not_a_stop(self):
        cap = K.JointCapture((0, 4095))
        t = move(cap, 2100, 1800, 0.0)                # nur 26 Grad gedreht
        v, t = hold(cap, 1800, t)
        self.assertIsNone(v)

    def test_range_over_zero_is_measured_continuously(self):
        """Anschlag hinter 0/4095: Werte laufen weiter (z. B. -400) statt zu springen."""
        cap = K.JointCapture((0, 4095))
        t = 0.0

        def go(a, b, t):                              # Bewegung in "durchgezaehlten" Werten, Servo meldet mod 4096
            for i in range(31):
                cap.feed(int(a + (b - a) * i / 30) % 4096, t)
                t += 0.02
            return t
        pos = 1500
        for b in (-400, 2600, -397, 2598):
            t = go(pos, b, t)
            _, t = hold(cap, b % 4096, t)
            pos = b
        self.assertFalse(cap.wrapped)
        self.assertTrue(cap.done)
        r = cap.result()
        self.assertAlmostEqual(r["lo"], -398.5)
        self.assertAlmostEqual(r["hi"], 2599)
        plan = K.rezero_plan(r, -1235)
        self.assertTrue(plan["needed"])
        self.assertEqual(plan["d"], round((-398.5 + 2599) / 2) - 2047)
        self.assertEqual((plan["lo"] + plan["hi"]) / 2, 2047)
        self.assertTrue(0 <= plan["lo"] < plan["hi"] <= 4095)

    def test_limited_joint_jump_is_still_refused(self):
        cap = K.JointCapture((900, 3100))
        t = move(cap, 1000, 950, 0.0)
        cap.feed(4080, t)
        self.assertTrue(cap.wrapped)


class RezeroTests(unittest.TestCase):
    def test_offset_wraps_into_register_range(self):
        plan = K.rezero_plan({"lo": -600, "hi": 2400}, -1235)
        self.assertEqual(plan["d"], -1147)
        self.assertEqual(plan["offset"], 1714)          # -2382 ist gleichwertig zu +1714 (mod 4096)
        self.assertEqual((plan["lo"], plan["hi"]), (547, 3547))

    def test_already_centered_needs_nothing(self):
        plan = K.rezero_plan({"lo": 600, "hi": 3500}, 100)
        self.assertFalse(plan["needed"])

    def test_full_turn_has_no_center(self):
        self.assertIsNone(K.rezero_plan({"lo": 0, "hi": 4095}, 0))

    def test_saved_poses_are_shifted(self):
        with tempfile.TemporaryDirectory() as d:
            import json, os
            cfg = os.path.join(d, "config.json")
            text = ('{\n  "follower": {"label": "Setup 1", "cameras": [1, 2],\n'
                    '    "rest_pose": {"1": 2073, "5": 2159, "6": 1418}},\n'
                    '  "follower2": {"rest_pose": {"5": 3138}},\n  "cameras": [{"name": "Setup 1 · Arm"}]\n}\n')
            open(cfg, "w", encoding="utf-8").write(text)
            json.dump({"1": 2058, "5": 2150}, open(os.path.join(d, "follower_start_pose.json"), "w"))
            changed = K.shift_saved_poses("follower", 5, -1147, caldir=d, config_path=cfg)
            self.assertEqual(len(changed), 2)
            new = json.load(open(cfg, encoding="utf-8"))
            self.assertEqual(new["follower"]["rest_pose"]["5"], (2159 + 1147) % 4096)
            self.assertEqual(new["follower"]["rest_pose"]["1"], 2073)
            self.assertEqual(new["follower2"]["rest_pose"]["5"], 3138)
            self.assertEqual(new["cameras"][0]["name"], "Setup 1 · Arm")
            self.assertEqual(json.load(open(os.path.join(d, "follower_start_pose.json")))["5"], 2150 + 1147)


class AlignTests(unittest.TestCase):
    def setUp(self):
        self.leader = {"arm": "leader", "offsets": {"5": -100, "3": 0},
                       "joints": {"5": {"lo": 200, "hi": 3600}, "3": {"lo": 919, "hi": 3112}}}
        self.follower = {"arm": "follower", "offsets": {"5": 50, "3": 0},
                         "joints": {"5": {"lo": 300, "hi": 3700}, "3": {"lo": 885, "hi": 3093}}}

    def test_same_pose_replaces_stop_center(self):
        with tempfile.TemporaryDirectory() as d:
            a = K.save_align("follower", 5, 2000, 2455, -100, 50, caldir=d)
            self.assertEqual(a["shift"], 455)
            m = K.build_map(self.leader, self.follower, K.load(K.align_path("follower", d)))
            self.assertEqual(m["joints"]["5"]["shift"], 455)
            self.assertEqual(m["joints"]["5"]["source"], "gleiche Stellung")
            self.assertEqual(K.apply(m, 5, 2000), 2455)
            self.assertAlmostEqual(m["joints"]["3"]["shift"], -26.5)        # andere Gelenke: Anschlaege

    def test_align_shift_takes_short_way_over_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(K.save_align("follower", 5, 4000, 100, 0, 0, caldir=d)["shift"], 196)

    def test_align_invalid_after_rezero(self):
        with tempfile.TemporaryDirectory() as d:
            K.save_align("follower", 5, 2000, 2455, -100, 999, caldir=d)   # Offset passt nicht mehr
            m = K.build_map(self.leader, self.follower, K.load(K.align_path("follower", d)))
            self.assertEqual(m["joints"]["5"]["shift"], 100)                # zurueck auf Anschlag-Mitte

    def test_vertical_reference_of_both_arms_sets_shift(self):
        K.USE_REF_SHIFT = True
        self.addCleanup(setattr, K, "USE_REF_SHIFT", True)
        self.leader["joints"]["5"]["ref"] = 1600
        self.follower["joints"]["5"]["ref"] = 2055                   # Follower 40 Grad anders als Anschlag-Mitte
        m = K.build_map(self.leader, self.follower)
        self.assertEqual(m["joints"]["5"]["shift"], 455)
        self.assertEqual(m["joints"]["5"]["source"], "senkrecht")
        del self.follower["joints"]["5"]["ref"]                       # nur ein Arm -> Anschlag-Mitte
        self.assertNotIn("source", K.build_map(self.leader, self.follower)["joints"]["5"])

    def test_leader_over_zero_is_unwrapped_not_blocked(self):
        K.USE_REF_SHIFT = True
        self.addCleanup(setattr, K, "USE_REF_SHIFT", True)
        """Leader-Drehung -30..3759 (laeuft knapp ueber 0/4095); Follower nach Nullpunkt 155..3939."""
        leader = {"arm": "leader", "offsets": {"5": -1841}, "joints": {"5": {"lo": -30.0, "hi": 3759.5, "ref": 1848}}}
        follower = {"arm": "follower", "offsets": {"5": 10}, "joints": {"5": {"lo": 155.0, "hi": 3939.5, "ref": 1019}}}
        m = K.build_map(leader, follower)
        self.assertEqual(m["joints"]["5"]["shift"], -829)
        self.assertEqual(K.apply(m, 5, 1848), 1019)
        self.assertEqual(K.apply(m, 5, 4080), -16 - 829)            # am Anschlag hinter 0: kein Sprung
        self.assertEqual(K.apply(m, 5, 20), 20 - 829)

    def test_unwrap_into_range(self):
        self.assertEqual(K.unwrap_into(300, 1400, 5184), 4396)
        self.assertEqual(K.unwrap_into(2000, 1400, 5184), 2000)
        self.assertEqual(K.unwrap_into(4050, -30, 3759), -46)

    def test_range_over_zero_is_blocked(self):
        self.follower["joints"]["5"] = {"lo": 1400, "hi": 5184}
        m = K.build_map(self.leader, self.follower)
        self.assertEqual(m["joints"]["5"]["kind"], "blocked")
        self.assertEqual(K.apply(m, 5, 1234), 1234)


class StopsMatchTests(unittest.TestCase):
    def test_roll_stops_map_onto_stops_despite_ref(self):
        K.USE_REF_SHIFT = False
        self.addCleanup(setattr, K, "USE_REF_SHIFT", True)
        leader = {"arm": "leader", "offsets": {"5": 0}, "joints": {"5": {"lo": -29.0, "hi": 3760.0, "ref": 1848}}}
        follower = {"arm": "follower", "offsets": {"5": 0}, "joints": {"5": {"lo": 156.0, "hi": 3942.5, "ref": 1019}}}
        m = K.build_map(leader, follower)
        self.assertAlmostEqual(K.apply(m, 5, 3760.0), 3942.5, delta=3)    # Anschlag -> Anschlag
        self.assertAlmostEqual(K.apply(m, 5, -29.0), 156.0, delta=3)
        self.assertAlmostEqual(K.apply(m, 5, 4080), -16 + 183.8, delta=3)   # Leader hinter 0: kein Sprung


class MapTests(unittest.TestCase):
    def stops(self, arm, joints, offsets=None):
        return {"arm": arm, "offsets": offsets or {"1": 0}, "joints": joints}

    def test_shift_and_gripper_linear(self):
        leader = self.stops("leader", {"2": {"lo": 845, "hi": 3218}, "6": {"lo": 1334, "hi": 2510}})
        follower = self.stops("follower", {"2": {"lo": 835, "hi": 3210}, "6": {"lo": 1418, "hi": 2903}})
        m = K.build_map(leader, follower)
        self.assertEqual(m["joints"]["2"]["shift"], -9.0)
        self.assertEqual(m["joints"]["2"]["mismatch"], 2.0)
        self.assertEqual(K.apply(m, 2, 2000), 1991.0)
        self.assertAlmostEqual(K.apply(m, 6, 1334), 1418)
        self.assertAlmostEqual(K.apply(m, 6, 2510), 2903)
        self.assertEqual(K.apply(m, 1, 1234), 1234)           # nicht gemessen -> unveraendert
        self.assertEqual(K.apply(None, 2, 2000), 2000)

    def test_map_only_used_while_offsets_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            leader = self.stops("leader", {"2": {"lo": 845, "hi": 3218}}, {"2": -1020})
            follower = self.stops("follower", {"2": {"lo": 835, "hi": 3210}}, {"2": -1166})
            self.assertIsNone(K.usable_map("follower", {"2": -1020}, {"2": -1166}, tmp)[0])
            K.activate(K.build_map(leader, follower), tmp)
            m, why = K.usable_map("follower", {2: -1020}, {2: -1166}, tmp)
            self.assertIsNotNone(m)
            m, why = K.usable_map("follower", {"2": -1020}, {"2": -1100}, tmp)
            self.assertIsNone(m)
            self.assertIn("Offsets", why)
            K.deactivate("follower", tmp)
            self.assertIsNone(K.usable_map("follower", {"2": -1020}, {"2": -1166}, tmp)[0])

    def test_save_and_load_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            K.save_stops("leader", {2: {"lo": 845.0, "hi": 3218.0}}, {2: -1020}, tmp)
            d = K.load(K.stops_path("leader", tmp))
            self.assertEqual(d["joints"]["2"]["hi"], 3218.0)
            self.assertEqual(d["offsets"]["2"], -1020)


class WorkerTests(unittest.TestCase):
    def test_map_target_uses_stop_map_and_still_clamps(self):
        import types, lab_worker
        f = types.SimpleNamespace(lim={6: (1418, 2903)}, clamp=lambda s, p: int(max(900, min(3100, p))))
        l = types.SimpleNamespace(lim={6: (1334, 2510)})
        f.stop_map = {"joints": {"2": {"kind": "shift", "shift": -9.0}}}
        self.assertEqual(lab_worker.map_target(f, l, 2, 2000), 1991)
        self.assertEqual(lab_worker.map_target(f, l, 2, 3200), 3100)       # Grenze bleibt
        self.assertEqual(lab_worker.map_target(f, l, 3, 2000), 2000)       # nicht gemessen
        self.assertEqual(lab_worker.map_target(f, l, 6, 1334), 1418)       # Greifer wie bisher ueber Grenzen

    def test_remote_source_never_gets_a_stop_map(self):
        import types, lab_worker
        f = types.SimpleNamespace(name="follower")
        lab_worker.attach_stop_map(f, lab_worker.RemoteFeed({s: (0, 4095) for s in range(1, 7)}))
        self.assertIsNone(f.stop_map)


if __name__ == "__main__":
    unittest.main()
