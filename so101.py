"""Gemeinsame Basis fuer den SO-101 (Feetech STS3215, Seeed Bus Servo Driver Board).
Plattformunabhaengig ueber pyserial (Windows, macOS, Linux)."""
import json, os, sys, time
import serial
from serial.tools import list_ports

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as _f:
        CFG = json.load(_f)
except FileNotFoundError:
    # z. B. in der Fernsteuerungs-App auf dem Bediener-Rechner: dort gibt es keine Arm-Zuordnung, nur den Bus
    CFG = {"baud": 1000000}
CALDIR = os.path.join(HERE, "calibration")
JOINTS = {1: "Basis", 2: "Schulter", 3: "Ellbogen", 4: "Handgelenk-Beugung", 5: "Handgelenk-Drehung", 6: "Greifer"}
MID = 2047
PARALLEL_ROLL_GRIP = True   # Hochfahren: Drehung und Greifer gleichzeitig (aendern die Hoehe nicht)
ARRIVE_SETTLE_S = 0.25   # so lange still knapp vor dem Ziel = angekommen
LOW_CONFIRM = 3     # Messungen unter 4,0 V in Folge, bevor step_to abbricht
# Register (STS3215)
MIN_ANGLE, MAX_ANGLE, OFFSET, TORQUE, ACC, GOAL, LOCK = 9, 11, 31, 40, 41, 42, 55
POS, LOAD, VOLT, TEMP, STATUS = 56, 60, 62, 63, 65


def find_port(arm):
    c = CFG[arm]
    if c.get("port"):
        return c["port"]
    want = c["usb_serial"].upper()
    for p in list_ports.comports():
        sn = (p.serial_number or "").upper()
        if sn and (sn.startswith(want) or want.startswith(sn)):
            return p.device
    found = ", ".join(f"{p.device} (SN {p.serial_number})" for p in list_ports.comports()) or "keine"
    sys.exit(f"Board fuer '{arm}' (USB-Seriennr. {want}) nicht gefunden. Vorhandene Ports: {found}. "
             f"Notfalls den Port fest in config.json eintragen.")


class Bus:
    def __init__(self, port, baud=None):
        self.ser = serial.Serial(port, baud or CFG["baud"], timeout=0.002, write_timeout=0.5)
        time.sleep(0.05)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def txrx(self, sid, instr, params=b"", timeout=0.03):
        body = bytes([sid, len(params) + 2, instr]) + bytes(params)
        pkt = b"\xff\xff" + body + bytes([(~sum(body)) & 0xFF])
        self.ser.reset_input_buffer()
        self.ser.write(pkt)
        raw = b""
        end = time.time() + timeout
        while time.time() < end:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if not chunk:
                continue
            raw += chunk
            r = raw[len(pkt):] if raw.startswith(pkt) else raw      # evtl. Echo entfernen
            i = r.find(b"\xff\xff")
            if i >= 0 and len(r) >= i + 4 and len(r) >= i + 4 + r[i + 3]:
                ln = r[i + 3]
                if (~sum(r[i + 2:i + 3 + ln])) & 0xFF != r[i + 3 + ln]:
                    return None
                return r[i + 2], r[i + 4], r[i + 5:i + 3 + ln]
        return None

    def ping(self, sid):
        return self.txrx(sid, 0x01)

    def read(self, sid, addr, n):
        r = self.txrx(sid, 0x02, bytes([addr, n]))
        return r[2] if r and len(r[2]) == n else None

    def write(self, sid, addr, data):
        return self.txrx(sid, 0x03, bytes([addr]) + bytes(data))


class Abort(Exception):
    pass


def sm(v):   # Vorzeichen-Betrag (Bit 11) fuer das Offset-Register
    return (abs(v) | 0x800) if v < 0 else v


def usm(v):
    return -(v & 0x7FF) if v & 0x800 else v


