"""Safety regression tests with fake arms only; never opens a serial port."""
import io
import types
import unittest
import threading
import itertools
from unittest.mock import Mock, patch
import so101
import lab_worker


class SafetyTests(unittest.TestCase):
    def fast_arms(self):
        f, l = Mock(), Mock()
        f.lim = l.lim = {s: (0, 4095) for s in so101.JOINTS}
        f.clamp.side_effect = lambda s, p: int(max(0, min(4095, p)))
        l.rd.return_value = 2047
        l.read_group.return_value = {s: (2047).to_bytes(2, "little") for s in so101.JOINTS}
        data = bytearray(10)
        data[:2] = (2047).to_bytes(2, "little")
        data[6] = 49
        f.rd.return_value = int.from_bytes(data, "little")
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        return f, l

    def test_fast_follow_streams_all_joints_without_waiting_for_arrival(self):
        f, l = self.fast_arms()
        stop = threading.Event()
        f.send_goals.side_effect = lambda goals: stop.set()
        with patch("sys.stdout", new_callable=io.StringIO):
            lab_worker.follow(f, l, stop, blend_seconds=0)
        self.assertEqual(f.send_goals.call_args.args[0], {s: 2047 for s in so101.JOINTS})
        f.step_to.assert_not_called()

    def test_stop_after_leader_read_does_not_send_new_goal(self):
        f, l = self.fast_arms()
        stop = threading.Event()
        def read(*args):
            stop.set()
            return {s: (2047).to_bytes(2, "little") for s in so101.JOINTS}
        l.read_group.side_effect = read
        with patch("sys.stdout", new_callable=io.StringIO):
            lab_worker.follow(f, l, stop)
        f.send_goals.assert_not_called()

    def test_fast_follow_aborts_on_servo_status(self):
        f, l = self.fast_arms()
        data = bytearray(10)
        data[6] = 49
        data[9] = 4
        f.rd.return_value = int.from_bytes(data, "little")
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        with patch("sys.stdout", new_callable=io.StringIO), self.assertRaises(so101.Abort):
            lab_worker.follow(f, l, threading.Event())

    def test_gripper_overload_holds_gripper_and_keeps_following(self):
        f, l = self.fast_arms()
        normal = bytearray(10)
        normal[:2] = (2047).to_bytes(2, "little")
        normal[6] = 49
        over = bytearray(normal)
        over[:2] = (1800).to_bytes(2, "little")
        over[9] = 0x20
        f.read_group.return_value = {s: bytes(over if s == 6 else normal) for s in so101.JOINTS}
        stop = threading.Event()
        sent = []
        def send(goals):
            sent.append(dict(goals))
            if len(sent) >= 3:
                stop.set()
        f.send_goals.side_effect = send
        with patch("sys.stdout", new_callable=io.StringIO) as log:
            lab_worker.follow(f, l, stop, blend_seconds=0)
        self.assertIn("GREIFER GEHALTEN", log.getvalue())
        self.assertEqual(sent[-1][6], 1800)
        self.assertEqual(sent[-1][2], 2047)
        f.wr.assert_any_call(6, lab_worker.TORQUE_LIMIT, (1000).to_bytes(2, "little"))

    def test_blocked_joint_is_held_even_while_leader_keeps_moving(self):
        # Log 14.11. 00:24: wrist roll stuck at 3211 while leader went 3349 -> 3551.
        track = {}
        held_at = None
        for i in range(30):
            t = i * 0.02
            target = min(3551, 3211 + i * 15)
            if lab_worker.update_stall(track, 3211, target, t):
                held_at = t
                break
        self.assertIsNotNone(held_at)
        self.assertLess(held_at, 0.5)

    def test_resting_joint_is_not_held_when_leader_starts_a_fast_move(self):
        track = {}
        for t in (0.0, 1.0, 2.0):
            self.assertFalse(lab_worker.update_stall(track, 2047, 2050, t))
        # Leader jumps; joint starts moving within 60 ms and keeps moving.
        for i, p in enumerate((2047, 2047, 2047, 2080, 2130, 2190, 2250, 2300)):
            self.assertFalse(lab_worker.update_stall(track, p, 2500, 2.0 + i * 0.02))

    def test_regulator_residual_under_load_is_not_a_blockade(self):
        track = {}
        for i in range(500):
            self.assertFalse(lab_worker.update_stall(track, 1980, 2047, i * 0.02))

    def test_overload_bit_does_not_prevent_parking(self):
        self.assertTrue(lab_worker.fatal_bits(5, 0x20))
        self.assertFalse(lab_worker.fatal_bits(5, 0x20, parking=True))
        self.assertTrue(lab_worker.fatal_bits(5, 0x24, parking=True))   # other bits stay fatal

    def test_height_model_reproduces_table_contact_of_old_parking(self):
        # 12:38: elbow+wrist folded while the shoulder was still forward -> table.
        tip = so101.heights({2: 2701, 3: 3097, 4: 904})[2]
        self.assertLess(tip, 0.03)
        self.assertAlmostEqual(min(so101.heights({2: 2047, 3: 2047, 4: 2047})), 0.216, places=3)

    def test_rest_pose_keeps_the_proven_shoulder_first_order(self):
        order, clearance = so101.plan_mid_order({2: 835, 3: 3097, 4: 902})
        self.assertEqual(order, so101.ORDER)
        self.assertGreater(clearance, 0.05)

    def test_planner_never_picks_an_order_that_goes_lower_than_standard(self):
        import itertools
        poses = [{2: a, 3: b, 4: c} for a in range(900, 3200, 300)
                 for b in range(1000, 3200, 300) for c in range(900, 3200, 300)]
        for p in poses:
            order, clearance = so101.plan_mid_order(p)
            self.assertGreaterEqual(clearance + 1e-9, so101.path_clearance(p, so101.PITCH))
            self.assertAlmostEqual(clearance, so101.path_clearance(p, order[:3]))
            self.assertEqual(order[3:], [1, 5, 6])

    def test_worker_refuses_to_move_without_safe_path_to_mid(self):
        def fake_arm(name):
            arm = Mock()
            arm.name = name
            arm.disconnected = False
            arm.limits.return_value = {s: (500, 3600) for s in so101.JOINTS}
            arm.lim = arm.limits.return_value
            arm.positions.return_value = {s: 2047 for s in so101.JOINTS}
            arm.rd.side_effect = lambda s, addr, n: 49 if addr == so101.VOLT else 0
            arm.clamp.side_effect = lambda s, p: int(p)
            return arm
        with patch("lab_worker.CheckedArm", side_effect=fake_arm), patch("lab_worker.threading.Thread"), \
             patch("lab_worker.plan_mid_order", return_value=(so101.ORDER, -0.02)), \
             patch("lab_worker.raise_to_mid") as raising, patch("lab_worker.park") as parking, \
             patch("sys.stdout", new_callable=io.StringIO) as log:
            self.assertEqual(lab_worker.main(move=True), 1)
        raising.assert_not_called()
        parking.assert_not_called()
        self.assertIn("Kein sicherer Weg", log.getvalue())

    def test_resting_gripper_is_not_limited_when_leader_starts_moving(self):
        # Log 15:26:50: gripper rested at 1939 for seconds, leader jumped to 1772 ->
        # torque was limited immediately and the gripper crawled.
        f = Mock()
        grip = {"squeezing": 0, "anchor": None, "anchor_t": 0.0}
        with patch("sys.stdout", new_callable=io.StringIO):
            for t in (0.0, 1.0, 2.0):
                lab_worker.update_grip(f, grip, 1939, 1936, t)
            lab_worker.update_grip(f, grip, 1939, 1772, 2.02)   # leader moves
            lab_worker.update_grip(f, grip, 1900, 1772, 2.04)   # gripper follows
            lab_worker.update_grip(f, grip, 1840, 1772, 2.06)
        f.wr.assert_not_called()

    def test_gripper_start_delay_and_opening_never_limit_torque(self):
        # Log 17.11. 17:52: gripper waits ~0.15 s before it starts moving -> torque was limited and it crawled,
        # even while OPENING (nothing to grip). Follower: closed = low end (lim 1418..2903).
        f = Mock()
        f.lim = {6: (1418, 2903)}
        with patch("sys.stdout", new_callable=io.StringIO):
            grip = {"squeezing": 0, "anchor": None, "anchor_t": 0.0}
            for t in (0.0, 1.0):
                lab_worker.update_grip(f, grip, 1420, 1420, t)
            for t in (1.02, 1.1, 1.2, 1.3):                         # opening, still not moving
                lab_worker.update_grip(f, grip, 1420, 2240, t)
            grip = {"squeezing": 0, "anchor": None, "anchor_t": 0.0}
            lab_worker.update_grip(f, grip, 2237, 2237, 0.0)
            for t in (0.02, 0.1, 0.2, 0.3):                         # closing, start-up dead time
                lab_worker.update_grip(f, grip, 2237, 1400, t)
            lab_worker.update_grip(f, grip, 2100, 1400, 0.4)        # now it moves
        f.wr.assert_not_called()

    def test_part_already_between_fingers_is_still_detected(self):
        f = Mock()
        f.lim = {6: (1418, 2903)}
        grip = {"squeezing": 0, "anchor": None, "anchor_t": 0.0}
        with patch("sys.stdout", new_callable=io.StringIO):
            lab_worker.update_grip(f, grip, 1700, 1700, 0.0)
            for t in (0.02, 0.2, 0.4, 0.6):                         # closing, blocked from the start
                lab_worker.update_grip(f, grip, 1700, 1420, t)
        f.wr.assert_called_once_with(6, lab_worker.TORQUE_LIMIT, (500).to_bytes(2, "little"))

    def test_grip_limits_torque_only_while_squeezing(self):
        f = Mock()
        grip = {"squeezing": 0, "anchor": None, "anchor_t": 0.0}
        limit = lambda v: unittest.mock.call(6, lab_worker.TORQUE_LIMIT, v.to_bytes(2, "little"))
        with patch("sys.stdout", new_callable=io.StringIO):
            # Fast free motion with lag: moving, so no limit.
            for i, p in enumerate((1800, 1760, 1720)):
                lab_worker.update_grip(f, grip, p, 1600, i * 0.02)
            f.wr.assert_not_called()
            # Contact: stalled with large error -> limit.
            for t in (0.10, 0.20, 0.30):
                lab_worker.update_grip(f, grip, 1720, 1600, t)
            self.assertEqual(f.wr.call_args_list, [limit(500)])
            # Leader opens -> full torque again.
            lab_worker.update_grip(f, grip, 1720, 1800, 0.32)
            self.assertEqual(f.wr.call_args_list, [limit(500), limit(1000)])

    def test_shoulder_overload_still_aborts_follow(self):
        f, l = self.fast_arms()
        data = bytearray(10)
        data[6] = 49
        data[9] = 0x20
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        with patch("sys.stdout", new_callable=io.StringIO), self.assertRaises(so101.Abort):
            lab_worker.follow(f, l, threading.Event())

    def test_fast_follow_aborts_on_persistent_low_voltage(self):
        f, l = self.fast_arms()
        data = bytearray(10)
        data[:2] = (2047).to_bytes(2, "little")
        data[6] = 41
        f.rd.return_value = int.from_bytes(data, "little")
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        ticks = itertools.count()
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(ticks) * 0.1), \
             patch("sys.stdout", new_callable=io.StringIO), self.assertRaisesRegex(so101.Abort, "Unterspannung"):
            lab_worker.follow(f, l, threading.Event())

    def test_stalled_joint_holds_but_loop_runs_until_user_stop(self):
        f, l = self.fast_arms()
        data = bytearray(10)
        data[:2] = (1000).to_bytes(2, "little")
        data[6] = 49
        f.rd.return_value = int.from_bytes(data, "little")
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        stop = threading.Event()
        def send(goals):
            if f.send_goals.call_count >= 100:
                stop.set()
        f.send_goals.side_effect = send
        ticks = itertools.count()
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(ticks) * 0.1), \
             patch("sys.stdout", new_callable=io.StringIO):
            lab_worker.follow(f, l, stop, blend_seconds=0)
        self.assertEqual(f.send_goals.call_count, 100)
        # Joints 1-5 are held. The gripper is blocked while OPENING (1000 -> 2047): that is not a grip,
        # so its torque is not limited (17.11.: limiting on opening made the gripper crawl).
        self.assertEqual(f.goal.call_count, 5)
        expected = {s: 1000 for s in so101.JOINTS}
        expected[6] = 2047
        self.assertEqual(f.send_goals.call_args.args[0], expected)
        self.assertNotIn(unittest.mock.call(6, lab_worker.TORQUE_LIMIT, (500).to_bytes(2, "little")),
                         f.wr.call_args_list)

    def test_normal_regulator_error_runs_beyond_sixty_seconds(self):
        f, l = self.fast_arms()
        data = bytearray(10)
        data[:2] = (1980).to_bytes(2, "little")  # about six degrees from target
        data[6] = 49
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        stop = threading.Event()
        def send(goals):
            if f.send_goals.call_count >= 300:
                stop.set()
        f.send_goals.side_effect = send
        ticks = itertools.count()
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(ticks) * 0.1), \
             patch("sys.stdout", new_callable=io.StringIO):
            lab_worker.follow(f, l, stop, blend_seconds=0)
        self.assertEqual(f.send_goals.call_count, 300)
        f.goal.assert_not_called()

    def test_held_joint_resumes_when_leader_returns(self):
        f, l = self.fast_arms()
        data = bytearray(10)
        data[:2] = (1000).to_bytes(2, "little")
        data[6] = 49
        f.read_group.return_value = {s: bytes(data) for s in so101.JOINTS}
        stop = threading.Event()
        def leader(size):
            value = 2047 if f.send_goals.call_count < 50 else 1000
            return {s: value.to_bytes(2, "little") for s in so101.JOINTS}
        l.read_group.side_effect = leader
        def send(goals):
            if f.send_goals.call_count >= 100:
                stop.set()
        f.send_goals.side_effect = send
        ticks = itertools.count()
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(ticks) * 0.1), \
             patch("sys.stdout", new_callable=io.StringIO) as log:
            lab_worker.follow(f, l, stop, blend_seconds=0)
        self.assertEqual(f.goal.call_count, 5)
        # 6x ACC + gripper full torque + 5x ACC on resume (opening never limits the gripper torque).
        self.assertEqual(f.wr.call_count, 12)
        self.assertIn("folgt wieder", log.getvalue())

    def test_group_disconnect_prevents_subsequent_motion_commands(self):
        arm = object.__new__(lab_worker.CheckedArm)
        arm.name = "test"
        arm.disconnected = False
        arm.bus = Mock()
        arm.bus.sync_read.return_value = None
        with self.assertRaises(lab_worker.ConnectionLost):
            arm.read_group(2)
        with self.assertRaises(lab_worker.ConnectionLost):
            arm.send_goals({s: 2047 for s in so101.JOINTS})
        arm.bus.sync_write.assert_not_called()

    def test_mapping_preserves_limits_and_gripper_conversion(self):
        f, l = self.fast_arms()
        f.lim = dict(f.lim)
        l.lim = dict(l.lim)
        f.lim[6] = (1418, 2903)
        l.lim[6] = (1334, 2510)
        f.clamp.side_effect = lambda s, p: int(max(f.lim[s][0], min(f.lim[s][1], p)))
        self.assertEqual(lab_worker.map_target(f, l, 6, 1334), 1418)
        self.assertEqual(lab_worker.map_target(f, l, 6, 2510), 2903)
        self.assertEqual(lab_worker.map_target(f, l, 1, 9999), 4095)

    def test_partial_raise_remains_visible_to_caller(self):
        arm = Mock(name="arm")
        arm.name = "test"
        arm.stop_requested = lambda: False
        arm.hold.side_effect = so101.Abort("test failure")
        moved = []
        with patch("builtins.open", unittest.mock.mock_open()), self.assertRaises(so101.Abort):
            so101.raise_to_mid(arm, {s: 2047 for s in so101.JOINTS}, moved)
        self.assertEqual(moved, [3])

    def test_failed_parking_never_releases_torque(self):
        arm = Mock()
        arm.step_to.side_effect = so101.Abort("obstruction")
        with self.assertRaises(so101.Abort):
            so101.park(arm, {s: 2047 for s in so101.JOINTS}, [2, 3], via_mid=False)
        arm.release.assert_not_called()

    def test_parking_reverses_order_before_release(self):
        arm = Mock()
        with patch("so101.time.sleep"):
            so101.park(arm, {s: 2047 for s in so101.JOINTS}, so101.ORDER, via_mid=False)
        self.assertEqual([c.args[0] for c in arm.step_to.call_args_list], list(reversed(so101.ORDER)))
        self.assertEqual(arm.mock_calls[-1], unittest.mock.call.release())

    @patch("so101.PARALLEL_PITCH", False)   # prueft den Einzel-Weg (Rueckfall)

    def test_parking_from_follow_pose_goes_via_mid_first(self):
        arm = Mock()
        rest = {1: 1944, 2: 835, 3: 3097, 4: 902, 5: 1955, 6: 1549}
        with patch("so101.time.sleep"):
            so101.park(arm, rest, so101.ORDER, via_mid=True)
        calls = [(c.args[0], c.args[1]) for c in arm.step_to.call_args_list]
        self.assertEqual(calls[:6], [(s, so101.MID) for s in so101.ORDER])
        self.assertEqual(calls[6:], [(s, rest[s]) for s in reversed(so101.ORDER)])
        self.assertEqual(arm.mock_calls[-1], unittest.mock.call.release())

    def test_lab_worker_parks_via_mid(self):
        import inspect
        src = inspect.getsource(lab_worker.run_arm)
        self.assertIn("via_mid=True", src)
        self.assertNotIn("via_mid=False", src)

    def test_bus_timeout_prevents_all_further_transactions(self):
        arm = object.__new__(lab_worker.CheckedArm)
        arm.name = "test"
        arm.disconnected = False
        arm.bus = Mock()
        arm.bus.read.return_value = None
        with self.assertRaises(lab_worker.ConnectionLost):
            arm.rd(1, so101.POS, 2)
        with self.assertRaises(lab_worker.ConnectionLost):
            arm.rd(2, so101.POS, 2)
        with self.assertRaises(lab_worker.ConnectionLost):
            arm.wr(1, so101.GOAL, [0, 0])
        self.assertEqual(arm.bus.read.call_count, 1)
        arm.bus.write.assert_not_called()

    def test_worker_parks_after_exception_during_raise(self):
        def fake_arm(name):
            arm = Mock()
            arm.name = name
            arm.disconnected = False
            arm.limits.return_value = {s: (500, 3600) for s in so101.JOINTS}
            arm.lim = arm.limits.return_value
            arm.positions.return_value = {s: 2047 for s in so101.JOINTS}
            if name == "follower":
                arm.positions.return_value[2] = 859
            arm.rd.side_effect = lambda s, addr, n: 49 if addr == so101.VOLT else 0
            arm.clamp.side_effect = lambda s, p: int(p)
            return arm
        def fail_raise(arm, start, moved, **kwargs):
            moved.append(2)
            raise so101.Abort("interrupted raise")
        with patch("lab_worker.CheckedArm", side_effect=fake_arm), patch("lab_worker.threading.Thread"), \
             patch("lab_worker.raise_to_mid", side_effect=fail_raise), patch("lab_worker.park") as parking, \
             patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(lab_worker.main(move=True), 1)
        self.assertEqual(parking.call_args.args[2], [2])

    def test_emergency_stop_opens_gripper_before_parking(self):
        f = Mock()
        f.name = "follower"
        f.disconnected = False
        f.lim = {s: (500, 3600) for s in so101.JOINTS}
        f.limits.return_value = f.lim
        f.positions.return_value = {s: 2047 for s in so101.JOINTS}
        f.rd.side_effect = lambda s, addr, n: 49 if addr == so101.VOLT else 0
        f.clamp.side_effect = lambda s, p: int(p)
        leader = Mock()
        leader.positions.return_value = {s: 2047 for s in so101.JOINTS}
        leader.lim = {s: (500, 3600) for s in so101.JOINTS}
        leader.offsets = None                               # keine Anschlag-Kalibrierung im Test
        leader.disconnected = False
        stop = threading.Event()
        stop.free = True
        order = []
        def raise_and_stop(arm, start, moved, **kw):
            moved.append(2)
            stop.set()                                      # Not-Ablage waehrend des Hochfahrens
        f.step_to.side_effect = lambda s, *a, **kw: order.append(("greifer" if s == 6 else s, a[0] if a else None))
        with patch("lab_worker.CheckedArm", return_value=f), patch("lab_worker.raise_to_mid", side_effect=raise_and_stop), \
             patch("lab_worker.park", side_effect=lambda *a, **kw: order.append(("ablegen", None))), \
             patch("lab_worker.precheck"), patch("sys.stdout", new_callable=io.StringIO) as log:
            lab_worker.run_arm("follower", leader, stop)
        self.assertEqual(order[0], ("greifer", 3600 - 40))   # erst Greifer ganz auf
        self.assertEqual(order[-1], ("ablegen", None))
        self.assertIn("Not-Ablage", log.getvalue())

    def test_stop_frei_command_marks_emergency(self):
        seen = {}
        def fake_run(key, source, stop, move=True, record=None):
            stop.wait(2)
            seen["free"] = getattr(stop, "free", False)
            return 0
        def commands():
            import time
            yield "start follower\n"
            time.sleep(0.05)
            yield "stop follower frei\n"
            time.sleep(0.05)
            yield "quit\n"
        with patch("lab_worker.run_arm", side_effect=fake_run):
            lab_worker.multi_main(commands(), out=io.StringIO(), open_leader=lambda: MultiArmTests.leader(None))
        self.assertTrue(seen["free"])

    def test_rest_start_parks_into_start_pose(self):
        actual = dict(lab_worker.REST_POSE)
        actual[2] += 100
        self.assertIs(lab_worker.rest_target(actual), actual)

    def test_raised_start_parks_into_fixed_rest_pose(self):
        actual = {1: 1952, 2: 1426, 3: 3080, 4: 912, 5: 1956, 6: 1551}
        self.assertEqual(lab_worker.rest_target(actual), lab_worker.REST_POSE)


