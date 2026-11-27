"""Hardware worker for the local test window. Never starts motion without --move."""
import os
import sys
import threading
import time
from collections import deque
from so101 import Arm, Abort, JOINTS, POS, VOLT, STATUS, ACC, GOAL, find_port, raise_to_mid, park, plan_mid_order, plan_fold_order, MIN_CLEARANCE_M
from fast_bus import FastBus
import stopcal
import arbeitsbereich

# Acceleration limit while following. Was 40 for the old 5 V / 3 A supply;
# raised for the 5 V / 20 A supply to reduce follow lag. RAM register only. Max 254.
FOLLOW_ACC = 150
# Consecutive sub-4.0 V readings of one servo required before aborting.
LOW_VOLTAGE_CONFIRM = 3
LOW_VOLTAGE_CONFIRM_S = 0.06
# Gripper: RAM torque limit (0-1000) while following, and overload handling.
GRIPPER = 6
TORQUE_LIMIT = 48          # STS3215 RAM register, 2 bytes
GRIPPER_FREE_TORQUE = 1000     # free motion: full torque, fastest response
GRIPPER_TORQUE_LIMIT = 500     # while squeezing an object
GRIPPER_ACC = 0                # 0 = keine Rampe (schnellste Reaktion); 254 bremste noch sichtbar ab
GRIP_ERR = 60                  # steps the gripper lags its target while stalled
GRIP_STALL_S = 0.15            # no movement for this long = object contact
GRIP_START_S = 0.5             # never moved since the command: only then contact (start-up dead time ~0.2 s)
OVERLOAD = 0x20            # status bit 5


def update_grip(f, grip, p, target, now):
    """Detect squeezing (stalled with a large error) and only then reduce the
    gripper torque; restore full torque as soon as the leader opens again."""
    if grip["anchor"] is None or abs(p - grip["anchor"]) >= 6:
        grip["anchor"], grip["anchor_t"] = p, now
    err = target - p
    # The stall must be measured from when the large error began. Otherwise a
    # gripper that was resting looks "stalled" the moment the leader starts to
    # move, and the torque was wrongly limited at the start of every motion.
    if abs(err) > GRIP_ERR:
        grip.setdefault("err_since", now)
    else:
        grip.pop("err_since", None)
    if not grip["squeezing"]:
        # Greifen gibt es nur beim SCHLIESSEN (Log 17.11. 17:52: beim Oeffnen wurde gedrosselt). Die geschlossene
        # Seite ist das untere Ende der Greifergrenzen.
        lim = getattr(f, "lim", None)
        lo, hi = lim[GRIPPER] if isinstance(lim, dict) and GRIPPER in lim else (0, 4095)
        closing = abs(target - lo) < abs(p - lo) if lo <= hi else abs(target - hi) < abs(p - hi)
        err_since = grip.get("err_since", now)
        # Am Anfang jeder Bewegung steht der Greifer 0,1-0,2 s still, bevor er loslaeuft. Das ist KEIN Griff.
        # Griff = er hat sich in dieser Bewegung schon bewegt und steht jetzt (Teil erreicht), oder er steht
        # von Anfang an deutlich laenger still (Teil lag schon zwischen den Fingern).
        moved = grip["anchor_t"] > err_since
        contact = (moved and now - grip["anchor_t"] >= GRIP_STALL_S) or (not moved and now - err_since >= GRIP_START_S)
        if abs(err) > GRIP_ERR and closing and contact:
            grip["squeezing"] = 1 if err > 0 else -1
            f.wr(GRIPPER, TORQUE_LIMIT, GRIPPER_TORQUE_LIMIT.to_bytes(2, "little"))
            print(f"GREIFER GREIFT: Ist {p}, Ziel {target}; Kraft auf {GRIPPER_TORQUE_LIMIT}/1000 begrenzt.", flush=True)
    elif err * grip["squeezing"] < 20:
        grip["squeezing"] = 0
        grip["anchor"], grip["anchor_t"] = p, now
        f.wr(GRIPPER, TORQUE_LIMIT, GRIPPER_FREE_TORQUE.to_bytes(2, "little"))
        print("GREIFER LOESEN: volle Kraft fuer schnelle Bewegung.", flush=True)


def fatal_bits(s, status, parking=False):
    """Alarm bits that abort. Bit 0 (voltage) is checked via measured voltage;
    gripper overload (squeezing an object) is handled, not fatal. While parking,
    overload is never fatal: the bit stays set until power-off, and refusing to
    park would leave the arm raised. Parking moves slowly with its own stall stop."""
    mask = ~1
    if s == GRIPPER or parking:
        mask &= ~OVERLOAD
    return status & mask


# Blocked-joint detection while following (joints 1-5; gripper: update_grip).
STALL_ERR = 120        # steps (~10.5 deg); regulator residual under load is ~6 deg
STALL_MOVE = 6         # steps of movement that count as "still moving"
STALL_S = 0.3          # stalled this long with a large error -> hold the joint


def update_stall(track, p, target, now):
    """True when the joint has been stuck for STALL_S while far from its target.
    Measured from when the large error began, so a joint that rested before the
    leader moved is not mistaken for blocked. Independent of leader motion."""
    if track.get("anchor") is None or abs(p - track["anchor"]) >= STALL_MOVE:
        track["anchor"], track["anchor_t"] = p, now
    if abs(target - p) > STALL_ERR:
        track.setdefault("err_since", now)
    else:
        track.pop("err_since", None)
        return False
    return now - max(track["anchor_t"], track["err_since"]) >= STALL_S


class ConnectionLost(Abort):
    pass


