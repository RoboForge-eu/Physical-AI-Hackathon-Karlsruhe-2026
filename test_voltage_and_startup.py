"""No hardware access: voltage classification and faster monitored startup."""
import io
import unittest
from unittest.mock import Mock, patch, mock_open
from lab_worker import CheckedArm
from so101 import Arm, Abort, JOINTS, ORDER, POS, VOLT, raise_to_mid


class VoltageAndStartupTests(unittest.TestCase):
    def arm(self, name="follower"):
        arm = object.__new__(CheckedArm)
        arm.name = name
        arm.disconnected = False
        arm.voltage_low_since = {}
        arm.voltage_warnings = {}
        arm.bus = Mock()
        arm.rd = Mock(return_value=49)
        return arm

    def test_single_voltage_flag_checks_actual_voltage_and_keeps_positions(self):
        arm = self.arm()
        replies = {s: (0, (2047).to_bytes(2, "little")) for s in JOINTS}
        replies[6] = (1, (1454).to_bytes(2, "little"))
        arm.bus.sync_read.return_value = replies
        with patch("sys.stdout", new_callable=io.StringIO) as log:
            result = arm.read_group(2)
        self.assertEqual(int.from_bytes(result[6], "little"), 1454)
        arm.rd.assert_called_once_with(6, VOLT, 1)
        self.assertFalse(arm.disconnected)
        self.assertIn("4.9 V", log.getvalue())

    def test_sustained_low_voltage_remains_fatal(self):
        arm = self.arm()
        with patch("lab_worker.time.monotonic", side_effect=[0, 0.3, 0.7]), patch("sys.stdout", new_callable=io.StringIO):
            arm.check_voltage(6, 4.1, True)
            arm.check_voltage(6, 4.1, True)
            with self.assertRaisesRegex(Abort, "anhaltende Unterspannung"):
                arm.check_voltage(6, 4.1, True)

    def test_overvoltage_aborts_immediately(self):
        with self.assertRaises(Abort):
            self.arm().check_voltage(6, 8.1, True)

    def test_single_low_outlier_is_tolerated_but_confirmed_low_aborts(self):
        arm = self.arm()
        times = iter([0.0, 0.02, 0.04, 0.06, 0.08, 0.10])
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(times)), \
             patch("sys.stdout", new_callable=io.StringIO):
            arm.check_voltage(6, 3.7)
            arm.check_voltage(6, 4.8)      # outlier gone: counter resets
            arm.check_voltage(6, 3.7)      # t=0.04
            arm.check_voltage(6, 3.7)
            arm.check_voltage(6, 3.7)      # 3 readings but only 40 ms
            with self.assertRaisesRegex(Abort, "Messungen in Folge"):
                arm.check_voltage(6, 3.7)  # 4 readings over 60 ms

    def test_three_fast_readings_within_a_few_ms_do_not_abort(self):
        arm = self.arm()
        times = iter([0.0, 0.001, 0.002, 0.003])
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(times)), \
             patch("sys.stdout", new_callable=io.StringIO):
            for _ in range(4):
                arm.check_voltage(6, 3.7)

    def test_clean_status_reply_resets_low_voltage_counter(self):
        # Log 14.11. 15:24: leader outliers seconds apart were counted as "in a row".
        arm = self.arm()
        arm.voltage_bad_count = {6: (2, 0.0)}
        arm.bus.sync_read.return_value = {s: (0, b'\xff\x07') for s in JOINTS}
        arm.read_group(2)
        self.assertNotIn(6, arm.voltage_bad_count)

    def test_leader_low_voltage_only_warns(self):
        arm = self.arm("leader")
        times = iter([i * 0.1 for i in range(20)])
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(times)), \
             patch("sys.stdout", new_callable=io.StringIO):
            for _ in range(20):
                arm.check_voltage(6, 3.5, True)
        with self.assertRaises(Abort):
            self.arm("leader").check_voltage(6, 8.1, True)

    def test_telemetry_sample_counts_once_even_with_voltage_flags(self):
        arm = self.arm()
        data = bytearray(10)
        data[6] = 37
        data[9] = 1
        arm.bus.sync_read.return_value = {s: (1, bytes(data)) for s in JOINTS}
        times = iter([i * 0.02 for i in range(200)])
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(times)), \
             patch("sys.stdout", new_callable=io.StringIO):
            arm.read_group(10)   # each sample counts once: 2 reads never reach 3
            arm.read_group(10)
            with self.assertRaises(Abort):
                arm.read_group(10)

    def test_other_alarm_bits_are_fatal_even_with_voltage_flag(self):
        for s, status in ((6, 2), (6, 4), (6, 5), (6, 8), (6, 0x22), (5, 32)):
            arm = self.arm()
            with self.subTest(s=s, status=status), self.assertRaises(Abort):
                arm.check_status(s, status)
            arm.rd.assert_not_called()

    def test_gripper_overload_is_not_fatal_but_other_joints_are(self):
        arm = self.arm()
        with patch("sys.stdout", new_callable=io.StringIO) as log:
            arm.check_status(6, 0x20)
        self.assertIn("GREIFER-UEBERLAST", log.getvalue())
        for s in (1, 2, 3, 4, 5):
            with self.subTest(s=s), self.assertRaises(Abort):
                arm.check_status(s, 0x20)

    def test_gripper_overload_in_write_reply_does_not_block_parking(self):
        arm = self.arm()
        arm.bus.write.return_value = (6, 0x20, b'')
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(arm.wr(6, 42, [0, 0, 0, 0, 60, 0]))
        self.assertFalse(arm.disconnected)

    def test_clean_leader_reply_resets_transient_voltage_timer(self):
        arm = self.arm()
        arm.voltage_low_since[6] = 0
        arm.bus.sync_read.return_value = {s: (0, b'\xff\x07') for s in JOINTS}
        arm.read_group(2)
        self.assertNotIn(6, arm.voltage_low_since)

    def test_voltage_flag_in_write_reply_is_not_a_disconnect(self):
        arm = self.arm()
        arm.bus.write.return_value = (6, 1, b'')
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(arm.wr(6, 41, [80]))
        self.assertFalse(arm.disconnected)

    @patch("so101.PARALLEL_PITCH", False)   # prueft den Einzel-Weg (Rueckfall)

    def test_fast_raise_keeps_joint_order_and_passes_monitoring_settings(self):
        arm = Mock()
        arm.name = "test"
        arm.stop_requested = lambda: False
        with patch("builtins.open", mock_open()):
            raise_to_mid(arm, start={s: 2047 for s in JOINTS}, moved=[], speed=900, acc=80, poll_interval=0.03, hold_delay=0.05)
        self.assertEqual([c.args[0] for c in arm.step_to.call_args_list], ORDER)
        for call in arm.step_to.call_args_list:
            self.assertEqual(call.kwargs, dict(speed=900, acc=80, poll_interval=0.03))

    def test_fast_polling_accumulates_slow_progress_instead_of_false_stall(self):
        arm = object.__new__(Arm)
        arm.clamp = lambda s, p: p
        arm.goal = Mock()
        arm.stop_requested = lambda: False
        positions = iter(range(101))
        arm.rd = lambda s, addr, n: next(positions) if addr == POS else 49
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        with patch("so101.time.sleep", side_effect=sleep), patch("so101.time.monotonic", side_effect=lambda: clock[0]):
            result = arm.step_to(2, 100, speed=900, acc=80, poll_interval=0.03, quiet=True)
        self.assertGreater(clock[0], 1.5)
        self.assertEqual(result, 82)
        arm.goal.assert_called_once_with(2, 100, 900, acc=80)

    def _stepping_arm(self, volts):
        """Arm, der sich 2 Schritte je Abfrage Richtung 100 bewegt; volts liefert die Spannungsfolge."""
        arm = object.__new__(Arm)
        arm.clamp = lambda s, p: p
        arm.goal = Mock()
        arm.stop_requested = lambda: False
        positions = iter(range(0, 1000, 2))
        volts = iter(volts)
        arm.rd = lambda s, addr, n: next(positions) if addr == POS else next(volts, 49)
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        return arm, patch("so101.time.sleep", side_effect=sleep), patch("so101.time.monotonic", side_effect=lambda: clock[0])

    def test_step_to_tolerates_single_low_voltage_readings(self):
        arm, sleep, mono = self._stepping_arm([49, 35, 49, 49, 36, 39, 49])
        with sleep, mono:
            result = arm.step_to(6, 100, poll_interval=0.03, quiet=True)
        self.assertGreaterEqual(result, 82)
        arm.goal.assert_called_once()             # nur der Fahrbefehl, kein Halten

    def test_step_to_aborts_on_three_low_readings_in_a_row_and_holds(self):
        arm, sleep, mono = self._stepping_arm([49, 37, 36, 35])
        with sleep, mono, self.assertRaisesRegex(Abort, "3 Messungen in Folge"):
            arm.step_to(6, 100, poll_interval=0.03, quiet=True)
        self.assertEqual(arm.goal.call_args.args[2], 60)   # an aktueller Position gehalten


