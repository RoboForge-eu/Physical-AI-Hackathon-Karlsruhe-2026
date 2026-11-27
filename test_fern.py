"""Offline-Tests der Fernsteuerung: Leader-Modus im Kern, Zugangscode, App-Logik (ohne Netz, ohne Arme)."""
import base64, json, time, unittest
import remote_core as C
import remote_access as A
import fern_core as F


def start(ctl, now=0.0):
    ctl.connect(1)
    return [ctl.joints[s] for s in range(1, 6)]


def msg(seq, j, clutch=True, grip=0.0):
    return {"t": "joints", "seq": seq, "clutch": clutch, "j": list(j), "grip": grip}


class LeaderModeTests(unittest.TestCase):
    def test_engages_only_when_close_then_follows_with_rate_limit(self):
        c = C.RemoteController()
        j = start(c)
        far = [j[0] + 400] + j[1:]                          # ~35 Grad daneben
        self.assertIn("angleichen", c.handle(1, msg(1, far), 0.0)[0]["msg"])
        self.assertFalse(c.engaged)
        goal = [j[0] + 150] + j[1:]                         # ~13 Grad: kuppelt
        self.assertEqual(c.handle(1, msg(2, goal), 0.0), [])
        self.assertTrue(c.engaged)
        st = c.tick(0.02)
        step = st["joints"][0] - j[0]
        self.assertTrue(0 < step <= C.Config().joint_rate * C.K.TICKS_PER_RAD * 0.02 + 1)   # nicht im Sprung
        for i in range(3, 40):
            c.handle(1, msg(i, goal), i * 0.02)
            st = c.tick(i * 0.02)
        self.assertEqual(st["joints"][0], goal[0])
        self.assertEqual(st["mode"], "joints")
        self.assertEqual(st["joints"][5], C.K.GRIP_OPEN)    # grip 0 = offen

    def test_watchdog_release_stop_and_bad_messages(self):
        c = C.RemoteController()
        j = start(c)
        c.handle(1, msg(1, j), 0.0)
        c.tick(0.01)
        self.assertEqual(c.tick(0.5)["reason"], "funkloch")    # Aussetzer: anhalten, gekuppelt bleiben
        self.assertTrue(c.engaged)
        self.assertEqual(c.handle(1, {"t": "joints", "seq": 9, "clutch": True, "j": [1, 2], "grip": 0}, 0.6)[0]["t"], "error")
        self.assertEqual(c.handle(1, {"t": "joints", "seq": 9, "clutch": "ja", "j": j, "grip": 0}, 0.6)[0]["t"], "error")
        c.handle(1, msg(10, j), 0.7)
        self.assertTrue(c.engaged)                          # Signal wieder da: weiter
        self.assertIsNone(c.state()["reason"])
        c.handle(1, {"t": "stop"}, 0.71)
        self.assertFalse(c.engaged)
        c.handle(1, msg(13, j), 0.72)                       # Kupplung erst loslassen
        self.assertFalse(c.engaged)
        c.handle(1, msg(14, j, clutch=False), 0.73)
        c.handle(1, msg(15, j), 0.74)
        self.assertTrue(c.engaged)

    def test_spectator_cannot_steer_and_table_is_not_crossed(self):
        c = C.RemoteController()
        j = start(c)
        c.connect(2)
        c.handle(2, msg(1, j), 0.0)
        self.assertFalse(c.engaged)
        c.handle(1, msg(1, j), 0.0)
        low = list(j)
        low[1] = j[1] + 100                                  # nach vorn kippen, bis zu tief waere
        t = 0.0
        for i in range(2, 200):
            t = i * 0.02
            low[1] = min(low[1] + 30, 4000)
            c.handle(1, msg(i, low), t)
            st = c.tick(t)
            z = C.K.heights({s: v for s, v in zip(range(1, 6), st["joints"][:5])})
            self.assertGreaterEqual(min(z[:2]), C.K.MIN_LINK_Z - 1e-6)
            self.assertGreaterEqual(z[2], -1e-6)


class AccessCodeTests(unittest.TestCase):
    def test_roundtrip_expiry_and_garbage(self):
        cfg = {"url": "wss://x.livekit.cloud", "api_key": "KEY", "api_secret": "SECRET" * 8, "room": "r"}
        code = A.make_code(cfg, hours=1)
        self.assertTrue(code.startswith("RF1."))
        self.assertNotIn("SECRET", base64.urlsafe_b64decode(code[4:]).decode())   # nie das Geheimnis
        d = A.read_code(" " + code[:20] + "\n" + code[20:] + " ")
        self.assertEqual(d["url"], cfg["url"])
        old = A.PREFIX + base64.urlsafe_b64encode(json.dumps({"url": "u", "token": "t", "bis": 1}).encode()).decode()
        with self.assertRaises(ValueError):
            A.read_code(old)
        for bad in ("", "hallo", "RF1.###"):
            with self.assertRaises(ValueError):
                A.read_code(bad)