class CheckedArm(Arm):
    """Fail closed on an ambiguous bus transaction; no retries after disconnect."""
    def __init__(self, name):
        self.name = name
        self.port = find_port(name)
        self.bus = FastBus(self.port)
        self.lim = {}
        self.disconnected = False
        self.voltage_low_since = {}
        self.voltage_warnings = {}

    def check_voltage(self, s, voltage, flagged=False):
        now = time.monotonic()
        if voltage > 8.0:
            raise Abort(f"{self.name} ID {s}: Spannung {voltage:.1f} V ausserhalb 4,0–8,0 V")
        # Logs showed single sub-4.0 V readings only on IDs 5/6 while all other
        # servos read 4.8 V, even at rest. Require consecutive confirmation;
        # a real outage still aborts via missing replies (ConnectionLost).
        # The leader exerts no force: its voltage is not a safety issue. A real
        # supply failure still aborts because the servos stop answering.
        fatal = self.name != "leader"
        bad = getattr(self, "voltage_bad_count", None)
        if bad is None:
            bad = self.voltage_bad_count = {}
        if voltage < 4.0:
            count, first = bad.get(s, (0, now))
            count += 1
            bad[s] = (count, first)
            # Confirmed only if consecutive (reset by any clean reading or clean
            # status reply) AND lasting at least LOW_VOLTAGE_CONFIRM_S.
            if fatal and count >= LOW_VOLTAGE_CONFIRM and now - first >= LOW_VOLTAGE_CONFIRM_S:
                raise Abort(f"{self.name} ID {s}: Spannung {voltage:.1f} V ausserhalb 4,0–8,0 V ({count} Messungen in Folge, {(now-first)*1000:.0f} ms)")
            if fatal:
                print(f"SPANNUNGSAUSREISSER {self.name} ID {s}: {voltage:.1f} V (Messung {count}); wird bestaetigt, bevor abgebrochen wird.", flush=True)
        else:
            bad.pop(s, None)
        if voltage < 4.3:
            self.voltage_low_since.setdefault(s, now)
            if fatal and now - self.voltage_low_since[s] >= 0.6:
                raise Abort(f"{self.name} ID {s}: anhaltende Unterspannung {voltage:.1f} V")
        else:
            self.voltage_low_since.pop(s, None)
        if flagged or voltage < 4.3:
            if now - self.voltage_warnings.get(s, -100) >= 2:
                print(f"SPANNUNGSWARNUNG {self.name} ID {s}: Statusbit Spannung, nachgemessen {voltage:.1f} V; kurze Warnung beendet den Lauf nicht.", flush=True)
                self.voltage_warnings[s] = now

    def check_status(self, s, status, voltage=None):
        # Bit 0 = voltage, not a framing/USB fault. Other alarm bits stay fatal,
        # except gripper overload.
        if fatal_bits(s, status, getattr(self, "parking", False) is True):
            raise Abort(f"{self.name} ID {s}: Servofehler 0x{status:02x}")
        self.note_gripper_overload(s, status)
        if status & 1:
            if voltage is None:
                voltage = self.rd(s, VOLT, 1) / 10
            self.check_voltage(s, voltage, flagged=True)

    def note_gripper_overload(self, s, status):
        if s != GRIPPER and status & OVERLOAD and getattr(self, "parking", False) is True:
            now = time.monotonic()
            if now - getattr(self, "overload_logged", -100) >= 2:
                print(f"UEBERLASTBIT {self.name} ID {s} beim Ablegen (bleibt bis Netzteil aus gesetzt); Ablage laeuft langsam mit Stillstandserkennung weiter.", flush=True)
                self.overload_logged = now
            return
        if s == GRIPPER and status & OVERLOAD:
            now = time.monotonic()
            last = getattr(self, "overload_logged", -100)
            if now - last >= 2:
                print(f"GREIFER-UEBERLAST {self.name}: Servo meldet 0x{status:02x}; Greifer drueckt nicht weiter, andere Gelenke laufen weiter.", flush=True)
                self.overload_logged = now

    def rd(self, s, addr, n, tries=1):
        if self.disconnected:
            raise ConnectionLost(self.name)
        try:
            value = super().rd(s, addr, n, tries=1)
            if value is None:
                raise ConnectionLost(f"{self.name}: ID {s} antwortet nicht")
            return value
        except Exception:
            self.disconnected = True
            raise

    def read_group(self, size):
        if self.disconnected:
            raise ConnectionLost(self.name)
        try:
            reply = self.bus.sync_read(JOINTS, POS, size)
            if reply is None:
                raise ConnectionLost(f"{self.name}: unvollstaendige Sammelantwort; Netzteil/USB pruefen")
        except Exception:
            self.disconnected = True
            raise
        for s, (status, _) in reply.items():
            data = reply[s][1]
            if status == 0 and size == 2:
                # Clean reply without voltage flag: low-voltage episode is over.
                self.voltage_low_since.pop(s, None)
                getattr(self, "voltage_bad_count", {}).pop(s, None)
            if size >= 10:
                # Evaluate this sample's voltage exactly once (confirmation counter).
                for st in (status, data[9]):
                    if fatal_bits(s, st, getattr(self, "parking", False) is True):
                        raise Abort(f"{self.name} ID {s}: Servofehler 0x{st:02x}")
                    self.note_gripper_overload(s, st)
                self.check_voltage(s, data[6] / 10, flagged=bool((status | data[9]) & 1))
            else:
                self.check_status(s, status, data[6] / 10 if size >= 7 else None)
        return {s: data for s, (_, data) in reply.items()}

    def send_goals(self, goals):
        if self.disconnected:
            raise ConnectionLost(self.name)
        values = {s: self.clamp(s, p).to_bytes(2, "little") + b"\0\0\0\0" for s, p in goals.items()}
        try:
            self.bus.sync_write(GOAL, values)
        except Exception:
            self.disconnected = True
            raise

    def wr(self, s, addr, data, tries=1):
        if self.disconnected:
            raise ConnectionLost(self.name)
        try:
            reply = self.bus.write(s, addr, data)
            if reply is None:
                raise ConnectionLost(f"{self.name}: ID {s}, Schreibantwort fehlt/Fehler")
        except Exception:
            self.disconnected = True
            raise
        self.check_status(s, reply[1])
        return True


# Rest pose of Setup 1, hand folded up (measured 2026-11-15; config.json rest_pose takes precedence). Wrist roll re-zeroed 2026-11-16 15:49 (d=1245).
REST_POSE = {1: 2073, 2: 846, 3: 3095, 4: 902, 5: 914, 6: 1418}
REST_SHOULDER_TOL = 150


def rest_pose(arm_name):
    """Measured rest pose of a follower from config.json (None = not measured yet)."""
    from so101 import CFG
    raw = CFG.get(arm_name, {}).get("rest_pose")
    if raw:
        return {int(s): int(p) for s, p in raw.items()}
    return dict(REST_POSE) if arm_name == "follower" else None


def rest_target(actual, rest=REST_POSE):
    """Park into the start pose only if it is the rest pose; a raised start parks
    into the fixed rest pose so release never happens with the arm in the air.
    Without a measured rest pose the start pose is the park target (start must be from rest)."""
    if rest is None:
        return actual
    pitch_ok = all(abs(actual[s] - rest[s]) <= REST_SHOULDER_TOL for s in (2, 3, 4))
    if pitch_ok:
        return actual
    if abs(actual[2] - rest[2]) <= REST_SHOULDER_TOL:
        # In der Ablage gestartet, aber z. B. mit nicht hochgeklappter Hand (Log 17.11.): Schulter, Ellbogen
        # und Handgelenk-Beugung kommen aus der gemessenen Ablagepose, Basis/Drehung/Greifer bleiben.
        target = dict(actual)
        for s in (2, 3, 4):
            target[s] = rest[s]
        return target
    return dict(rest)


