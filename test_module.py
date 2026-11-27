"""Offline-Tests: lokale Harness-Schnittstelle, Arbeitssitzung, Agenten-Werkzeuge und -Schleife, Orchestrator."""
import json, tempfile, threading, time, types, unittest
from ki import skills as S


class FakeRos:
    """Antwortet wie der Harness-Kern; merkt sich alle Aufrufe."""
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def call(self, name, /, timeout=None, **args):     # "/": Befehle duerfen selbst ein Argument "name" haben
        self.calls.append((name, args))
        a = self.answers.get(name)
        if isinstance(a, Exception):
            raise a
        return a(**args) if callable(a) else a

    def tools(self):
        return self.call("skills.liste")


class KernApiTests(unittest.TestCase):
    def test_client_calls_skills_over_websocket(self):
        import kern_api, ros_client
        reg = S.Registry()
        reg.skill("echo", "gibt zurueck", {"a": {"type": "integer"}})(lambda a=0: {"a": a})
        reg.skill("langsam", "dauert")(lambda: (time.sleep(0.5), {"ok": 1})[1])
        reg.skill("bewegen", "bewegt", {"arm": {"type": "string"}}, ["arm"], moves=True)(lambda arm: {"bewegt": arm})
        reg.move_allowed = lambda skill, args, source: source == "modul" and args.get("arm") == "frei"
        api = kern_api.KernAPI(reg, log=lambda *_: None, port=18770).start()
        c = ros_client.RosClient("test", url="ws://127.0.0.1:18770")
        self.assertEqual(c.call("echo", a=5), {"a": 5})
        self.assertEqual(c.tools()[0]["name"], "echo")
        with self.assertRaises(ros_client.RosError):
            c.call("gibtsnicht")
        with self.assertRaises(ros_client.RosError):
            c.call("bewegen", arm="gesperrt")                 # keine Sitzung -> gesperrt
        self.assertEqual(c.call("bewegen", arm="frei"), {"bewegt": "frei"})
        # ein langsamer Befehl in einem Thread blockiert andere Threads nicht
        t0 = time.monotonic()
        th = threading.Thread(target=lambda: c.call("langsam"))
        th.start()
        time.sleep(0.05)
        self.assertEqual(c.call("echo", a=1), {"a": 1})
        self.assertLess(time.monotonic() - t0, 0.4)
        th.join()
        self.assertIn("test", api.modules())

    def test_client_reports_missing_ros(self):
        import ros_client
        with self.assertRaises(ros_client.RosNotConnected):
            ros_client.RosClient("x", url="ws://127.0.0.1:18799").call("arme.liste")


class SessionTests(unittest.TestCase):
    def test_holds_then_runs_model_then_holds_again(self):
        from ki.session import ArmSession
        sent = []
        s = ArmSession("follower", "test", sent.append, lambda: [2047] * 6, period=0.01)
        time.sleep(0.05)
        self.assertTrue(sent and sent[-1] == [2047] * 6)       # haelt die Ist-Stellung

        class Client:
            def __init__(self):
                self.halt, self.ready = threading.Event(), threading.Event()
                self.error, self.last_sent = None, [2100] * 6
                self.stats = {"requests": 7, "skipped": 0}
                self.ready.set()
            def stop(self):
                pass
        n_before = len(sent)
        res = s.run_model(Client, 0.1)
        self.assertEqual(res["schritte"], 7)
        time.sleep(0.05)
        self.assertEqual(sent[-1], [2100] * 6)                  # haelt jetzt die letzte Modell-Stellung
        self.assertGreater(len(sent), n_before)
        s.stop()
        self.assertFalse(s.info()["aktiv"])

    def test_only_one_skill_at_a_time(self):
        from ki.session import ArmSession
        s = ArmSession("f", "t", lambda t: None, lambda: [1] * 6, period=0.01)
        s.busy.acquire()
        with self.assertRaises(RuntimeError):
            s.run_model(lambda: None, 1)
        s.busy.release()
        s.stop()