class FakeBus:
    def __init__(self, pos, lo=1400, hi=2900):
        self.pos, self.lo, self.hi, self.closed = pos, lo, hi, False
    def read(self, sid, addr, n):
        return (self.lo if addr == F.MIN_ANGLE else self.hi).to_bytes(2, "little")
    def sync_read(self, ids, addr, size):
        return {s: (0, self.pos[s - 1].to_bytes(2, "little")) for s in ids}
    def write(self, *a):
        raise AssertionError("Leader darf nie beschrieben werden")
    def close(self):
        self.closed = True


class AppLogicTests(unittest.TestCase):
    def test_dropout_keeps_steering(self):
        from types import SimpleNamespace
        from fernsteuerung import App
        from fern_sim import KeyTeleop
        c = C.RemoteController()
        j = start(c)
        c.handle(1, msg(1, j), 0.01)
        c.tick(0.01)
        app = App.__new__(App)
        app.steering, app.practice_on = True, False
        app.remote_was_active = True
        app.keys, app.shift = {"w"}, True
        app.teleop = KeyTeleop(j + [1430])
        app.status = SimpleNamespace(set=lambda text: None)
        app.ui = lambda fn: fn()
        c.tick(0.4)                                    # Funkloch: App steuert weiter
        app._event("state", c.state())
        self.assertTrue(app.steering)
        c.handle(1, msg(2, j), 0.41)
        self.assertTrue(c.engaged)
        self.assertIsNone(c.state()["reason"])

    def test_limit_feedback_does_not_queue_system_bells(self):
        import queue
        from types import SimpleNamespace
        from fernsteuerung import App
        app = App.__new__(App)
        app.inbox = queue.Queue()
        app.root = SimpleNamespace(bell=lambda: self.fail("Kein blockierender Systemton"))
        for _ in range(100):
            app._event("haptic", {"kind": "limit"})
        self.assertTrue(app.inbox.empty())
        self.assertGreater(app.limit_feedback_until, time.monotonic())

    def test_ui_queue_yields_to_keyboard_and_mouse(self):
        import queue
        from types import SimpleNamespace
        from fernsteuerung import App
        app = App.__new__(App)
        app.inbox = queue.Queue()
        scheduled, handled = [], []
        app.root = SimpleNamespace(after=lambda delay, fn: scheduled.append((delay, fn)))
        for i in range(100):
            app.inbox.put(lambda: handled.append(True))
        app._drain()
        self.assertGreater(len(handled), 0)
        self.assertLessEqual(len(handled), 32)
        self.assertFalse(app.inbox.empty())
        self.assertEqual(len(scheduled), 1)

    def test_leader_reader_is_read_only_and_maps_gripper(self):
        bus = FakeBus([2000, 2100, 2200, 2300, 2400, 1400])
        r = F.LeaderReader("COM9", bus_factory=lambda p: bus).open()
        j, g = r.read()
        self.assertEqual(j, [2000, 2100, 2200, 2300, 2400])
        self.assertAlmostEqual(g, 1.0)                       # unteres Ende = zu
        bus.pos[5] = 2900
        self.assertAlmostEqual(r.read()[1], 0.0)
        r.close()
        self.assertTrue(bus.closed)
        self.assertAlmostEqual(F.deviation_deg([2047] * 5, [2047, 2047, 2047, 2047, 2047 + 114]), 10.0, delta=0.1)

    def test_link_messages_and_skill_replies(self):
        events = []
        link = F.Link("u", "t", on_event=lambda k, d: events.append(k))
        link._message({"t": "welcome", "role": "operator"})
        link._message({"t": "state", "joints": [1] * 6, "active": False})
        link._message({"t": "pong", "ts": time.monotonic() - 0.05})
        self.assertEqual(events[:2], ["welcome", "state"])
        self.assertGreater(link.rtt_ms, 40)
        sent = []
        link.send = lambda m, reliable=False: sent.append(m)
        import threading
        def answer():
            time.sleep(0.05)
            link._message({"t": "skill_result", "id": sent[0]["id"], "ok": True, "result": [1, 2]})
        threading.Thread(target=answer).start()
        self.assertEqual(link.call("modelle.liste", timeout=2), [1, 2])
        threading.Thread(target=lambda: (time.sleep(0.05), link._message(
            {"t": "skill_result", "id": sent[1]["id"], "ok": False, "error": "gesperrt"}))).start()
        with self.assertRaises(RuntimeError):
            link.call("modell.ausfuehren", timeout=2)
        link.send_joints([1, 2, 3, 4, 5], 0.123456, True)
        self.assertEqual(sent[-1]["t"], "joints")
        self.assertEqual(sent[-1]["grip"], 0.123)


