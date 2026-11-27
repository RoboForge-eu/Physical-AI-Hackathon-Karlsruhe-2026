"""Offline-Tests des KI-Pakets (ohne LeRobot, ohne Arme, ohne Grafikkarte)."""
import io, json, os, sys, tempfile, threading, time, unittest
from unittest import mock
import numpy as np
import cameras
from ki import episodes as E, methods as M, skills as S, jobs as J


def img(v=100):
    return np.full((720, 1280, 3), v, np.uint8)


class EpisodeTests(unittest.TestCase):
    def test_keep_and_discard(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = E.open_dataset("Würfel in Schale", "Leg den Würfel in die Schale", "follower", ["arm", "turm"], root=tmp)
            self.assertEqual(ds.name, "wuerfel_in_schale")
            w = E.EpisodeWriter(ds, ds.meta["task"], cameras.cv2)
            for i in range(10):
                self.assertTrue(w.add(i / 30, [2047] * 6, [2050] * 6, {"arm": img(), "turm": img(50)}))
            self.assertFalse(w.add(1, [1] * 6, [1] * 6, {"arm": img()}))         # Kamera fehlt -> verworfen
            path = w.finish(keep=True)
            self.assertEqual(ds.episodes(), ["ep_0000"])
            with np.load(os.path.join(path, "daten.npz")) as d:
                self.assertEqual(d["state"].shape, (10, 6))
                self.assertEqual(d["action"][0, 0], 2050)
            cap = cameras.cv2.VideoCapture(os.path.join(path, "arm.mp4"))
            self.assertEqual(int(cap.get(cameras.cv2.CAP_PROP_FRAME_COUNT)), 10)
            cap.release()
            w2 = E.EpisodeWriter(ds, "x", cameras.cv2)
            w2.add(0, [1] * 6, [1] * 6, {"arm": img(), "turm": img()})
            w2.add(1, [1] * 6, [1] * 6, {"arm": img(), "turm": img()})
            self.assertIsNone(w2.finish(keep=False))
            self.assertEqual(ds.episodes(), ["ep_0000"])
            self.assertEqual(ds.next_episode_dir()[-7:], "ep_0001")
            self.assertEqual(ds.frames(), 10)

    def test_dataset_is_bound_to_arm_and_cameras(self):
        with tempfile.TemporaryDirectory() as tmp:
            E.open_dataset("a", "t", "follower", ["arm", "turm"], root=tmp)
            with self.assertRaises(ValueError):
                E.open_dataset("a", "t", "follower2", ["arm", "turm"], root=tmp)
            self.assertEqual([d.name for d in E.datasets(tmp)], ["a"])


class MethodTests(unittest.TestCase):
    def test_builtin_methods_and_command(self):
        keys = [m.key for m in M.all_methods()]
        self.assertIn("act", keys)
        self.assertIn("smolvla", keys)
        cmd = M.get("act").train_command("py", "D", "r/x", "O", steps=10)
        self.assertIn("--policy.type=act", cmd)
        self.assertIn("--steps=10", cmd)
        self.assertIn("--dataset.root=D", cmd)
        self.assertTrue(M.get("smolvla").uses_language)
        with self.assertRaises(KeyError):
            M.get("gibtsnicht")

    def test_own_method_plugs_in(self):
        M.register(M.Method("test_eigen", "Eigen", "x", False, False, 5, 1, train=["{python}", "-c", "pass"]))
        self.assertEqual(M.get("test_eigen").train_command("py", "d", "r", "o"), ["py", "-c", "pass"])


class SkillTests(unittest.TestCase):
    def test_call_checks_params_remote_and_motion(self):
        r = S.Registry()
        moved = []
        @r.skill("arm.ablegen", "Legt ab", {"arm": {"type": "string"}}, ["arm"], moves=True)
        def ablegen(arm):
            moved.append(arm)
            return {"ok": True}
        @r.skill("intern", "nur lokal", remote_ok=False)
        def intern():
            return {}
        self.assertEqual(r.call("arm.ablegen", {"arm": "follower"}), {"ok": True})
        with self.assertRaises(S.SkillError):
            r.call("arm.ablegen", {})
        with self.assertRaises(S.SkillError):
            r.call("arm.ablegen", {"arm": "x", "boese": 1})
        with self.assertRaises(S.SkillError):
            r.call("intern", source="remote")
        r.move_allowed = lambda skill, args, source: source == "lokal"
        with self.assertRaises(S.SkillError):
            r.call("arm.ablegen", {"arm": "follower"}, source="agent")
        tools = r.tool_schemas(source="remote")
        self.assertEqual([t["name"] for t in tools], ["arm.ablegen"])
        self.assertIn("Bewegt den Arm", tools[0]["description"])


class FakeProc:
    def __init__(self, lines, rc=0):
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))
        self.rc = rc
    def wait(self):
        return self.rc
    def poll(self):
        return self.rc
    def terminate(self):
        pass


