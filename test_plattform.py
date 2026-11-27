"""Tests fuer den Physical AI Harness (plattform/): ohne Arm, ohne Internet.

  python -m unittest test_plattform
"""
import datetime, json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock

from plattform import kern, station, repo_bauen
from ki import geraet


def git_da():
    return shutil.which("git") is not None


class ZustandTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.z = kern.Zustand(self.d)

    def test_erster_start_oben(self):
        self.assertEqual(self.z.startpunkt()["abschnitt"], "start")

    def test_springt_zur_letzten_arbeit(self):
        self.z.ansehen("teilen", 100)
        self.z.arbeit("trainieren", "Training x gestartet")
        sp = self.z.startpunkt()
        self.assertEqual(sp["abschnitt"], "trainieren")
        self.assertIn("Training", sp["grund"])
        self.assertTrue(self.z.get()["erledigt"]["trainieren"])

    def test_langes_lesen_danach_gewinnt(self):
        self.z.arbeit("orchestrator", "x gespeichert")
        d = self.z.get()
        d["angesehen"] = {"abschnitt": "vorstellen", "scroll": 40, "zeit": d["gearbeitet"]["zeit"] + 900}
        kern._write(self.z.path, d)
        self.assertEqual(self.z.startpunkt()["abschnitt"], "vorstellen")


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.pakete = os.path.join(self.root, "pakete")
        self.kit = os.path.join(self.root, "kit")
        self.teams = os.path.join(self.kit, "teams")
        os.makedirs(os.path.join(self.teams, "_vorlage"))
        open(os.path.join(self.teams, "_vorlage", "orchestrator.py"), "w").close()
        os.makedirs(os.path.join(self.kit, "calibration"))
        kern._write(os.path.join(self.kit, "calibration", "follower_calibration.json"), {"alt": 1})
        os.makedirs(self.pakete)
        self.t = kern.Teams(self.pakete, os.path.join(self.root, "daten"), self.kit, self.teams)

    def paket(self, **extra):
        p = {"code": "BLAU-1234", "team": "Team Blau", "huggingface": {"token": "hf_geheim"},
             "github": {"token": "gh_geheim"}, **extra}
        kern._write(os.path.join(self.pakete, "blau.json"), p)

    def test_login_legt_ordner_aus_vorlage_an(self):
        self.paket()
        p, notes = self.t.login(" blau-1234 ")
        self.assertEqual(p["ordner"], "team-blau")
        self.assertTrue(os.path.exists(os.path.join(self.teams, "team-blau", "orchestrator.py")))
        self.assertEqual(self.t.aktiv()["team"], "Team Blau")

    def test_falscher_code(self):
        self.paket()
        with self.assertRaises(ValueError):
            self.t.login("ROT-0000")

    def test_kalibrierung_wird_installiert_und_gesichert(self):
        self.paket(station={"name": "S3", "kalibrierung": {"follower_calibration.json": {"neu": 2},
                                                           "../boese.json": {"x": 1}},
                            "config": {"follower": {"usb_serial": "AB"}}})
        p, notes = self.t.login("BLAU-1234")
        cal = json.load(open(os.path.join(self.kit, "calibration", "follower_calibration.json")))
        self.assertEqual(cal, {"neu": 2})
        self.assertFalse(os.path.exists(os.path.join(self.kit, "boese.json")))      # kein Pfad nach draussen
        self.assertTrue(os.path.exists(os.path.join(self.kit, "config.json")))
        backups = os.listdir(os.path.join(self.root, "daten", "sicherung"))
        self.assertTrue(os.path.exists(os.path.join(self.root, "daten", "sicherung", backups[0],
                                                    "follower_calibration.json")))
        self.assertIn("Station", notes[0])

    def test_public_versteckt_tokens(self):
        self.paket()
        p, _ = self.t.login("BLAU-1234")
        pub = kern.public(p)
        self.assertNotIn("hf_geheim", json.dumps(pub))
        self.assertNotIn("gh_geheim", json.dumps(pub))


class HackathonTests(unittest.TestCase):
    def setUp(self):
        self.h = kern.Hackathon()

    def test_phasen_am_tag(self):
        j = self.h.jetzt(datetime.datetime(2026, 11, 28, 11, 35))
        self.assertTrue(j["heute"])
        self.assertEqual(j["phasen"][j["aktuell"]]["titel"], "Training 1 starten")
        self.assertTrue(any("Training" in e["text"] for e in j["erinnerungen"]))

    def test_anderer_tag_ohne_erinnerung(self):
        j = self.h.jetzt(datetime.datetime(2026, 11, 27, 11, 35))
        self.assertFalse(j["heute"])
        self.assertIsNone(j["aktuell"])
        self.assertEqual(j["erinnerungen"], [])

    def test_plan_lueckenlos(self):
        ph = self.h.plan()["phasen"]
        for a, b in zip(ph, ph[1:]):
            self.assertEqual(a["ende"], b["start"])


