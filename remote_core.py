"""Steuerlogik der Fernsteuerung, Protokoll v1 (siehe remote-teleop/MAC_IOS_APP_PROMPT.md).

Reine Logik ohne Netzwerk und ohne Hardware, Zeit wird von aussen uebergeben (testbar).
- Nur ein Bediener (der erste Client), alle weiteren sind Zuschauer.
- Kupplung: Beim Druecken werden Handy- und Roboterpose gemerkt, danach bewegt sich der
  Roboter relativ. Blickrichtung des Handys beim Druecken = "vorn".
- Watchdog: 200 ms ohne Pose -> Halt; weiter erst nach Loslassen und erneutem Druecken.
- STOP: Halt; weiter ebenso erst nach Loslassen und erneutem Druecken.
- Begrenzte Geschwindigkeit, Arbeitsraum-Box und Gelenkgrenzen aus remote_kin.
"""
import math
from dataclasses import dataclass
import remote_kin as K

PROTOCOL_VERSION = 1
WORLD_UP = (0.0, 1.0, 0.0)     # ARKit, worldAlignment = .gravity


@dataclass
class Config:
    scale: float = 1.0          # Handyweg -> Roboterweg
    camera_yaw: float = 0.0     # Drehung "vorn des Bedieners" -> Roboter-x (rad), je nach Kameraposition
    pitch_gain: float = 1.0
    roll_gain: float = 1.0
    v_max: float = 0.25         # m/s Greiferspitze
    phi_rate: float = 2.5       # rad/s Handneigung
    roll_rate: float = 4.0      # rad/s Handgelenk-Drehung
    watchdog_s: float = 0.2
    haptic_interval: float = 0.3
    roll_limit: float = math.radians(150)   # max. Drehung gegenueber der Startstellung
    joint_rate: float = 1.5     # rad/s je Gelenk im Leader-Modus (~86 Grad/s)
    engage_tol: float = math.radians(20)    # Leader-Modus: so nah muss der Bediener-Leader am Arm sein, um zu kuppeln


# --- kleine Vektor- und Quaternion-Helfer (ohne numpy) ---
def qrot(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qaxis(axis, angle):
    s = math.sin(angle / 2)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(angle / 2))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(v):
    n = math.sqrt(_dot(v, v))
    return tuple(c / n for c in v) if n > 1e-9 else None


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def phone_angles(q):
    """Kamera-Blickrichtung (horizontal, normiert oder None), Nickwinkel und Rollwinkel des Handys."""
    fwd = qrot(q, (0.0, 0.0, -1.0))
    pitch = math.asin(max(-1.0, min(1.0, fwd[1])))
    heading = _norm((fwd[0], 0.0, fwd[2]))
    roll = None
    if abs(fwd[1]) < 0.95:
        right = _norm(_cross(fwd, WORLD_UP))
        up = _cross(right, fwd)
        xa = qrot(q, (1.0, 0.0, 0.0))
        roll = math.atan2(_dot(xa, up), _dot(xa, right))
    return heading, pitch, roll


def _finite(v, lim):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= lim


