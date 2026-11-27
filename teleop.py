"""Teleoperation: Follower folgt dem Leader.
  python teleop.py [sekunden]      Standard 60 s; Strg+C beendet vorzeitig (Arm legt sich dann ab)
  python teleop.py --dry-run       nur lesen und Zielwerte anzeigen, nichts bewegen
Vor dem Start den Leader ungefaehr in die Mittelstellung halten."""
import sys
from so101 import *
args = [x for x in sys.argv[1:] if not x.startswith("--")]
DRY = "--dry-run" in sys.argv
DUR = float(args[0]) if args else 60
F = Arm("follower"); L = Arm("leader"); F.limits(); L.limits()

def mapped(s, lp):
    if s == 6:      # Griffweg des Leaders auf den Greiferweg des Followers umrechnen
        (a, b), (c, d) = L.lim[6], F.lim[6]
        lp = c + (lp - a) * (d - c) / (b - a)
    lo, hi = F.lim[s]
    return int(max(lo + 8, min(hi - 8, lp)))

if DRY:
    lp = L.positions(); print("Leader  :", lp); print("Follower:", F.positions())
    print("Ziele   :", {s: mapped(s, lp[s]) for s in JOINTS}); F.close(); L.close(); sys.exit()

start, moved = None, []
try:
    start = F.positions()
    raise_to_mid(F, start=start, moved=moved)
    print(">>> Follower ist oben. Angleichen an den Leader (4 s) ...", flush=True)
    t0 = time.time(); n = 0; fast = False; vmin = 99; maxerr = 0; lastp = t0; tgt = {}
    while time.time() - t0 < DUR + 4:
        tc = time.time(); sync = tc - t0 < 4
        speed = 150 if sync else 0                     # 0 = keine Geschwindigkeitsbegrenzung
        for s in JOINTS:
            lp = L.rd(s, POS, 2, tries=2)
            if lp is None:
                continue
            tgt[s] = mapped(s, lp)
            F.bus.write(s, GOAL, tgt[s].to_bytes(2, "little") + b"\0\0" + speed.to_bytes(2, "little"))
        n += 1
        if n == 1:
            [F.wr(s, ACC, [25]) for s in JOINTS]
        if not sync and not fast:
            fast = True; [F.wr(s, ACC, [254]) for s in JOINTS]
            print(">>> FOLGT JETZT - Leader bewegen!", flush=True)
        if n % 50 == 0:
            vs = [v for v in (F.rd(s, VOLT, 1, tries=1) for s in JOINTS) if v]
            if vs: vmin = min(vmin, min(vs))
        if time.time() - lastp > 5:
            lastp = time.time(); cur = F.positions()
            err = max(abs(cur[s] - tgt[s]) for s in tgt if cur[s] is not None); maxerr = max(maxerr, err)
            print(f"    t={time.time() - t0 - 4:4.0f}s  {n / (time.time() - t0):.0f} Hz  Abweichung {err * 360 / 4096:.0f} Grad  "
                  f"tiefste Spannung {vmin / 10} V", flush=True)
        time.sleep(max(0, 0.01 - (time.time() - tc)))
    print(f">>> Ende ({n} Zyklen). Leader loslassen.", flush=True)
except Abort as e:
    print("ABBRUCH:", e, flush=True)
except KeyboardInterrupt:
    print(">>> Strg+C - Follower legt sich ab.", flush=True)
finally:
    if start is not None:
        print("Zur Mitte und ablegen:", flush=True)
        park(F, start, moved, via_mid=False)
        print("Freigegeben:", F.positions())
    F.close(); L.close()
