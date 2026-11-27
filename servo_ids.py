"""IDs fuer neue Servos setzen (ab Werk haben alle ID 1 und stoeren sich am gemeinsamen Bus).
Immer nur EINEN Servo direkt am Board anstecken.

  python servo_ids.py scan <arm>          nur lesen: welche IDs antworten (alle Baudraten)
  python servo_ids.py set  <arm> <neu>    genau ein Servo am Bus -> bekommt ID <neu> (EEPROM)

<arm> = follower | follower2 | leader. Keine Bewegung: das Drehmoment bleibt aus.
Vor dem Schreiben werden die Werkswerte in calibration/<arm>_servo<neu>_factory.json gesichert."""
import json, os, sys, time
from so101 import Bus, CFG, CALDIR, JOINTS, find_port, TORQUE, LOCK, MIN_ANGLE, MAX_ANGLE, OFFSET, usm

ID_ADDR, BAUD_ADDR = 5, 6
BAUDS = (1000000, 500000, 250000, 128000, 115200, 76800, 57600, 38400)


def scan(bus, ids=range(0, 254)):
    return [s for s in ids if bus.txrx(s, 0x01, timeout=0.01) or bus.txrx(s, 0x01, timeout=0.01)]


def read(bus, s, addr, n):
    for _ in range(5):
        d = bus.read(s, addr, n)
        if d:
            return int.from_bytes(d, "little")
    return None


def set_id(bus, new, arm="arm", log=print):
    """Gibt der einzigen angeschlossenen Servo-ID <new>. Schreibt nichts, wenn nicht genau einer antwortet."""
    if not 1 <= new <= 252:
        raise SystemExit("ID muss 1-252 sein")
    found = scan(bus)
    if len(found) != 1:
        raise SystemExit(f"NICHT geschrieben: es muss genau ein Servo antworten, gefunden: {found or 'keiner'}. "
                         "Nur einen Servo direkt ans Board stecken.")
    old = found[0]
    factory = {"id": old, "min": read(bus, old, MIN_ANGLE, 2), "max": read(bus, old, MAX_ANGLE, 2),
               "offset": usm(read(bus, old, OFFSET, 2) or 0), "baud_index": read(bus, old, BAUD_ADDR, 1)}
    log(f"gefunden: ID {old}, Werte {factory}")
    if old == new:
        log(f"Hat schon ID {new}. Nichts geschrieben.")
        return factory
    os.makedirs(CALDIR, exist_ok=True)
    path = os.path.join(CALDIR, f"{arm}_servo{new}_factory.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(factory, fh, indent=1)
    ok = bus.write(old, TORQUE, [0]) and bus.write(old, LOCK, [0]) and bus.write(old, ID_ADDR, [new])
    time.sleep(0.05)
    if ok:
        bus.write(new, LOCK, [1])
    time.sleep(0.05)
    if scan(bus, (new,)) != [new]:
        raise SystemExit(f"FEHLER: Servo antwortet nach dem Schreiben nicht unter ID {new}. Werkswerte: {path}")
    log(f"OK: Servo hat jetzt ID {new} ({JOINTS.get(new, '?')}). Werkswerte gesichert in {path}")
    return factory


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("scan", "set"):
        sys.exit(__doc__)
    cmd, arm = sys.argv[1], sys.argv[2]
    if arm not in CFG:
        sys.exit(f"Unbekannter Arm: {arm}")
    port = find_port(arm)
    if cmd == "scan":
        for baud in BAUDS:
            bus = Bus(port, baud)
            print(f"{baud:>8}: {scan(bus) or '-'}", flush=True)
            bus.close()
    else:
        bus = Bus(port)
        try:
            set_id(bus, int(sys.argv[3]), arm)
        finally:
            bus.close()