def check_calibrated(arm, lim):
    """Uncalibrated servos report the full range 0-4095; mid 2047 would then be an
    arbitrary pose. Pitch joints and base must have real limits before any motion."""
    for s in (1, 2, 3, 4):
        lo, hi = lim[s]
        if lo == 0 and hi == 4095:
            raise Abort(f"{arm.name} ID {s} ({JOINTS[s]}): Grenzen 0-4095, Arm nicht kalibriert. "
                        f"Erst kalibrieren (calib.py), keine Bewegung.")


def targets(f, l):
    return {s: map_target(f, l, s, p) for s, p in l.positions().items()}


BASE_CENTER_TOL = 60     # Schritte (~5 Grad): weiter weg von der Mitte -> Basis zuerst eingeklappt drehen


def base_center(arm, lim=None):
    """Mitte zwischen den beiden Anschlaegen der Basis. Aus der Anschlag-Messung, wenn sie zum
    aktuellen Offset passt, sonst die Mitte der EEPROM-Grenzen. Nie ein Anschlag."""
    try:
        data = stopcal.load(stopcal.stops_path(arm.name)) or {}
        j = (data.get("joints") or {}).get("1")
        offs = read_offsets(arm)
        if j and offs and int((data.get("offsets") or {}).get("1", 99999)) == offs[1]:
            return int(round((j["lo"] + j["hi"]) / 2))
    except Exception:
        pass
    lo, hi = (lim or arm.lim)[1]
    return int(round((lo + hi) / 2))


def center_base_first(f, start, moved, stop, center):
    """Basis aus der Ablage zuerst EINGEKLAPPT zur Mitte drehen, dann erst hochfahren.
    Sonst streckt sich der Arm am Anschlag aus und dreht ausgestreckt zur Mitte (Hindernisse neben dem Tisch)."""
    if abs(start[1] - center) <= BASE_CENTER_TOL:
        return
    print(f"BEWEGUNG: Basis steht bei {start[1]}, Mitte zwischen den Anschlaegen ist {center}. "
          "Erst eingeklappt zur Mitte drehen, dann hochfahren.", flush=True)
    for s in (3, 4, 2, 1):                    # eingeklappte Gelenke halten, damit nichts nachgibt
        if stop.is_set():
            raise Abort("Stop angefordert")
        if s not in moved:
            moved.append(s)
        f.hold(s, delay=0.05)
    f.step_to(1, center, speed=600, acc=40, poll_interval=0.03)


def raise_path(rest, center, order):
    """Stellungen (Gelenke 1-6) auf dem Weg aus der Ablage in die Mitte, wie center_base_first + raise_to_mid."""
    from so101 import MID
    pose = {s: rest[s] for s in (1, 2, 3, 4, 5, 6)}
    out = [dict(pose)]
    steps = [(1, center)] + [(s, MID) for s in order if s in (2, 3, 4)] + [(1, MID), (5, MID), (6, MID)]
    for s, target in steps:
        a = pose[s]
        for i in range(1, 11):
            pose[s] = a + (target - a) * i / 10
            out.append(dict(pose))
    return out


def attach_fence(f, center, start, order):
    """Arbeitsbereich (Waende) des Arms laden und den Weg nach oben vorab pruefen. Kein Bereich -> None."""
    karte = arbeitsbereich.load(f.name)
    f.fence = None
    if not karte or not karte.get("aktiv"):
        print("ZAUN: kein Arbeitsbereich aktiv", flush=True)
        return None
    fence = arbeitsbereich.Fence(karte, center, log=lambda m: print(m, flush=True))
    if arbeitsbereich.base_clearance(karte) < -0.002:
        raise Abort("ZAUN: Die Basis steht laut Karte selbst ueber einer Wand. Basis-Lage in der Karte pruefen.")
    path = raise_path(start, center, order)
    here = arbeitsbereich.clearance(karte, path[0], center)[0]
    if here < fence.margin:
        print(f"ZAUN-WARNUNG: Schon die Ablage-Stellung liegt {max(0, fence.margin - here) * 100:.1f} cm zu nah an/hinter "
              "einer Wand (z. B. Gestell ueber der Tischkante). Der Weg nach oben darf nicht tiefer hinein.", flush=True)
    worst = min(arbeitsbereich.clearance(karte, p, center)[0] for p in path[1:])
    if worst < min(fence.margin, here - 0.002):
        raise Abort(f"ZAUN: Der Weg aus der Ablage in die Mittelstellung kaeme {max(0, fence.margin - worst) * 100:.1f} cm "
                    "zu nah an eine Wand des Arbeitsbereichs. Karte pruefen (Basis-Lage, Richtung) oder Bereich deaktivieren.")
    print(f"ZAUN: Arbeitsbereich aktiv ({len(karte.get('erlaubt') or [])} Flaeche(n), "
          f"{len(karte.get('verboten') or [])} Hindernis(se), Abstand {fence.margin * 100:.0f} cm).", flush=True)
    f.fence = fence
    return fence


def karte_mtime(f):
    try:
        return os.path.getmtime(arbeitsbereich.path(f.name))
    except (OSError, TypeError):
        return None


def reload_fence(f, fence, mtime, pose):
    """Karte neu laden, wenn die Datei sich geaendert hat. Die aktuelle Stellung muss sicher sein,
    sonst bleibt es vorerst beim alten Stand (Arm wuerde sonst sofort festgehalten). -> (fence, mtime)"""
    now = karte_mtime(f)
    if now == mtime:
        return fence, mtime
    karte = arbeitsbereich.load(f.name)
    if not karte or not karte.get("aktiv"):
        if fence is not None:
            print("ZAUN: Arbeitsbereich ausgeschaltet.", flush=True)
        return None, now
    center = fence.base_center if fence is not None else base_center(f)
    new = arbeitsbereich.Fence(karte, center, log=lambda m: print(m, flush=True))
    ok, d = new.start(pose)
    if not ok:
        print(f"ZAUN: neue Karte NICHT uebernommen - der Arm steht gerade {max(0, new.margin - d) * 100:.1f} cm zu nah "
              "an/hinter einer Wand. Arm in den gruenen Bereich bewegen, dann Karte nochmal speichern.", flush=True)
        return fence, now
    print(f"ZAUN: Arbeitsbereich jetzt AKTIV (Abstand {new.margin * 100:.0f} cm).", flush=True)
    return new, now