class PoseTests(unittest.TestCase):
    def test_store_and_path_check(self):
        from ki import poses as P
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/posen.json"
            P.save_pose("follower", "oben", [2047, 2047, 2047, 2047, 2047, 1500], path)
            self.assertEqual(P.get_pose("follower", "oben", path)[5], 1500)
            with self.assertRaises(KeyError):
                P.get_pose("follower", "gibtsnicht", path)
        mid = [2047] * 6
        self.assertTrue(P.check_path(mid, [2400, 1900, 2200, 2047, 2047, 2047])[0])
        # ueber den Kopf nach hinten und wieder nach vorn: in der Mitte tiefer als Start/Ziel -> abgelehnt
        low_a = [2047, 1300, 2047, 2047, 2047, 2047]
        low_b = [2047, 2800, 2047, 2047, 2047, 2047]
        self.assertGreater(P.lowest(mid), P.lowest(low_a))
        ok, why = P.check_path([2047, 2047, 1200, 2047, 2047, 2047], [2047, 2047, 2900, 2047, 2047, 2047])
        self.assertIsInstance(ok, bool)
        self.assertTrue(why)

    def test_session_move_to_ramps_and_stops_when_blocked(self):
        from ki.session import ArmSession
        state = {"v": [2000] * 6}
        sent = []
        def send(t):
            sent.append(list(t))
            state["v"] = list(t)                          # folgt sofort
        s = ArmSession("f", "t", send, lambda: list(state["v"]), period=0.005)
        time.sleep(0.02)
        ok, st = s.move_to([2100] * 6, 20, settle=0.01)
        self.assertTrue(ok)
        steps = [b[0] - a[0] for a, b in zip(sent, sent[1:]) if b[0] != a[0]]
        self.assertTrue(any(2000 < x[0] < 2100 for x in sent))   # Zwischenwerte: nicht in einem Sprung
        self.assertEqual(sent[-1][0], 2100)
        state_fixed = [2100] * 6
        s.get_state = lambda: list(state_fixed)            # Arm bleibt stehen (Hindernis)
        s.send_target = lambda t: None
        ok, st = s.move_to([2600, 2100, 2100, 2100, 2100, 2100], 20, settle=0.01)
        self.assertFalse(ok)
        self.assertEqual(s.hold, state_fixed)              # haelt dort, wo er ist
        s.stop()

    def test_gripper_skills(self):
        from ki import ros_skills, poses as P
        from ki.session import ArmSession
        with tempfile.TemporaryDirectory() as tmp:
            old = P.PATH
            P.PATH = tmp + "/posen.json"
            try:
                state = {"v": [2047, 2047, 2047, 2047, 2047, 1400]}
                class Var:
                    def __init__(s, v): s.v = v
                    def get(s): return s.v
                panel = types.SimpleNamespace(label="S1", running=True, mode="ki", source=Var("ki"),
                                              status=Var("ARBEITSSITZUNG (t)"), ki_model=None, ki_task="", slots=[])
                sess = ArmSession("follower", "t", lambda t: None, lambda: list(state["v"]), period=0.005)
                lab = types.SimpleNamespace(panels={"follower": panel}, sessions={"follower": sess}, ki_queue=None,
                                            on_ui=lambda fn: fn(), arm_state=lambda a: list(state["v"]),
                                            ready_session=lambda a: sess, session_ok=lambda a: True)
                reg = ros_skills.build(lab)
                reg.call("greifer.merken", {"arm": "follower", "zustand": "zu"})
                state["v"][5] = 2600
                reg.call("greifer.merken", {"arm": "follower", "zustand": "auf"})
                r = reg.call("greifer.setzen", {"arm": "follower", "prozent": 0}, source="modul")
                self.assertEqual(r["ziel"], 1400)
                state["v"][5] = 1700                                   # bleibt am Teil haengen
                self.assertTrue(reg.call("greifer.pruefen", {"arm": "follower"})["haelt_etwas"])
                state["v"][5] = 1405                                   # ganz zu: leer
                self.assertFalse(reg.call("greifer.pruefen", {"arm": "follower"})["haelt_etwas"])
                reg.call("pose.merken", {"arm": "follower", "name": "oben"})
                self.assertIn("oben", reg.call("pose.liste", {"arm": "follower"}))
                with self.assertRaises(S.SkillError):
                    reg.call("pose.anfahren", {"arm": "follower", "name": "oben"}, source="remote")
                sess.stop()
            finally:
                P.PATH = old


