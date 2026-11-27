"""Offline-Tests fuer servo_ids.py mit simuliertem Bus."""
import os, tempfile, unittest
from unittest.mock import patch
import servo_ids as S


class FakeBus:
    def __init__(self, ids):
        self.servos = {i: {S.ID_ADDR: i, S.LOCK: 1} for i in ids}
        self.writes = []

    def txrx(self, sid, instr, params=b"", timeout=0.03):
        return (sid, 0, b"") if sid in self.servos else None

    def read(self, sid, addr, n):
        return (0).to_bytes(n, "little") if sid in self.servos else None

    def write(self, sid, addr, data):
        if sid not in self.servos:
            return None
        self.writes.append((sid, addr, list(data)))
        if addr == S.ID_ADDR and self.servos[sid][S.LOCK] == 0:
            self.servos[data[0]] = self.servos.pop(sid)
        else:
            self.servos[sid][addr] = data[0]
        return (sid, 0, b"")


class ServoIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(S, "CALDIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_refuses_with_several_servos(self):
        bus = FakeBus([1, 1 + 0, 2])
        with self.assertRaises(SystemExit):
            S.set_id(bus, 3, "follower2", log=lambda *a: None)
        self.assertEqual(bus.writes, [])

    def test_refuses_with_no_servo(self):
        bus = FakeBus([])
        with self.assertRaises(SystemExit):
            S.set_id(bus, 3, "follower2", log=lambda *a: None)

    def test_sets_id_and_locks_eeprom(self):
        bus = FakeBus([1])
        S.set_id(bus, 4, "follower2", log=lambda *a: None)
        self.assertEqual(list(bus.servos), [4])
        self.assertEqual(bus.servos[4][S.LOCK], 1)
        self.assertEqual(bus.writes[0], (1, S.TORQUE, [0]))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "follower2_servo4_factory.json")))

    def test_same_id_writes_nothing(self):
        bus = FakeBus([1])
        S.set_id(bus, 1, "follower2", log=lambda *a: None)
        self.assertEqual(bus.writes, [])


if __name__ == "__main__":
    unittest.main()