def read_offsets(arm):
    """Offsets 1-6 aus dem EEPROM lesen (nur Lesen). None, wenn nicht lesbar."""
    from so101 import OFFSET, usm
    try:
        out = {}
        for s in JOINTS:
            v = arm.rd(s, OFFSET, 2)
            if not isinstance(v, int):
                return None
            out[s] = usm(v)
        return out
    except Exception:
        return None


def attach_stop_map(f, l):
    """Anschlag-Zuordnung Leader -> Follower setzen, wenn aktiviert und Offsets unveraendert.
    Nur fuer die Leader-Steuerung; Fernsteuerung (RemoteFeed) hat keine Offsets."""
    f.stop_map = None
    f.grip_fix = stopcal.load(stopcal.grip_path(f.name))
    if f.grip_fix and f.grip_fix.get("steps"):
        print(f"GREIFER: Feinkorrektur {f.grip_fix['close_deg']:.1f} Grad weiter zu.", flush=True)
    lo = getattr(l, "offsets", None)
    if lo is None:
        return
    fo = read_offsets(f)
    m, why = stopcal.usable_map(f.name, lo, fo or {})
    f.stop_map = m
    print(f"KALIBRIERUNG: {why}", flush=True)


def map_target(f, l, s, value):
    m = getattr(f, "stop_map", None)        # Anschlag-Kalibrierung (nur bei Leader-Steuerung gesetzt)
    fix = getattr(f, "grip_fix", None)
    fix = fix if isinstance(fix, dict) else None
    if isinstance(m, dict) and str(s) in m["joints"]:
        j = m["joints"][str(s)]
        if s == 6 and j.get("kind") == "linear":
            (a, b), (c, d) = j["leader"], j["follower"]
            return f.clamp(s, stopcal.grip_target(value, a, b, c, d, fix))
        return f.clamp(s, stopcal.apply(m, s, value))
    if getattr(l, "identity", False) is True:   # KI-Ziele sind bereits Follower-Werte
        return f.clamp(s, value)
    if s == 6:
        a, b = l.lim[6]
        c, d = f.lim[6]
        if fix and isinstance(fix.get("closed"), int):
            c = fix["closed"]               # Untergrenze wurde fuer die Korrektur abgesenkt: altes 'zu' behalten
        value = stopcal.grip_target(value, a, b, c, d, fix)
    return f.clamp(s, value)


BLEND_DEG_S = 40.0      # mittleres Tempo beim Angleichen an den Leader (Spitze ~60 Grad/s)
BLEND_MAX_S = 4.0


def blend_duration(f, l, initial, leader, minimum):
    """Wie lange das Angleichen dauert: so, dass das am weitesten entfernte Gelenk im Mittel hoechstens
    BLEND_DEG_S faehrt (vorher immer 0,75 s - bei 90 Grad Abstand ein Sprung mit 120 Grad/s)."""
    if minimum <= 0:
        return 0.0
    far = 0
    for s, data in leader.items():
        try:
            far = max(far, abs(map_target(f, l, s, int.from_bytes(data, "little")) - initial[s]))
        except (TypeError, KeyError, ValueError):
            pass
    return max(minimum, min(BLEND_MAX_S, far * 360 / 4096 / BLEND_DEG_S))