class JobTests(unittest.TestCase):
    def test_parse_progress(self):
        self.assertEqual(J.parse_progress("INFO step:2K smpl:16K ep:10 epch:0.5 loss:0.234 grdn:12"), (2000, 0.234))
        self.assertEqual(J.parse_progress("step: 150 loss: 1.5e-1"), (150, 0.15))
        self.assertIsNone(J.parse_progress("Lade Datensatz"))

    def test_queue_runs_convert_then_train_and_writes_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = E.open_dataset("t", "Aufgabe", "follower", ["arm"], root=tmp)
            w = E.EpisodeWriter(ds, "Aufgabe", cameras.cv2)
            for i in range(3):
                w.add(i, [1] * 6, [1] * 6, {"arm": img()})
            w.finish(True)
            calls = []
            def popen(cmd, **kw):
                calls.append(cmd)
                return FakeProc(["ok"] if len(calls) == 1 else ["step:500 loss:0.5", "step:1K loss:0.2"])
            py = os.path.join(tmp, "python.exe")
            open(py, "w").close()
            old = J.MODELS
            J.MODELS = os.path.join(tmp, "modelle")
            try:
                q = J.Queue(python=py, popen=popen)
                job = q.add(ds, "act", steps=1000)
                for _ in range(100):
                    if job.state in ("fertig", "fehler"):
                        break
                    time.sleep(0.05)
                self.assertEqual(job.state, "fertig", job.message)
                self.assertIn("ki.convert", calls[0])
                self.assertIn("--policy.type=act", calls[1])
                self.assertEqual(job.loss, 0.2)
                m = J.models(J.MODELS)
                self.assertEqual(m[0]["method"], "act")
                self.assertEqual(m[0]["task"], "Aufgabe")
            finally:
                J.MODELS = old

    def test_failed_step_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = E.open_dataset("t", "A", "follower", ["arm"], root=tmp)
            w = E.EpisodeWriter(ds, "A", cameras.cv2)
            w.add(0, [1] * 6, [1] * 6, {"arm": img()}); w.add(1, [1] * 6, [1] * 6, {"arm": img()})
            w.finish(True)
            py = os.path.join(tmp, "python.exe"); open(py, "w").close()
            old = J.MODELS
            J.MODELS = os.path.join(tmp, "m")
            try:
                q = J.Queue(python=py, popen=lambda cmd, **kw: FakeProc(["Traceback"], rc=1))
                job = q.add(ds, "smolvla")
                for _ in range(100):
                    if job.state == "fehler":
                        break
                    time.sleep(0.05)
                self.assertEqual(job.state, "fehler")
                self.assertIn("umwandeln", job.message)
            finally:
                J.MODELS = old


class RecorderTests(unittest.TestCase):
    def test_parse_obs(self):
        from ki.recorder import parse_obs
        self.assertEqual(parse_obs("OBS 1 2 3 4 5 6 | 7 8 9 10 11 12"), ([1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]))
        self.assertIsNone(parse_obs("OBS 1 2 | 3"))
        self.assertIsNone(parse_obs("TRACE ..."))

    def test_ticks_need_fresh_frames_and_joints(self):
        from ki.recorder import Recorder
        clock = [0.0]
        frames = {"arm": (img(), 0.0)}
        with tempfile.TemporaryDirectory() as tmp:
            ds = E.open_dataset("r", "A", "follower", ["arm"], root=tmp)
            r = Recorder(cameras.cv2, lambda: frames, clock=lambda: clock[0])
            r.writer, r.state = E.EpisodeWriter(ds, "A", cameras.cv2), "nimmt_auf"
            self.assertFalse(r.tick())                      # noch keine Gelenkdaten
            r.obs([1] * 6, [2] * 6)
            self.assertTrue(r.tick())
            clock[0] = 1.0                                  # Bild und Gelenke veraltet
            self.assertFalse(r.tick())
            frames["arm"] = (img(), 1.0)
            r.obs([1] * 6, [2] * 6)
            self.assertTrue(r.tick())
            r.state = "nimmt_auf"
            r.stop()
            self.assertEqual(r.state, "wartet_entscheidung")
            self.assertTrue(r.keep())
            self.assertEqual(ds.episodes(), ["ep_0000"])

    def test_real_thread_records_about_30_fps(self):
        from ki.recorder import Recorder
        with tempfile.TemporaryDirectory() as tmp:
            ds = E.open_dataset("r", "A", "follower", ["arm"], root=tmp)
            small = np.full((360, 640, 3), 80, np.uint8)
            r = Recorder(cameras.cv2, lambda: {"arm": (small, time.monotonic())})
            stop = [False]
            import threading
            def feed():
                while not stop[0]:
                    r.obs([1] * 6, [2] * 6)
                    time.sleep(0.02)
            threading.Thread(target=feed, daemon=True).start()
            r.start(ds, "A")
            time.sleep(1.0)
            r.stop()
            stop[0] = True
            self.assertTrue(24 <= r.frames <= 33, r.frames)
            r.discard()
            self.assertEqual(ds.episodes(), [])