class Arm:
    def __init__(self, name):
        self.name = name
        self.port = find_port(name)
        self.bus = Bus(self.port)
        self.lim = {}

    def close(self):
        self.bus.close()

    def rd(self, s, addr, n, tries=5):
        for _ in range(tries):
            d = self.bus.read(s, addr, n)
            if d:
                return int.from_bytes(d, "little")
        return None

    def wr(self, s, addr, data, tries=5):
        for _ in range(tries):
            if self.bus.write(s, addr, data):
                return True
        return False

    def wr16(self, s, addr, val):
        return self.wr(s, addr, int(val).to_bytes(2, "little"))

    def ids(self):
        return [s for s in range(1, 13) if self.bus.ping(s) or self.bus.ping(s)]

    def limits(self):
        self.lim = {s: (self.rd(s, MIN_ANGLE, 2), self.rd(s, MAX_ANGLE, 2)) for s in JOINTS}
        return self.lim

    def positions(self):
        return {s: self.rd(s, POS, 2) for s in JOINTS}

    def clamp(self, s, pos):
        lo, hi = self.lim[s]
        return int(max(lo, min(hi, pos)))

    def goal(self, s, pos, speed=0, acc=4):
        self.wr(s, ACC, [acc])
        self.wr(s, GOAL, int(pos).to_bytes(2, "little") + b"\0\0" + int(speed).to_bytes(2, "little"))

    def hold(self, s, delay=0.3):
        p = self.rd(s, POS, 2)
        if p is None:
            raise Abort(f"{JOINTS[s]} antwortet nicht")
        self.goal(s, self.clamp(s, p), 60)
        time.sleep(delay)

    def release(self):
        for s in JOINTS:
            self.wr(s, TORQUE, [0])

    def eeprom(self, s, items):
        """items: [(adresse, 16-bit-wert), ...] - schaltet Drehmoment aus, entsperrt, schreibt, sperrt."""
        ok = self.wr(s, TORQUE, [0]) and self.wr(s, LOCK, [0])
        for addr, val in items:
            ok = ok and self.wr16(s, addr, val)
        ok = self.wr(s, LOCK, [1]) and ok
        time.sleep(0.05)
        if not ok:
            raise RuntimeError(f"EEPROM-Schreiben auf ID {s} fehlgeschlagen")

    def step_to(self, s, target, speed=110, tol=18, quiet=False, acc=4, poll_interval=0.15):
        """Faehrt ein Gelenk langsam zum Ziel und ueberwacht es.
        Bricht ab bei Stillstand weit vor dem Ziel (Hindernis), anhaltender Unterspannung oder Funkstille.
        Ein Rest bis ca. 6 Grad unter Last ist normal (Regler ohne I-Anteil) und gilt als erreicht."""
        target = self.clamp(s, target)
        cur = self.rd(s, POS, 2)
        if cur is None:
            raise Abort(f"{JOINTS[s]} antwortet nicht")
        self.goal(s, target, speed, acc=acc)
        t = time.monotonic(); last = cur; lost = 0; low_count = 0
        stuck_since = low_since = None
        while True:
            time.sleep(poll_interval)
            if getattr(self, "stop_requested", lambda: False)():
                p = self.rd(s, POS, 2)
                if p is None:
                    raise Abort(f"{JOINTS[s]} antwortet nicht")
                self.goal(s, p, 60)
                raise Abort("Stop angefordert")
            p = self.rd(s, POS, 2); v = self.rd(s, VOLT, 1)
            if p is None or v is None:
                lost += 1
                if lost >= 3:
                    raise Abort(f"{JOINTS[s]} antwortet nicht mehr")
                continue
            lost = 0
            now = time.monotonic()
            low_since = (now if low_since is None else low_since) if v < 43 else None
            lowv = low_since is not None and now - low_since >= 0.6
            # Einzelne Messwerte unter 4,0 V kommen an Servo 5/6 auch in Ruhe vor (Spannungsmessung
            # 15.11.: ~0,3 % der Werte, alle drei Arme). Abbruch erst bei 3 Messungen in Folge,
            # wie im laufenden Betrieb (CheckedArm.check_voltage). Vom Nutzer so freigegeben.
            if v < 40:
                low_count += 1
                if low_count >= LOW_CONFIRM:
                    self.goal(s, p, 60)
                    raise Abort(f"{JOINTS[s]}: Spannung {v / 10} V unter Untergrenze ({low_count} Messungen in Folge)")
            else:
                low_count = 0
            if abs(p - target) <= tol and not lowv:
                break
            # Compare against an anchor: slow progress accumulates even when
            # polling faster. Timeouts are seconds, independent of polling rate.
            if abs(p - last) >= 4:
                last = p
                stuck_since = None
            elif stuck_since is None:
                stuck_since = now
            # Knapp vor dem Ziel stehengeblieben (Regler-Rest unter Last, ~6 Grad): nach kurzer Ruhe angekommen.
            # Vorher wurden hier jedes Mal 1,5 s gewartet (Log 16.11. 20:55: Hochfahren 13,7 s).
            if (not lowv and stuck_since is not None and abs(p - target) <= 70
                    and now - stuck_since >= ARRIVE_SETTLE_S):
                break
            stuck = stuck_since is not None and now - stuck_since >= 1.5
            if lowv or stuck or now - t > 40:
                if not lowv and abs(p - target) <= 70:
                    break
                self.goal(s, p, 60)      # nicht weiter druecken
                raise Abort(f"{JOINTS[s]} kommt bei {p} nicht weiter (Ziel {target}, "
                            f"Last {(self.rd(s, LOAD, 2) or 0) & 1023}, {v / 10} V)")
        if not quiet:
            print(f"  {JOINTS[s]:20s} -> {target} (ist {p}, {v / 10} V)", flush=True)
        return p

    def step_many(self, targets, speed=110, tol=18, acc=4, poll_interval=0.15, quiet=False):
        """Mehrere Gelenke GLEICHZEITIG, Tempo je Gelenk nach Weg verteilt (kommen etwa zusammen an,
        der Weg ist dann ungefaehr eine Gerade im Gelenkraum - so prueft ihn das Hoehenmodell).
        Gleiche Ueberwachung wie step_to je Gelenk: Stop, Funkstille, Unterspannung, Stillstand.
        Bei jedem Abbruch halten ALLE beteiligten Gelenke an ihrer Stelle."""
        targets = {j: self.clamp(j, t) for j, t in targets.items()}
        cur = {j: self.rd(j, POS, 2) for j in targets}
        if any(v is None for v in cur.values()):
            raise Abort("Gelenk antwortet nicht")
        far = max(1, max(abs(targets[j] - cur[j]) for j in targets))
        for j in targets:
            self.goal(j, targets[j], max(40, int(speed * abs(targets[j] - cur[j]) / far)), acc=acc)
        state = {j: {"last": cur[j], "stuck": None, "lost": 0, "low": 0, "low_since": None, "done": False,
                     "p": cur[j], "v": None} for j in targets}
        t = time.monotonic()

        def hold_all(reason):
            for j in targets:
                p = self.rd(j, POS, 2)
                if p is not None:
                    self.goal(j, p, 60)
            raise Abort(reason)

        while not all(st["done"] for st in state.values()):
            time.sleep(poll_interval)
            if getattr(self, "stop_requested", lambda: False)():
                hold_all("Stop angefordert")
            now = time.monotonic()
            for j, st in state.items():
                if st["done"]:
                    continue
                p = self.rd(j, POS, 2); v = self.rd(j, VOLT, 1)
                if p is None or v is None:
                    st["lost"] += 1
                    if st["lost"] >= 3:
                        hold_all(f"{JOINTS[j]} antwortet nicht mehr")
                    continue
                st["lost"], st["p"], st["v"] = 0, p, v
                st["low_since"] = (now if st["low_since"] is None else st["low_since"]) if v < 43 else None
                lowv = st["low_since"] is not None and now - st["low_since"] >= 0.6
                if v < 40:
                    st["low"] += 1
                    if st["low"] >= LOW_CONFIRM:
                        hold_all(f"{JOINTS[j]}: Spannung {v / 10} V unter Untergrenze ({st['low']} Messungen in Folge)")
                else:
                    st["low"] = 0
                if abs(p - targets[j]) <= tol and not lowv:
                    st["done"] = True
                    continue
                if abs(p - st["last"]) >= 4:
                    st["last"], st["stuck"] = p, None
                elif st["stuck"] is None:
                    st["stuck"] = now
                if (not lowv and st["stuck"] is not None and abs(p - targets[j]) <= 70
                        and now - st["stuck"] >= ARRIVE_SETTLE_S):
                    st["done"] = True
                    continue
                stuck = st["stuck"] is not None and now - st["stuck"] >= 1.5
                if lowv or stuck or now - t > 40:
                    if not lowv and abs(p - targets[j]) <= 70:
                        st["done"] = True
                        continue
                    hold_all(f"{JOINTS[j]} kommt bei {p} nicht weiter (Ziel {targets[j]}, "
                             f"Last {(self.rd(j, LOAD, 2) or 0) & 1023}, {v / 10} V)")
        if not quiet:
            print("  gemeinsam: " + ", ".join(f"{JOINTS[j]} -> {targets[j]} (ist {st['p']})" for j, st in state.items()),
                  flush=True)
        return {j: st["p"] for j, st in state.items()}


