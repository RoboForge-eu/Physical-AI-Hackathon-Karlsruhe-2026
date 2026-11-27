"""Offline-Tests: Aufnahmeplan (Geometrie, Plan, Fortschritt), Maske, Automatik."""
import json, math, os, tempfile, unittest
import numpy as np
from aufnahme import geometrie as G, plan as P, automatik as A, maske as M

GEO = json.load(open(os.path.join(os.path.dirname(__file__), "plaene", "kartongriffe.json"), encoding="utf-8"))["geometrie"]


class GeometryTests(unittest.TestCase):
    def test_ring_check(self):
        L, B = GEO["laenge"], GEO["breite"]
        self.assertTrue(G.inside_ring(G.corners(0, 28, 0, L, B), 16, 42, 1))          # quer mittig
        self.assertFalse(G.inside_ring(G.corners(0, 10, 0, L, B), 16, 42, 1))         # ueber der Basis
        self.assertFalse(G.inside_ring(G.corners(0, 38, 0, L, B), 16, 42, 1))         # zu weit
        self.assertEqual(G.classify(0, 28, 0), "quer")
        self.assertEqual(G.classify(0, 28, 90), "laengs")
        self.assertEqual(G.approach_side(0, 28, 0), -1)                                # untere Seite zur Basis
        # laengs: immer die rechte lange Seite, von der Basis aus geschaut (links und rechts im Halbring)
        for x, y, w in ((-25.3, 13.4, 153), (25.3, 13.4, 27), (0, 28, 90)):
            p = {"x": x, "y": y, "winkel": w, "seite": G.approach_side(x, y, w)}
            (ax, ay), (bx, by) = G.side_points(p, 25, 15.5)
            mx, my = (ax + bx) / 2 - x, (ay + by) / 2 - y
            self.assertGreater(mx * y - my * x, 0, (x, y, w))      # Seitenmitte liegt rechts der Blickrichtung

    def test_all_classes_possible_and_valid(self):
        pool = G.candidates(GEO)
        kinds = {c[3] for c in pool}
        self.assertEqual(kinds, {"quer", "schraeg", "laengs"})
        ps = G.generate(["quer", "schraeg", "laengs"] * 3, GEO, 1, pool=pool)
        self.assertEqual([p["ausrichtung"] for p in ps], ["quer", "schraeg", "laengs"] * 3)
        for p in ps:
            margin = GEO["rand_laengs"] if p["ausrichtung"] == "laengs" else GEO["rand"]
            self.assertTrue(G.inside_ring(G.corners(p["x"], p["y"], p["winkel"], GEO["laenge"], GEO["breite"]),
                                          GEO["r_innen"], GEO["r_aussen"], margin))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = P.PlanRun.open("kartongriffe", root=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_matches_spec(self):
        rs = self.run.rounds
        self.assertEqual(len(rs), 36)
        parts = [o["teil"] for r in rs for o in r["auftraege"]]
        self.assertEqual(len(parts), 195)
        self.assertEqual({p: parts.count(p) for p in "DPV"}, {"D": 65, "P": 65, "V": 65})
        self.assertTrue(all(v <= 2 for r in rs for v in self.run.defn["ladungen"][r["ladung"]].values()))
        per_session = {}
        for r in rs:
            per_session[r["session"]] = per_session.get(r["session"], 0) + len(r["auftraege"])
        self.assertEqual(per_session, {1: 49, 2: 50, 3: 49, 4: 47})
        spec = sum(o["art"] == "spezifisch" for r in rs for o in r["auftraege"])
        self.assertTrue(0.22 <= spec / 195 <= 0.36, spec)
        for r in rs:                                         # spezifisch nur bei >= 2 gleichen Teilen
            c = dict(self.run.defn["ladungen"][r["ladung"]])
            for o in r["auftraege"]:
                if o["art"] == "spezifisch":
                    self.assertGreaterEqual(c[o["teil"]], 2)
                c[o["teil"]] -= 1
        self.assertEqual(sum(r["platzierung"]["ausrichtung"] == "laengs" for r in rs), 5)
        self.assertEqual([t["id"] for t in self.run.data["tests"]], ["T1", "T2", "T3"])

    def test_schaerfe_im_plan(self):
        self.assertEqual(self.run.schaerfe(), {})
        self.assertEqual(self.run.schaerfe_vergleich({"wrist": 300.0}), {"wrist": (300.0, None, True)})
        self.run.schaerfe_speichern({"wrist": 412.34})
        again = P.PlanRun.open("kartongriffe", root=self.tmp.name)       # bleibt nach Neustart erhalten
        self.assertEqual(again.schaerfe()["wrist"]["wert"], 412.3)
        cmp = again.schaerfe_vergleich({"wrist": 400.0, "turm": 90.0})
        self.assertTrue(cmp["wrist"][2])                                 # 97 % vom Bezug: ok
        self.assertEqual(cmp["turm"][1], None)                           # nicht gemessen: kein Urteil
        self.assertFalse(again.schaerfe_vergleich({"wrist": 250.0})["wrist"][2])   # deutlich unschaerfer
        self.assertTrue(any("Schaerfe gemessen" in z for z in again.data["protokoll"]))

    def test_reproducible(self):
        with tempfile.TemporaryDirectory() as t2:
            other = P.PlanRun.open("kartongriffe", root=t2)
        self.assertEqual(other.rounds, self.run.rounds)

    def test_progress_keep_discard_swap(self):
        run = self.run
        r, o, i = run.current()
        self.assertEqual((r["runde"], i), (1, 0))
        run.confirm_round()
        before = run.content()
        if o["art"] == "spezifisch":
            with self.assertRaises(ValueError):
                run.keep("ep_0000")
            run.keep("ep_0000", lage="back left")
        else:
            run.keep("ep_0000")
        after = run.content()
        self.assertEqual(sum(before.values()) - 1, sum(after.values()))
        r, o2, i2 = run.current()
        self.assertEqual(i2, 1)
        # nicht greifbar: tauscht mit naechstem anderen Bauteil
        res = run.not_graspable({"teil": o2["teil"], "bild": "x.jpg"})
        self.assertEqual(res, "getauscht")
        self.assertNotEqual(run.current()[1]["teil"], o2["teil"])
        # neu laden: Fortschritt bleibt
        again = P.PlanRun.open("kartongriffe", root=self.tmp.name)
        self.assertEqual(again.current()[2], 1)
        self.assertEqual(len(again.round()["nicht_greifbar"]), 1)

    def test_round_finishes_and_advances(self):
        run = self.run
        run.confirm_round()
        n = len(run.round()["auftraege"])
        for k in range(n):
            o = run.current()[1]
            run.keep(f"ep_{k:04d}", lage="middle" if o["art"] == "spezifisch" else None)
        self.assertEqual(run.data["aktuelle_runde"], 1)
        self.assertEqual(run.rounds[0]["status"], "fertig")
        soll, ist = run.stats()
        self.assertEqual(sum(ist.values()), n)

    def test_unreachable_makes_replacement(self):
        old = dict(self.run.round()["platzierung"])
        new = self.run.unreachable()
        self.assertNotEqual((old["x"], old["y"], old["winkel"]), (new["x"], new["y"], new["winkel"]))
        self.assertEqual(new["ausrichtung"], old["ausrichtung"])

    def test_repeat_single_order(self):
        from pathlib import Path
        from ki.episodes import Dataset
        run = self.run
        root = Path(self.tmp.name)
        dataset = Dataset(str(root / "ds_einzel"))
        run.confirm_round()
        names = []
        while run.round()["runde"] == 1:
            r, a, i = run.current()
            name = f"ep_{len(names):04d}"
            lage = "middle" if a["art"] == "spezifisch" else None
            folder = Path(dataset.path) / name
            folder.mkdir(parents=True)
            (folder / "info.json").write_text(json.dumps(dict(plan=run.defn["id"], session=r["session"], runde=1,
                                              zielbauteil=a["teil"], befehlsart=a["art"], lage=lage)), encoding="utf-8")
            run.keep(name, lage)
            names.append(name)
        run.confirm_round()                                   # Runde 2 liegt schon bereit
        run.repeat_order(1, 2, dataset, root / "trash_einzel")
        self.assertEqual(len(dataset.episodes()), len(names) - 1)
        r1 = run.rounds[0]
        self.assertEqual(r1["auftraege"][2]["status"], "offen")
        self.assertEqual(len(r1["behalten"]), len(names) - 1)
        self.assertEqual(run.round()["runde"], 1)             # zurueck zu Runde 1
        self.assertEqual(r1["status"], "offen")               # Karton neu hinlegen
        self.assertEqual(run.rounds[1]["status"], "offen")
        r, o, i = run.current()
        self.assertEqual(i, 2)                                 # genau dieser Griff ist dran
        run.confirm_round()
        lage = "middle" if o["art"] == "spezifisch" else None
        run.keep("ep_0100", lage)
        self.assertEqual(run.round()["runde"], 2)             # danach weiter mit Runde 2

    def test_repeat_round_only_resets_that_round(self):
        from pathlib import Path
        from ki.episodes import Dataset
        run = self.run
        root = Path(self.tmp.name)
        dataset = Dataset(str(root / "ds_runde"))
        trash = root / "trash_runde"
        pos = dict(run.rounds[0]["platzierung"])
        run.confirm_round()
        n = 0
        while run.round()["runde"] == 1:                     # Runde 1 komplett aufnehmen
            r, a, _ = run.current()
            name = f"ep_{n:04d}"
            folder = Path(dataset.path) / name
            folder.mkdir(parents=True)
            lage = "middle" if a["art"] == "spezifisch" else None
            (folder / "info.json").write_text(json.dumps(dict(plan=run.defn["id"], session=r["session"],
                                              runde=1, zielbauteil=a["teil"], befehlsart=a["art"], lage=lage)),
                                              encoding="utf-8")
            run.keep(name, lage)
            n += 1
        run.confirm_round()                                  # Runde 2 schon bereit
        self.assertEqual(run.repeat_round(1, dataset, trash), n)
        self.assertEqual(dataset.episodes(), [])
        self.assertEqual(run.round()["runde"], 1)            # zurueck zu Runde 1, gleiche Position
        self.assertEqual(run.rounds[0]["platzierung"], pos)
        self.assertEqual(run.rounds[0]["status"], "offen")
        self.assertEqual(run.rounds[1]["status"], "offen")   # Runde 2 spaeter neu hinlegen
        self.assertEqual(len(list(trash.glob("ds_runde/runde_1_*/ep_*"))), n)

    def test_repeat_session_keeps_positions_and_removes_only_its_recordings(self):
        from pathlib import Path
        from unittest.mock import patch
        from ki.episodes import Dataset

        run = self.run
        root = Path(self.tmp.name)
        dataset = Dataset(str(root / "dataset"))
        trash = root / "trash"

        def record(ep, r, a, lage):
            folder = Path(dataset.path) / ep
            folder.mkdir(parents=True)
            info = dict(plan=run.defn["id"], session=r["session"], runde=r["runde"],
                        zielbauteil=a["teil"], befehlsart=a["art"], lage=lage)
            (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")

        placements = [dict(r["platzierung"]) for r in run.rounds]
        first_session = run.round()["session"]
        run.confirm_round()
        ep = 0
        while run.round()["runde"] == 1:
            r, a, _ = run.current()
            name = f"ep_{ep:04d}"
            lage = "middle" if a["art"] == "spezifisch" else None
            record(name, r, a, lage)
            run.keep(name, lage)
            ep += 1
        other = next(r for r in run.rounds if r["session"] != first_session)
        record("ep_0999", other, other["auftraege"][0], None)
        # Alter Planverweis nach Loeschen oder Wiederverwendung einer Nummer.
        run.round()["auftraege"][0]["episode"] = "ep_0999"
        self.assertEqual(run.rounds[0]["status"], "fertig")
        with patch.object(run, "save", side_effect=OSError("Schreibfehler")):
            with self.assertRaises(OSError):
                run.repeat_session(first_session, dataset, trash)
        self.assertEqual(len(dataset.episodes()), ep + 1)
        self.assertEqual(run.round()["runde"], 2)

        self.assertEqual(run.repeat_session(first_session, dataset, trash), ep)
        self.assertEqual(dataset.episodes(), ["ep_0999"])
        self.assertEqual(len(list(trash.glob("dataset/session_*/ep_*"))), ep)
        resumed = P.PlanRun.open("kartongriffe", root=self.tmp.name)
        self.assertEqual(resumed.round()["runde"], 1)
        self.assertEqual(placements, [r["platzierung"] for r in resumed.rounds])
        self.assertEqual(sum(resumed.stats()[1].values()), 0)
        self.assertTrue(all(a["status"] == "offen" and "episode" not in a
                            for r in resumed.rounds if r["session"] == first_session for a in r["auftraege"]))

    def test_task_text(self):
        o = {"teil": "P", "art": "spezifisch"}
        self.assertEqual(self.run.task_text(o, self.run.lage_text(0, 2)), "Pick up the back right red circuit board")
        self.assertEqual(self.run.task_text({"teil": "D", "art": "allgemein"}), "Pick up an orange junction box")


class AutomatikTests(unittest.TestCase):
    CFG = {"an": True, "countdown_s": 1.0, "ruhe_s": 1.0, "ruhe_grad": 1.5, "halten_s": 1.5, "zeitlimit_s": 30,
           "greifer_zu_toleranz": 40, "greifer_haelt_min": 60, "hoehe_toleranz_grad": 10}

    def test_start_then_stop_after_grip(self):
        a = A.Automatik(self.CFG, greifer_zu=1400)
        pose = [2000, 1500, 2500, 2000, 2000, 1400]
        t, res = 0.0, None
        while t < 0.9:                                         # noch nicht lange genug ruhig
            self.assertIsNone(a.update(t, pose, True, True))
            t += 0.1
        self.assertIsNone(a.update(t, pose, False, True))       # Runde nicht bestaetigt
        self.assertIn("Runde", a.grund)
        t += 0.1                                                # Countdown startet neu
        for _ in range(9):
            self.assertIsNone(a.update(t, pose, True, True))
            t += 0.1
        self.assertEqual(a.update(t + 0.15, pose, True, True), "start")
        b = A.Automatik(dict(self.CFG, countdown_s=0), greifer_zu=1400)
        self.assertEqual(b.update(0, pose, True, True), "start")          # 0 s = sofort
        c = A.Automatik(self.CFG, greifer_zu=1400)
        self.assertIsNone(c.update(5, pose[:5] + [1600], True, True))     # Greifer offen: kein Start
        self.assertIn("Greifer", c.grund)
        seq = []
        for g in range(1400, 2400, 100):                        # oeffnen
            seq.append(pose[:5] + [g])
        for k in range(10):                                     # eintauchen
            seq.append([2000, 1500 + 40 * k, 2500, 2000, 2000, 2400])
        for g in range(2400, 1650, -100):                       # schliessen am Teil (bleibt bei ~1650)
            seq.append([2000, 1900, 2500, 2000, 2000, g])
        for k in range(10):                                     # hochfahren
            seq.append([2000, 1900 - 40 * k, 2500, 2000, 2000, 1650])
        for s in seq:
            t += 0.1
            self.assertIsNone(a.update(t, s, True, True))
        result = None
        for _ in range(30):                                     # ruhig halten
            t += 0.1
            result = a.update(t, [2000, 1500, 2500, 2000, 2000, 1650], True, True) or result
            if result:
                break
        self.assertEqual(result, "stop")

    def test_timeout(self):
        a = A.Automatik(dict(self.CFG, zeitlimit_s=2), greifer_zu=1400)
        pose = [2000] * 5 + [1400]
        t = 0
        while a.update(t, pose, True, True) != "start":
            t += 0.1
        r = None
        while r is None and t < 10:
            t += 0.1
            r = a.update(t, pose[:5] + [2400], True, True)
        self.assertEqual(r, "zeitlimit")


class MaskTests(unittest.TestCase):
    def test_synthetic_box_edges(self):
        import cv2
        img = np.full((720, 1280, 3), 230, np.uint8)
        cv2.rectangle(img, (250, 45), (1050, 515), (90, 130, 170), -1)       # Karton: Hinterkante y~0.06, Vorderkante y~0.72
        r = M.detect(img)
        self.assertTrue(r["ok_b"], r["werte"])
        self.assertTrue(r["ok_a"], r["werte"])
        out = M.draw(img, r)
        self.assertEqual(out.shape, img.shape)
        self.assertTrue((img == 230).any())                                   # Original unveraendert
        self.assertFalse(M.detect(np.full((720, 1280, 3), 200, np.uint8))["ok"])


if __name__ == "__main__":
    unittest.main()


class Plan2Test(unittest.TestCase):
    def test_folgeplan_neue_positionen_licht_und_305(self):
        import tempfile, math
        with tempfile.TemporaryDirectory() as t:
            run = P.create(P.load_definition("kartongriffe2"), root=t)
            used, old_tests = P.used_placements(run.defn, root=t)
        rs = run.rounds
        parts = [o["teil"] for r in rs for o in r["auftraege"]]
        self.assertEqual(len(parts), 305)
        self.assertEqual({p: parts.count(p) for p in "DPV"}, {"D": 102, "P": 102, "V": 101})
        self.assertTrue(all(v <= 2 for r in rs for v in run.defn["ladungen"][r["ladung"]].values()))
        for r in rs:                                          # wirklich neue Kartonpositionen
            p = r["platzierung"]
            d = min(math.hypot(p["x"] - u["x"], p["y"] - u["y"]) + 0.15 * min(abs(p["winkel"] - u["winkel"]) % 180,
                    180 - abs(p["winkel"] - u["winkel"]) % 180) for u in used)
            self.assertGreaterEqual(d, 4.0 - 1e-6, r["runde"])
        licht = [r["licht"] for r in rs]
        self.assertEqual(licht.count("decke"), 26)
        self.assertEqual(licht.count("decke_tisch"), 26)
        self.assertEqual(P.light_phase(run.defn, 27)["id"], "decke_tisch")
        self.assertEqual([x["id"] for x in run.data["tests"]], [x["id"] for x in old_tests])   # gleiche Tests
        self.assertTrue({"K", "H"} <= {r["anordnung"] for r in rs})
        alt = P.load_definition("kartongriffe")                # mischbar: gleiche Bauteile/Befehle/Kameras
        self.assertEqual(alt["bauteile"], run.defn["bauteile"])
        self.assertEqual(alt["kameras"], run.defn["kameras"])
        self.assertNotEqual(alt["datensatz"], run.defn["datensatz"])


class AuswahlTest(unittest.TestCase):
    def test_kameras_split_und_befehle(self):
        import tempfile, json, os
        from ki import episodes, auswahl
        root = tempfile.mkdtemp()
        ds = episodes.open_dataset("t", "x", "follower", ["wrist", "overview"], root=root, variabel=True,
                                   extra_meta={"plan": "p"})
        def ep(n, **info):
            d = os.path.join(ds.path, f"ep_{n:04d}")
            os.makedirs(d)
            json.dump(info, open(os.path.join(d, "info.json"), "w"))
        ep(0, kameras=["wrist"], platzierung_id="P01", befehlsart="allgemein", frames=10)
        ep(1, kameras=["wrist", "overview"], platzierung_id="P02", befehlsart="spezifisch", frames=10)
        ep(2, kameras=["wrist"], platzierung_id="T1", befehlsart="allgemein", frames=10)
        self.assertEqual(auswahl.select(ds, ["wrist"])[0], ["ep_0000", "ep_0001"])
        self.assertEqual(auswahl.select(ds, ["wrist", "overview"])[0], ["ep_0001"])
        self.assertEqual(auswahl.select(ds, ["wrist"], {"befehle": "allgemein"})[0], ["ep_0000"])
        self.assertEqual(auswahl.select(ds, ["wrist"], {"split": "test"})[0], ["ep_0002"])
        self.assertEqual(auswahl.slot_map(ds), {"wrist": "arm", "overview": "turm"})