class DriverClientTests(unittest.TestCase):
    def test_limit_step(self):
        from ki.client import limit_step
        self.assertEqual(limit_step([2000, 2000], [2100, 1950], 30), [2030, 1970])
        self.assertEqual(limit_step(None, [5, 6], 1), [5, 6])

    def test_step_sends_images_and_limited_target(self):
        import json as _json
        from ki.client import DriverClient
        sent = []
        class Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO((_json.dumps({"action": [2400, 2047, 2047, 2047, 2047, 2047], "ms": 2}) + "\n").encode())
        c = DriverClient("m", "Aufgabe", lambda: {"arm": np.zeros((360, 640, 3), np.uint8)},
                         lambda: [2047] * 6, sent.append, deg_per_s=45)
        c.proc, c.cameras = Proc(), ["arm"]
        self.assertTrue(c.step())
        self.assertEqual(sent[0][0], 2047 + c.max_step)          # begrenzt, nicht 2400
        head, rest = c.proc.stdin.getvalue().split(b"\n", 1)
        self.assertEqual(_json.loads(head)["images"], {"arm": [360, 640]})
        self.assertEqual(len(rest), 360 * 640 * 3)

    def test_missing_state_or_camera_skips(self):
        from ki.client import DriverClient
        c = DriverClient("m", "", lambda: {"arm": None}, lambda: [1] * 6, lambda t: None)
        c.cameras = ["arm"]
        self.assertFalse(c.step())
        c = DriverClient("m", "", lambda: {"arm": img()}, lambda: None, lambda t: None)
        c.cameras = ["arm"]
        self.assertFalse(c.step())


class ChunkTests(unittest.TestCase):
    def test_next_chunk_is_ready_before_queue_runs_empty(self):
        from ki.chunks import ChunkScheduler
        started = []
        def compute(obs):
            started.append(obs)
            time.sleep(0.1)                       # "Rechnung" dauert 3 Takte
            return [[obs * 100 + i] for i in range(20)]
        s = ChunkScheduler(compute)
        out, waits_after_start = [], None
        for tick in range(60):
            out.append(s.next(tick)[0])
            if tick == 0:
                waits_after_start = s.stats["waits"]
            time.sleep(1 / 30)
        self.assertEqual(s.stats["waits"], waits_after_start)     # nach dem Start nie mehr gewartet
        self.assertGreaterEqual(s.stats["chunks"], 3)
        self.assertGreater(s.stats["skipped"], 0)                 # vergangene Schritte uebersprungen

    def test_skip_aligns_new_chunk_with_time(self):
        from ki.chunks import ChunkScheduler
        import threading
        gate = threading.Event()
        calls = []
        def compute(obs):
            calls.append(obs)
            if len(calls) > 1:
                gate.wait(2)
            return [[obs, i] for i in range(10)]
        s = ChunkScheduler(compute, min_left=0, blend=0)
        self.assertEqual(s.next(0), [0, 0])        # erstes Stueck: warten muss sein; 9 uebrig
        s.compute_s = 0.1                          # Schwelle: ceil(0.1*30*1.5) = 5 uebrige Schritte
        for n in range(1, 5):
            s.next(n)                              # 9 -> 5 uebrig, noch keine neue Rechnung
        self.assertEqual(len(calls), 1)
        s.next(5)                                  # 5 uebrig -> Rechnung mit Beobachtung 5 startet (Takt 5)
        self.assertEqual(calls[-1], 5)
        s.next(6); s.next(7)                       # Rechnung laeuft noch -> altes Stueck weiter
        gate.set()
        s.pending[0].join()
        self.assertEqual(s.next(8), [5, 3])        # Takt 8, gestartet bei Takt 5 -> 3 Schritte uebersprungen

    def test_blend_avoids_jump_at_chunk_border(self):
        from ki.chunks import ChunkScheduler
        n = [0]
        def compute(obs):
            n[0] += 1
            return [[0.0]] * 20 if n[0] == 1 else [[100.0]] * 20    # zweites Stueck liegt 100 daneben
        s = ChunkScheduler(compute, blend=10)
        out = []
        for t in range(40):
            out.append(s.next(t)[0])
            if s.pending:
                s.pending[0].join()
        jumps = [abs(b - a) for a, b in zip(out, out[1:])]
        self.assertLess(max(jumps), 100 / 10 + 1)                    # statt 100 auf einmal: ~9 je Schritt
        self.assertEqual(out[-1], 100.0)

    def test_errors_reach_the_caller(self):
        from ki.chunks import ChunkScheduler
        s = ChunkScheduler(lambda obs: (_ for _ in ()).throw(RuntimeError("kaputt")))
        with self.assertRaises(RuntimeError):
            s.next(0)


class RosSkillTests(unittest.TestCase):
    def lab(self):
        import types
        calls = []
        class Var:
            def __init__(self, v): self.v = v
            def get(self): return self.v
        panel = types.SimpleNamespace(label="Setup 1", running=False, mode="lokal", source=Var("ki"),
                                      status=Var("Bereit"), ki_model=None, ki_task="")
        lab = types.SimpleNamespace(panels={"follower": panel}, ki_queue=None, calls=calls,
                                    on_ui=lambda fn: (calls.append(fn), fn()), update_buttons=lambda: None,
                                    stop=lambda arm: calls.append(("stop", arm)), take_ki=lambda arm: calls.append(("ki", arm)))
        return lab

    def test_remote_can_read_and_stop_but_not_move(self):
        from ki import ros_skills
        lab = self.lab()
        reg = ros_skills.build(lab)
        names = [t["name"] for t in reg.tool_schemas()]
        for n in ("training.start", "modelle.liste", "ki.starten", "arm.ablegen", "kamera.bild"):
            self.assertIn(n, names)
        self.assertEqual(reg.call("arm.status", {"arm": "follower"}, source="remote")["label"], "Setup 1")
        reg.call("arm.ablegen", {"arm": "follower"}, source="remote")
        self.assertIn(("stop", "follower"), lab.calls)
        with self.assertRaises(S.SkillError):
            reg.call("ki.starten", {"arm": "follower"}, source="remote")
        with self.assertRaises(S.SkillError):
            reg.call("ki.starten", {"arm": "follower"}, source="agent")
        reg.call("ki.starten", {"arm": "follower"}, source="lokal")
        self.assertIn(("ki", "follower"), lab.calls)
        self.assertTrue(any(m["key"] == "smolvla" for m in reg.call("methoden.liste", source="remote")))