class SecondArmTests(unittest.TestCase):
    def test_unknown_rest_pose_parks_into_start_pose(self):
        actual = {1: 2000, 2: 2500, 3: 2000, 4: 2000, 5: 2000, 6: 2000}
        self.assertIs(lab_worker.rest_target(actual, None), actual)

    def test_rest_pose_from_config(self):
        self.assertEqual(lab_worker.rest_pose("follower"), lab_worker.REST_POSE)
        self.assertEqual(lab_worker.rest_pose("follower2")[4], 862)
        self.assertIsNone(lab_worker.rest_pose("follower9"))

    def test_uncalibrated_arm_is_refused(self):
        arm = Mock()
        arm.name = "follower2"
        lim = {s: (500, 3600) for s in so101.JOINTS}
        lab_worker.check_calibrated(arm, lim)
        lim[2] = (0, 4095)
        with self.assertRaises(so101.Abort):
            lab_worker.check_calibrated(arm, lim)

    def test_worker_uses_selected_follower(self):
        names = []
        def fake_arm(name):
            names.append(name)
            raise so101.Abort("kein Board")
        with patch("lab_worker.CheckedArm", side_effect=fake_arm), patch("lab_worker.threading.Thread"), \
             patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(lab_worker.run_arm("follower2", Mock(disconnected=False), threading.Event()), 1)
        self.assertEqual(names, ["follower2"])

    def test_leader_is_prechecked_again(self):
        leader = Mock()
        leader.name, leader.port = "leader", "COM3"
        leader.limits.return_value = {s: (500, 3600) for s in so101.JOINTS}
        leader.rd.side_effect = lambda s, addr, n: 49 if addr == so101.VOLT else (so101.STATUS == addr and s == 3 and 0x20 or 0)
        with patch("lab_worker.CheckedArm", return_value=leader), patch("lab_worker.threading.Thread"),              patch("lab_worker.run_arm") as run, patch("sys.stdout", new_callable=io.StringIO) as log:
            self.assertEqual(lab_worker.main(move=True), 1)
        run.assert_not_called()
        self.assertIn("Ueberlast", log.getvalue())

    def test_window_arm_list_and_ports(self):
        import ros as lab
        arms, leader = lab.load_arms()
        self.assertEqual([a[0] for a in arms], ["follower", "follower2"])
        self.assertEqual(arms[0][3], [0, 1])
        self.assertEqual(arms[1][3], [2, 3])
        self.assertEqual(lab.port_of({"5B79080235": "COM6"}, "5B79080235"), "COM6")
        self.assertIsNone(lab.port_of({"5B79080086": "COM3"}, "5B79080235"))



