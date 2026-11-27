"""Offline-Tests der Fernsteuerung (keine Hardware)."""
import asyncio, json, math, unittest
import remote_kin as K
from remote_core import RemoteController, Config, qaxis, qmul, phone_angles

MIDJ = {1: 2047, 2: 2047, 3: 2047, 4: 2047}
Q0 = [0, 0, 0, 1]


def pose(seq, p=(0, 0, 0), q=Q0, clutch=True, grip=0.0, track="normal"):
    return {"t": "pose", "seq": seq, "ts": 0, "clutch": clutch, "p": list(p), "q": list(q),
            "grip": grip, "track": track}


class KinematicsTests(unittest.TestCase):
    def test_mid_pose(self):
        x, y, z, phi = K.fk(MIDJ)
        self.assertAlmostEqual(x, 0.235, places=3)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.216, places=3)
        self.assertAlmostEqual(phi, math.pi / 2, places=6)

    def test_fk_height_matches_heights_model(self):
        j = {1: 2300, 2: 2351, 3: 1917, 4: 2841}
        self.assertAlmostEqual(K.fk(j)[2], K.heights(j)[2], places=9)

    def test_grasp_log_pose_is_forward_and_low(self):
        x, y, z, phi = K.fk({1: 2047, 2: 2351, 3: 1917, 4: 2841})
        self.assertGreater(x, 0.15)
        self.assertLess(z, 0.10)
        self.assertGreater(phi, 2.9)          # zeigt nach unten
        self.assertIsNotNone(K.solve((x, y, z, phi)))

    def test_ik_roundtrip_over_workspace(self):
        n = 0
        for x in (0.12, 0.18, 0.24, 0.30):
            for y in (-0.15, 0.0, 0.15):
                for z in (0.05, 0.12, 0.20, 0.28):
                    for phi in (1.4, 2.2, 3.0):
                        j = K.solve((x, y, z, phi))
                        if j is None:
                            continue
                        n += 1
                        for a, b in zip(K.fk(j), (x, y, z, phi)):
                            self.assertAlmostEqual(a, b, places=6)
        self.assertGreater(n, 60)             # grosser Teil des Arbeitsraums erreichbar

    def test_below_table_is_never_solved(self):
        self.assertIsNone(K.solve((0.2, 0.0, 0.0, math.pi)))
        self.assertIsNone(K.solve((0.2, 0.0, 0.2, 0.5)))       # Hand nach oben gekippt

    def test_safe_target_clamps_table_and_reach(self):
        start = K.fk(MIDJ)
        p, lim = K.safe_target(start, (0.2, 0.0, -0.2, math.pi))
        self.assertTrue(lim)
        self.assertGreaterEqual(p[2], K.BOX["z"][0])
        self.assertIsNotNone(K.solve(p))
        p, lim = K.safe_target(start, (2.0, 0.0, 0.2, 1.6))
        self.assertTrue(lim)
        self.assertIsNotNone(K.solve(p))

    def test_measured_directions(self):
        # 14.11.: Basis nach links = kleinere Ticks, Handgelenk gegen Uhrzeigersinn = kleinere Ticks
        j = K.solve((0.2, 0.1, 0.15, 2.0))
        self.assertLess(j[1], 2047)
        self.assertEqual(K.ROLL_SIGN, -1)
        self.assertGreater(K.GRIP_OPEN, K.GRIP_CLOSED)

    def test_safe_joints_keep_links_above_table(self):
        for x in (0.12, 0.2, 0.3):
            for z in (0.03, 0.06):
                j = K.solve((x, 0.0, z, math.pi))
                if j:
                    self.assertTrue(all(h >= K.MIN_LINK_Z - 1e-9 for h in K.heights(j)[:2]))