class RemoteSkillTests(unittest.TestCase):
    def test_server_answers_skill_messages(self):
        import asyncio, remote_server
        srv = remote_server.Server(log=lambda *_: None)
        sent = []
        async def sender(raw, msg):
            sent.append(msg)
        srv.add_client(1, sender, "test")
        reg = S.Registry()
        reg.skill("echo", "x", {"a": {"type": "integer"}})(lambda a=0: {"a": a})
        srv.skills = reg
        async def go():
            await srv.receive(1, json.dumps({"t": "skill", "id": 5, "name": "echo", "args": {"a": 3}}))
            await srv.receive(1, json.dumps({"t": "skill", "id": 6, "name": "nope"}))
            await srv.receive(1, json.dumps({"t": "skill", "id": 7, "name": "skills.liste"}))
        asyncio.run(go())
        self.assertEqual(sent[0], {"t": "skill_result", "id": 5, "name": "echo", "ok": True, "result": {"a": 3}})
        self.assertFalse(sent[1]["ok"])
        self.assertEqual(sent[2]["result"][0]["name"], "echo")




class TrashTests(unittest.TestCase):
    def test_trash_moves_episode_out_of_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = E.open_dataset("t", "a", "follower", ["arm"], root=tmp)
            for _ in range(2):
                w = E.EpisodeWriter(ds, "a", cameras.cv2)
                for i in range(3):
                    w.add(i, [1] * 6, [1] * 6, {"arm": img()})
                w.finish(True)
            target = ds.trash_episode("ep_0001", trash=os.path.join(tmp, "papierkorb"))
            self.assertEqual(ds.episodes(), ["ep_0000"])
            self.assertTrue(os.path.exists(os.path.join(target, "daten.npz")))
            self.assertEqual(ds.next_episode_dir()[-7:], "ep_0001")
            with self.assertRaises(ValueError):
                ds.trash_episode("ep_0009")


class HistoryTests(unittest.TestCase):
    def test_latest_first_without_duplicates(self):
        from ki import history
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "h.json")
            history.remember("a", "Aufgabe A", p)
            history.remember("b", "", p)
            history.remember("a", "Aufgabe A", p)
            self.assertEqual(history.load(p), {"datensatz": ["a", "b"], "aufgabe": ["Aufgabe A"]})
            self.assertEqual(history.options("datensatz", ["c", "a", None], p), ["a", "b", "c"])


class PauseTests(unittest.TestCase):
    def test_paused_client_sends_nothing_until_released(self):
        import json as _json, threading
        from ki.client import DriverClient
        sent = []
        class Proc:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.lines = [(_json.dumps({"ready": True, "cameras": ["arm"]}) + "\n").encode()] + \
                             [(_json.dumps({"action": [2100] * 6}) + "\n").encode()] * 200
                self.stdout = self
            def readline(self):
                return self.lines.pop(0) if self.lines else b""
        c = DriverClient("m", "", lambda: {"arm": np.zeros((360, 640, 3), np.uint8)}, lambda: [2047] * 6,
                         sent.append, popen=lambda *a, **k: Proc())
        c.paused.set()
        c.start()
        time.sleep(0.3)
        self.assertEqual(sent, [])                           # wartet auf die Startpose
        c.last_sent = [2050] * 6
        c.paused.clear()
        time.sleep(0.3)
        c.halt.set()
        self.assertTrue(sent)
        self.assertLessEqual(abs(sent[0][0] - 2050), c.max_step)   # setzt an der Startpose an


class PolicyFeedStartTests(unittest.TestCase):
    def test_holds_own_position_until_driver_then_limited_grace(self):
        import lab_worker as W
        f = W.PolicyFeed()
        f.START_GRACE_S = 0.4
        f.seed({s: 2000 for s in range(1, 7)})
        time.sleep(0.6)
        f.seed({s: 2010 for s in range(1, 7)})                  # Start des Folgens: frisch nachgesaet
        self.assertEqual(f.positions()[1], 2010)
        time.sleep(0.2)
        self.assertEqual(f.positions()[1], 2010)                 # innerhalb der Frist: kein Abbruch
        f.update([2100] * 6)
        f.seed({s: 1 for s in range(1, 7)})
        self.assertEqual(f.positions()[1], 2100)                 # Fahrer hat Vorrang
        g = W.PolicyFeed()
        g.START_GRACE_S = 0.2
        g.seed({s: 2000 for s in range(1, 7)})
        time.sleep(1.4)
        with self.assertRaises(Exception):
            g.positions()                                        # Fahrer kommt nie: Abbruch -> Ablegen