def follow(f, l, stop, blend_seconds=0.75):
    """No duration limit. Group reads/writes; no stale target queue or arrival waits."""
    for s in JOINTS:
        if stop.is_set():
            return
        f.wr(s, ACC, [GRIPPER_ACC if s == GRIPPER else FOLLOW_ACC])
    # Free gripper motion with full torque (fast); the limit is applied only
    # while squeezing an object (RAM only; EEPROM value returns after power cycle).
    f.wr(GRIPPER, TORQUE_LIMIT, GRIPPER_FREE_TORQUE.to_bytes(2, "little"))
    grip = {"squeezing": 0, "anchor": None, "anchor_t": 0.0}
    initial = {s:int.from_bytes(d[:2], "little") for s, d in f.read_group(10).items()}
    if getattr(l, "identity", False) is True and callable(getattr(l, "seed", None)):
        l.seed(initial)            # KI-Fahrer: bis zum ersten Modellziel die aktuelle Stellung halten
    blend_total = None             # Dauer des Angleichens, aus dem Abstand zum ersten Leader-Wert
    fence = getattr(f, "fence", None)
    fence = fence if isinstance(fence, arbeitsbereich.Fence) else None
    if fence is not None:
        ok, d = fence.start(initial)
        if not ok:
            raise Abort(f"ZAUN: Ausgangsstellung liegt {max(0, fence.margin - d) * 100:.1f} cm zu nah an/hinter einer Wand")
    fence_checked = time.monotonic()
    fence_mtime = karte_mtime(f)
    history = {s: {} for s in JOINTS}   # stall tracking per joint
    low_since = {}
    goal = {}
    blocked = {}
    t0 = last_log = time.monotonic()
    last_telemetry = t0 - 1
    last_trace = t0 - 1
    last_pose = t0 - 1
    last_obs = t0 - 1
    last_load = t0 - 1         # LAST-Zeilen (Servolast) fuer die Kontakterkennung, nur lesen
    interval_start = t0
    interval_cycles = 0
    transfer_ms = deque(maxlen=2000)
    vmin = 99.0
    maxerr = 0
    while not stop.is_set():
        tick = time.monotonic()
        leader = l.read_group(2)
        if blend_total is None:
            blend_total = blend_duration(f, l, initial, leader, blend_seconds)
            t0 = time.monotonic()
            print(f"BEWEGUNG: Sanft an aktuellen Leader angleichen ({blend_total:.1f} s, hoechstens "
                  f"{BLEND_DEG_S:.0f} Grad/s im Mittel), danach direkt folgen.", flush=True)
        a = min(1.0, (time.monotonic() - t0) / blend_total) if blend_total > 0 else 1.0
        alpha = a * a * (3 - 2 * a)    # weich anfahren und weich ankommen statt Ruck
        for s, data in leader.items():
            mapped = map_target(f, l, s, int.from_bytes(data, "little"))
            goal[s] = f.clamp(s, initial[s] + alpha * (mapped - initial[s]))
        commanded = dict(goal)
        for s, position in list(blocked.items()):
            if abs(goal[s] - position) <= 70:
                del blocked[s]
                history[s].clear()
                f.wr(s, ACC, [GRIPPER_ACC if s == GRIPPER else FOLLOW_ACC])
                print(f"ID {s}: Leader zur gehaltenen Position zurueckgefuehrt; folgt wieder.", flush=True)
            else:
                commanded[s] = position
        if tick - fence_checked >= 1.0:  # Karte geaendert? (Fenster 'Arbeitsbereich') -> ohne Neustart uebernehmen
            fence_checked = tick
            fence, fence_mtime = reload_fence(f, fence, fence_mtime, commanded)
        if fence is not None:            # Arbeitsbereich: an der Wand halten, bis der Leader zurueckkommt
            fenced = fence.filter(commanded, tick)
            commanded = fenced if fenced is not None else {**commanded, **{s: initial[s] for s in JOINTS}}
        if stop.is_set():
            return
        f.send_goals(commanded)
        now = time.monotonic()
        transfer_ms.append((now - tick) * 1000)
        if now - last_telemetry >= 0.02:
            telemetry = f.read_group(10)
            now = time.monotonic()
            last_telemetry = now
            if now - last_pose >= 0.04:   # Ist-Stellung fuer die 3D-Ansicht, 25 Hz (nicht ins Protokoll)
                last_pose = now
                print("POSE", " ".join(str(int.from_bytes(telemetry[s][:2], "little")) for s in JOINTS), flush=True)
            if now - last_trace >= 0.1:
                last_trace = now
                print("TRACE IDs 1-6 | Leader", [int.from_bytes(leader[s], "little") for s in JOINTS],
                      "| gesendet", [commanded[s] for s in JOINTS],
                      "| Ist", [int.from_bytes(telemetry[s][:2], "little") for s in JOINTS],
                      "| Spannung [0.1 V]", [telemetry[s][6] for s in JOINTS], flush=True)
            rec = getattr(f, "record", None)
            # OBS-Zeilen: schnell beim Aufnehmen/KI, sonst 10x pro Sekunde (Startpose-Anzeige, Posen merken)
            obs_every = OBS_INTERVAL_S if rec is not None and rec.is_set() else 0.1
            if alpha >= 1 and now - last_obs >= obs_every:
                last_obs = now
                # Aufnahme fuer die KI: Ist-Stellung und Ziel (= Aktion) in Follower-Werten
                print("OBS", " ".join(str(int.from_bytes(telemetry[s][:2], "little")) for s in JOINTS),
                      "|", " ".join(str(int(goal[s])) for s in JOINTS), flush=True)
            if alpha >= 1 and now - last_load >= 0.1:
                last_load = now
                # Present Load (Bit 10 = Richtung, hier nur Betrag in Promille); reine Ausgabe, keine Regelung
                print("LAST", " ".join(str(int.from_bytes(telemetry[s][4:6], "little") & 1023) for s in JOINTS), flush=True)
            for s, data in telemetry.items():
                p = int.from_bytes(data[:2], "little")
                load = int.from_bytes(data[4:6], "little") & 1023
                v = data[6] / 10
                vmin = min(vmin, v)
                maxerr = max(maxerr, abs(p - commanded[s]))
                if fatal_bits(s, data[9], getattr(f, "parking", False) is True):
                    raise Abort(f"Follower ID {s}: Status {data[9]}")
                if s == GRIPPER and data[9] & OVERLOAD and s not in blocked:
                    # Stop squeezing: hold where the gripper is; resumes once the
                    # leader gripper returns near this position.
                    blocked[s] = f.clamp(s, p)
                    f.goal(s, blocked[s], speed=60)
                    print(f"GREIFER GEHALTEN: Ueberlast bei Ist {p}, Ziel {goal[s]}. Leader-Greifer etwas oeffnen zum Fortsetzen.", flush=True)
                if s == GRIPPER and s not in blocked and alpha >= 1:
                    update_grip(f, grip, p, goal[s], now)
                # Sub-4.0 V is checked with consecutive confirmation in
                # CheckedArm.check_voltage (called by read_group).
                if v < 4.3:
                    low_since.setdefault(s, now)
                    if now - low_since[s] >= 0.6:
                        raise Abort(f"Follower ID {s}: anhaltende Unterspannung {v:.1f} V")
                else:
                    low_since.pop(s, None)
                if s in blocked or alpha < 1 or s == GRIPPER:
                    # Gripper contact is handled by update_grip (torque-limited squeezing).
                    continue
                # Blocked joint (obstacle, cable, own body): stuck while far from
                # target. Works even while the leader keeps moving (log 14.11. 00:24:
                # wrist roll pushed for 2 s until servo overload).
                if fence is not None and fence.limiting:
                    history[s].clear()           # Zaun begrenzt gerade absichtlich: keine Blockade-Erkennung
                    continue
                if update_stall(history[s], p, commanded[s], now):   # gegen das GESENDETE Ziel pruefen
                    blocked[s] = f.clamp(s, p)
                    f.goal(s, blocked[s], speed=60)
                    print(f"GELENK GEHALTEN ID {s} ({JOINTS[s]}): Ist {p}, Ziel {goal[s]}, Abstand {abs(p-goal[s])*360/4096:.1f} Grad, Last {load}, {v:.1f} V. Blockade vermutet; drueckt nicht weiter. Andere Gelenke folgen weiter. Leader zu dieser Position zurueckfuehren zum Fortsetzen.", flush=True)
        interval_cycles += 1
        if now - last_log >= 2:
            ordered = sorted(transfer_ms)
            p95 = ordered[int(0.95 * (len(ordered)-1))]
            print(f"TELEOP: {interval_cycles / (now - interval_start):.1f} Hz | Lesen->Senden p95 {p95:.2f} ms | min {vmin:.1f} V | Abweichung {maxerr * 360 / 4096:.1f} Grad | gehalten {list(blocked)}", flush=True)
            last_log = now
            interval_start = now
            interval_cycles = 0
            maxerr = 0




def precheck(arm, calibrated=False):
    """Limits, voltage and alarm bits of every joint before anything moves."""
    lim = arm.limits()
    for s, (lo, hi) in lim.items():
        if not 0 <= lo < hi <= 4095:
            raise Abort(f"Ungueltige Grenzen: {arm.name}, ID {s}")
    if calibrated:
        check_calibrated(arm, lim)
    for s in lim:
        v = arm.rd(s, VOLT, 1) / 10
        status = arm.rd(s, STATUS, 1)
        print(f"{arm.name} {arm.port}: ID {s}, {v:.1f} V, Status {status}", flush=True)
        if status & OVERLOAD:
            raise Abort(f"Vorpruefung fehlgeschlagen: {arm.name} ID {s} meldet noch Ueberlast (Status {status}). "
                        "Das Bit bleibt bis zum Stromlosmachen gesetzt: Arm sichern, Netzteil kurz ziehen, Arm in die Ablage legen.")
        if v < 4.3 or status:
            raise Abort("Vorpruefung fehlgeschlagen")