# Reihenfolge, in der die Gelenke aus der Ablage in die Mittelstellung fahren (Schulter zuerst!).
ORDER = [2, 3, 4, 1, 5, 6]

# --- Hoehenmodell (Seitenansicht) fuer kollisionsarme Wege aus beliebiger Pose ---
# Naeherungswerte SO-101 in Metern. Winkel von der Senkrechten, Mittelstellung 2047:
# Oberarm senkrecht, Unterarm rechtwinklig dazu, Handgelenk gerade. Geprueft an
# Logdaten: Ablage (835/3097/902) liegt gefaltet, und die Ablage vom 13.11. 12:38
# (Schulter 2701, Ellbogen 3097, Handgelenk 904) ergibt Spitze ~2 cm ueber dem
# Tisch - genau dort hat der Arm auf den Tisch gedrueckt.
import math
SHOULDER_H, UPPER, FORE, HAND = 0.10, 0.116, 0.135, 0.10
PITCH = (2, 3, 4)


def _ang(p):
    return (p - MID) * 2 * math.pi / 4096


def heights(pos):
    """Hoehe ueber dem Tisch von Ellbogen, Handgelenk und Greiferspitze (Meter).
    Spiegelung vorn/hinten aendert die Hoehe nicht; die Basisdrehung ebenso nicht."""
    a1 = _ang(pos[2])
    a2 = a1 + math.pi / 2 + _ang(pos[3])
    a3 = a2 + _ang(pos[4])
    elbow = SHOULDER_H + UPPER * math.cos(a1)
    wrist = elbow + FORE * math.cos(a2)
    tip = wrist + HAND * math.cos(a3)
    return elbow, wrist, tip


