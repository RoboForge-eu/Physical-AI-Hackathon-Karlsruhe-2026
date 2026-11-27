"""Kalibrierung (Werte liegen im EEPROM der Servos, nicht auf dem Rechner).
  python calib.py dump    <arm>          aktuelle Werte in calibration/<arm>_calibration.json sichern
  python calib.py restore <arm> [datei]  gesicherte Werte zurueckschreiben
  python calib.py mid     <arm>          aktuelle Stellung aller Gelenke wird Nullpunkt 2047 (Grenzen vorerst offen)
  python calib.py range   <arm> [sek]    Bewegungsbereiche aufzeichnen (Gelenke von Hand an beide Anschlaege)
  python calib.py apply   <arm>          aufgezeichnete Bereiche als Grenzen speichern
  python calib.py rezero  <arm> <id>     Nullpunkt EINES Gelenks auf die aktuelle Stellung, Grenzen wandern mit
<arm> = follower | leader.  Bei mid/range/apply/rezero sind die Motoren drehmomentfrei."""
import sys
from so101 import *
if len(sys.argv) < 3 or sys.argv[1] not in ("dump", "restore", "mid", "range", "apply", "rezero"):
    sys.exit(__doc__)
cmd, name = sys.argv[1], sys.argv[2]
a = Arm(name)
calfile = os.path.join(CALDIR, f"{name}_calibration.json")
rangefile = os.path.join(CALDIR, f"{name}_range.json")
def need(v, what):
    if v is None: raise RuntimeError(f"Keine Antwort beim Lesen von {what}")
    return v
if cmd == "dump":
    cal = {s: {"name": JOINTS[s], "min": need(a.rd(s, MIN_ANGLE, 2), "min"), "max": a.rd(s, MAX_ANGLE, 2),
               "offset": usm(a.rd(s, OFFSET, 2))} for s in JOINTS}
    json.dump(cal, open(calfile, "w"), indent=1); print(json.dumps(cal, indent=1)); print("gesichert in", calfile)
elif cmd == "restore":
    cal = json.load(open(sys.argv[3] if len(sys.argv) > 3 else calfile))
    for k, c in cal.items():
        s = int(k); a.eeprom(s, [(OFFSET, sm(c["offset"])), (MIN_ANGLE, c["min"]), (MAX_ANGLE, c["max"])])
        print(f"{JOINTS[s]:20s} Grenzen {a.rd(s, MIN_ANGLE, 2)}-{a.rd(s, MAX_ANGLE, 2)}  Offset {usm(a.rd(s, OFFSET, 2))}")
elif cmd == "mid":
    for s in JOINTS:
        a.eeprom(s, [(OFFSET, 0), (MIN_ANGLE, 0), (MAX_ANGLE, 4095)])
        raw = need(a.rd(s, POS, 2), "Position"); off = max(-2047, min(2047, raw - MID))
        a.eeprom(s, [(OFFSET, sm(off))])
        print(f"{JOINTS[s]:20s} roh {raw:5d}  Offset {off:6d}  -> liest jetzt {a.rd(s, POS, 2)}")
elif cmd == "range":
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 90
    lo = {s: 9999 for s in JOINTS}; hi = {s: -1 for s in JOINTS}; t = time.time()
    print(f"Aufzeichnung laeuft {dur:.0f} s - jedes Gelenk an beide Anschlaege bewegen ...", flush=True)
    while time.time() - t < dur:
        for s in JOINTS:
            p = a.rd(s, POS, 2)
            if p is not None: lo[s] = min(lo[s], p); hi[s] = max(hi[s], p)
    json.dump({"lo": lo, "hi": hi}, open(rangefile, "w"))
    for s in JOINTS: print(f"{JOINTS[s]:20s} min {lo[s]:5d}  max {hi[s]:5d}  Spanne {(hi[s] - lo[s]) * 360 / 4096:5.0f} Grad")
    print("Gelenke mit Spanne nahe 0 wurden nicht bewegt - dann range wiederholen, bevor apply.")
elif cmd == "apply":
    r = json.load(open(rangefile))
    for s in JOINTS:
        lo, hi = (0, 4095) if s == 5 else (r["lo"][str(s)], r["hi"][str(s)])     # Handgelenk-Drehung: voller Bereich
        if hi - lo < 200: print(f"{JOINTS[s]:20s} UEBERSPRUNGEN (Spanne zu klein)"); continue
        a.eeprom(s, [(MIN_ANGLE, lo), (MAX_ANGLE, hi)])
        print(f"{JOINTS[s]:20s} Grenzen {a.rd(s, MIN_ANGLE, 2)}-{a.rd(s, MAX_ANGLE, 2)}  Offset {usm(a.rd(s, OFFSET, 2))}")
elif cmd == "rezero":
    s = int(sys.argv[3])
    p, off, lo, hi = need(a.rd(s, POS, 2), "Position"), usm(a.rd(s, OFFSET, 2)), a.rd(s, MIN_ANGLE, 2), a.rd(s, MAX_ANGLE, 2)
    d = p - MID; noff, nlo, nhi = off + d, lo - d, hi - d
    print(f"vorher : Pos {p} Offset {off} Grenzen {lo}-{hi}; Verschiebung {d} ({d * 360 / 4096:.1f} Grad)")
    if not (abs(noff) <= 2047 and 0 <= nlo < nhi <= 4095):
        sys.exit(f"NICHT geschrieben: neue Werte ausserhalb des Bereichs ({noff}, {nlo}, {nhi})")
    a.eeprom(s, [(OFFSET, sm(noff)), (MIN_ANGLE, nlo), (MAX_ANGLE, nhi)])
    print(f"nachher: Pos {a.rd(s, POS, 2)} Offset {usm(a.rd(s, OFFSET, 2))} Grenzen {a.rd(s, MIN_ANGLE, 2)}-{a.rd(s, MAX_ANGLE, 2)}")
a.close()
