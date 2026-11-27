"""Anschlag-Kalibrierung: jedes Gelenk wird von Hand an seine beiden mechanischen Anschlaege gedrueckt.

Nur Lesen: Positionen, Grenzen, Offset und Drehmoment-Schalter werden gelesen, nie geschrieben.
Die Anschlaege von Leader und Follower ergeben eine genaue Zuordnung je Gelenk:
  Gelenk 1-5: Verschiebung = Mittel der Differenzen an beiden Anschlaegen (gleiche Mechanik -> Steigung 1)
  Greifer   : linear von Leader [zu, auf] auf Follower [zu, auf]
Die Zuordnung gilt erst, wenn sie im Fenster ausdruecklich aktiviert wurde (Datei stopmap_<follower>.json),
und nur solange die Offsets im EEPROM noch dieselben sind wie bei der Messung.
"""
import json, os, statistics, time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
CALDIR = os.path.join(HERE, "calibration")

JOINTS = {1: "Basis", 2: "Schulter", 3: "Ellbogen", 4: "Handgelenk-Beugung", 5: "Handgelenk-Drehung", 6: "Greifer"}
ORDER = [1, 6, 5, 4, 3, 2]       # aus der Ablage: Basis, Greifer, Drehung frei beweglich, Schulter zuletzt
PHASES = ("A", "B", "A", "B")    # zweimal hin und her -> Wiederholgenauigkeit
STABLE_S = 0.8                   # so lange ruhig halten
STABLE_SPREAD = 4                # Schritte Schwankung erlaubt (~0,35 Grad)
NEAR_END = 0.25                  # Anteil der Spanne: so nah an einer Grenze muss ein Anschlag liegen
REPEAT_OK = 6                    # Schritte (~0,5 Grad) Unterschied zwischen erster und zweiter Messung
EXTREME_TOL = 8                  # Schritte (~0,7 Grad): so nah am weitesten je gehaltenen Punkt muss ein Anschlag sein
EXTREME_TOL_JOINT = {6: 30}      # Greifer ist aus Kunststoff und federt beim Zudruecken nach (~2,6 Grad)
HOLD_S = 0.3                     # nur Stellungen, die so lange ruhig gehalten wurden, zaehlen als "schon weiter"
FULL_RANGE = 4000                # Grenzen 0..4095 = im EEPROM nicht begrenzt (Handgelenk-Drehung)
FREE_LEAVE = 512                 # ohne Grenzen: so weit (45 Grad) vom Start weg zaehlt als "an einem Ende"
FREE_SAME = 150                  # ohne Grenzen: so nah (13 Grad) am ersten Wert = dasselbe Ende
FREE_SPAN = 1024                 # ohne Grenzen: mindestens 90 Grad zwischen beiden Anschlaegen
WRAP_JUMP = 2048                 # Sprung zwischen zwei Messungen: Bereich laeuft ueber 0/4095
STEP_DEG = 360 / 4096
MID_POS = 2047                   # Mitte (wie so101.MID)

HINTS = {
    1: "Basis: den ganzen Arm (eingeklappt) waagerecht bis zum Anschlag drehen.",
    6: "Greifer: ganz zu (Backen aneinander) und ganz auf bis zum Anschlag.",
    5: "Handgelenk-Drehung (direkt hinter dem Greifer): den Greifer um seine Laengsachse bis zum Anschlag drehen.",
    4: "Handgelenk-Beugung: Hand ganz einklappen (Ablage) und ganz zur anderen Seite.",
    3: "Ellbogen: Unterarm ganz einklappen (Ablage) und ganz aufklappen. Unterarm dabei festhalten.",
    2: "Schulter: Arm unten in der Ablage, dann den ganzen Arm ganz nach oben bis zum Anschlag. Festhalten!",
}