def run_arm(follower, l, stop, move=True, record=None):
    """One follower from rest -> follow the leader source l -> park. l is a CheckedArm
    or a LeaderFeed shared by several followers. Returns 0 (parked/nothing moved) or 1."""
    f = None
    start = None
    moved = []
    failed = False
    try:
        f = CheckedArm(follower)
        print(f"ARM: {follower} ({f.port})", flush=True)
        precheck(f, calibrated=True)
        attach_stop_map(f, l)
        f.record = record
        if isinstance(l, PolicyFeed):
            l.seed(f.positions())        # KI-Fahrer wartet noch: bis zum Hochfahren gilt die eigene Stellung
        print("Leader:", l.positions(), flush=True)
        print("Follower:", f.positions(), flush=True)
        print("Ziele:", targets(f, l), flush=True)
        if not move:
            print("DRY-RUN OK. Keine Bewegung, keine Schreibbefehle.", flush=True)
            return 0
        if stop.is_set():
            return 0
        actual = f.positions()
        rest = rest_pose(follower)
        start = rest_target(actual, rest)
        if rest is None:
            print(f"ACHTUNG: Fuer {follower} ist noch keine Ablagepose eingetragen. Die Startpose wird als Ablageziel "
                  "verwendet; der Arm muss deshalb aus seiner Ablage starten.", flush=True)
        elif start is actual:
            print("Startpose ist die Ablage; sie wird als Ablageziel verwendet.", flush=True)
        elif abs(actual[2] - rest[2]) <= REST_SHOULDER_TOL:
            print(f"ACHTUNG: Arm liegt nicht wie gemessen in der Ablage (Ellbogen {actual[3]}/{rest[3]}, "
                  f"Handgelenk {actual[4]}/{rest[4]}). Abgelegt wird in die gemessene Ablagepose mit "
                  "hochgeklappter Hand.", flush=True)
        else:
            print(f"Start aus angehobener Pose (Schulter {actual[2]}). Ablageziel ist die feste Ablagepose {start}.", flush=True)
        f.stop_requested = stop.is_set
        f.limits()
        center = base_center(f)
        if abs(start[1] - center) > BASE_CENTER_TOL:     # nie an einen Basis-Anschlag zurueck ablegen
            start = dict(start)
            start[1] = center
            print(f"Ablageziel Basis: Mitte {center} (statt {actual[1]} nahe einem Anschlag).", flush=True)
        order, clearance = plan_mid_order(actual)
        names = ", ".join(JOINTS[s] for s in order)
        print(f"Weg zur Mitte geplant: {names}; niedrigster Gelenkpunkt laut Hoehenmodell {clearance*100:.1f} cm ueber dem Tisch.", flush=True)
        if clearance < MIN_CLEARANCE_M:
            raise Abort(f"Kein sicherer Weg zur Mitte gefunden (min. {clearance*100:.1f} cm). Follower vor Ort von Hand in eine hoehere Pose oder die Ablage bringen.")
        print(f"BEWEGUNG: Hochfahren einzeln: {names}. Speed=900, ACC=80, Ueberwachung alle 30 ms.", flush=True)
        attach_fence(f, center, actual, order)
        center_base_first(f, actual, moved, stop, center)
        raise_to_mid(f, start=start, moved=moved, speed=900, acc=80, poll_interval=0.03, hold_delay=0.05, order=order)
        if not stop.is_set():
            follow(f, l, stop)
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        failed = not stop.is_set()
        print(f"BEENDET: {exc}", flush=True)
    finally:
        if start is not None and moved:
            if any(a is not None and a.disconnected for a in (f, l)):
                failed = True
                print("VERBINDUNGSFEHLER: Keine weiteren Busbefehle. Arm sichern; bei Netzteilabschaltung Netzteil neu einstecken. Zustand unbestaetigt.", flush=True)
            else:
                f.stop_requested = lambda: False
                f.parking = True   # sticky overload bit must not prevent parking
                try:
                    print("BEWEGUNG: Aktuelle Positionen halten, danach ablegen.", flush=True)
                    if getattr(stop, "free", False) and GRIPPER in getattr(f, "lim", {}):
                        # Not-Ablage: erst den Greifer oeffnen, damit ein festgeklemmtes Teil den Arm loslaesst
                        print("BEWEGUNG: Not-Ablage - Greifer oeffnen, um verklemmte Teile loszulassen.", flush=True)
                        try:
                            f.step_to(GRIPPER, f.lim[GRIPPER][1] - 40, speed=600, acc=40, poll_interval=0.03, quiet=True)
                        except Abort as exc:
                            print(f"Greifer ging nicht ganz auf ({exc}); lege trotzdem ab.", flush=True)
                    positions = f.positions()
                    for s in moved:
                        f.goal(s, f.clamp(s, positions[s]), speed=60)
                    # Reverse order is only collision-safe starting from mid: first bring
                    # every moved joint to mid along the planned order, then fold into the rest pose.
                    mid_order, clearance = plan_mid_order(positions)
                    fold, fold_clear = plan_fold_order(start)
                    print(f"BEWEGUNG: Erst einzeln in Mittelstellung ({', '.join(JOINTS[s] for s in mid_order)}; min. {clearance*100:.1f} cm), "
                          f"dann einklappen ({', '.join(JOINTS[s] for s in fold)}; min. {fold_clear*100:.1f} cm).", flush=True)
                    park(f, start, moved, via_mid=True, speed=600, acc=40, poll_interval=0.03, mid_order=mid_order)
                    print("ABGELEGT. Motoren freigegeben.", flush=True)
                except BaseException as exc:
                    failed = True
                    print(f"ABLAGE NICHT BESTAETIGT: {exc}. Keine Freigabe gesendet. Arm vor Ort sichern; bei Busausfall Netzteil pruefen.", flush=True)
        if f is not None:
            f.close()
    return 1 if failed else 0