class KeyboardSimTests(unittest.TestCase):
    def test_blocked_hand_does_not_lock_other_directions(self):
        import fern_sim as S
        t = S.KeyTeleop()
        for _ in range(100):
            t.apply({"q"}, 0.02)
        self.assertTrue(t.blocked)
        before = t.pose
        # Hand weiter gegen die Grenze halten, gleichzeitig zurueckfahren.
        for _ in range(10):
            t.apply({"q", "s"}, 0.02)
        self.assertLess(t.pose[0], before[0] - 0.005)
        self.assertGreaterEqual(t.pose[3], S.K.PHI_RANGE[0])

    def test_releasing_keys_clears_boundary_warning(self):
        import fern_sim as S
        t = S.KeyTeleop()
        for _ in range(100):
            t.apply({"q"}, 0.02)
        self.assertTrue(t.blocked)
        before = t.values()
        self.assertFalse(t.apply(set(), 0.02))
        self.assertFalse(t.blocked)
        self.assertEqual(t.values(), before)

    def test_can_reverse_and_recouple_at_every_keyboard_boundary(self):
        import fern_sim as S
        for outward, inward in (("w", "s"), ("s", "w"), ("a", "d"), ("d", "a"),
                                ("r", "f"), ("f", "r"), ("q", "e"), ("e", "q")):
            with self.subTest(key=outward):
                t = S.KeyTeleop()
                for _ in range(400):
                    t.apply({outward}, 0.02)
                    j = dict(zip(range(1, 5), t.joints[:4]))
                    self.assertTrue(S.K.joints_ok(j))
                    self.assertTrue(S.K.in_box(S.K.fk(j)))
                self.assertTrue(t.blocked)
                # Wie Steuern aus/an: Ziel an den gesendeten ganzen Ticks starten.
                t.reset(t.joints + [1430])
                before = t.pose
                for _ in range(10):
                    t.apply({inward}, 0.02)
                self.assertFalse(t.blocked)
                self.assertGreater(max(abs(a - b) for a, b in zip(t.pose, before)), 0.001)

    def test_remote_keeps_following_after_keyboard_boundary(self):
        import fern_sim as S
        c = C.RemoteController()
        t = S.KeyTeleop(start(c) + [1430])
        seq = 0
        for keys, frames in (({"q"}, 100), ({"q", "s"}, 25), ({"e"}, 25)):
            before = c.state()["joints"]
            for _ in range(frames):
                seq += 1
                now = seq * 0.02
                t.apply(keys, 0.02)
                j, g = t.values()
                c.handle(1, msg(seq, j, grip=g), now)
                c.tick(now)
                self.assertTrue(c.engaged)
            self.assertNotEqual(c.state()["joints"][:4], before[:4])

    def test_keys_move_tip_and_unreachable_is_blocked(self):
        import fern_sim as S
        t = S.KeyTeleop([2047, 2047, 2047, 2047, 2047, 1430])
        x0 = t.pose[0]
        for _ in range(25):                                   # 0,5 s "w" = vor
            t.apply({"w"}, 0.02)
        self.assertAlmostEqual(t.pose[0] - x0, 0.03, delta=0.002)
        self.assertNotEqual(t.values()[0][:4], [2047] * 4)
        z0 = t.pose[2]
        for _ in range(400):                                  # sehr weit runter: bleibt ueber dem Tisch stehen
            t.apply({"f"}, 0.02)
        self.assertTrue(t.blocked)
        self.assertGreater(min(S.K.heights({s: v for s, v in zip(range(1, 5), t.values()[0])})), -1e-6)
        g = t.grip
        t.apply({"o"}, 0.5)
        self.assertLess(t.grip, g + 1e-9)
        self.assertFalse(t.apply(set(), 0.02))

    def test_start_at_robot_pose_means_no_jump(self):
        import fern_sim as S
        robot = [2200, 1800, 2300, 2100, 1900, 2000]
        t = S.KeyTeleop()
        t.reset(robot)
        j, g = t.values()
        self.assertTrue(max(abs(a - b) for a, b in zip(j, robot[:5])) <= 1)
        self.assertLess(F.deviation_deg(j, robot), 1.0)

    def test_chain_points(self):
        import fern_sim as S
        pts = S.chain([2047] * 5)
        self.assertEqual(len(pts), 5)
        self.assertAlmostEqual(pts[2][2], S.K.SHOULDER_H + S.K.UPPER, places=3)   # Oberarm senkrecht


class AfterReleaseTests(unittest.TestCase):
    def test_after_harness_release_first_unclutched_message_is_needed(self):
        # 18.11.: Tastatur bewegte nichts - nach "Remote uebernehmen" verlangt der Harness erst clutch=False
        c = C.RemoteController()
        j = start(c)
        c.need_release = True
        c.handle(1, msg(1, j), 0.0)
        self.assertFalse(c.engaged)
        c.handle(1, msg(2, j, clutch=False), 0.01)
        c.handle(1, msg(3, j), 0.02)
        self.assertTrue(c.engaged)


if __name__ == "__main__":
    unittest.main()
