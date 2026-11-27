"""SIMULATION: Episoden mit Domain Randomization skriptgesteuert aufnehmen (eigenes Format, ki/episodes.py).

  python -m sim.episoden_aufnehmen [--n 20] [--name sim_schachtel_auf_palette] [--skill schachtel_auf_palette]

Je Episode eine neue Szene: Licht (Helligkeit, Farbstich, Schatten, Rauschen), Tisch- und Schachtelfarbe,
Schachtel- und Palettenlage, Turmkamera-Position/-Richtung zufaellig. Der Code-Skill fuehrt den Arm, die
Aufnahme tastet mit 30 Hz Simulationszeit ab: state = Ist, action = Soll, Bilder 'arm' und 'turm' (640x360).
Der Datensatz gehoert dem Arm 'sim_follower' - er laesst sich nie mit Aufnahmen eines echten Arms mischen.
Nur behalten, wenn der Skill Erfolg meldet.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402
from ki import episodes  # noqa: E402
from sim.ros_sim import szenario  # noqa: E402
from skilllib.api import RobotAPI  # noqa: E402
from skilllib.runner import execute  # noqa: E402
from skilllib.vorlagen import code  # noqa: E402

AUFGABE = "Kabel-Schachtel greifen und auf die Palette legen"


def episode(ds, seed, skill="schachtel_auf_palette", log=lambda t: None):
    ros = szenario("standard", seed, True)
    w = ros.welt
    writer = episodes.EpisodeWriter(ds, ds.meta["task"], cv2)
    takt = {"next": 0.0}
    laufen = ros.laufen

    def laufen_mit_aufnahme(sekunden):
        for _ in range(max(1, int(round(sekunden * 100)))):
            laufen(0.01)
            if w.t >= takt["next"]:
                takt["next"] = w.t + 1 / episodes.FPS
                writer.add(w.t, w.stellung(), [int(round(v)) for v in w.soll], {"arm": w.bild("arm"), "turm": w.bild("turm")})
    ros.laufen = laufen_mit_aufnahme
    robot = RobotAPI(ros, ros.arm, log=log, run_skill=lambda n, p: execute(code(n), p, robot))
    robot.pose("start")
    res = execute(code(skill), {}, robot)
    robot.pose("start")
    pfad = writer.finish(bool(res.get("erfolg")))
    return res, pfad, writer.frames


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--name", default="sim_schachtel_auf_palette")
    ap.add_argument("--skill", default="schachtel_auf_palette")
    ap.add_argument("--seed0", type=int, default=100)
    a = ap.parse_args(argv)
    ds = episodes.open_dataset(a.name, AUFGABE, "sim_follower", ["arm", "turm"],
                               calibration={"simulation": True, "backend": "kinsim"})
    ok = 0
    for i in range(a.n):
        res, pfad, n = episode(ds, a.seed0 + i, a.skill)
        ok += pfad is not None
        print(f"Episode {i + 1}/{a.n} seed {a.seed0 + i}: {'gespeichert ' + os.path.basename(pfad) if pfad else 'verworfen'} "
              f"({n} Bilder) - {res.get('grund') or res.get('fehler')}", flush=True)
    print(f"{ok}/{a.n} Episoden gespeichert in {ds.path}")


if __name__ == "__main__":
    main()
