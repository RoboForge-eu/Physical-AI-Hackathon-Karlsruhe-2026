"""Offline-Tests der Spannungsmessung (ohne Boards)."""
import time, unittest
import voltmon as V


class FakeBus:
    def __init__(self, volts):
        self.volts, self.calls, self.closed, self.writes = volts, [], False, 0

    def read(self, sid, addr, n):
        self.calls.append((sid, addr, n))
        v = self.volts(sid)
        return None if v is None else bytes([int(round(v * 10)), 30, 0, 0])

    def write(self, *a):                      # darf nie aufgerufen werden
        self.writes += 1

    def close(self):
        self.closed = True


class TrackerTests(unittest.TestCase):
    def test_drop_counted_once_per_dip(self):
        t = V.Tracker()
        for v in (4.8, 3.6, 3.5, 4.8, 3.7, 4.8):
            t.sample("g", v)
        c = t.snapshot()["g"]
        self.assertEqual(c["drops"], 2)
        self.assertEqual(c["min"], 3.5)
        self.assertEqual(c["v"], 4.8)

    def test_missing_answers_counted(self):
        t = V.Tracker()
        t.sample("g", 4.8)
        t.missing("g")
        t.missing("g")
        self.assertEqual(t.snapshot()["g"]["lost"], 2)
        self.assertIsNone(t.snapshot()["g"]["v"])
        t.reset()
        self.assertEqual(t.snapshot(), {})

    def test_levels(self):
        self.assertEqual([V.level(v) for v in (None, 3.9, 4.2, 4.8)], ["lost", "bad", "warn", "ok"])


class MonitorTests(unittest.TestCase):
    def test_reads_only_and_finds_bad_gripper(self):
        n = [0]
        def volts(sid):
            n[0] += 1
            if sid == 6:
                return 3.5 if n[0] % 12 == 0 else (None if n[0] % 17 == 0 else 4.8)
            return 4.8
        bus = FakeBus(volts)
        mon = V.Monitor(arms=["follower"], bus_factory=lambda arm: bus).start()
        time.sleep(0.2)
        mon.stop()
        self.assertTrue(mon.stopped)
        self.assertTrue(bus.closed)
        self.assertEqual(bus.writes, 0)
        self.assertTrue(all(addr == 62 and size == 4 for _, addr, size in bus.calls))
        snap = mon.tracker.snapshot()
        self.assertGreater(snap[("follower", 6)]["drops"], 0)
        self.assertGreater(snap[("follower", 6)]["lost"], 0)
        self.assertEqual(snap[("follower", 1)]["drops"], 0)

    def test_missing_board_is_reported_not_raised(self):
        def factory(arm):
            raise SystemExit("Board fuer 'follower2' nicht gefunden. Vorhandene Ports: COM3")
        mon = V.Monitor(arms=["follower2"], bus_factory=factory).start()
        mon.stop()
        self.assertIn("Board fehlt", mon.state["follower2"])


if __name__ == "__main__":
    unittest.main()