class PhoneAngleTests(unittest.TestCase):
    def test_identity(self):
        h, pitch, roll = phone_angles(Q0)
        self.assertAlmostEqual(h[2], -1.0)
        self.assertAlmostEqual(pitch, 0.0)
        self.assertAlmostEqual(roll, 0.0)

    def test_nose_down_is_negative_pitch(self):
        _, pitch, _ = phone_angles(qaxis((1, 0, 0), math.radians(-20)))
        self.assertAlmostEqual(pitch, math.radians(-20), places=6)

    def test_roll(self):
        _, _, roll = phone_angles(qaxis((0, 0, 1), math.radians(30)))
        self.assertAlmostEqual(roll, math.radians(30), places=6)

    def test_vertical_phone_has_no_heading_issue(self):
        h, _, roll = phone_angles(qaxis((1, 0, 0), math.radians(-90)))
        self.assertIsNone(roll)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.c = RemoteController(Config(), now=0.0)
        self.c.handle(1, {"t": "hello", "v": 1}, 0.0)
        self.t = 0.0
        self.seq = 0

    def run_for(self, seconds, **kw):
        end = self.t + seconds
        while self.t < end:
            self.t += 1 / 60
            self.seq += 1
            self.c.handle(1, pose(self.seq, **kw), self.t)
            self.c.tick(self.t)
        return self.c.target

    def test_no_motion_without_clutch(self):
        start = self.c.target
        self.run_for(0.5, p=(0.0, 0.1, -0.1), clutch=False)
        self.assertEqual(self.c.target, start)

    def test_relative_mapping_forward_up_left(self):
        x0, y0, z0, _ = self.c.target
        self.run_for(0.1, p=(0.0, 0.0, 0.0))
        self.run_for(1.0, p=(-0.03, 0.04, -0.05))     # ARKit: links, oben, vorn
        x, y, z, _ = self.c.target
        self.assertAlmostEqual(x - x0, 0.05, places=3)
        self.assertAlmostEqual(y - y0, 0.03, places=3)
        self.assertAlmostEqual(z - z0, 0.04, places=3)
        self.assertTrue(self.c.state()["active"])

    def test_anchor_means_no_jump_at_press(self):
        start = self.c.target
        self.run_for(0.2, p=(0.5, 0.3, -0.4))          # Handy irgendwo im Raum
        self.assertEqual(self.c.target, start)

    def test_heading_at_press_defines_forward(self):
        x0, y0, _, _ = self.c.target
        q = list(qaxis((0, 1, 0), math.radians(90)))   # Handy nach links gedreht
        self.run_for(0.1, p=(0, 0, 0), q=q)
        self.run_for(1.0, p=(-0.05, 0, 0), q=q)        # in Blickrichtung (Welt -x) bewegt
        x, y, _, _ = self.c.target
        self.assertAlmostEqual(x - x0, 0.05, places=3)
        self.assertAlmostEqual(y - y0, 0.0, places=3)

    def test_speed_is_limited(self):
        x0 = self.c.target[0]
        self.run_for(0.1, p=(0, 0, 0))
        self.seq += 1
        self.c.handle(1, pose(self.seq, p=(0, 0, -0.08)), self.t)
        self.t += 0.02
        self.c.tick(self.t)
        self.assertLessEqual(self.c.target[0] - x0, 0.25 * 0.02 + 1e-9)

    def test_tilt_down_points_gripper_down(self):
        phi0 = self.c.target[3]
        self.run_for(0.1)
        self.run_for(1.0, q=list(qaxis((1, 0, 0), math.radians(-30))))
        self.assertAlmostEqual(self.c.target[3] - phi0, math.radians(30), places=3)

    def test_roll_moves_wrist_rotation(self):
        r0 = self.c.joints[5]
        self.run_for(0.1)
        self.run_for(1.0, q=list(qaxis((0, 0, 1), math.radians(45))))
        self.assertAlmostEqual(self.c.joints[5] - r0, K.ROLL_SIGN * 512, delta=2)

    def test_table_limit_and_haptic(self):
        self.run_for(0.1)
        self.run_for(2.0, p=(0, -0.6, 0))              # weit nach unten
        self.assertGreaterEqual(self.c.target[2], K.BOX["z"][0] - 1e-9)
        self.assertIsNotNone(K.solve(self.c.target))
        kinds = [m for _, m in self.c.pop_events() if m["t"] == "haptic"]
        self.assertTrue(kinds)

    def test_dropout_pauses_and_resumes(self):
        self.run_for(0.1)
        self.run_for(0.3, p=(0, 0, -0.05))
        for _ in range(30):                            # 3 s Funkloch: Arm steht still
            self.t += 0.1
            self.c.tick(self.t)
        held = self.c.target
        st = self.c.state()
        self.assertTrue(st["active"])
        self.assertEqual(st["reason"], "funkloch")
        self.assertEqual(st["funkloch"], 1)
        self.run_for(0.5, p=(0, 0, -0.10))             # Signal wieder da: folgt ohne neues Druecken
        self.assertIsNone(self.c.state()["reason"])
        self.assertGreater(self.c.target[0] - held[0], 0.02)

    def test_dropout_while_idle_still_needs_release(self):
        self.run_for(0.1, clutch=False)
        self.t += 0.3
        self.assertEqual(self.c.tick(self.t)["reason"], "watchdog")
        self.assertFalse(self.c.engaged)

    def test_stop_latches(self):
        self.run_for(0.1)
        self.c.handle(1, {"t": "stop"}, self.t)
        held = self.c.target
        self.run_for(0.5, p=(0, 0, -0.1))
        self.assertEqual(self.c.target, held)
        self.assertEqual(self.c.state()["reason"], "stopped")

    def test_limited_tracking_holds(self):
        start = self.c.target
        self.run_for(0.1)
        self.run_for(0.5, p=(0, 0, -0.1), track="limited")
        self.assertEqual(self.c.target, start)

    def test_spectator_cannot_steer_and_takes_over_on_disconnect(self):
        r = self.c.handle(2, {"t": "hello", "v": 1}, 0.0)
        self.assertEqual(r[0]["role"], "spectator")
        start = self.c.target
        for i in range(1, 30):
            self.c.handle(2, pose(i, p=(0, 0, -0.01 * i)), i / 60)
            self.c.tick(i / 60)
        self.assertEqual(self.c.target, start)
        self.c.disconnect(1)
        ev = self.c.pop_events()
        self.assertEqual(ev[0][0], 2)
        self.assertEqual(ev[0][1]["role"], "operator")

    def test_stale_and_bad_messages(self):
        self.run_for(0.1)
        t = self.c.target
        self.c.handle(1, pose(1, p=(0, 0, -0.3)), self.t)           # alte seq
        self.assertEqual(self.c.handle(1, pose(self.seq + 1, p=(float("nan"), 0, 0)), self.t)[0]["t"], "error")
        self.assertEqual(self.c.handle(1, {"t": "pose", "seq": "x"}, self.t)[0]["t"], "error")
        self.assertEqual(self.c.handle(1, None, self.t)[0]["t"], "error")
        self.assertEqual(self.c.handle(1, {"t": "hello", "v": 2}, self.t)[0]["t"], "error")
        self.c.tick(self.t + 0.01)
        self.assertEqual(self.c.target, t)

    def test_gripper_follows_immediately(self):
        self.run_for(0.05, grip=1.0, clutch=False)
        self.assertEqual(self.c.joints[6], round(K.GRIP_CLOSED))
        self.run_for(0.05, grip=0.0, clutch=False)
        self.assertEqual(self.c.joints[6], round(K.GRIP_OPEN))

    def test_joints_always_safe_under_random_input(self):
        import random
        rnd = random.Random(1)
        for _ in range(1500):
            self.t += 1 / 60
            self.seq += 1
            q = qmul(qaxis((0, 1, 0), rnd.uniform(-3, 3)), qaxis((1, 0, 0), rnd.uniform(-1.4, 1.4)))
            self.c.handle(1, pose(self.seq, p=[rnd.uniform(-1, 1) for _ in range(3)], q=list(q),
                                  clutch=rnd.random() > 0.1, grip=rnd.random()), self.t)
            self.c.tick(self.t)
            j = self.c.joints
            self.assertTrue(K.joints_ok({s: j[s] for s in (1, 2, 3, 4)}) or
                            K.solve(self.c.target) is not None)
            self.assertTrue(K.in_box(self.c.target))


