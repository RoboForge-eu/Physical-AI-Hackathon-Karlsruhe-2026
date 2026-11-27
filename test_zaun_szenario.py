"""Ende-zu-Ende-Szenario des Arbeitsbereichs in der ECHTEN Folge-Schleife (lab_worker.follow), ohne Arme.

Nachgestellt (Bug 16.11. 20:47): Basis nach rechts hinter die Wand, draussen mit dem Leader herumwackeln
(auch Schulter/Ellbogen/Handgelenk/Greifer), zurueck in den Bereich. Danach muessen ALLE Gelenke wieder folgen.
Vorher hielt die Blockade-Erkennung die vom Zaun festgehaltenen Gelenke faelschlich als 'blockiert' fest.
"""
import io, itertools, threading, unittest
from unittest.mock import Mock, patch
import so101, lab_worker
import arbeitsbereich as A

C = 2047
START = {1: C, 2: 2047, 3: 2047, 4: 2047, 5: 2047, 6: 2000}


def karte():
    """Tisch mit Wand rechts bei x = 0,15 m (Basis bei x = 0, Arm zeigt in der Mitte nach +y)."""
    return {"arm": "t", "aktiv": True, "abstand_m": 0.03,
            "erlaubt": [[[-1, 0.0], [0.15, 0.0], [0.15, 1.0], [-1, 1.0]]], "verboten": [],
            "basis": {"x": 0.0, "y": A.base_back_offset(), "basis_grad": 90, "richtung_grad": 90, "drehsinn": -1}}


def script():
    """Leader-Stellungen Takt fuer Takt."""
    p = dict(START)
    for _ in range(30):
        yield dict(p)
    for b in range(C, C + 900, 10):                   # Basis nach rechts -> in die Wand
        p[1] = b
        yield dict(p)
    for k in range(200):                              # draussen herumwackeln (alle Gelenke)
        q = dict(p)
        q[2] += (k % 40 - 20) * 6
        q[3] += (k % 30 - 15) * 8
        q[4] += (k % 50 - 25) * 6
        q[5] += (k % 20 - 10) * 20
        q[6] = 1500 + (k % 10) * 80
        yield q
    for b in range(C + 900, C - 300, -10):            # zurueck in den Bereich und weiter nach links
        p[1] = b
        yield dict(p)
    for b in list(range(C - 300, C + 900, 15)) + list(range(C + 900, C, -15)):   # ZWEITES Mal rein und raus
        p[1] = b
        p[3] = 1900 + (b % 7) * 10
        yield dict(p)
    for k in range(120):                              # drinnen frei bewegen (Zeit zum Aufholen)
        q = dict(p)
        q[2] = 2047 + k * 3
        q[3] = 2047 - k * 2
        q[4] = 2047 + k
        q[6] = 1800 + k * 5
        yield q


class ZaunSzenario(unittest.TestCase):
    def test_wall_wiggle_return_all_joints_follow_again(self):
        f, l = Mock(), Mock()
        f.name = "t"
        f.lim = l.lim = {s: (0, 4095) for s in so101.JOINTS}
        f.clamp.side_effect = lambda s, p: int(max(0, min(4095, p)))
        f.record = None
        state = {"ist": dict(START)}
        f.fence = A.Fence(karte(), C, log=lambda m: print(m))

        def read_group(n):                          # Servo erreicht das gesendete Ziel im naechsten Takt
            out = {}
            for s in so101.JOINTS:
                d = bytearray(10)
                d[:2] = int(state["ist"][s]).to_bytes(2, "little")
                d[6] = 49
                out[s] = bytes(d)
            return out
        f.read_group.side_effect = read_group
        steps = list(script())
        it = iter(steps)
        stop = threading.Event()
        sent = []

        def leader(n):
            try:
                pose = next(it)
            except StopIteration:
                stop.set()
                pose = steps[-1]
            state["leader"] = pose
            return {s: int(pose[s]).to_bytes(2, "little") for s in so101.JOINTS}
        l.read_group.side_effect = leader

        def send(goals):
            sent.append((dict(state["leader"]), dict(goals)))
            state["ist"] = dict(goals)
        f.send_goals.side_effect = send
        ticks = itertools.count()
        with patch("lab_worker.time.monotonic", side_effect=lambda: next(ticks) * 0.02), \
             patch("sys.stdout", new_callable=io.StringIO) as log:
            lab_worker.follow(f, l, stop, blend_seconds=0)
        text = log.getvalue()
        self.assertEqual(text.count("ZAUN: Wand erreicht"), 2)      # zweimal an die Wand ...
        self.assertEqual(text.count("folgt direkt"), 2)             # ... und beide Male wieder frei
        self.assertNotIn("GELENK GEHALTEN", text)                   # keine falsche Blockade
        # Waehrend der Leader draussen ist: Follower nie hinter der Wand
        for lead, goals in sent:
            self.assertGreaterEqual(A.clearance(karte(), goals, C)[0], 0.03 - 1e-6)
        # Am Ende folgt jedes Gelenk wieder genau dem Leader
        lead, goals = sent[-1]
        for s in so101.JOINTS:
            self.assertEqual(goals[s], lead[s], f"Gelenk {s} folgt nicht")


if __name__ == "__main__":
    unittest.main()