class AgentToolTests(unittest.TestCase):
    def test_models_become_tools_and_dots_are_mapped(self):
        from agent import tools as T
        ros_tools = [{"name": "arme.liste", "description": "x", "input_schema": {"type": "object", "properties": {}}},
                     {"name": "training.start", "description": "x", "input_schema": {"type": "object", "properties": {}}}]
        tools, route = T.build(ros_tools, [{"name": "wuerfel-act-1", "method": "act", "task": "Wuerfel in Schale"}],
                               ["follower"])
        names = [t["name"] for t in tools]
        self.assertIn("arme__liste", names)
        self.assertNotIn("training__start", names)              # Werkstatt-Befehle fuer den Agenten gesperrt
        self.assertIn("faehigkeit_wuerfel-act-1", names)
        ros = FakeRos({"modell.ausfuehren": lambda **a: a, "arme.liste": []})
        self.assertEqual(T.call(ros, route, "faehigkeit_wuerfel-act-1", {"arm": "follower", "sekunden": 5}),
                         {"arm": "follower", "sekunden": 5, "modell": "wuerfel-act-1"})
        T.call(ros, route, "arme__liste", {})
        self.assertEqual(ros.calls[-1][0], "arme.liste")


def block(**kw):
    return types.SimpleNamespace(**kw)


class FakeClaude:
    """Spielt Antworten ab wie client.beta.messages.create."""
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


class AgentLoopTests(unittest.TestCase):
    def test_tool_loop_runs_tools_and_returns_images(self):
        from agent.loop import AgentRun
        ros = FakeRos({"arme.liste": [{"arm": "follower"}], "skills.liste": [
            {"name": "kamera.bild", "description": "Bild", "input_schema": {"type": "object", "properties": {}}}],
            "modelle.liste": [], "kamera.bild": {"jpeg_base64": "QUJD"}})
        claude = FakeClaude([
            block(content=[block(type="text", text="Ich schaue."), block(type="tool_use", id="t1", name="kamera__bild",
                                                                       input={"arm": "follower", "kamera": "turm"})],
                  stop_reason="tool_use"),
            block(content=[block(type="text", text="Auf dem Tisch liegt ein Wuerfel.")], stop_reason="end_turn")])
        log = []
        run = AgentRun(ros, "Was liegt da?", lambda k, t: log.append((k, t)), cfg={"model": "m", "effort": "high",
                                                                                     "max_turns": 5}, client=claude)
        self.assertEqual(run.run(), "fertig")
        self.assertEqual(run.result, "Auf dem Tisch liegt ein Wuerfel.")
        self.assertEqual(ros.calls[-1], ("kamera.bild", {"arm": "follower", "kamera": "turm"}))
        result = claude.requests[1]["messages"][2]["content"][0]      # Liste waechst weiter: Nachricht 3 = Ergebnisse
        self.assertEqual(result["content"][0]["type"], "image")
        self.assertEqual(claude.requests[0]["tools"][0]["name"], "kamera__bild")
        self.assertEqual(claude.requests[0]["fallbacks"], "default")

    def test_tool_errors_go_back_to_claude_and_refusal_stops(self):
        from agent.loop import AgentRun
        from ros_client import RosError
        ros = FakeRos({"arme.liste": [], "skills.liste": [{"name": "x.y", "description": "", "input_schema": {
            "type": "object", "properties": {}}}], "modelle.liste": [], "x.y": RosError("gesperrt")})
        claude = FakeClaude([block(content=[block(type="tool_use", id="a", name="x__y", input={})], stop_reason="tool_use"),
                             block(content=[], stop_reason="refusal")])
        run = AgentRun(ros, "t", lambda k, t: None, cfg={"model": "m", "max_turns": 5}, client=claude)
        self.assertEqual(run.run(), "abgelehnt")
        err = claude.requests[1]["messages"][2]["content"][0]
        self.assertTrue(err["is_error"])
        self.assertIn("gesperrt", err["content"])