class ServerTests(unittest.TestCase):
    def test_websocket_roundtrip(self):
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect
        from remote_server import Server

        async def go():
            srv = Server(log=lambda *_: None)
            async with serve(srv.handler, "127.0.0.1", 0) as s:
                port = s.sockets[0].getsockname()[1]
                loop = asyncio.create_task(srv.loop())
                async with connect(f"ws://127.0.0.1:{port}/teleop") as ws:
                    await ws.send(json.dumps({"t": "hello", "v": 1}))
                    w = json.loads(await ws.recv())
                    await ws.send(json.dumps({"t": "ping", "id": 5, "ts": 1.0}))
                    await ws.send(json.dumps(pose(1, clutch=False)))
                    got = {}
                    while not {"pong", "state"} <= got.keys():
                        m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                        got[m["t"]] = m
                loop.cancel()
                return w, got

        w, got = asyncio.run(go())
        self.assertEqual(w["role"], "operator")
        self.assertTrue(w["dry_run"])
        self.assertEqual(got["pong"]["id"], 5)
        self.assertEqual(len(got["state"]["joints"]), 6)

    def test_background_server_counts_download_and_upload(self):
        import socket, time
        from websockets.sync.client import connect
        import remote_server
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        srv, stop, url = remote_server.run_in_thread(port, log=lambda *_: None)
        try:
            self.assertTrue(url.endswith(f":{port}/teleop"))
            srv.snapshot()
            with connect(f"ws://127.0.0.1:{port}/teleop") as ws:
                ws.send(json.dumps({"t": "hello", "v": 1}))
                ws.recv()
                for i in range(20):
                    ws.send(json.dumps(pose(i + 1, clutch=True)))
                    time.sleep(0.01)
                time.sleep(0.2)
                snap = srv.snapshot()
            self.assertEqual(snap["clients"], 1)
            self.assertGreater(snap["pose_hz"], 10)
            self.assertGreater(snap["rx_kbs"], 0)
            self.assertGreater(snap["tx_kbs"], 0)
            self.assertTrue(snap["last_pose"]["clutch"])
            self.assertTrue(snap["state"]["dry_run"])
        finally:
            stop()