if __name__ == "__main__":
    unittest.main()


class ArriveTests(unittest.TestCase):
    """Hochfahren 16.11. 20:55 dauerte 13,7 s: Gelenke blieben unter Last knapp vor dem Ziel stehen und
    step_to wartete jedes Mal 1,5 s. Jetzt: knapp davor still -> nach ARRIVE_SETTLE_S angekommen."""
    def run_step(self, stuck_at, target=2047):
        import so101, itertools
        from unittest.mock import patch
        arm = object.__new__(so101.Arm)
        arm.name, arm.lim = "t", {2: (0, 4095)}
        arm.goal = lambda *a, **k: None
        arm.rd = lambda s, addr, n, tries=5: {so101.POS: stuck_at, so101.VOLT: 49, so101.LOAD: 0}.get(addr, 0)
        ticks = itertools.count()
        with patch("so101.time.sleep"), patch("so101.time.monotonic", side_effect=lambda: next(ticks) * 0.03), \
             patch("sys.stdout"):
            so101.Arm.step_to(arm, 2, target, poll_interval=0.03)
        return next(ticks) * 0.03

    def test_near_target_is_accepted_quickly(self):
        self.assertLess(self.run_step(2047 + 41), 0.6)

    def test_far_from_target_still_aborts(self):
        import so101
        with self.assertRaises(so101.Abort):
            self.run_step(2047 + 300)