class MultiArmTests(unittest.TestCase):
    def leader(self):
        leader = Mock()
        leader.name, leader.port = "leader", "COM3"
        leader.lim = {s: (500, 3600) for s in so101.JOINTS}
        leader.limits.return_value = leader.lim
        leader.rd.side_effect = lambda s, addr, n: 49 if addr == so101.VOLT else 0
        leader.read_group.side_effect = lambda size: {s: (2000 + s).to_bytes(2, "little") for s in so101.JOINTS}
        return leader

    def test_feed_hands_new_samples_to_every_arm(self):
        feed = lab_worker.LeaderFeed(self.leader())
        t = threading.Thread(target=feed.run, daemon=True)
        t.start()
        got = []
        def reader():
            got.append(feed.positions())
        threads = [threading.Thread(target=reader) for _ in range(2)]
        [x.start() for x in threads]
        [x.join() for x in threads]
        feed.halt.set()
        t.join(1)
        self.assertEqual(got[0][3], 2003)
        self.assertEqual(got[1][3], 2003)

    def test_feed_failure_reaches_followers(self):
        leader = self.leader()
        leader.read_group.side_effect = OSError("USB weg")
        feed = lab_worker.LeaderFeed(leader)
        with patch("sys.stdout", new_callable=io.StringIO):
            feed.run()
        self.assertTrue(feed.disconnected)
        with self.assertRaises(lab_worker.ConnectionLost):
            feed.read_group(2)

    def test_two_arms_run_in_parallel_and_quit_waits_for_parking(self):
        both_running = threading.Barrier(2, timeout=2)
        seen = {}
        def fake_run(key, feed, stop, move=True, record=None):
            both_running.wait()                 # deadlocks unless both arms run at the same time
            stop.wait(2)
            seen[key] = stop.is_set()
            print("ABGELEGT. Motoren freigegeben.", flush=True)
            return 0
        out = io.StringIO()
        def commands():
            yield "start follower\n"
            yield "start follower2\n"
            import time
            time.sleep(0.3)
            yield "quit\n"
        with patch("lab_worker.run_arm", side_effect=fake_run):
            rc = lab_worker.multi_main(commands(), out=out, open_leader=self.leader)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, {"follower": True, "follower2": True})
        text = out.getvalue()
        self.assertIn("[follower] ABGELEGT", text)
        self.assertIn("[follower2] ARMENDE 0", text)
        self.assertLess(text.index("[follower2] ARMENDE"), text.index("WORKER ENDE"))

    def test_switch_stops_one_arm_while_other_starts(self):
        events = []
        def fake_run(key, feed, stop, move=True, record=None):
            events.append(("start", key))
            stop.wait(2)
            events.append(("stopped", key))
            return 0
        def commands():
            import time
            yield "start follower\n"
            time.sleep(0.1)
            yield "stop follower\n"
            yield "start follower2\n"
            time.sleep(0.2)
            yield "quit\n"
        with patch("lab_worker.run_arm", side_effect=fake_run):
            lab_worker.multi_main(commands(), out=io.StringIO(), open_leader=self.leader)
        self.assertIn(("start", "follower2"), events)
        self.assertEqual(events.count(("stopped", "follower")), 1)

    def test_unknown_arm_is_rejected(self):
        out = io.StringIO()
        with patch("lab_worker.run_arm") as run:
            lab_worker.multi_main(iter(["start leader\n", "start foo\n"]), out=out, open_leader=self.leader)
        run.assert_not_called()
        self.assertIn("Unbekannter Arm", out.getvalue())