class RemoteController:
    def __init__(self, cfg=None, start_joints=None, now=0.0):
        self.cfg = cfg or Config()
        sj = start_joints or {1: K.MID, 2: K.MID, 3: K.MID, 4: K.MID, 5: K.MID, 6: K.GRIP_CLOSED}
        self.target = K.fk(sj)
        if K.solve(self.target) is None:
            raise ValueError("Startpose liegt nicht im sicheren Arbeitsraum")
        self.desired = self.target
        self.roll0 = float(sj[5])
        self.roll = self.desired_roll = float(sj[5])
        self.grip = self.desired_grip = float(sj[6])
        self.joints = self._joints()
        self.clients = []            # Reihenfolge = Warteschlange, [0] ist Bediener
        self.engaged = False
        self.need_release = False
        self.reason = None
        self.funkloch_n = 0          # Zahl der Aussetzer (Anzeige "Verbindung wackelt" in der App)
        self.last_seq = -1
        self.last_rx = None
        self.last_tick = now
        self.last_haptic = -1e9
        self.state_seq = 0
        self.anchor = None
        self.events = []             # (client_id, nachricht) fuer den Server
        self.mode = "pose"           # "pose" (Handy) oder "joints" (Leader-Arm des Bedieners)
        self.desired_joints = None   # Leader-Modus: Zielgelenke 1..5 (Ticks)

    # --- Clients ---
    @property
    def operator(self):
        desk = getattr(self, "desk", None)
        if desk is not None:                 # Server: Kontrolle auf Zeit (remote_control.ControlDesk)
            return desk.holder
        return self.clients[0] if self.clients else None

    def operator_changed(self):
        """Neuer (oder kein) Bediener: anhalten, Folge neu beginnen, erst Kupplung loslassen."""
        self._halt(None, release=True)
        self.reason = None
        self.last_seq = -1
        self.last_rx = None
        self.desired_joints = None

    def role(self, cid):
        if getattr(self, "desk", None) is not None and self.operator is None:
            return "operator"               # niemand steuert: jeder darf mit "Steuern" uebernehmen
        return "operator" if cid == self.operator else "spectator"

    def connect(self, cid):
        if cid not in self.clients:
            self.clients.append(cid)
        return self.role(cid)

    def disconnect(self, cid):
        was_op = cid == self.operator
        if cid in self.clients:
            self.clients.remove(cid)
        if was_op:
            self._halt(None, release=False)
            self.last_seq = -1
            self.last_rx = None
            if self.operator is not None:
                self.events.append((self.operator, self._welcome(self.operator)))

    def _welcome(self, cid):
        return {"t": "welcome", "v": PROTOCOL_VERSION, "role": self.role(cid), "session": str(cid),
                "limits": {"rate_hz": 60}, "dry_run": True}

    # --- Nachrichten ---
    def handle(self, cid, msg, now):
        """Verarbeitet eine Nachricht, gibt die Antworten an diesen Client zurueck."""
        if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
            return [{"t": "error", "msg": "ungueltige Nachricht"}]
        t = msg["t"]
        if t == "hello":
            if msg.get("v") != PROTOCOL_VERSION:
                return [{"t": "error", "msg": f"Protokollversion {PROTOCOL_VERSION} erwartet"}]
            self.connect(cid)
            if cid == self.operator:
                self.last_seq = -1
            return [self._welcome(cid)]
        if t == "ping":
            return [{"t": "pong", "id": msg.get("id"), "ts": msg.get("ts")}]
        if t == "stop":
            if cid == self.operator:
                self._halt("stopped")
                self.desired_grip = self.grip
            return []
        if t == "pose":
            return self._pose(cid, msg, now)
        if t == "joints":
            return self._leader(cid, msg, now)
        return [{"t": "error", "msg": f"unbekannter Typ {t!r}"}]

    def _pose(self, cid, m, now):
        if cid != self.operator:
            return []
        seq, p, q, grip = m.get("seq"), m.get("p"), m.get("q"), m.get("grip")
        if (not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(m.get("clutch"), bool)
                or not isinstance(p, list) or len(p) != 3 or not all(_finite(v, 10) for v in p)
                or not isinstance(q, list) or len(q) != 4 or not all(_finite(v, 2) for v in q)
                or not _finite(grip, 10)):
            return [{"t": "error", "msg": "ungueltige Pose"}]
        n = math.sqrt(sum(v * v for v in q))
        if not 0.5 < n < 1.5:
            return [{"t": "error", "msg": "ungueltige Orientierung"}]
        if seq <= self.last_seq:
            return []                               # veraltet oder doppelt
        self.last_seq = seq
        self.last_rx = now
        q = tuple(v / n for v in q)
        p = tuple(float(v) for v in p)
        if self.reason in ("watchdog", "funkloch"):
            self.reason = None
        if self.reason != "stopped":
            self.desired_grip = K.grip_ticks(float(grip))
        clutch = m["clutch"] and m.get("track") == "normal"
        if not clutch:
            if self.engaged:
                self._halt(None, release=False)
            self.need_release = False
            if self.reason == "stopped":
                self.reason = None
            return []
        if self.need_release:
            return []
        heading, pitch, roll = phone_angles(q)
        if not self.engaged:
            if heading is None:
                return []                           # Handy zeigt senkrecht: keine Vorwaertsrichtung
            self.anchor = {"p": p, "heading": heading, "pitch": pitch, "roll": roll,
                           "pose": self.target, "roll_t": self.roll}
            self.engaged, self.mode = True, "pose"
            self.reason = None
            return []
        a = self.anchor
        d = tuple(pi - ai for pi, ai in zip(p, a["p"]))
        f = a["heading"]
        left = (f[2], 0.0, -f[0])
        uf, ul, uu = _dot(d, f), _dot(d, left), d[1]
        c, s = math.cos(self.cfg.camera_yaw), math.sin(self.cfg.camera_yaw)
        k = self.cfg.scale
        x0, y0, z0, phi0 = a["pose"]
        phi = phi0 - self.cfg.pitch_gain * (pitch - a["pitch"])
        self.desired = (x0 + k * (c * uf - s * ul), y0 + k * (s * uf + c * ul), z0 + k * uu, phi)
        if roll is not None and a["roll"] is not None:
            dr = max(-self.cfg.roll_limit, min(self.cfg.roll_limit, _wrap(roll - a["roll"])))
            want = a["roll_t"] + K.ROLL_SIGN * self.cfg.roll_gain * dr * K.TICKS_PER_RAD
            lo, hi = K.LIMITS[5]
            r0 = self.roll0
            span = self.cfg.roll_limit * K.TICKS_PER_RAD
            self.desired_roll = min(max(want, lo + K.JOINT_MARGIN, r0 - span), hi - K.JOINT_MARGIN, r0 + span)
        return []

    def _leader(self, cid, m, now):
        """Leader-Arm des Bedieners: {"t":"joints","seq":n,"clutch":bool,"j":[j1..j5 Ticks],"grip":0..1}.
        Gekuppelt wird nur, wenn der Leader nah am Arm steht (kein Sprung). Danach folgen die Gelenke mit
        begrenztem Tempo; Grenzen und Mindesthoehen setzt tick() durch."""
        if cid != self.operator:
            return []
        seq, j, grip = m.get("seq"), m.get("j"), m.get("grip")
        if (not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(m.get("clutch"), bool)
                or not isinstance(j, list) or len(j) != 5 or not all(_finite(v, 4095) and v >= 0 for v in j)
                or not _finite(grip, 1.5)):
            return [{"t": "error", "msg": "ungueltige Gelenkwerte"}]
        if seq <= self.last_seq:
            return []
        self.last_seq = seq
        self.last_rx = now
        if self.reason in ("watchdog", "funkloch"):
            self.reason = None
        want = {s: float(v) for s, v in zip(range(1, 6), j)}
        if not m["clutch"]:
            if self.engaged:
                self._halt(None, release=False)
            self.need_release = False
            if self.reason in ("stopped", "too_far"):
                self.reason = None
            return []
        if self.need_release:
            return []
        if not self.engaged:
            far = max(abs(want[s] - self.joints[s]) for s in range(1, 6)) / K.TICKS_PER_RAD
            if far > self.cfg.engage_tol:
                self.reason = "too_far"         # Bediener soll seinen Leader erst an den Arm angleichen
                return [{"t": "error", "msg": f"Leader {math.degrees(far):.0f} Grad vom Arm entfernt - erst angleichen"}]
            self.engaged, self.mode, self.reason = True, "joints", None
        self.desired_joints = want
        if self.reason != "stopped":
            self.desired_grip = K.grip_ticks(float(grip))
        return []

    def _tick_joints(self, dt, now):
        """Leader-Modus: jedes Gelenk mit begrenztem Tempo zum Ziel; Grenzen und Mindesthoehen pruefen."""
        cur = {s: float(self.joints[s]) for s in range(1, 6)}
        if self.engaged and self.desired_joints is not None:
            step = self.cfg.joint_rate * K.TICKS_PER_RAD * dt
            cand = {}
            for s in range(1, 6):
                lo, hi = K.LIMITS[s]
                goal = min(max(self.desired_joints[s], lo + K.JOINT_MARGIN), hi - K.JOINT_MARGIN)
                cand[s] = cur[s] + max(-step, min(step, goal - cur[s]))
            if K.joints_ok(cand) and K.heights(cand)[2] >= 0.0:
                cur = cand
            elif now - self.last_haptic >= self.cfg.haptic_interval and self.operator:
                self.last_haptic = now          # waere zu tief: stehen bleiben, Bediener spuert die Grenze
                self.events.append((self.operator, {"t": "haptic", "kind": "limit"}))
        self.grip = self.desired_grip
        self.roll = self.desired_roll = cur[5]
        self.joints = {**{s: int(round(v)) for s, v in cur.items()}, 6: int(round(self.grip))}
        self.target = self.desired = K.fk(cur)     # damit ein Wechsel zum Handy-Modus dort weitermacht

    def _halt(self, reason, release=True):
        self.engaged = False
        self.anchor = None
        self.desired = self.target
        self.desired_roll = self.roll
        if release:
            self.need_release = True
        if reason is not None or release:
            self.reason = reason

    # --- Takt ---
    def tick(self, now):
        dt = min(max(now - self.last_tick, 0.0), 0.05)
        self.last_tick = now
        if self.operator is not None and self.last_rx is not None and now - self.last_rx > self.cfg.watchdog_s:
            if self.engaged:
                # Funkloch: Arm haelt an der aktuellen Stelle, bleibt gekuppelt und folgt, sobald wieder
                # Pakete kommen (Wunsch des Nutzers 18.11.2026: Aussetzer sollen die Steuerung nicht beenden)
                if self.reason != "funkloch":
                    self.reason = "funkloch"
                    self.funkloch_n += 1
                cur = {s: float(self.joints[s]) for s in range(1, 6)}
                self.desired_joints = cur if self.mode == "joints" else self.desired_joints
                self.desired = self.target
                self.desired_roll = self.roll
                self.desired_grip = self.grip
            elif self.reason != "watchdog":
                self._halt("watchdog")
                self.desired_grip = self.grip
        if self.mode == "joints":
            self._tick_joints(dt, now)
            self.state_seq += 1
            return self.state()
        # Geschwindigkeit begrenzen
        x, y, z, phi = self.target
        dx, dy, dz = (a - b for a, b in zip(self.desired[:3], self.target[:3]))
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        step = self.cfg.v_max * dt
        f = 1.0 if dist <= step else step / dist
        dphi = self.desired[3] - phi
        mphi = self.cfg.phi_rate * dt
        stepped = (x + dx * f, y + dy * f, z + dz * f, phi + max(-mphi, min(mphi, dphi)))
        self.target, limited = K.safe_target(self.target, stepped)
        if not K.in_box(self.desired) and dist > 1e-4:
            limited = True
        if limited and self.engaged and now - self.last_haptic >= self.cfg.haptic_interval and self.operator:
            self.last_haptic = now
            self.events.append((self.operator, {"t": "haptic", "kind": "limit"}))
        mroll = self.cfg.roll_rate * K.TICKS_PER_RAD * dt
        self.roll += max(-mroll, min(mroll, self.desired_roll - self.roll))
        self.grip = self.desired_grip
        self.joints = self._joints()
        self.state_seq += 1
        return self.state()

    def _joints(self):
        j = K.solve(self.target)
        assert j is not None, "Zielpose unsicher - darf nicht vorkommen"
        j[5] = self.roll
        j[6] = self.grip
        return {s: int(round(v)) for s, v in j.items()}

    def state(self):
        return {"t": "state", "seq": self.state_seq, "ack": self.last_seq, "active": self.engaged, "mode": self.mode,
                "joints": [self.joints[s] for s in range(1, 7)], "reason": self.reason,
                "ee": [round(v, 4) for v in self.target], "dry_run": True,
                "funkloch": self.funkloch_n}

    def pop_events(self):
        ev, self.events = self.events, []
        return ev
