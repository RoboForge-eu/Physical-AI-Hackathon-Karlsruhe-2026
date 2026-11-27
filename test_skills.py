"""Offline-Tests: Code-Skills (Pruefung, Versionen, Runner), Skill-Autor-Agent, Orchestrator-Knoten."""
import json, tempfile, types, unittest
from skilllib import check, store
from test_module import FakeRos, FakeClaude, block

GOOD = '''
def run(robot, versuche=2):
    for i in range(versuche):
        robot.pose("ueber_bett")
        robot.faehigkeit("greifen", sekunden=5)
        robot.greifer(0)
        if robot.greifer_haelt():
            robot.pose("ueber_kiste")
            robot.greifer(100)
            return {"erfolg": True, "versuche": i + 1}
    return {"erfolg": False, "grund": "nichts gegriffen"}
'''


class CheckTests(unittest.TestCase):
    def test_good_code_passes_and_dangerous_code_fails(self):
        self.assertEqual(check.check(GOOD), [])
        bad = "import os\ndef run(robot):\n    open('x')\n    robot._call('x')\n    __import__('os')\n    return {}"
        problems = " ".join(check.check(bad))
        for word in ("Import", "open", "_call", "__import__"):
            self.assertIn(word, problems)
        self.assertTrue(check.check("def los(robot):\n    return {}"))          # run fehlt
        self.assertTrue(check.check("def run(arm):\n    return {}"))           # robot fehlt
        self.assertTrue(check.check("def run(robot):\n  return (\n"))          # Syntax


class StoreTests(unittest.TestCase):
    def test_versions_stats_and_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            store.create("Teil in Kiste", "Teil vom Bett in die Kiste", "Teil liegt in der Kiste", {"versuche": "n"}, tmp)
            v1 = store.add_version("teil_in_kiste", GOOD, "erste", tmp)
            v2 = store.add_version("teil_in_kiste", GOOD.replace("versuche=2", "versuche=3"), "mehr Versuche", tmp)
            self.assertEqual((v1, v2), (1, 2))
            self.assertIn("versuche=2", store.code("teil_in_kiste", 1, tmp)[0])
            store.set_active("teil_in_kiste", 2, tmp)
            self.assertEqual(store.code("teil_in_kiste", root=tmp)[1], 2)
            store.record("teil_in_kiste", 2, "echt", {"erfolg": True}, tmp)
            store.record("teil_in_kiste", 2, "echt", {"erfolg": False}, tmp)
            self.assertEqual(store.get("teil_in_kiste", tmp)["versionen"]["2"]["echt"], [1, 2])
            with self.assertRaises(KeyError):
                store.set_active("teil_in_kiste", 9, tmp)


class RunnerTests(unittest.TestCase):
    def test_execute_in_process_with_dry_robot(self):
        from skilllib.runner import execute
        from skilllib.api import DryRunAPI
        lines = []
        robot = DryRunAPI(None, "follower", lines.append, posen=["ueber_bett", "ueber_kiste"], modelle=["greifen"],
                          haelt=[False, True])
        self.assertEqual(execute(GOOD, {}, robot), {"erfolg": True, "versuche": 2})
        self.assertEqual([c[0] for c in robot.calls].count("modell.ausfuehren"), 2)
        res = execute("def run(robot):\n    return 5\n", {}, robot)
        self.assertFalse(res["erfolg"])
        res = execute("def run(robot):\n    x = [1][3]\n    return {'erfolg': True}\n", {}, robot)
        self.assertIn("Zeile 2", res["fehler"])

    def test_real_robot_goes_through_harness(self):
        from skilllib.runner import execute
        from skilllib.api import RobotAPI
        ros = FakeRos({"pose.anfahren": {"erreicht": True}, "modell.ausfuehren": {"schritte": 1},
                       "greifer.setzen": {}, "greifer.pruefen": {"haelt_etwas": True}})
        self.assertTrue(execute(GOOD, {}, RobotAPI(ros, "follower", lambda t: None))["erfolg"])
        self.assertTrue(all(args.get("arm") == "follower" for _, args in ros.calls))
        decided = RobotAPI(ros, "f", lambda t: None, decide=lambda f, o, b: "rechts")
        self.assertEqual(decided.frage("wohin?", ["links", "rechts"]), "rechts")


