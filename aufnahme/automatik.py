"""Automatischer Aufnahmestart und -stopp fuer planbasierte Griffe. Reine Logik (testbar).

Start:  Runde bestaetigt UND Maske gruen (oder manuell bestaetigt) UND Greifer geschlossen, und das
        ununterbrochen seit 'countdown_s' Sekunden (einstellbar, 0 = sofort).
Stopp:  Greifer hat sich waehrend der Episode geoeffnet und wieder geschlossen, haelt ein Teil (deutlich
        offener als 'zu'), der Arm ist wieder ungefaehr auf Startpose-Hoehe (Schulter/Ellbogen/Handgelenk
        innerhalb 'hoehe_toleranz_grad') und seit 'halten_s' ruhig. Rueckfall: 'zeitlimit_s'.
Gelenkwerte in Servo-Schritten (4096 = 360 Grad). Greifer: kleiner Wert = geschlossen.
"""
from collections import deque

STEP_DEG = 360 / 4096


class Automatik:
    def __init__(self, cfg, greifer_zu):
        self.c = cfg
        self.zu = greifer_zu
        self.hist = deque()                 # (t, stellung)
        self.reset()

    def reset(self):
        self.recording = False
        self.start_pose = None
        self.t_start = None
        self.opened = False
        self.closed_on_part = False
        self.grund = ""
        self.ok_since = None                # seit wann alle Startbedingungen erfuellt sind
        self.closed = False

    def _still(self, now, seconds):
        pts = [s for t, s in self.hist if now - t <= seconds]
        if not self.hist or now - self.hist[0][0] < seconds or len(pts) < 2:
            return False
        for j in range(6):
            vals = [p[j] for p in pts]
            if (max(vals) - min(vals)) * STEP_DEG > self.c.get("ruhe_grad", 1.5):
                return False
        return True

    def update(self, now, stellung, bereit, maske_ok):
        """Neue Stellung. Gibt 'start', 'stop', 'zeitlimit' oder None zurueck."""
        self.now = now
        self.hist.append((now, list(stellung)))
        while self.hist and now - self.hist[0][0] > 5:
            self.hist.popleft()
        g = stellung[5]
        zu_tol = self.c.get("greifer_zu_toleranz", 40)
        if not self.recording:
            closed = self.closed = g <= self.zu + zu_tol
            missing = [n for n, ok in (("Runde nicht bestaetigt", bereit), ("Maske nicht gruen", maske_ok),
                                       ("Greifer nicht geschlossen", closed)) if not ok]
            self.grund = ", ".join(missing)
            if missing or not self.c.get("an", True):
                self.ok_since = None
                return None
            if self.ok_since is None:
                self.ok_since = now
            if now - self.ok_since >= self.c.get("countdown_s", 2.0) - 1e-9:
                self.ok_since = None
                self.recording, self.start_pose, self.t_start = True, list(stellung), now
                self.opened = self.closed_on_part = False
                return "start"
            return None
        # waehrend der Aufnahme
        if g > self.zu + 200:
            self.opened = True
        holds = self.opened and g > self.zu + self.c.get("greifer_haelt_min", 60) and g < self.zu + 2000
        if self.opened and holds and self._closing_recently(now):
            self.closed_on_part = True
        tol = self.c.get("hoehe_toleranz_grad", 10)
        height_ok = all(abs(stellung[j] - self.start_pose[j]) * STEP_DEG <= tol for j in (1, 2, 3))
        if self.closed_on_part and holds and height_ok and self._still(now, self.c.get("halten_s", 1.5)):
            self.recording = False
            return "stop"
        if now - self.t_start > self.c.get("zeitlimit_s", 30):
            self.recording = False
            return "zeitlimit"
        return None

    @property
    def rest(self):
        """Restzeit des Start-Countdowns (s) oder None."""
        if self.ok_since is None:
            return None
        return max(0.0, self.c.get("countdown_s", 2.0) - (self.now - self.ok_since))

    def _closing_recently(self, now):
        """Greifer ist in den letzten 2 s um mindestens 150 Schritte zugegangen."""
        pts = [s[5] for t, s in self.hist if now - t <= 2]
        return len(pts) >= 2 and max(pts) - pts[-1] >= 150

    def status_text(self):
        if self.recording:
            parts = ["Greifer " + ("haelt ein Teil" if self.closed_on_part else "offen" if self.opened else "noch zu")]
            return "● Aufnahme · " + ", ".join(parts)
        if self.ok_since is not None:
            return f"Alles bereit · Start in {self.rest:.1f} s"

        return "Start, sobald: " + (self.grund or "alles bereit")