class RemoteSourceTests(unittest.TestCase):
    def test_holds_last_target_then_aborts_when_stale(self):
        feed = lab_worker.RemoteFeed({s: (500, 3600) for s in so101.JOINTS})
        feed.update([2047, 2100, 2000, 2047, 2047, 1500])
        self.assertEqual(feed.positions()[2], 2100)
        self.assertEqual(feed.positions()[2], 2100)            # keine neuen Ziele: letztes halten
        feed.time -= lab_worker.REMOTE_STALE_S + 0.1
        with self.assertRaises(so101.Abort):
            feed.read_group(2)
        self.assertFalse(feed.disconnected)                    # -> normales Ablegen, kein Busfehler

    def test_rejects_bad_targets_and_missing_data(self):
        feed = lab_worker.RemoteFeed({})
        with self.assertRaises(ValueError):
            feed.update([2047] * 5)
        with self.assertRaises(ValueError):
            feed.update([2047, 2047, 2047, 2047, 2047, 5000])
        with patch("lab_worker.threading.Condition.wait_for", return_value=False):
            with self.assertRaises(so101.Abort):
                feed.read_group(2)

    def test_remote_arm_follows_remote_feed_and_leader_arm_the_leader(self):
        used = {}
        def fake_run(key, source, stop, move=True, record=None):
            used[key] = source.name
            if source.name == "remote":
                used["pos"] = source.positions()[3]
            stop.wait(2)
            return 0
        def commands():
            import time
            yield "target 2047 2047 1900 2047 2047 1500\n"
            yield "start follower2 remote\n"
            yield "start follower\n"
            time.sleep(0.2)
            yield "quit\n"
        leader = MultiArmTests.leader(None)
        with patch("lab_worker.run_arm", side_effect=fake_run):
            lab_worker.multi_main(commands(), out=io.StringIO(), open_leader=lambda: leader)
        self.assertEqual(used["follower2"], "remote")
        self.assertEqual(used["follower"], "leader")
        self.assertEqual(used["pos"], 1900)

    def test_ki_arm_gets_its_own_policy_feed_and_recording_flag(self):
        used = {}
        def fake_run(key, source, stop, move=True, record=None):
            import time
            used[key] = source.name
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and source.data is None:
                time.sleep(0.01)
            used["rec"] = record.is_set()               # KI-Lauf: Ist-Stellung wird automatisch gemeldet
            used["pos"] = source.positions()[3]
            used["identity"] = lab_worker.map_target(types.SimpleNamespace(clamp=lambda s, p: p), source, 6, 1500)
            stop.wait(2)
            return 0
        def commands():
            import time
            yield "start follower ki\n"
            time.sleep(0.05)
            yield "ktarget follower 2047 2047 1800 2047 2047 1500\n"
            yield "ktarget follower2 1 1 1 1 1 1\n"            # kein KI-Lauf: nur Meldung
            yield "rec follower on\n"
            time.sleep(0.3)
            yield "quit\n"
        out = io.StringIO()
        with patch("lab_worker.run_arm", side_effect=fake_run):
            lab_worker.multi_main(commands(), out=out, open_leader=lambda: MultiArmTests.leader(None))
        self.assertEqual(used["follower"], "ki")
        self.assertTrue(used["rec"])
        self.assertEqual(used["pos"], 1800)
        self.assertEqual(used["identity"], 1500)                # keine Greifer-Umrechnung
        self.assertIn("kein KI-Lauf", out.getvalue())

    def test_follow_prints_obs_lines_while_recording(self):
        f, l = SafetyTests.fast_arms(None)
        f.record = threading.Event()
        f.record.set()
        stop = threading.Event()
        n = [0]
        def send(goals):
            n[0] += 1
            if n[0] > 40:
                stop.set()
        f.send_goals.side_effect = send
        with patch("sys.stdout", new_callable=io.StringIO) as log:
            lab_worker.follow(f, l, stop, blend_seconds=0)
        lines = [x for x in log.getvalue().splitlines() if x.startswith("OBS ")]
        self.assertTrue(lines)
        state, action = lines[0][4:].split("|")
        self.assertEqual(len(state.split()), 6)
        self.assertEqual(len(action.split()), 6)

    def test_remote_follow_parks_when_targets_stop(self):
        f, _ = SafetyTests.fast_arms(None)
        feed = lab_worker.RemoteFeed({s: (0, 4095) for s in so101.JOINTS})
        feed.update([2047] * 6)
        stop = threading.Event()
        calls = []
        def send(goals):
            calls.append(goals)
            feed.time -= 5                                     # Ziele veralten
        f.send_goals.side_effect = send
        with patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(so101.Abort):
                lab_worker.follow(f, feed, stop, blend_seconds=0)
        self.assertEqual(len(calls), 1)