class BandTests(unittest.TestCase):
    def pipeline(self):
        from workflow import engine as E
        p = E.new_pipeline("Test")
        for nid, kind in (("k2", "sitzung"), ("k3", "wiederholen"), ("k4", "faehigkeit"), ("k5", "bedingung"),
                          ("k6", "ende"), ("k7", "befehl")):
            p["nodes"][nid] = E.new_node(kind, nid)
        n = p["nodes"]
        n["k1"]["next"] = "k2"
        n["k2"]["next"] = "k3"
        n["k3"]["params"]["mal"] = 2
        n["k3"]["next"], n["k3"]["sonst"] = "k4", "k7"
        n["k4"]["params"]["modell"] = "wuerfel"
        n["k4"]["next"] = "k5"
        n["k5"]["params"].update(wert="{{k4.ergebnis.schritte}}", vergleich=">", mit="10")
        n["k5"]["next"], n["k5"]["sonst"] = "k3", "k6"
        n["k7"]["params"].update(name="arm.status", args='{"arm": "{{k2.ergebnis.arm}}"}')
        n["k7"]["next"] = "k6"
        return p

    def test_loop_condition_variables_and_session(self):
        from workflow import engine as E
        status = iter([{"bereit": False, "freigegeben": False}, {"bereit": False, "freigegeben": True},
                       {"bereit": True, "freigegeben": True, "arm": "follower"}])
        ros = FakeRos({"sitzung.status": lambda **a: next(status), "sitzung.anfragen": {"angefragt": True},
                       "modell.ausfuehren": {"schritte": 50}, "arm.status": lambda **a: {"label": a["arm"]},
                       "sitzung.beenden": {}})
        nodes = []
        r = E.Runner(self.pipeline(), ros, log=lambda t: None, on_node=lambda nid, st: nodes.append((nid, st)),
                     sleep=lambda s: None)
        r._wait = lambda s: None
        self.assertEqual(r.run(), "fertig")
        names = [c[0] for c in ros.calls]
        self.assertEqual(names.count("modell.ausfuehren"), 2)        # zweimal wiederholt
        self.assertIn("sitzung.anfragen", names)
        self.assertEqual(ros.calls[names.index("arm.status")][1], {"arm": "follower"})   # Variable eingesetzt
        self.assertEqual(names[-1], "sitzung.beenden")
        self.assertIn(("k6", "ok"), nodes)

    def test_condition_else_branch_and_validation(self):
        from workflow import engine as E
        self.assertTrue(E.compare("5", ">", "3"))
        self.assertFalse(E.compare("abc", "==", "abd"))
        self.assertTrue(E.compare({"x": "Wuerfel"}, "enthaelt", "Wuerfel"))
        self.assertTrue(E.compare("ja", "ist wahr", ""))
        p = self.pipeline()
        p["nodes"]["k4"]["params"]["modell"] = ""
        p["nodes"]["k6"]["next"] = "k99"
        problems = E.validate(p)
        self.assertTrue(any("kein Modell" in x for x in problems))
        self.assertTrue(any("k99" in x for x in problems))
        with self.assertRaises(E.PipelineError):
            E.Runner(p, FakeRos()).run()

    def test_missing_variable_and_failing_node_stop_the_run(self):
        from workflow import engine as E
        with self.assertRaises(E.PipelineError):
            E.fill("{{k9.ergebnis}}", {})
        self.assertEqual(E.fill("{{k1.ergebnis.n}}", {"k1": {"ergebnis": {"n": 3}}}), 3)        # Typ bleibt
        self.assertEqual(E.fill("Wert {{k1.ergebnis.n}}!", {"k1": {"ergebnis": {"n": 3}}}), "Wert 3!")
        p = E.new_pipeline()
        p["nodes"]["k2"] = E.new_node("befehl", "k2")
        p["nodes"]["k1"]["next"] = "k2"
        states = []
        from ros_client import RosError
        r = E.Runner(p, FakeRos({"arme.liste": RosError("ROS weg")}), log=lambda t: None,
                     on_node=lambda nid, st: states.append((nid, st)))
        with self.assertRaises(RosError):
            r.run()
        self.assertIn(("k2", "fehler"), states)

    def test_store_roundtrip(self):
        from workflow import engine as E, store
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pipeline()
            p["name"] = "Würfel räumen"
            path = store.save(p, tmp)
            self.assertTrue(path.endswith("wuerfel_raeumen.json"))
            self.assertEqual(store.names(tmp)[0][0], "Würfel räumen")
            self.assertEqual(store.load(path)["nodes"]["k3"]["params"]["mal"], 2)


if __name__ == "__main__":
    unittest.main()