def main(move=False, follower="follower"):
    """Single follower, own leader connection (classic mode, also the read-only test)."""
    stop = threading.Event()
    def listen():
        # EOF also requests stop if the window disappears.
        line = sys.stdin.readline()
        print("STOP: Bedienknopf" if line else "STOP: Bedienfenster-Verbindung geschlossen (EOF)", flush=True)
        stop.set()
    if move:
        threading.Thread(target=listen, daemon=True).start()
    l = None
    try:
        l = CheckedArm("leader")
        precheck(l)
        l.offsets = read_offsets(l)
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        print(f"BEENDET: {exc}", flush=True)
        if l is not None:
            l.close()
        return 1
    try:
        return run_arm(follower, l, stop, move)
    finally:
        l.close()


# --- Mehrere Follower an einem Leader ---------------------------------------
LEADER_STALE_S = 0.1


class LeaderFeed:
    """Owns the leader connection, reads it continuously and hands the newest sample
    to every following arm. Looks like a leader arm to follow()/targets()."""
    name = "leader"

    def __init__(self, leader):
        self.leader = leader
        self.lim = leader.lim
        self.port = getattr(leader, "port", "")
        self.offsets = getattr(leader, "offsets", None)
        self.cond = threading.Condition()
        self.data = None
        self.time = 0.0
        self.seq = 0
        self.error = None
        self.rate = 0.0
        self.halt = threading.Event()
        self.local = threading.local()

    @property
    def disconnected(self):
        return self.error is not None

    def run(self):
        n, t0 = 0, time.monotonic()
        while not self.halt.is_set():
            try:
                data = self.leader.read_group(2)
            except BaseException as exc:
                with self.cond:
                    self.error = exc
                    self.cond.notify_all()
                print(f"LEADER AUSGEFALLEN: {exc}", flush=True)
                return
            now = time.monotonic()
            with self.cond:
                self.data, self.time = dict(data), now
                self.seq += 1
                self.cond.notify_all()
            n += 1
            if now - t0 >= 2:
                self.rate, n, t0 = n / (now - t0), 0, now

    def read_group(self, size=2):
        """Waits for a sample newer than the one this thread saw last (max 0.1 s)."""
        last = getattr(self.local, "seq", -1)
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last or self.error is not None, timeout=LEADER_STALE_S)
            if self.error is not None:
                raise ConnectionLost(f"Leader: {self.error}")
            if self.data is None or time.monotonic() - self.time > LEADER_STALE_S:
                raise ConnectionLost("Leader liefert keine aktuellen Daten")
            self.local.seq = self.seq
            return dict(self.data)

    def positions(self):
        return {s: int.from_bytes(d[:2], "little") for s, d in self.read_group(2).items()}

    def limits(self):
        return self.lim

    def close(self):
        pass        # the owner closes the real leader connection


REMOTE_STALE_S = 1.0
OBS_INTERVAL_S = 1 / 50     # Aufnahme-Zeilen; das Fenster tastet daraus mit 30 Hz ab


class RemoteFeed:
    """Zielgelenke aus der Fernsteuerung (das Fenster schreibt 'target j1..j6' mit ~50 Hz).
    Sieht fuer follow() aus wie ein Leader. Kommen kurz keine neuen Ziele, haelt der Arm das
    letzte Ziel; nach REMOTE_STALE_S ohne Ziele bricht das Folgen ab und der Arm legt sich ab."""
    name = "remote"
    port = "Fernsteuerung"
    disconnected = False            # kein Bus: ein Ausfall fuehrt zum normalen Ablegen

    def __init__(self, lim):
        self.lim = dict(lim)        # Gelenkgrenzen, in denen die Ziele gerechnet sind (Setup-1-Kalibrierung)
        self.cond = threading.Condition()
        self.data = None
        self.time = 0.0
        self.seq = 0
        self.local = threading.local()

    def update(self, values):
        if len(values) != 6 or not all(isinstance(v, int) and 0 <= v <= 4095 for v in values):
            raise ValueError(f"ungueltige Ziele {values}")
        with self.cond:
            self.data = {s: v for s, v in zip(JOINTS, values)}
            self.time = time.monotonic()
            self.seq += 1
            self.cond.notify_all()

    def read_group(self, size=2):
        last = getattr(self.local, "seq", -1)
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last, timeout=1.0 if self.data is None else 0.1)
            if self.data is None:
                raise Abort("Fernsteuerung liefert keine Ziele")
            age = time.monotonic() - self.time
            if age > REMOTE_STALE_S:
                raise Abort(f"Fernsteuerungs-Ziele seit {age:.1f} s veraltet (Fenster haengt?)")
            self.local.seq = self.seq
            return {s: v.to_bytes(2, "little") for s, v in self.data.items()}

    def positions(self):
        return {s: int.from_bytes(d, "little") for s, d in self.read_group(2).items()}

    def limits(self):
        return self.lim

    def close(self):
        pass


class PolicyFeed(RemoteFeed):
    """Gelenkziele eines KI-Modells fuer genau einen Arm ('ktarget <arm> j1..j6').
    Werte sind bereits in Follower-Koordinaten (so wurden sie aufgenommen): keine Umrechnung."""
    name = "ki"
    port = "KI-Fahrer"
    identity = True

    def __init__(self):
        super().__init__({s: (0, 4095) for s in JOINTS})
        self.from_driver = False         # erst ab dem ersten 'ktarget' kommen die Ziele vom Fahrer

    def update(self, values):
        super().update(values)
        self.from_driver = True

    START_GRACE_S = 10.0                 # so lange haelt der Arm ohne Fahrer-Ziele (Modell laedt, Startpose)

    def read_group(self, size=2):
        with self.cond:
            if not self.from_driver and self.data is not None and                     time.monotonic() - getattr(self, "seed_time", 0) < self.START_GRACE_S:
                self.time = time.monotonic()      # eigene Stellung halten gilt als frisch, aber nur begrenzt
        return super().read_group(size)

    def seed(self, positions):
        """Startwert = aktuelle Follower-Stellung, solange vom Fahrer noch nichts kam (jedes Mal frisch, damit
        er nicht als veraltet gilt: Vorpruefung und Hochfahren dauern laenger als die 1-s-Grenze)."""
        with self.cond:
            if not self.from_driver:
                self.seed_time = time.monotonic()
                self.data = {s: int(positions[s]) for s in JOINTS}
                self.time = time.monotonic()
                self.seq += 1
                self.cond.notify_all()