class AuthorTests(unittest.TestCase):
    def test_write_dry_run_real_trial_and_finish(self):
        import agent.author as A
        with tempfile.TemporaryDirectory() as tmp:
            old_root = store.ROOT
            store.ROOT = tmp
            try:
                store.create("greifen_probe", "Teil greifen", "Greifer haelt etwas")
                ros = FakeRos({"pose.liste": {"ueber_bett": [1] * 6, "ueber_kiste": [1] * 6}, "modelle.liste":
                               [{"name": "greifen", "task": "greifen", "method": "act"}],
                               "sitzung.status": {"bereit": True}, "kamera.bild": {"jpeg_base64": "QUJD"}})
                runs = []
                def fake_run(name, params, arm=None, modus=None, version=None, **kw):
                    runs.append((modus, version))
                    return {"erfolg": True}
                A.run_skill = fake_run
                claude = FakeClaude([
                    block(content=[block(type="tool_use", id="1", name="bibliothek", input={})], stop_reason="tool_use"),
                    block(content=[block(type="tool_use", id="2", name="code_speichern",
                                         input={"code": "import os", "notiz": "falsch"})], stop_reason="tool_use"),
                    block(content=[block(type="tool_use", id="3", name="code_speichern",
                                         input={"code": GOOD, "notiz": "v1"})], stop_reason="tool_use"),
                    block(content=[block(type="tool_use", id="4", name="trockenlauf", input={"haelt": [False, True]})],
                          stop_reason="tool_use"),
                    block(content=[block(type="tool_use", id="5", name="echter_versuch", input={})], stop_reason="tool_use"),
                    block(content=[block(type="tool_use", id="6", name="aktiv_setzen", input={"version": 1}),
                                   block(type="tool_use", id="7", name="fertig", input={"zusammenfassung": "laeuft"})],
                          stop_reason="tool_use")])
                asked = []
                author = A.SkillAuthor(ros, "greifen_probe", "follower", lambda k, t: None,
                                       lambda text: (asked.append(text), True)[1],
                                       cfg={"model": "m", "max_echte_versuche": 3}, client=claude)
                self.assertEqual(author.run("los"), "fertig")
                self.assertEqual(author.result, "laeuft")
                meta = store.get("greifen_probe")
                self.assertEqual(list(meta["versionen"]), ["1"])          # die verbotene Version wurde nicht gespeichert
                self.assertEqual(meta["aktiv"], 1)
                self.assertEqual(runs, [("trocken", 1), ("echt", 1)])
                self.assertEqual(len(asked), 1)                            # echter Versuch nur nach Freigabe
                rejected = claude.requests[2]["messages"][4]["content"][0]["content"]
                self.assertIn("NICHT gespeichert", rejected)
                real = claude.requests[5]["messages"][10]["content"][0]["content"]
                self.assertEqual(real[1]["type"], "image")                 # Kamerabild nach dem Versuch
            finally:
                store.ROOT = old_root
                import skilllib.runner as R
                A.run_skill = R.run_skill

    def test_trial_refused_when_human_says_no_or_no_session(self):
        import agent.author as A
        with tempfile.TemporaryDirectory() as tmp:
            old = store.ROOT
            store.ROOT = tmp
            try:
                store.create("x", "z", "k")
                store.add_version("x", GOOD)
                ros = FakeRos({"sitzung.status": {"bereit": False}})
                a = A.SkillAuthor(ros, "x", "follower", lambda k, t: None, lambda t: True, cfg={"model": "m"})
                self.assertIn("Keine bereite Arbeitssitzung", a.tool("echter_versuch", {}))
                ros.answers["sitzung.status"] = {"bereit": True}
                a.ask_trial = lambda t: False
                self.assertIn("abgelehnt", a.tool("echter_versuch", {}))
                self.assertEqual(a.real_trials, 0)
            finally:
                store.ROOT = old


class OrchestratorSkillTests(unittest.TestCase):
    def test_skill_node_branches_on_success_and_decision_node(self):
        from workflow import engine as E
        p = E.new_pipeline()
        n = p["nodes"]
        n["k2"] = E.new_node("skill", "k2")
        n["k2"]["params"].update(name="teil_in_kiste", parameter='{"versuche": 3}')
        n["k3"] = E.new_node("entscheidung", "k3")
        n["k3"]["params"].update(frage="Bett leer?", optionen="ja, nein", kamera="")
        n["k4"] = E.new_node("ende", "k4")
        n["k4"]["params"]["sitzung_beenden"] = False
        n["k1"]["next"] = "k2"
        n["k2"]["next"], n["k2"]["sonst"] = "k3", "k4"
        n["k3"]["next"] = "k4"
        calls = []
        ok = {"v": True}
        def fake_run(name, params, arm=None, modus=None, log=None):
            calls.append((name, params, modus))
            return {"erfolg": ok["v"]}
        r = E.Runner(p, FakeRos(), log=lambda t: None, run_skill=fake_run, decide=lambda f, o, b: "nein")
        self.assertEqual(r.run(), "fertig")
        self.assertEqual(calls, [("teil_in_kiste", {"versuche": 3}, "echt")])
        self.assertEqual(r.ctx["k3"]["ergebnis"], {"antwort": "nein"})
        ok["v"] = False
        r = E.Runner(p, FakeRos(), log=lambda t: None, run_skill=fake_run, decide=lambda f, o, b: "ja")
        r.run()
        self.assertNotIn("k3", r.ctx)                                      # Fehlschlag -> sonst-Ausgang

    def test_active_code_skills_become_agent_tools(self):
        from agent import tools as T
        with tempfile.TemporaryDirectory() as tmp:
            old = store.ROOT
            store.ROOT = tmp
            try:
                store.create("teil_in_kiste", "Teil in Kiste", "liegt drin", {"versuche": "wie oft"})
                store.add_version("teil_in_kiste", GOOD)
                tools, route = T.build([], [], ["follower"])
                self.assertEqual(tools, [])                                # noch nicht aktiv -> kein Werkzeug
                store.set_active("teil_in_kiste", 1)
                tools, route = T.build([], [], ["follower"])
                self.assertEqual(route["skill_teil_in_kiste"], ("code", "teil_in_kiste"))
                self.assertIn("versuche", tools[0]["input_schema"]["properties"])
            finally:
                store.ROOT = old


if __name__ == "__main__":
    unittest.main()