class RemoteResetTests(unittest.TestCase):
    def test_reset_keeps_clients_and_needs_new_clutch(self):
        import remote_server
        srv = remote_server.Server(log=lambda *_: None)
        srv.ctl.connect(7)
        srv.desk.claim(7, 10, 0)
        srv.ctl.target = (0.3, 0.0, 0.25, 1.57)
        srv.reset()
        self.assertEqual(srv.ctl.operator, 7)
        self.assertTrue(srv.ctl.need_release)
        self.assertEqual(srv.state["joints"][:5], [2047] * 5)



class BaseCenterTests(unittest.TestCase):
    """Log 2026-11-16 15:26: Basis lag nach dem Kalibrieren bei 3179 (nahe Anschlag); der Arm streckte sich
    dort aus und drehte erst dann zur Mitte -> stiess an den Rechner neben dem Tisch."""
    def test_base_turns_to_center_before_raising(self):
        f, calls = Mock(), []
        f.hold.side_effect = lambda s, delay=0: calls.append(("hold", s))
        f.step_to.side_effect = lambda s, t, **k: calls.append(("step", s, t))
        moved, stop = [], threading.Event()
        with patch("sys.stdout", new_callable=io.StringIO):
            lab_worker.center_base_first(f, {1: 3179, 2: 845, 3: 3097, 4: 929}, moved, stop, 2126)
        self.assertEqual(calls[-1], ("step", 1, 2126))
        self.assertEqual([c[1] for c in calls if c[0] == "step"], [1])     # nur die Basis faehrt
        self.assertEqual(set(moved), {1, 2, 3, 4})

    def test_base_near_center_does_nothing(self):
        f = Mock()
        lab_worker.center_base_first(f, {1: 2100}, [], threading.Event(), 2126)
        f.step_to.assert_not_called()

    def test_center_from_stop_measurement(self):
        f = Mock()
        f.name = "follower"
        f.lim = {1: (870, 3253)}
        with patch("lab_worker.read_offsets", return_value={1: 1964}),              patch("lab_worker.stopcal.load", return_value={"offsets": {"1": 1964}, "joints": {"1": {"lo": 773, "hi": 3479.5}}}):
            self.assertEqual(lab_worker.base_center(f), 2126)
        with patch("lab_worker.read_offsets", return_value={1: 5}),              patch("lab_worker.stopcal.load", return_value={"offsets": {"1": 1964}, "joints": {"1": {"lo": 773, "hi": 3479.5}}}):
            self.assertEqual(lab_worker.base_center(f), 2062)            # Offset geaendert -> EEPROM-Grenzen