class PfadTests(unittest.TestCase):
    def test_nur_im_team_ordner(self):
        d = tempfile.mkdtemp()
        self.assertTrue(kern.sicherer_pfad(d, "skills/a.py").startswith(os.path.realpath(d)))
        for boese in ("../x.py", "..\\x.py", "/etc/passwd", "skills/../../x"):
            with self.assertRaises(ValueError):
                kern.sicherer_pfad(d, boese)


class GeraetTests(unittest.TestCase):
    def fake(self, cuda=False, mps=False):
        return mock.Mock(cuda=mock.Mock(is_available=lambda: cuda),
                         backends=mock.Mock(mps=mock.Mock(is_available=lambda: mps)))

    def test_reihenfolge(self):
        self.assertEqual(geraet.detect(self.fake(cuda=True, mps=True)), "cuda")
        self.assertEqual(geraet.detect(self.fake(mps=True)), "mps")
        self.assertEqual(geraet.detect(self.fake()), "cpu")

    def test_auto_in_argumenten(self):
        args = geraet.fix_args(["--policy.device=auto", "--steps=5"], self.fake(mps=True))
        self.assertEqual(args, ["--policy.device=mps", "--steps=5"])
        self.assertEqual(geraet.resolve("cuda", self.fake()), "cpu")

    def test_empfehlung(self):
        self.assertEqual(geraet.empfehlung("mps")[0], "act")
        self.assertEqual(geraet.empfehlung("cuda")[0], "smolvla")

    def test_methoden_nutzen_auto(self):
        from ki import methods
        cmd = methods.get("act").train_command("py", "ds", "repo", "out")
        self.assertIn("--policy.device=auto", cmd)


class ModellKarteTests(unittest.TestCase):
    def test_schlagwoerter_und_team(self):
        k = kern.modell_karte({"name": "m1", "method": "act", "dataset": "elektrodose", "steps": 20000},
                              {"team": "Team Blau"})
        self.assertIn("physical-ai-harness", k)
        self.assertIn("Team Blau", k)
        self.assertTrue(k.startswith("---"))

    def test_hochladen_token_nur_in_umgebung(self):
        calls = []

        class P:
            def __init__(self, cmd, **kw):
                calls.append((cmd, kw["env"]))
                self.stdout = iter(["ok\n"])
                self.returncode = 0

            def wait(self):
                return 0
        team = {"huggingface": {"token": "hf_xyz"}}
        kern.hf_hochladen(team, "ordner", "RoboForge/a", "m1", "model", "karte", lambda l: None, python="py", popen=P)
        cmd, env = calls[0]
        self.assertNotIn("hf_xyz", " ".join(cmd))
        self.assertEqual(env["HF_TOKEN"], "hf_xyz")


@unittest.skipUnless(git_da(), "git fehlt")
class GitTeilenTests(unittest.TestCase):
    """Echtes git mit einem lokalen 'GitHub' (bare repo)."""

    def run_git(self, *a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.remote = os.path.join(self.root, "remote.git")
        self.run_git("init", "--bare", "-b", "main", self.remote, cwd=self.root)
        seed = os.path.join(self.root, "seed")
        self.run_git("clone", self.remote, seed, cwd=self.root)
        os.makedirs(os.path.join(seed, "teams", "_vorlage"))
        open(os.path.join(seed, "teams", "_vorlage", "a.py"), "w").write("x=1\n")
        open(os.path.join(seed, "ros.py"), "w").write("# kern\n")
        for a in (("add", "."), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "start"),
                  ("push", "origin", "main")):
            self.run_git(*a, cwd=seed)
        self.kit = os.path.join(self.root, "kit")
        self.run_git("clone", self.remote, self.kit, cwd=self.root)
        self.team = {"team": "Team Blau", "ordner": "team-blau",
                     "github": {"repo": self.remote, "zweig": "team/team-blau"}}

    def test_teilen_nur_team_ordner_in_team_zweig(self):
        os.makedirs(os.path.join(self.kit, "teams", "team-blau"))
        open(os.path.join(self.kit, "teams", "team-blau", "orchestrator.py"), "w").write("print(1)\n")
        open(os.path.join(self.kit, "ros.py"), "a").write("# veraendert\n")       # darf NICHT mit
        log = []
        r = kern.git_teilen(self.team, "erster Stand", log.append, cwd=self.kit)
        self.assertEqual(r["zweig"], "team/team-blau")
        files = self.run_git("ls-tree", "-r", "--name-only", "team/team-blau", cwd=self.remote).split()
        self.assertIn("teams/team-blau/orchestrator.py", files)
        diff = self.run_git("diff", "main", "team/team-blau", "--name-only", cwd=self.remote).split()
        self.assertEqual(diff, ["teams/team-blau/orchestrator.py"])

    def test_fremdes_repo_wird_abgelehnt(self):
        team = dict(self.team, github={"repo": "https://github.com/x/anderes"})
        with self.assertRaises(ValueError):
            kern.git_teilen(team, "", lambda l: None, cwd=self.kit)