class FinishTests(unittest.TestCase):
    def test_done_after_moving_then_holding_still(self):
        from ki.client import FinishDetector
        f = FinishDetector(hold_s=1.0, tol_deg=2.0, moved_deg=15.0, max_s=60)
        t = 0.0
        self.assertIsNone(f.feed([2047] * 6, t))
        for i in range(60):                                      # ruhig am Start: noch nicht "fertig"
            t += 1 / 30
            self.assertIsNone(f.feed([2047 + (i % 2) * 5] * 6, t))
        for i in range(30):                                      # echte Bewegung
            t += 1 / 30
            f.feed([2047 + 10 * i] * 6, t)
        result = None
        for i in range(40):                                      # stillhalten mit leichtem Zittern
            t += 1 / 30
            result = result or f.feed([2337 + (i % 3) * 5] * 6, t)
        self.assertEqual(result, "fertig")

    def test_time_limit(self):
        from ki.client import FinishDetector
        f = FinishDetector(max_s=1.0)
        f.feed([1] * 6, 0.0)
        self.assertEqual(f.feed([1] * 6, 1.5), "zeitgrenze")


class ReverseTests(unittest.TestCase):
    def test_reverse_keeps_squeeze_and_hold_offset(self):
        from ki.reverse import reverse_episode
        n = 60
        state = np.zeros((n, 6), np.float32)
        state[:, 1] = np.linspace(1000, 2000, n)                   # Schulter faehrt hoch
        state[:, 5] = 2000
        action = state.copy()
        action[:, 1] += 30                                         # Halte-Ausgleich (gegen Absacken)
        action[:-3, 1] += (state[3:, 1] - state[:-3, 1])           # Vorlauf in Fahrtrichtung
        action[20:40, 5] = 1700                                    # zudruecken beim Halten
        st, act = reverse_episode(state, action, lead=3)
        self.assertEqual(st[0, 1], 2000)                           # beginnt am Ende
        self.assertLess(act[10, 1], st[10, 1] + 30)                # Vorlauf zeigt jetzt nach unten
        self.assertAlmostEqual(float(act[-1, 1] - st[-1, 1]), 30, delta=1)   # Ausgleich im Stillstand bleibt
        self.assertTrue((act[:, 5] < 2000).sum() >= 15)            # Zudruecken bleibt erhalten


def _make_ds(root, name, n, arm="follower", cams=("arm",)):
    ds = E.open_dataset(name, "a", arm, list(cams), root=root)
    for _ in range(n):
        w = E.EpisodeWriter(ds, "a", cameras.cv2)
        for i in range(3):
            w.add(i, [1] * 6, [1] * 6, {c: img() for c in cams})
        w.finish(True)
    return ds