def path_clearance(start, order, target=None, samples=40):
    """Niedrigste Hoehe eines Gelenkpunkts, wenn die Nickgelenke einzeln in
    'order' von start zum Ziel (Standard: Mittelstellung) fahren."""
    target = target or {s: MID for s in PITCH}
    pos = {s: start[s] for s in PITCH}
    low = min(heights(pos))
    for s in order:
        a, b = pos[s], target[s]
        for i in range(1, samples + 1):
            pos[s] = a + (b - a) * i / samples
            low = min(low, min(heights(pos)))
    return low


def plan_mid_order(start):
    """Waehlt die Reihenfolge von Schulter/Ellbogen/Handgelenk, bei der kein
    Gelenkpunkt tiefer kommt als noetig (hoechste Mindesthoehe auf dem Weg).
    Bei Gleichstand gilt die bewaehrte Reihenfolge Schulter, Ellbogen, Handgelenk.
    Basis, Drehung und Greifer folgen danach (veraendern die Hoehe nicht)."""
    import itertools
    standard = path_clearance(start, PITCH)
    best = (standard, list(PITCH))
    for perm in itertools.permutations(PITCH):
        score = path_clearance(start, perm)
        # Abweichen von der bewaehrten Reihenfolge nur bei deutlichem Gewinn (2 cm),
        # weil das Modell Selbstkollisionen nicht kennt.
        if score > best[0] and score >= standard + PREFER_STANDARD_M:
            best = (score, list(perm))
    return best[1] + [1, 5, 6], best[0]


