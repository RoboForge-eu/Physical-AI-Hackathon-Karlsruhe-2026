"""Follower bewegen.
  python arm.py mid    in die Mittelstellung fahren und HALTEN (Motoren bleiben an!)
  python arm.py park   zurueck in die gespeicherte Ablage und freigeben
  python arm.py demo   hochfahren, jedes Gelenk hin und her, ablegen, freigeben
  python arm.py off    sofort alle Motoren freigeben (Arm sackt ab, falls er oben ist!)"""
import sys
from so101 import *
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd not in ("mid", "park", "demo", "off"):
    sys.exit(__doc__)
a = Arm("follower"); a.limits()
pose_file = os.path.join(CALDIR, "follower_start_pose.json")
try:
    if cmd == "off":
        a.release(); print("Alle Motoren freigegeben.")
    elif cmd == "park":
        start = {int(k): v for k, v in json.load(open(pose_file)).items()}
        park(a, start, via_mid=False); print("Abgelegt und freigegeben:", a.positions())
    else:
        start, moved = None, []
        try:
            start = a.positions()
            raise_to_mid(a, start=start, moved=moved)
            print("Mittelstellung erreicht:", a.positions(), flush=True)
            if cmd == "demo":
                L = a.lim
                for s, p, sp in [(1, MID + 350, 200), (1, MID - 350, 200), (1, MID, 200),
                                 (6, L[6][1] - 60, 300), (6, L[6][0] + 60, 300), (6, MID, 300),
                                 (5, MID + 600, 300), (5, MID - 600, 300), (5, MID, 300),
                                 (4, MID + 300, 150), (4, MID - 300, 150), (4, MID, 150),
                                 (3, MID + 250, 120), (3, MID - 250, 120), (3, MID, 120),
                                 (2, MID + 200, 110), (2, MID - 200, 110), (2, MID, 110)]:
                    a.step_to(s, p, speed=sp)
        except (Abort, KeyboardInterrupt) as e:
            print("ABBRUCH:", e or "Strg+C", flush=True); cmd = "demo"     # nach Abbruch immer ablegen
        if cmd == "demo":
            if start is None:
                start = {int(k): v for k, v in json.load(open(pose_file)).items()}
            print("Ablegen:", flush=True)
            park(a, start, moved or None, via_mid=False)
            print("Freigegeben:", a.positions())
        else:
            print("Arm HAELT. Zum Ablegen:  python arm.py park")
finally:
    a.close()
