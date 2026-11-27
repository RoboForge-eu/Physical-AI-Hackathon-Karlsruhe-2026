"""Ablegen ohne Tischkontakt (Log 17.11.: Ablage mit gestreckter Hand, Ellbogen fuhr beim Einklappen in den Tisch)."""
import unittest
from unittest.mock import Mock, patch
import so101
import lab_worker as W

REST = {1: 2073, 2: 846, 3: 3095, 4: 902, 5: 2159, 6: 1418}
STRAIGHT_HAND = {1: 2068, 2: 850, 3: 3085, 4: 2454, 5: 1020, 6: 1469}


class AblageTests(unittest.TestCase):
    def test_rest_with_straight_hand_parks_with_hand_folded_up(self):
        t = W.rest_target(STRAIGHT_HAND, REST)
        self.assertEqual((t[2], t[3], t[4]), (846, 3095, 902))         # Nickgelenke aus der gemessenen Ablage
        self.assertEqual((t[1], t[5], t[6]), (2068, 1020, 1469))       # Basis/Drehung/Greifer bleiben
        proper = {**STRAIGHT_HAND, 4: 905}
        self.assertIs(W.rest_target(proper, REST), proper)

    def test_fold_order_never_goes_below_table_when_avoidable(self):
        # die alte, stur umgekehrte Reihenfolge haette 1,7 cm in den Tisch gefuehrt
        self.assertLess(so101.path_clearance({2: 2047, 3: 2047, 4: 2047}, [4, 3, 2], STRAIGHT_HAND), 0)
        order, clear = so101.plan_fold_order(STRAIGHT_HAND)
        self.assertGreater(clear, so101.MIN_CLEARANCE_M)
        order, clear = so101.plan_fold_order(REST)
        self.assertEqual(order, [4, 3, 2])                              # bewaehrte Reihenfolge bleibt
        self.assertGreater(clear, 0.05)

    @patch("so101.PARALLEL_PITCH", False)   # prueft den Einzel-Weg (Rueckfall)

    def test_park_uses_planned_fold_order(self):
        arm = Mock()
        with patch("so101.time.sleep"):
            so101.park(arm, STRAIGHT_HAND, moved=so101.ORDER, via_mid=True)
        calls = [c.args[0] for c in arm.step_to.call_args_list]
        fold = calls[len(so101.ORDER):]
        self.assertEqual(fold[:3], [6, 5, 1])                           # erst Greifer, Drehung, Basis
        self.assertEqual(fold[3:], so101.plan_fold_order(STRAIGHT_HAND)[0])
        arm.release.assert_called_once()


class Fake(so101.Arm):
    """Arm ohne Bus: Gelenke laufen pro Abfrage ein Stueck aufs Ziel zu; optional bleibt eins haengen."""
    def __init__(self, pos, stuck=None):
        self.name, self.pos, self.goals, self.stuck = "t", dict(pos), {}, stuck
        self.lim = {s: (0, 4095) for s in so101.JOINTS}
        self.log = []

    def rd(self, s, addr, n, tries=5):
        if addr == so101.VOLT:
            return 49
        if addr == so101.LOAD:
            return 0
        g = self.goals.get(s)
        if g is not None and s != self.stuck:
            self.pos[s] += max(-150, min(150, g - self.pos[s]))
        return self.pos[s]

    def goal(self, s, pos, speed=0, acc=4):
        self.goals[s] = int(pos)
        self.log.append((s, int(pos), speed))


class TogetherTests(unittest.TestCase):
    def test_raise_moves_pitch_joints_together_and_speeds_scale_with_distance(self):
        arm = Fake({1: 2073, 2: 846, 3: 3095, 4: 902, 5: 2047, 6: 1418})
        with patch("so101.time.sleep"), patch("so101.json.dump"), patch("builtins.open"), patch("sys.stdout"):
            arm.limits = lambda: arm.lim
            arm.hold = lambda s, delay=0: None
            so101.raise_to_mid(arm, start=dict(arm.pos), speed=900, poll_interval=0)
        self.assertTrue(all(abs(arm.pos[s] - 2047) <= 18 for s in (2, 3, 4)))
        first = {s: sp for s, pos, sp in arm.log[:3]}
        self.assertEqual(set(first), {2, 3, 4})                         # alle drei Befehle zuerst
        self.assertEqual(max(first.values()), 900)
        self.assertEqual(first[2], 900)                                 # laengster Weg (Schulter) volles Tempo
        self.assertLess(first[3], first[2])                             # kuerzerer Weg -> langsamer, kommen zusammen an

    def test_blocked_joint_stops_all_joints_where_they_are(self):
        arm = Fake({2: 846, 3: 3095, 4: 902}, stuck=3)
        arm.stop_requested = lambda: False
        with patch("so101.time.sleep"), patch("so101.time.monotonic", side_effect=[i * 0.2 for i in range(400)]):
            with self.assertRaisesRegex(so101.Abort, "Ellbogen kommt"):
                arm.step_many({2: 2047, 3: 2047, 4: 2047}, speed=900, poll_interval=0)
        last = {s: p for s, p, sp in arm.log[-3:]}
        self.assertEqual(last, {2: arm.pos[2], 3: arm.pos[3], 4: arm.pos[4]})   # alle halten dort, wo sie sind

    def test_not_together_when_straight_path_is_worse(self):
        ok, c = so101.together_ok({2: 2047, 3: 2047, 4: 2047}, STRAIGHT_HAND, 0.065)
        self.assertFalse(ok and c < 0.065 - 0.005)


class BlendTests(unittest.TestCase):
    def test_blend_time_grows_with_distance(self):
        f = Mock(); f.clamp = lambda s, p: p
        f.stop_map = None
        l = Mock(); l.identity = True
        near = W.blend_duration(f, l, {1: 2047}, {1: (2100).to_bytes(2, "little")}, 0.75)
        far = W.blend_duration(f, l, {1: 2047}, {1: (3047).to_bytes(2, "little")}, 0.75)
        self.assertEqual(near, 0.75)
        self.assertAlmostEqual(far, 1000 * 360 / 4096 / W.BLEND_DEG_S, places=2)   # 88 Grad -> 2,2 s statt 0,75 s
        self.assertEqual(W.blend_duration(f, l, {1: 0}, {1: (4095).to_bytes(2, "little")}, 0.75), W.BLEND_MAX_S)


if __name__ == "__main__":
    unittest.main()