def plan_fold_order(target, start=None):
    """Reihenfolge, in der Schulter/Ellbogen/Handgelenk aus der Mittelstellung (oder start) in die Ablage
    einklappen, mit der hoechsten Mindesthoehe. Standard ist Handgelenk, Ellbogen, Schulter (umgekehrtes
    Hochfahren); abgewichen wird nur bei deutlichem Gewinn (2 cm). Log 17.11.: Ablage mit gestreckter Hand,
    Einklappen Handgelenk-Ellbogen-Schulter -> Modell -1,7 cm, Ellbogen fuhr in den Tisch."""
    import itertools
    start = start or {s: MID for s in PITCH}
    standard_order = [4, 3, 2]
    standard = path_clearance(start, standard_order, target)
    best = (standard, standard_order)
    for perm in itertools.permutations(PITCH):
        score = path_clearance(start, perm, target)
        if score > best[0] and (score >= standard + PREFER_STANDARD_M or standard < MIN_CLEARANCE_M):
            best = (score, list(perm))
    return best[1], best[0]


PREFER_STANDARD_M = 0.02
# Kein Start, wenn selbst der beste Weg einen Gelenkpunkt naeher als 1 cm an den Tisch fuehrt.
MIN_CLEARANCE_M = 0.01


# Schulter, Ellbogen und Handgelenk-Beugung gleichzeitig fahren, wenn das Hoehenmodell den gemeinsamen Weg
# mindestens so hoch bewertet wie den besten einzelnen (vom Nutzer gewuenscht, 17.11.: Aufwachen/Ablegen zu lang).
PARALLEL_PITCH = True


def straight_clearance(start, target, samples=60):
    """Tiefster Gelenkpunkt, wenn die Nickgelenke gleichzeitig auf einer Geraden von start nach target fahren."""
    return min(min(heights({s: start[s] + (target[s] - start[s]) * i / samples for s in PITCH}))
               for i in range(samples + 1))


def together_ok(start, target, sequential_clearance):
    if not PARALLEL_PITCH:
        return False, None
    c = straight_clearance(start, target)
    return c >= MIN_CLEARANCE_M and c >= sequential_clearance - 0.005, c