class GripFixTests(unittest.TestCase):
    """Setup 1: Leader ganz zu (1336) -> Follower-Ziel 1420, Greifer blieb ~2 mm offen."""
    def arms(self, fix, f_lo=1418):
        f, l = Mock(), Mock()
        f.stop_map, f.grip_fix = None, fix
        f.lim = {6: (f_lo, 2903)}
        f.clamp.side_effect = lambda s, p: int(max(f.lim[s][0], min(f.lim[s][1], p)))
        l.identity = False
        l.lim = {6: (1334, 2510)}
        return f, l

    def test_without_fix_unchanged(self):
        f, l = self.arms(None)
        self.assertEqual(lab_worker.map_target(f, l, 6, 1334), 1418)

    def test_fix_closes_further_only_at_closed_end(self):
        fix = {"close_deg": 2.5, "steps": 28, "closed": 1418}
        f, l = self.arms(fix, f_lo=1385)                  # Untergrenze fuer die Korrektur abgesenkt
        self.assertEqual(lab_worker.map_target(f, l, 6, 1334), 1390)
        self.assertEqual(lab_worker.map_target(f, l, 6, 2510), 2903)     # ganz auf: unveraendert

    def test_fix_with_stop_map(self):
        fix = {"close_deg": 2.5, "steps": 28, "closed": 1418}
        f, l = self.arms(fix, f_lo=1370)
        f.stop_map = {"joints": {"6": {"kind": "linear", "leader": [1336.5, 2504.5], "follower": [1403.5, 2902.5]}}}
        self.assertEqual(lab_worker.map_target(f, l, 6, 1336.5), 1375)

if __name__ == "__main__":
    unittest.main()