class JointCapture:
    """Erkennt nacheinander die vier Anschlag-Messungen eines Gelenks (A, B, A, B).
    lim = (lo, hi) aus dem EEPROM: dient nur zur Plausibilitaet ("liegt nahe an einem Ende").
    Ein Wert zaehlt nur, wenn das Gelenk an dieser Seite nie weiter war (ueber einen Anschlag kommt man nicht)."""
    def __init__(self, lim, joint=None):
        lo, hi = lim
        self.tol = EXTREME_TOL_JOINT.get(joint, EXTREME_TOL)
        self.hold = deque()              # die letzten HOLD_S Sekunden, fuer min_seen/max_seen
        self.lo, self.hi = lo, hi
        self.span = max(1, hi - lo)
        self.free = self.span >= FULL_RANGE      # keine Grenzen bekannt -> Enden aus der Bewegung ableiten
        self.values = []                 # gemessene Anschlaege in Reihenfolge
        self.end_of = []                 # "lo" oder "hi" je Messung
        self.window = deque()
        self.need_leave = False          # nach einer Messung erst wegbewegen
        self.start = None                # erste Position (nur ohne Grenzen gebraucht)
        self.last = None
        self.min_seen = self.max_seen = None
        self.recent = deque(maxlen=3)
        self.short = False               # haelt ruhig, war an dieser Seite aber schon weiter
        self.wrapped = False             # Sprung bei Gelenk mit Grenzen: so nicht messbar
        self.turns = 0                   # freie Gelenke: wie oft ueber 0/4095 gelaufen (Werte laufen weiter, z. B. -120)

    @property
    def done(self):
        return len(self.values) >= len(PHASES)

    def _first(self, end):
        for v, e in zip(self.values, self.end_of):
            if e == end:
                return v
        return None

    def _end(self, pos):
        if not self.free:
            if abs(pos - self.lo) <= NEAR_END * self.span:
                return "lo"
            if abs(pos - self.hi) <= NEAR_END * self.span:
                return "hi"
            return None
        for end in ("lo", "hi"):                     # bekannte Enden: nahe am ersten Wert
            v = self._first(end)
            if v is not None and abs(pos - v) <= FREE_SAME:
                return end
        if not self.values:
            if pos <= self.start - FREE_LEAVE:
                return "lo"
            if pos >= self.start + FREE_LEAVE:
                return "hi"
            return None
        a, e = self.values[0], self.end_of[0]
        if e == "lo" and pos >= a + FREE_SPAN:
            return "hi"
        if e == "hi" and pos <= a - FREE_SPAN:
            return "lo"
        return None

    def wanted_end(self):
        """None = beliebiges Ende (erste Messung), sonst das Ende, das als naechstes kommen muss."""
        if not self.end_of:
            return None
        first = self.end_of[0]
        other = "hi" if first == "lo" else "lo"
        return first if len(self.values) % 2 == 0 else other

    def feed(self, pos, now):
        """Gibt den gemessenen Wert zurueck, wenn gerade ein Anschlag erkannt wurde, sonst None."""
        if self.done or pos is None or self.wrapped:
            return None
        if self.last is not None and abs(pos - self.last) > WRAP_JUMP:
            if not self.free:            # mit Grenzen kann das nicht sein: lieber nicht messen
                self.wrapped = True
                return None
            self.turns += -1 if pos > self.last else 1     # ueber 0/4095 gelaufen: weiterzaehlen statt springen
        self.last = pos
        pos += self.turns * 4096
        if self.start is None:
            self.start = pos
        self.recent.append(pos)                      # Median aus 3: ein einzelner Fehlwert verschiebt nichts
        smooth = sorted(self.recent)[len(self.recent) // 2]
        self._track_held(smooth, now)
        end = self._end(pos)
        if self.need_leave:
            if end != self.end_of[-1]:   # Gelenk hat das letzte Ende verlassen
                self.need_leave = False
                self.window.clear()
            return None
        want = self.wanted_end()
        if end is None or (want is not None and end != want):
            self.window.clear()
            self.short = False
            return None
        w = self.window
        w.append((now, pos))
        while len(w) > 1 and now - w[1][0] >= STABLE_S:     # nur die letzten STABLE_S Sekunden (mind. so lang)
            w.popleft()
        while max(p for _, p in w) - min(p for _, p in w) > STABLE_SPREAD:   # Bewegung: neu anfangen
            w.popleft()
        if now - w[0][0] < STABLE_S * 0.95:
            return None
        value = int(round(statistics.median(p for _, p in w)))
        extreme = self.min_seen if end == "lo" else self.max_seen
        self.short = extreme is not None and abs(value - extreme) > self.tol
        if self.short:                   # vor dem Anschlag stehengeblieben
            return None
        self.values.append(value)
        self.end_of.append(end)
        self.window.clear()
        self.need_leave = not self.done
        return value

    def _track_held(self, pos, now):
        """Weitester Punkt je Seite, aber nur aus ruhig gehaltenen Stellungen: kurzes Ueberdruecken
        oder Nachfedern beim Anschlagen zaehlt nicht, sonst kaeme man nie wieder 'weit genug'."""
        h = self.hold
        h.append((now, pos))
        while len(h) > 1 and now - h[1][0] >= HOLD_S:
            h.popleft()
        while max(p for _, p in h) - min(p for _, p in h) > STABLE_SPREAD:
            h.popleft()
        if now - h[0][0] < HOLD_S * 0.95:
            return
        v = int(round(statistics.median(p for _, p in h)))
        self.min_seen = v if self.min_seen is None else min(self.min_seen, v)
        self.max_seen = v if self.max_seen is None else max(self.max_seen, v)

    def missing(self):
        """Wie viele Schritte noch bis zum weitesten gehaltenen Punkt dieser Seite (nur wenn short)."""
        if not self.short or not self.window:
            return 0
        pos = self.window[-1][1]
        end = self.end_of[-1] if self.need_leave else (self.wanted_end() or self._end(pos))
        extreme = self.min_seen if end == "lo" else self.max_seen
        return 0 if extreme is None else abs(pos - extreme)

    def progress(self):
        """0..1: wie lange schon ruhig am richtigen Ende gehalten."""
        if not self.window:
            return 0.0
        return min(1.0, (self.window[-1][0] - self.window[0][0]) / STABLE_S)

    def result(self):
        """{'lo', 'hi', 'repeat'} nach vier Messungen."""
        lo_vals = [v for v, e in zip(self.values, self.end_of) if e == "lo"]
        hi_vals = [v for v, e in zip(self.values, self.end_of) if e == "hi"]
        repeat = max(abs(lo_vals[0] - lo_vals[-1]), abs(hi_vals[0] - hi_vals[-1]))
        return {"lo": sum(lo_vals) / len(lo_vals), "hi": sum(hi_vals) / len(hi_vals),
                "lo_all": lo_vals, "hi_all": hi_vals, "repeat": repeat, "ok": repeat <= REPEAT_OK}


REZERO_MIN = 12                  # Schritte (~1 Grad): darunter lohnt sich kein neuer Nullpunkt


def rezero_plan(result, offset):
    """Neuer Nullpunkt aus beiden Anschlaegen: die Mitte wird 2047, die Anschlaege werden die Grenzen.
    result: JointCapture.result() (Werte koennen bei freien Gelenken unter 0 / ueber 4095 liegen),
    offset: aktueller Offset im EEPROM. -> dict(d, offset, lo, hi, needed) oder None, wenn nicht moeglich.
    Servo: angezeigt = mechanisch - Offset. Neuer Offset = alter + d verschiebt alle Werte um -d."""
    lo, hi = result["lo"], result["hi"]
    if hi - lo >= 4090:
        return None                                      # (fast) volle Umdrehung: keine Mitte bestimmbar
    d = int(round((lo + hi) / 2)) - MID_POS
    new_off = ((offset + d + 2048) % 4096) - 2048        # gleichwertiger Offset im Bereich -2048..2047
    if new_off == -2048:
        return None
    nlo, nhi = int(round(lo - d)), int(round(hi - d))
    if not (0 <= nlo < nhi <= 4095):
        return None
    crosses = lo < 0 or hi > 4095
    return {"d": d, "offset": new_off, "lo": nlo, "hi": nhi, "needed": crosses or abs(d) >= REZERO_MIN}


def unwrap_into(pos, lo, hi):
    """Rohwert 0..4095 in den (evtl. ueber 0/4095 durchgezaehlten) Bereich lo..hi legen."""
    best = pos
    for k in (-1, 0, 1, 2):
        v = pos + k * 4096
        if lo - 200 <= v <= hi + 200:
            return v
    return best


def shift_pose_value(v, d):
    """Gespeicherte Stellung (alter Nullpunkt) in die neue umrechnen."""
    return (int(v) - d) % 4096


def shift_saved_poses(arm, joint, d, caldir=None, config_path=None):
    """Ablage- und Startstellung eines Arms fuer ein Gelenk auf den neuen Nullpunkt umrechnen.
    Aendert nur die eine Zahl, Formatierung von config.json bleibt. -> Liste der geaenderten Dateien."""
    import re
    changed = []
    sp = os.path.join(caldir or CALDIR, f"{arm}_start_pose.json")
    pose = load(sp)
    if pose and str(joint) in pose:
        pose[str(joint)] = shift_pose_value(pose[str(joint)], d)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(pose, f)
        changed.append(sp)
    cp = config_path or os.path.join(HERE, "config.json")
    try:
        text = open(cp, encoding="utf-8").read()
    except OSError:
        return changed
    pat = re.compile(r'("%s"\s*:\s*\{[^{}]*?"rest_pose"\s*:\s*\{[^}]*?"%d"\s*:\s*)(\d+)' % (re.escape(arm), joint))
    m = pat.search(text)
    if m:
        text = text[:m.start(2)] + str(shift_pose_value(m.group(2), d)) + text[m.end(2):]
        with open(cp, "w", encoding="utf-8") as f:
            f.write(text)
        changed.append(cp)
    return changed


GRIP_FIX_MAX_DEG = 8.0           # mehr als 8 Grad Zusatz waere kein Feinabgleich mehr
GRIP_LIMIT_MARGIN = 5            # EEPROM-Untergrenze: so viel Luft unter dem tiefsten Ziel


def grip_path(follower, caldir=None):
    return os.path.join(caldir or CALDIR, f"grip_{follower}.json")


def save_grip_fix(follower, deg, closed, caldir=None):
    """Greifer-Feinkorrektur: Leader ganz zu -> Follower um deg Grad weiter zu.
    closed: 'zu'-Ziel ohne Korrektur (EEPROM-Untergrenze vor dem Absenken), damit die Zuordnung
    nicht wandert, wenn die Untergrenze fuer die Korrektur abgesenkt wird."""
    deg = max(0.0, min(GRIP_FIX_MAX_DEG, float(deg)))
    data = {"follower": follower, "close_deg": deg, "steps": int(round(deg / STEP_DEG)), "closed": int(closed),
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(grip_path(follower, caldir), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return data


def grip_target(value, a, b, c, d, fix=None):
    """Leader-Greifer value (zu=a, auf=b) -> Follower (zu=c, auf=d), plus Feinkorrektur:
    am 'zu'-Ende volle Korrektur, zum 'auf'-Ende hin auf 0 auslaufend."""
    t = c + (value - a) * (d - c) / (b - a) if b != a else value
    steps = (fix or {}).get("steps") or 0
    if steps and d != c:
        frac = max(0.0, min(1.0, (d - t) / (d - c)))
        t -= steps * frac
    return t


def stops_path(arm, caldir=None):
    return os.path.join(caldir or CALDIR, f"stops_{arm}.json")


def map_path(follower, caldir=None):
    return os.path.join(caldir or CALDIR, f"stopmap_{follower}.json")


def save_stops(arm, joints, offsets, caldir=None):
    data = {"arm": arm, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "offsets": {str(s): o for s, o in offsets.items()},
            "joints": {str(s): r for s, r in joints.items()}}
    os.makedirs(caldir or CALDIR, exist_ok=True)
    with open(stops_path(arm, caldir), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return data


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def align_path(follower, caldir=None):
    return os.path.join(caldir or CALDIR, f"align_{follower}.json")


def wrap_diff(d):
    """Differenz zweier Servowerte auf -2048..2047 (kuerzester Weg ueber 0/4095)."""
    return ((d + 2048) % 4096) - 2048


def save_align(follower, joint, leader_pos, follower_pos, leader_offset, follower_offset, caldir=None):
    """'Gleiche Stellung': beide Arme von Hand gleich ausgerichtet -> Versatz Leader->Follower fuer ein Gelenk.
    Gilt nur, solange die Offsets dieses Gelenks unveraendert sind."""
    path = align_path(follower, caldir)
    data = load(path) or {"follower": follower, "joints": {}}
    data["joints"][str(joint)] = {"shift": wrap_diff(int(round(follower_pos - leader_pos))),
                                  "leader_pos": leader_pos, "follower_pos": follower_pos,
                                  "leader_offset": int(leader_offset), "follower_offset": int(follower_offset),
                                  "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return data["joints"][str(joint)]


def crosses_zero(r):
    """Anschlaege liegen auf beiden Seiten von 0/4095 (nur bei freien Gelenken moeglich)."""
    return r["lo"] < 0 or r["hi"] > 4095


USE_REF_SHIFT = True     # Senkrecht-Bezug vor Anschlag-Mitte (Greiferstellung passt zum Leader)


def build_map(leader, follower, align=None):
    """leader/follower: Inhalt von stops_<arm>.json, align: Inhalt von align_<follower>.json (optional).
    Gibt die Zuordnung samt Guete zurueck. Ein Abgleich 'gleiche Stellung' ersetzt die Anschlag-Mitte
    fuer sein Gelenk (z. B. Handgelenk-Drehung: Leader-Griff und Follower-Greifer haben andere Anschlaege)."""
    joints = {}
    lo_off = {str(k): int(v) for k, v in (leader.get("offsets") or {}).items()}
    fo_off = {str(k): int(v) for k, v in (follower.get("offsets") or {}).items()}
    for key in JOINTS:
        s = str(key)
        l, f = leader["joints"].get(s), follower["joints"].get(s)
        a = (align or {}).get("joints", {}).get(s)
        if a and (a["leader_offset"] != lo_off.get(s) or a["follower_offset"] != fo_off.get(s)):
            a = None                                     # Nullpunkt seit dem Abgleich geaendert -> ungueltig
        if key != 6 and f and crosses_zero(f):          # Follower-Ziele muessen 0..4095 sein
            joints[s] = {"kind": "blocked", "reason": "erst Nullpunkt setzen (Bereich ueber 0/4095)"}
            continue
        lrange = [l["lo"], l["hi"]] if key != 6 and l and crosses_zero(l) else None   # Leader: Werte durchzaehlen
        if a and key != 6:
            joints[s] = {"kind": "shift", "shift": a["shift"], "mismatch": 0, "source": "gleiche Stellung"}
            if lrange:
                joints[s]["leader_range"] = lrange
            continue
        # 'Senkrecht'-Bezug (ref) wird NICHT mehr als Versatz genutzt: er verschob die Drehung gegen die
        # Anschlaege, der Follower erreichte dann seinen Anschlag nicht. Anschlag passt auf Anschlag.
        if USE_REF_SHIFT and key != 6 and l and f and l.get("ref") is not None and f.get("ref") is not None:
            lref = unwrap_into(int(round(l["ref"])), *lrange) if lrange else l["ref"]
            joints[s] = {"kind": "shift", "shift": int(round(f["ref"] - lref)), "mismatch": 0, "source": "senkrecht"}
            if lrange:
                joints[s]["leader_range"] = lrange
            continue
        if not l or not f:
            continue
        if key == 6:
            joints[s] = {"kind": "linear", "leader": [l["lo"], l["hi"]], "follower": [f["lo"], f["hi"]]}
        else:
            d_lo, d_hi = f["lo"] - l["lo"], f["hi"] - l["hi"]
            joints[s] = {"kind": "shift", "shift": round((d_lo + d_hi) / 2, 1),
                         "mismatch": round(abs(d_hi - d_lo), 1)}      # unterschiedliche Spannen -> Restfehler/2
            if lrange:
                joints[s]["leader_range"] = lrange
    return {"leader": leader["arm"], "follower": follower["arm"], "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "leader_offsets": leader["offsets"], "follower_offsets": follower["offsets"], "joints": joints}


def activate(m, caldir=None):
    with open(map_path(m["follower"], caldir), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)


def deactivate(follower, caldir=None):
    try:
        os.remove(map_path(follower, caldir))
    except FileNotFoundError:
        pass


def usable_map(follower, leader_offsets, follower_offsets, caldir=None):
    """Aktive Zuordnung, wenn vorhanden und die Offsets seitdem unveraendert sind. Sonst (None, grund)."""
    m = load(map_path(follower, caldir))
    if m is None:
        return None, "keine Anschlag-Zuordnung aktiv"
    norm = lambda d: {str(k): int(v) for k, v in (d or {}).items()}
    if norm(m["leader_offsets"]) != norm(leader_offsets) or norm(m["follower_offsets"]) != norm(follower_offsets):
        return None, "Anschlag-Zuordnung NICHT verwendet: Offsets im EEPROM haben sich seit der Messung geaendert"
    return m, "Anschlag-Zuordnung aktiv vom " + m.get("time", "?")


def apply(m, s, value):
    """Leaderwert -> Followerwert fuer Gelenk s (ohne Begrenzung; die macht clamp())."""
    j = m["joints"].get(str(s)) if m else None
    if j is None or j["kind"] == "blocked":
        return value
    if j["kind"] == "shift":
        if j.get("leader_range"):                       # Leader-Bereich ueber 0/4095: erst durchzaehlen
            value = unwrap_into(value, *j["leader_range"])
        return value + j["shift"]
    (a, b), (c, d) = j["leader"], j["follower"]
    return c + (value - a) * (d - c) / (b - a) if b != a else value
