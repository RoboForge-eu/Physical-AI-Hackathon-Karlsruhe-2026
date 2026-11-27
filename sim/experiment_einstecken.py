"""Experiment: Stift ueber der Oeffnung ausrichten und einstecken - N zufaellige Startlagen in der Simulation.

  python -m sim.experiment_einstecken [--n 20] [--spiel-mm 0.5] [--ohne-ausrichten]

Je Versuch: neue Szene mit Domain Randomization (Licht, Schatten, Farben, Lochlage +-2 mm), die Pose
'ueber_oeffnung' liegt zufaellig bis +-4 mm daneben (wie ein VLA, das das Teil nur grob hinbringt).
Dann laeuft der Code-Skill stift_einstecken (ausrichten -> Spiralsuche -> Zugtest) unveraendert.
Ergebnis: Erfolgsquote, Berichte, Messbilder (ki_daten/messbilder).
"""
import argparse, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.ros_sim import szenario  # noqa: E402
from skilllib.api import RobotAPI  # noqa: E402
from skilllib.runner import execute  # noqa: E402
from skilllib.vorlagen import code  # noqa: E402


def versuch(seed, spiel_mm=0.5, ausrichten=True, log=lambda t: None):
    ros = szenario("einstecken", seed, True, spiel_mm)
    w = ros.welt
    h = w.szene.halter
    def nested(name, params):
        if name == "visuelles_ausrichten" and not ausrichten:
            return {"erfolg": True, "bericht": "(ohne Ausrichten)"}
        return execute(code(name), params, robot)
    robot = RobotAPI(ros, "sim_follower", log=log, run_skill=nested)
    res = execute(code("stift_einstecken"), {}, robot)
    x, y, z, _ = w.spitze()
    L = w.szene.loch
    res["wirklich_drin"] = bool(math.hypot(x - L["x"], y - L["y"]) <= L["r"] and z < h["h"] - 0.005)
    res["startversatz_mm"] = ros.startversatz_mm
    res["sim_zeit_s"] = round(w.t, 1)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--spiel-mm", type=float, default=0.5)
    ap.add_argument("--ohne-ausrichten", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    ergebnisse = [versuch(s, a.spiel_mm, not a.ohne_ausrichten) for s in range(a.n)]
    ok = sum(1 for e in ergebnisse if e["erfolg"])
    echt = sum(1 for e in ergebnisse if e["wirklich_drin"])
    falsch_pos = sum(1 for e in ergebnisse if e["erfolg"] and not e["wirklich_drin"])
    for i, e in enumerate(ergebnisse):
        print(f"{i:2d} {'OK ' if e['erfolg'] else 'NEIN'} drin={e['wirklich_drin']} start={e['startversatz_mm']} "
              f"{e['grund']} | {e.get('bericht', '')[:200]}")
    zus = {"versuche": a.n, "spiel_mm": a.spiel_mm, "ausrichten": not a.ohne_ausrichten, "erfolg_gemeldet": ok,
           "wirklich_drin": echt, "falsch_positiv": falsch_pos}
    print(json.dumps(zus, ensure_ascii=False))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"zusammenfassung": zus, "versuche": ergebnisse}, f, ensure_ascii=False, indent=1, default=str)
    return zus


if __name__ == "__main__":
    main()