class ParallelRollGripTests(unittest.TestCase):
    @patch("so101.PARALLEL_PITCH", False)   # prueft den Einzel-Weg (Rueckfall)
    def test_gripper_starts_together_with_roll_pitch_joints_stay_single(self):
        import so101
        from unittest.mock import Mock, patch
        arm = Mock()
        arm.name = "t"
        arm.stop_requested = lambda: False
        arm.positions.return_value = {s: 2047 for s in so101.JOINTS}
        arm.clamp.side_effect = lambda s, p: p
        calls = []
        arm.step_to.side_effect = lambda s, *a, **k: calls.append(("step", s))
        arm.goal.side_effect = lambda s, *a, **k: calls.append(("goal", s))
        with patch("so101.json.dump"), patch("builtins.open"):
            start, moved = so101.raise_to_mid(arm, start={s: 2047 for s in so101.JOINTS}, moved=[])
        self.assertEqual([c for c in calls if c[0] == "step"],
                         [("step", 2), ("step", 3), ("step", 4), ("step", 1), ("step", 5), ("step", 6)])
        self.assertLess(calls.index(("goal", 6)), calls.index(("step", 5)))   # Greifer startet vor der Drehung
        self.assertEqual(sorted(moved), [1, 2, 3, 4, 5, 6])