class PrefixedOutput:
    """Every line printed by an arm thread starts with '[<arm>] ' so the window can sort it."""
    def __init__(self, out):
        self.out = out
        self.lock = threading.Lock()
        self.local = threading.local()

    def set_prefix(self, prefix):
        self.local.prefix = prefix

    def write(self, text):
        buf = getattr(self.local, "buf", "") + text
        *lines, rest = buf.split("\n")
        self.local.buf = rest
        if lines:
            prefix = getattr(self.local, "prefix", "")
            with self.lock:
                self.out.write("".join(prefix + line + "\n" for line in lines))
                self.out.flush()
        return len(text)

    def flush(self):
        pass


def multi_main(commands=None, out=None, open_leader=None):
    """Worker for the window: one leader, several followers in parallel.
    stdin commands: 'start <arm>', 'stop <arm>', 'quit' (EOF = quit). Every arm parks on stop/quit."""
    from so101 import CFG
    real = out or sys.stdout
    output = PrefixedOutput(real)
    sys.stdout = output
    commands = sys.stdin if commands is None else commands
    leader = None
    try:
        leader = (open_leader or (lambda: CheckedArm("leader")))()
        precheck(leader)
        leader.offsets = read_offsets(leader)
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        print(f"LEADER FEHLER: {exc}", flush=True)
        if leader is not None:
            leader.close()
        sys.stdout = real
        return 1
    feed = LeaderFeed(leader)
    feed_thread = threading.Thread(target=feed.run, daemon=True, name="leader")
    feed_thread.start()
    import remote_kin
    remotes = {}                      # Arm -> RemoteFeed (jeder Arm hat seinen eigenen Fernsteuerer)

    legacy = []                       # letzte Ziele im alten Format "target j1..j6" (fuer alle Arme)

    def remote_for(key):
        if key not in remotes:
            remotes[key] = RemoteFeed(remote_kin.LIMITS)
            if legacy:
                remotes[key].update(legacy[-1])
        return remotes[key]
    policies = {}                  # arm -> PolicyFeed (KI-Fahrer)
    recording = {}                 # arm -> Event: Aufnahme-Zeilen ausgeben
    runs = {}
    codes = {}

    def arm_thread(key, stop, source):
        output.set_prefix(f"[{key}] ")
        rc = 1
        try:
            if type(source) is RemoteFeed:
                print("QUELLE: Fernsteuerung (Ziele vom Remote-Server)", flush=True)
            elif isinstance(source, PolicyFeed):
                print("QUELLE: KI-Fahrer (Ziele vom Modell)", flush=True)
            flag = recording.setdefault(key, threading.Event())
            if isinstance(source, PolicyFeed):
                flag.set()             # der KI-Fahrer braucht laufend die Ist-Stellung (OBS-Zeilen)
            rc = run_arm(key, source, stop, record=flag)
            if isinstance(source, PolicyFeed):
                flag.clear()
        finally:
            codes[key] = rc
            print(f"ARMENDE {rc}", flush=True)

    def status_loop():
        while not feed.halt.wait(2):
            active = [k for k, (t, _) in runs.items() if t.is_alive()]
            print(f"LEADER: {feed.rate:.0f} Hz | aktiv {active}", flush=True)

    threading.Thread(target=status_loop, daemon=True, name="status").start()
    print("BEREIT: Leader verbunden, warte auf Befehle.", flush=True)
    for line in commands:
        parts = line.split()
        if not parts:
            continue
        cmd, key = parts[0], (parts[1] if len(parts) > 1 else "")
        if cmd == "quit":
            break
        if cmd == "target":
            try:
                if key.startswith("follower"):           # "target <arm> j1..j6"
                    remote_for(key).update([int(v) for v in parts[2:]])
                else:                                    # alt: "target j1..j6" an alle
                    vals = [int(v) for v in parts[1:]]
                    RemoteFeed(remote_kin.LIMITS).update(vals)      # prueft die Werte
                    legacy[:] = [vals]
                    for feed_r in list(remotes.values()):
                        feed_r.update(vals)
            except ValueError as exc:
                print(f"Fernsteuerung: {exc}", flush=True)
            continue
        if cmd == "ktarget":
            try:
                if key not in policies:
                    raise ValueError(f"kein KI-Lauf fuer {key!r}")
                policies[key].update([int(v) for v in parts[2:]])
            except ValueError as exc:
                print(f"KI-Fahrer: {exc}", flush=True)
            continue
        if key not in CFG or not key.startswith("follower"):
            print(f"Unbekannter Arm: {key!r}", flush=True)
            continue
        if cmd == "start":
            if key in runs and runs[key][0].is_alive():
                print(f"{key} laeuft bereits.", flush=True)
                continue
            mode = parts[2] if len(parts) > 2 else "lokal"
            use_remote = mode in ("remote", "ki")
            if not use_remote and feed.disconnected:
                print(f"Kein Start von {key}: Leader ausgefallen.", flush=True)
                continue
            stop = threading.Event()
            if mode == "ki":
                policies[key] = PolicyFeed()
            source = policies[key] if mode == "ki" else remote_for(key) if mode == "remote" else feed
            thread = threading.Thread(target=arm_thread, args=(key, stop, source), name=key)
            runs[key] = (thread, stop)
            thread.start()
        elif cmd == "rec":
            flag = recording.setdefault(key, threading.Event())
            (flag.set if len(parts) > 2 and parts[2] == "on" else flag.clear)()
            print(f"AUFNAHME {'AN' if flag.is_set() else 'AUS'}", flush=True)
        elif cmd == "stop":
            if key in runs:
                free = len(parts) > 2 and parts[2] == "frei"
                print(f"STOP: {key} ({'Not-Ablage' if free else 'Bedienknopf'})", flush=True)
                runs[key][1].free = free or getattr(runs[key][1], "free", False)
                runs[key][1].set()
    print("STOP: alle Arme (Fenster geschlossen oder quit)", flush=True)
    for thread, stop in runs.values():
        stop.set()
    for thread, _ in runs.values():
        thread.join()              # Ablegen muss vollstaendig abgeschlossen sein
    feed.halt.set()
    feed_thread.join(timeout=2)    # laufenden Lesevorgang abwarten, sonst schliesst der Port mitten im Lesen
    leader.close()
    print("WORKER ENDE", flush=True)
    sys.stdout = real
    return 1 if any(codes.values()) else 0


if __name__ == "__main__":
    if "--multi" in sys.argv:
        raise SystemExit(multi_main())
    arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "follower"
    if arm == "leader" or not arm.startswith("follower"):
        raise SystemExit(f"Unbekannter Arm: {arm}")
    raise SystemExit(main(move="--move" in sys.argv, follower=arm))