class SilentOperatorTests(unittest.TestCase):
    def test_dead_operator_is_replaced(self):
        from remote_server import Server
        srv = Server(log=lambda *_: None)
        async def nop(raw, msg):
            pass
        async def run():
            srv.add_client("lk:alt", nop, "Internet alt")
            await srv.receive("lk:alt", json.dumps({"t": "hello", "v": 1}))
            await srv.receive("lk:alt", json.dumps({"t": "claim", "min": 5}))
            srv.add_client("lk:mac", nop, "Internet mac")
            await srv.receive("lk:mac", json.dumps({"t": "hello", "v": 1}))
            self.assertEqual(srv.ctl.operator, "lk:alt")
            t = srv.seen["lk:mac"]
            self.assertFalse(srv.drop_silent_operator(t + 0.5))     # beide frisch: nichts tun
            srv.seen["lk:alt"] = t - 5                               # alt ist seit 5 s stumm
            self.assertTrue(srv.drop_silent_operator(t + 0.5))
            self.assertIsNone(srv.ctl.operator)                      # Kontrolle wieder frei
        asyncio.run(run())

    def test_alone_silent_operator_stays(self):
        from remote_server import Server
        srv = Server(log=lambda *_: None)
        async def nop(raw, msg):
            pass
        async def run():
            srv.add_client("lk:a", nop, "Internet a")
            await srv.receive("lk:a", json.dumps({"t": "hello", "v": 1}))
            self.assertFalse(srv.drop_silent_operator(srv.seen["lk:a"] + 10))
        asyncio.run(run())


class WindowHelperTests(unittest.TestCase):
    def test_worker_lines_are_sorted_by_arm(self):
        import ros as lab
        self.assertEqual(lab.parse_line("[follower2] ARMENDE 0\n"), ("follower2", "ARMENDE 0\n"))
        self.assertEqual(lab.parse_line("LEADER: 600 Hz\n"), (None, "LEADER: 600 Hz\n"))
        self.assertEqual(lab.arm_status("ABGELEGT. Motoren freigegeben."), "Abgelegt · Motoren frei")
        self.assertIsNone(lab.arm_status("TRACE IDs 1-6"))


if __name__ == "__main__":
    unittest.main()