class ComposeTests(unittest.TestCase):
    def test_picks_episodes_from_several_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_ds(tmp, "tag", 3)
            _make_ds(tmp, "abend", 2)
            ds = E.compose("Gemischt", "Schachtel ablegen",
                           [("tag", "ep_0002"), ("abend", "ep_0000"), ("abend", "ep_0001")], root=tmp)
            self.assertEqual(ds.episodes(), ["ep_0000", "ep_0001", "ep_0002"])
            self.assertEqual(ds.episode_info("ep_0000")["herkunft"], "tag/ep_0002")
            self.assertEqual(ds.meta["task"], "Schachtel ablegen")
            self.assertEqual(len(E.Dataset(os.path.join(tmp, "tag")).episodes()), 3)     # Quelle bleibt
            with self.assertRaises(FileExistsError):
                E.compose("Gemischt", "x", [("tag", "ep_0000")], root=tmp)

    def test_keeps_task_per_episode_for_multitask(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            _make_ds(tmp, "hin", 1)
            _make_ds(tmp, "rueck", 1)
            p = os.path.join(tmp, "rueck", "ep_0000", "info.json")
            info = json.load(open(p, encoding="utf-8"))
            info["task"] = "Schachtel zurueck"
            json.dump(info, open(p, "w", encoding="utf-8"))
            ds = E.compose("Beides", "Schachtel hin und zurueck", [("hin", "ep_0000"), ("rueck", "ep_0000")],
                           root=tmp, eigene_aufgaben=True)
            self.assertEqual(ds.episode_info("ep_0000")["task"], "a")
            self.assertEqual(ds.episode_info("ep_0001")["task"], "Schachtel zurueck")
            self.assertEqual(ds.meta["aufgaben"], ["Schachtel zurueck", "a"])
            alt = E.compose("Eins", "gleich", [("hin", "ep_0000"), ("rueck", "ep_0000")], root=tmp)
            self.assertEqual(alt.episode_info("ep_0001")["task"], "gleich")       # Standard unveraendert

    def test_refuses_other_arm_or_cameras(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_ds(tmp, "a1", 1)
            _make_ds(tmp, "a2", 1, arm="follower2")
            with self.assertRaises(ValueError):
                E.compose("x", "t", [("a1", "ep_0000"), ("a2", "ep_0000")], root=tmp)
            self.assertFalse(os.path.exists(os.path.join(tmp, "x")))


class QueueNightTests(unittest.TestCase):
    def test_runs_jobs_back_to_back_quiet_flag_and_survives_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds1, ds2 = _make_ds(tmp, "eins", 1), _make_ds(tmp, "zwei", 1)
            envs = []
            def popen(cmd, **kw):
                envs.append((cmd, kw["env"]["ROBOFORGE_LEISE"]))
                if len(envs) == 1:
                    raise OSError("kaputt")             # erstes Training scheitert hart
                return FakeProc(["step:1K loss:0.1"])
            py = os.path.join(tmp, "python.exe"); open(py, "w").close()
            old = J.MODELS
            J.MODELS = os.path.join(tmp, "m")
            try:
                q = J.Queue(python=py, popen=popen)
                a = q.add(ds1, "act", 1000)
                b = q.add(ds2, "act", 1000, quiet=True)
                c = q.add(ds2, "act", 1000, augment=True)
                self.assertEqual(len({a.name, b.name, c.name}), 3)     # gleiche Minute, trotzdem eindeutig
                for _ in range(200):
                    if c.state in ("fertig", "fehler"):
                        break
                    time.sleep(0.05)
                self.assertEqual(a.state, "fehler")
                self.assertEqual((b.state, c.state), ("fertig", "fertig"))
                quiet_vals = {e for cmd, e in envs if "ki.train" in cmd}
                self.assertEqual(quiet_vals, {str(J.QUIET_PAUSE), "0"})
                self.assertTrue(b.info()["quiet"])
                trains = [cmd for cmd, e in envs if "ki.train" in cmd]
                self.assertNotIn(J.AUGMENT_ARG, trains[0])
                self.assertIn(J.AUGMENT_ARG, trains[1])
            finally:
                J.MODELS = old


class ZustandRauschenTests(unittest.TestCase):
    """Dritter Trainingsplan 'SmolVLA robust': Gelenkstellung beim Lernen verrauscht."""

    def test_plan_vorhanden(self):
        m = M.get("smolvla_robust")
        self.assertGreater(m.state_noise_deg, 0)
        self.assertEqual(M.get("smolvla").state_noise_deg, 0)
        self.assertEqual(m.runner, M.get("smolvla").runner)        # Fahren wie SmolVLA

    def test_greifer_bleibt_gelenke_streuen(self):
        import numpy as np
        from ki.zustand_rauschen import verrauschen
        z = np.tile(np.array([10, 20, 30, 40, 50, 60], np.float32), (4000, 1))
        d = verrauschen(z, 8.0) - z
        self.assertTrue(np.all(d[:, 5] == 0))
        self.assertTrue(np.all(np.abs(d[:, :5].std(0) - 8.0) < 0.5))
        self.assertIs(verrauschen(z, 0), z)

    def test_stapel_und_einzeln_verrauscht(self):
        import numpy as np
        from ki.zustand_rauschen import mit_rauschen

        class Daten:                                       # wie LeRobotDataset: __getitem__ und __getitems__
            def __getitem__(self, i):
                return {"observation.state": np.zeros(6, np.float32), "action": np.ones(6, np.float32)}

            def __getitems__(self, idxs):
                return [self[i] for i in idxs]

        ds = mit_rauschen(Daten(), 8.0)
        self.assertTrue(np.any(ds[0]["observation.state"][:5] != 0))
        stapel = ds.__getitems__([0, 1, 2])
        self.assertTrue(all(np.any(s["observation.state"][:5] != 0) for s in stapel))
        self.assertTrue(all(np.all(s["action"] == 1) for s in stapel))   # Ziele unveraendert

    def test_training_bekommt_rauschen(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = _make_ds(tmp, "eins", 1)
            envs = []

            def popen(cmd, **kw):
                envs.append((cmd, kw["env"]["ROBOFORGE_ZUSTAND_RAUSCHEN"]))
                return FakeProc(["step:1K loss:0.1"])
            py = os.path.join(tmp, "python.exe"); open(py, "w").close()
            old = J.MODELS
            J.MODELS = os.path.join(tmp, "m")
            try:
                q = J.Queue(python=py, popen=popen)
                a = q.add(ds, "smolvla", 1000)
                b = q.add(ds, "smolvla_robust", 1000)
                for _ in range(200):
                    if b.state in ("fertig", "fehler"):
                        break
                    time.sleep(0.05)
                werte = [e for cmd, e in envs if "ki.train" in cmd]
                self.assertEqual(werte, ["0", str(M.get("smolvla_robust").state_noise_deg)])
            finally:
                J.MODELS = old


class TrainingsDienstTests(unittest.TestCase):
    """Training unabhaengig vom Harness: Auftraege als Dateien, Dienst arbeitet sie ab."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "auftraege")
        self.old = J.MODELS
        J.MODELS = os.path.join(self.tmp.name, "m")
        self.py = os.path.join(self.tmp.name, "python.exe")
        open(self.py, "w").close()
        self.ds = _make_ds(self.tmp.name, "eins", 2)

    def tearDown(self):
        J.MODELS = self.old
        self.tmp.cleanup()

    def wait(self, cond, s=10):
        end = time.time() + s
        while time.time() < end and not cond():
            time.sleep(0.05)
        return cond()

    def harness(self, running=lambda store: True):
        starts = []
        return J.DetachedQueue(self.store, start=lambda store: starts.append(store), running=running), starts

    def test_speichern_trotz_kurz_gesperrter_datei(self):
        h, _ = self.harness()
        job = h.add(self.ds, "act", 100)
        real, calls = os.replace, []
        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "Zugriff verweigert")
            real(a, b)
        with mock.patch.object(J.os, "replace", flaky):
            job.step = 42
            job.save()
        self.assertEqual(J.read_jobs(self.store)[0]["step"], 42)
        with mock.patch.object(J.os, "replace", side_effect=PermissionError(5, "x")):
            job.save(force=False)                              # Fortschritt: auslassen statt abstuerzen

    def test_pause_haelt_prozess_an_und_setzt_fort(self):
        import psutil, subprocess as sp
        h, _ = self.harness()
        job = h.add(self.ds, "act", 100)
        job.state, job.started = "training", time.time()
        job.process = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        done = threading.Event()
        try:
            threading.Thread(target=J._watch, args=(job, done, "training"), daemon=True).start()
            h.pause(job.name, True)
            self.assertTrue(self.wait(lambda: job.state == "pausiert"))
            self.assertEqual(psutil.Process(job.process.pid).status(), psutil.STATUS_STOPPED)
            self.assertTrue(self.wait(lambda: h.snapshot()[0]["state"] == "pausiert"))
            h.pause(job.name, False)
            self.assertTrue(self.wait(lambda: job.state == "training"))
            self.assertNotEqual(psutil.Process(job.process.pid).status(), psutil.STATUS_STOPPED)
            h.cancel(job.name)
            self.assertTrue(self.wait(lambda: job.process.poll() is not None))
        finally:
            done.set()
            if job.process.poll() is None:
                job.process.kill()

    def test_auftrag_ueberlebt_harness_und_wird_fertig(self):
        h, starts = self.harness(running=lambda store: False)
        job = h.add(self.ds, "act", 1000, augment=True, filters=None)
        self.assertEqual(starts, [self.store])                 # Harness startet den Dienst
        self.assertEqual(h.snapshot()[0]["state"], "wartet")
        del h                                                  # "Harness neu gestartet"
        J.Queue(python=self.py, popen=lambda cmd, **kw: FakeProc(["step:500 loss:0.3", "step:1K loss:0.1"]),
                store=self.store)                              # der Dienst
        h2, _ = self.harness()
        self.assertTrue(self.wait(lambda: h2.snapshot()[0]["state"] == "fertig"))
        s = h2.snapshot()[0]
        self.assertEqual((s["name"], s["step"], s["loss"], s["augment"]), (job.name, 1000, 0.1, True))
        self.assertTrue(os.path.exists(os.path.join(J.MODELS, job.name, "modell.json")))

    def _checkpoint(self, name, step, complete=True):
        d = os.path.join(J.MODELS, name, "lauf", "checkpoints", f"{step:06d}")
        os.makedirs(os.path.join(d, "pretrained_model"))
        os.makedirs(os.path.join(d, "training_state"))
        open(os.path.join(d, "pretrained_model", "train_config.json"), "w").close()
        if complete:
            open(os.path.join(d, "training_state", "training_step.json"), "w").close()
            with open(os.path.join(os.path.dirname(d), "last.txt"), "w") as f:
                f.write(f"{step:06d}")

    def test_weitertrainieren_nach_neustart(self):
        h, _ = self.harness()
        job = h.add(self.ds, "act", 4000)
        path = os.path.join(self.store, job.name + ".json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.update(state="training", step=2600)               # PC ging waehrend des Trainings aus
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.makedirs(os.path.join(J.MODELS, job.name, "lerobot_datensatz"))
        self._checkpoint(job.name, 2000)
        self._checkpoint(job.name, 3000, complete=False)       # halb geschrieben: zaehlt nicht
        cmds = []
        def popen(cmd, **kw):
            cmds.append(cmd)
            return FakeProc(["step:3K loss:0.2", "step:4K loss:0.1"])
        q = J.Queue(python=self.py, popen=popen, store=self.store)      # Dienst nach PC-Neustart
        s = h.snapshot()[0]
        self.assertEqual((s["state"], s["weiter_ab"]), ("fehler", 2000))
        self.assertIn("Schritt 2000", s["message"])
        self.assertEqual(h.resume(job.name)["weiter_ab"], 2000)
        self.assertTrue(self.wait(lambda: h.snapshot()[0]["state"] == "fertig"))
        self.assertEqual(len(cmds), 1)                          # kein erneutes Umwandeln
        self.assertIn("--resume=true", cmds[0])
        self.assertTrue(any(c.startswith("--config_path=") and "000002000" not in c and "002000" in c for c in cmds[0]))
        self.assertEqual(h.snapshot()[0]["step"], 4000)
        with self.assertRaises(ValueError):                    # fertig: nichts weiterzutrainieren
            h.resume(job.name)

    def test_weitertrainieren_nach_fehler_im_laufenden_dienst(self):
        h, _ = self.harness()
        job = h.add(self.ds, "act", 2000)
        runs = []
        def popen(cmd, **kw):
            runs.append(cmd)
            if len(runs) == 2:                                 # 1. Training stirbt bei Schritt 1000
                os.makedirs(os.path.join(J.MODELS, job.name, "lerobot_datensatz"), exist_ok=True)
                self._checkpoint(job.name, 1000)
                return FakeProc(["step:1K loss:0.3"], rc=1)
            return FakeProc(["step:2K loss:0.1"])
        J.Queue(python=self.py, popen=popen, store=self.store)
        self.assertTrue(self.wait(lambda: h.snapshot()[0]["state"] == "fehler"))
        h.resume(job.name)                                     # Dienst laeuft weiter und uebernimmt den Auftrag
        self.assertTrue(self.wait(lambda: h.snapshot()[0]["state"] == "fertig"))
        self.assertIn("--resume=true", runs[-1])

    def test_alte_zwischenstaende_werden_aufgeraeumt(self):
        import importlib
        T = importlib.import_module("ki.train")
        base = os.path.join(self.tmp.name, "checkpoints")
        for n in (1000, 2000, 5000, 6000, 7000):
            os.makedirs(os.path.join(base, f"{n:06d}"))
        T._write_last(os.path.join(base, "007000"))
        self.assertEqual(sorted(os.listdir(base)), ["005000", "007000", "last.txt"])

    def test_abbrechen_per_datei(self):
        h, _ = self.harness()
        job = h.add(self.ds, "act", 1000)
        self.assertTrue(h.cancel(job.name))
        J.Queue(python=self.py, popen=lambda cmd, **kw: FakeProc(["step:1K"]), store=self.store)
        self.assertTrue(self.wait(lambda: h.snapshot()[0]["state"] == "abgebrochen"))
        self.assertFalse(os.path.exists(os.path.join(J.MODELS, job.name, "modell.json")))

    def test_unterbrochenes_training_wird_fehler(self):
        h, _ = self.harness()
        job = h.add(self.ds, "act", 1000)
        job.state = "training"
        job.save()                                             # Dienst/PC war mitten im Training weg
        J.Queue(python=self.py, popen=lambda cmd, **kw: FakeProc([]), store=self.store)
        d = J.read_jobs(self.store)[0]
        self.assertEqual(d["state"], "fehler")
        self.assertIn("unterbrochen", d["message"])

    def test_harness_sieht_toten_dienst(self):
        h, _ = self.harness(running=lambda store: False)
        job = h.add(self.ds, "act", 1000)
        job.state = "training"
        job.save()
        self.assertEqual(h.snapshot()[0]["state"], "fehler")

    def test_sperre_erkennt_laufenden_dienst(self):
        from ki import trainer
        os.makedirs(self.store, exist_ok=True)
        self.assertFalse(J.service_running(self.store))
        held = trainer.lock(self.store)
        try:
            self.assertIsNotNone(held)
            self.assertTrue(J.service_running(self.store))
            self.assertIsNone(trainer.lock(self.store))       # zweiter Dienst startet nicht
        finally:
            held.close()
        self.assertFalse(J.service_running(self.store))

    def test_filter_und_kameras_bleiben_gleich(self):
        job = J.Job(self.ds, "smolvla", 500, cameras=["arm"], filters={"split": "train"}, export=None,
                    store=self.store)
        job.save()
        again = J.Job.load(os.path.join(self.store, job.name + ".json"), self.store)
        self.assertEqual((again.name, again.steps, again.cameras, again.filters, again.episodes),
                         (job.name, 500, ["arm"], job.filters, job.episodes))


class QuietTrainTests(unittest.TestCase):
    def test_pause_proportional_to_step_time(self):
        from ki.train import quiet
        t = [0.0]
        slept = []
        def update(x):
            t[0] += 0.2
            return x * 2
        f = quiet(update, 1.0, sleep=slept.append, clock=lambda: t[0])
        self.assertEqual(f(3), 6)
        self.assertAlmostEqual(slept[0], 0.2)

if __name__ == "__main__":
    unittest.main()


class DatensatzVorbereitenTests(unittest.TestCase):
    def test_zusammenfuehren_mit_links_und_filtern(self):
        import vla_datensatz as V
        with tempfile.TemporaryDirectory() as tmp:
            a, b = _make_ds(tmp, "eins", 2), _make_ds(tmp, "zwei", 3)
            for ds, teil in ((a, "D"), (b, "V")):
                for ep in ds.episodes():
                    p = os.path.join(ds.path, ep, "info.json")
                    with open(p, encoding="utf-8") as f:
                        info = json.load(f)
                    info.update(zielbauteil=teil, task=f"greife {teil} {ep}")
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(info, f)
            rows = V.rows_for([a, b])
            self.assertEqual(len(rows), 5)
            self.assertEqual(V.check([a, b])[0], None)
            picks = [r["key"] for r in rows if r["teil"] == "V"] + [rows[0]["key"]]
            new = E.compose("beide", "alles", picks, root=tmp, eigene_aufgaben=True)
            self.assertEqual(len(new.episodes()), 4)
            first = os.path.join(new.path, "ep_0000")
            self.assertEqual(new.episode_info("ep_0000")["task"], "greife V ep_0000")
            src = os.path.join(b.path, "ep_0000")
            for f in os.listdir(src):
                if f != "info.json":     # Videos/Daten verlinkt: gleiche Datei, kein Platz
                    self.assertTrue(os.path.samefile(os.path.join(src, f), os.path.join(first, f)))
            self.assertFalse(os.path.samefile(os.path.join(src, "info.json"), os.path.join(first, "info.json")))
            with open(os.path.join(src, "info.json"), encoding="utf-8") as f:
                self.assertNotIn("herkunft", json.load(f))   # Quelle unveraendert
