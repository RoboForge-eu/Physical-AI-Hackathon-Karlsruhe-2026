"""Zustand eines Arms anzeigen (nur Lesen).   python status.py [follower|leader]"""
import sys
from so101 import *
name = sys.argv[1] if len(sys.argv) > 1 else "follower"
a = Arm(name); ids = a.ids()
print(f"{name}: Port {a.port}, gefundene IDs {ids}")
print(f"{'ID':>3} {'Gelenk':20s} {'Min':>5} {'Max':>5} {'Offset':>6} {'Pos':>5} {'Volt':>5} {'Temp':>4} {'Torque':>6} {'Status':>6}")
for s in ids:
    v = a.rd(s, VOLT, 1)
    print(f"{s:>3} {JOINTS.get(s, '?'):20s} {a.rd(s, MIN_ANGLE, 2):>5} {a.rd(s, MAX_ANGLE, 2):>5} {usm(a.rd(s, OFFSET, 2)):>6} "
          f"{a.rd(s, POS, 2):>5} {v / 10 if v else '?':>5} {a.rd(s, TEMP, 1):>4} {a.rd(s, TORQUE, 1):>6} {a.rd(s, STATUS, 1):>6}")
a.close()