def raise_to_mid(arm, start=None, moved=None, speed=110, acc=4, poll_interval=0.15, hold_delay=0.3, order=None):
    """Aus der Ablage kollisionsarm in die Mittelstellung. Gibt (start, bewegte_gelenke) zurueck.
    order: Reihenfolge der Gelenke (Standard ORDER, aus der Ablage bewaehrt)."""
    order = ORDER if order is None else order
    arm.limits()
    start = arm.positions() if start is None else start
    if any(start.get(s) is None for s in JOINTS):
        raise Abort("Ablage konnte nicht vollstaendig gelesen werden")
    json.dump(start, open(os.path.join(CALDIR, f"{arm.name}_start_pose.json"), "w"))
    moved = [] if moved is None else moved
    for s in (3, 4, 2):
        if getattr(arm, "stop_requested", lambda: False)():
            raise Abort("Stop angefordert")
        if s not in moved:
            moved.append(s)
            moved.sort(key=ORDER.index)
        arm.hold(s, delay=hold_delay)
    mid = {s: MID for s in PITCH}
    ok, c = together_ok(start, mid, path_clearance(start, [s for s in order if s in PITCH]))
    if ok and all(s in order for s in PITCH):
        print(f"  Schulter, Ellbogen, Handgelenk gemeinsam (tiefster Punkt {c * 100:.1f} cm)", flush=True)
        arm.step_many(mid, speed=speed, acc=acc, poll_interval=poll_interval)
        order = [s for s in order if s not in PITCH]
    for s in order:
        if getattr(arm, "stop_requested", lambda: False)():
            raise Abort("Stop angefordert")
        if s not in moved:
            moved.append(s)
            moved.sort(key=ORDER.index)
        if s == 6 and PARALLEL_ROLL_GRIP and 5 in order:
            continue                     # Greifer ist schon zusammen mit der Drehung gefahren
        if s not in (2, 3, 4):
            arm.hold(s, delay=hold_delay)
        if s == 5 and PARALLEL_ROLL_GRIP and 6 in order:
            # Drehung und Greifer veraendern die Hoehe nicht: gleichzeitig fahren (vom Nutzer so freigegeben,
            # 16.11.). Der Greifer startet zuerst, dann wird die Drehung ueberwacht, danach der Greifer.
            if 6 not in moved:
                moved.append(6)
                moved.sort(key=ORDER.index)
            arm.hold(6, delay=hold_delay)
            arm.goal(6, arm.clamp(6, MID), speed, acc=acc)
            arm.step_to(5, MID, speed=speed, acc=acc, poll_interval=poll_interval)
            arm.step_to(6, MID, speed=speed, acc=acc, poll_interval=poll_interval)
            continue
        arm.step_to(s, MID, speed=speed, acc=acc, poll_interval=poll_interval)
    return start, moved


def park(arm, start, moved=None, via_mid=True, speed=110, acc=4, poll_interval=0.15, mid_order=None):
    """Zurueck in die Ablage (umgekehrte Reihenfolge) und freigeben.
    mid_order: Reihenfolge fuer den Weg in die Mittelstellung (z. B. aus plan_mid_order)."""
    moved = ORDER if moved is None else moved
    mid_order = ORDER if mid_order is None else mid_order
    # Einklappen: erst Greifer/Drehung/Basis (aendern die Hoehe nicht), dann die Nickgelenke in der
    # Reihenfolge mit dem meisten Abstand zum Tisch (Hoehenmodell), nicht stur umgekehrt.
    fold, fold_clear = plan_fold_order(start) if via_mid else (None, None)
    fold_seq = ([s for s in reversed(moved) if s not in PITCH] + fold) if fold else list(reversed(moved))
    seqs = ([(mid_order, None)] if via_mid else []) + [(fold_seq, start)]
    together, c = (together_ok({s: MID for s in PITCH}, start, fold_clear) if via_mid else (False, None))
    for seq, tgt in seqs:
        pitch_done = False
        for s in seq:
            if s not in moved:
                continue
            if tgt is not None and together and s in PITCH and all(j in moved for j in PITCH):
                if not pitch_done:
                    print(f"  Einklappen gemeinsam (tiefster Punkt {c * 100:.1f} cm)", flush=True)
                    arm.step_many({j: start[j] for j in PITCH}, speed=speed, acc=acc, poll_interval=poll_interval)
                    pitch_done = True
                continue
            arm.step_to(s, MID if tgt is None else tgt[s], speed=speed, acc=acc, poll_interval=poll_interval)
    time.sleep(0.4)
    arm.release()