@unittest.skipUnless(git_da(), "git fehlt")
class WaechterTests(unittest.TestCase):
    def test_uebernimmt_nur_eigenen_ordner(self):
        root = tempfile.mkdtemp()
        g = lambda *a, cwd=root: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout
        remote = os.path.join(root, "r.git")
        g("init", "--bare", "-b", "main", remote)
        w = os.path.join(root, "w")
        g("clone", remote, w)
        who = ("-c", "user.name=t", "-c", "user.email=t@t")
        open(os.path.join(w, "ros.py"), "w").write("gut\n")
        g("add", ".", cwd=w); g(*who, "commit", "-m", "a", cwd=w); g("push", "origin", "main", cwd=w)
        g("checkout", "-b", "team/blau", cwd=w)
        os.makedirs(os.path.join(w, "teams", "blau"))
        os.makedirs(os.path.join(w, "teams", "rot"))
        open(os.path.join(w, "teams", "blau", "a.py"), "w").write("blau\n")
        open(os.path.join(w, "teams", "blau", "m.safetensors"), "w").write("gross\n")
        open(os.path.join(w, "teams", "rot", "b.py"), "w").write("fremd\n")
        open(os.path.join(w, "ros.py"), "w").write("boese\n")
        g("add", ".", cwd=w); g(*who, "commit", "-m", "b", cwd=w); g("push", "origin", "team/blau", cwd=w)
        main = os.path.join(root, "main")
        g("clone", remote, main)
        script = os.path.join(main, "waechter.py")
        open(script, "w", encoding="utf-8").write(repo_bauen.WAECHTER_PY)
        subprocess.run([sys.executable, script], cwd=main, check=True, capture_output=True)
        staged = g("diff", "--cached", "--name-only", cwd=main).split()
        self.assertEqual(staged, ["teams/blau/a.py"])
        self.assertEqual(open(os.path.join(main, "ros.py")).read(), "gut\n")


class StationTests(unittest.TestCase):
    def test_paket_behaelt_code_und_tokens(self):
        root = tempfile.mkdtemp()
        kit = os.path.join(root, "kit")
        os.makedirs(os.path.join(kit, "calibration"))
        kern._write(os.path.join(kit, "calibration", "follower_calibration.json"), {"a": 1})
        kern._write(os.path.join(kit, "calibration", "follower_calibration_2026-11-16_154955.json"), {"alt": 1})
        pak = os.path.join(root, "p")
        path, p = station.paket("Team Gelb", "Station 2", True, pakete=pak, kit=kit, env={"TEAM_HF_TOKEN": "hf_1"})
        self.assertEqual(p["ordner"], "team-gelb")
        self.assertEqual(list(p["station"]["kalibrierung"]), ["follower_calibration.json"])
        path2, p2 = station.paket("Team Gelb", pakete=pak, kit=kit, env={})
        self.assertEqual(p2["code"], p["code"])
        self.assertEqual(p2["huggingface"]["token"], "hf_1")

    def test_config_ein_setup(self):
        kit = tempfile.mkdtemp()
        kern._write(os.path.join(kit, "config.json"), {"follower": {"usb_serial": "A"}, "follower2": {"usb_serial": "B"}})
        station.config_schreiben("abc", "def", "Station 1", kit=kit)
        cfg = json.load(open(os.path.join(kit, "config.json"), encoding="utf-8"))
        self.assertEqual(cfg["follower"]["usb_serial"], "ABC")
        self.assertNotIn("follower2", cfg)


class RepoBauenTests(unittest.TestCase):
    def test_keine_geheimnisse_und_daten(self):
        ziel = tempfile.mkdtemp()
        repo_bauen.bauen(ziel)
        alle = [os.path.relpath(os.path.join(r, f), ziel).replace(os.sep, "/") for r, _, fs in os.walk(ziel) for f in fs]
        for verboten in ("config.json", "livekit.json", "agent.json", "fernzugriff.json"):
            self.assertNotIn(verboten, alle)
        self.assertFalse(any(a.startswith(("ki_daten/", "calibration/", "stationspakete/", "plattform_daten/"))
                             for a in alle))
        for noetig in ("physical_ai_harness.py", "ros.py", "plattform/server.py", "plattform/static/index.html",
                       "teams/_vorlage/AGENTS.md", "plaene/elektrodose.json", ".github/workflows/ordner-waechter.yml",
                       "Start Windows.cmd", "Start macOS.command", "config.example.json", "requirements-plattform.txt"):
            self.assertIn(noetig, alle)
        self.assertFalse(any(a.startswith("teams/") and not a.startswith(("teams/_vorlage/", "teams/README"))
                             for a in alle))


if __name__ == "__main__":
    unittest.main()
