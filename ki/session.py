"""Arbeitssitzung eines Arms fuer Module (Agentic-Skill-Studio, Orchestrator).

Vor Ort freigegeben faehrt der Arm hoch (KI-Quelle) und HAELT seine Stellung. Module koennen dann
Faehigkeiten (trainierte Modelle) fuer eine Zeit ausfuehren lassen; danach haelt der Arm wieder die
letzte Stellung. Zwischen zwei Faehigkeiten legt er sich nicht ab. Stop / Sitzung beenden = ablegen.

Diese Klasse sendet die Halte-Ziele mit 30 Hz, solange kein KI-Fahrer laeuft (ohne Ziele wuerde der
Worker den Arm nach 1 s ablegen)."""
import threading, time

STILL_S = 0.3        # so lange darf das Modell ohne neues Ziel sein, dann haelt die Sitzung wieder


class ArmSession:
    def __init__(self, key, who, send_target, get_state, period=1 / 30):
        self.key, self.who = key, who
        self.send_target, self.get_state, self.period = send_target, get_state, period
        self.hold = None
        self.client = None             # laufender KI-Fahrer (ki.client.DriverClient) oder None
        self.halt = threading.Event()
        self.busy = threading.Lock()   # immer nur eine Faehigkeit gleichzeitig
        self.started = time.time()
        self.runs = 0
        threading.Thread(target=self._loop, daemon=True, name=f"sitzung-{key}").start()

    def driving(self):
        c = self.client
        return c is not None and not c.halt.is_set() and c.error is None

    def model_sends(self):
        """Das Modell schickt gerade selbst Ziele. Solange es laedt oder rechnet (erste Antwort > 1 s),
        haelt die Sitzung weiter - sonst legt der Worker den Arm nach 1 s ohne Ziele ab."""
        c = self.client
        if not self.driving() or c.last_sent is None:
            return False
        at = getattr(c, "sent_at", None)
        return at is None or time.monotonic() - at < STILL_S

    def _loop(self):
        while not self.halt.is_set():
            if self.model_sends():
                self.hold = list(self.client.last_sent)
            else:
                if self.hold is None:
                    state = self.get_state()
                    if state is not None:
                        self.hold = list(state)
                if self.hold is not None:
                    self.send_target(self.hold)
            self.halt.wait(self.period)

    def run_model(self, make_client, seconds, ready_timeout=60):
        """Laesst ein Modell `seconds` lang fahren; danach haelt der Arm. make_client() -> gestarteter DriverClient."""
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Auf diesem Arm laeuft schon eine Faehigkeit")
        try:
            client = make_client()
            self.client = client
            if getattr(client, "paused", None) is not None:
                client.paused.clear()         # vorgeladenes Modell: erst jetzt Ziele senden
            if not client.ready.wait(ready_timeout) or client.error:
                raise RuntimeError(f"KI-Fahrer startet nicht: {client.error or 'Zeitueberschreitung'}")
            end = time.monotonic() + float(seconds)
            while time.monotonic() < end and not self.halt.is_set() and client.error is None:
                time.sleep(0.05)
            err = client.error
            client.halt.set()           # ab jetzt haelt die Sitzung wieder
            if client.last_sent is not None:
                self.hold = list(client.last_sent)
            threading.Thread(target=client.stop, daemon=True).start()
            self.runs += 1
            if self.halt.is_set():
                raise RuntimeError("Sitzung wurde beendet (Stop)")
            if err:
                raise RuntimeError(f"KI-Fahrer: {err}")
            return {"schritte": client.stats["requests"], "uebersprungen": client.stats["skipped"],
                    "sekunden": float(seconds)}
        finally:
            self.client = None
            self.busy.release()

    def move_to(self, target, step, joints=None, tol=25, timeout=30, settle=0.4):
        """Fest programmierte Fahrt: Halte-Ziel schrittweise (step je Takt) zum Ziel schieben.
        joints: nur diese Gelenk-Indizes (0..5) bewegen, z. B. [5] fuer den Greifer.
        Gibt (erreicht, ist_stellung) zurueck. Bleibt der Arm zurueck (Hindernis), haelt er dort, wo er ist."""
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Auf diesem Arm laeuft schon eine Bewegung")
        try:
            if self.hold is None:
                state = self.get_state()
                if state is None:
                    raise RuntimeError("Keine aktuelle Stellung vom Arm (faehrt er noch hoch?)")
                self.hold = list(state)
            goal = [int(t) if joints is None or i in joints else int(h)
                    for i, (t, h) in enumerate(zip(target, self.hold))]
            end = time.monotonic() + timeout
            while self.hold != goal:
                if self.halt.is_set():
                    raise RuntimeError("Sitzung beendet (Stop)")
                self.hold = [h + max(-step, min(step, g - h)) for h, g in zip(self.hold, goal)]
                time.sleep(self.period)
                state = self.get_state()
                # Greifer (Index 5) ausgenommen: am Teil bleibt er absichtlich zurueck, der Worker begrenzt die Kraft
                if state is not None and max(abs(h - s) for h, s in zip(self.hold[:5], state[:5])) > 250:
                    self.hold = list(state)            # Arm kommt nicht nach: dort halten, nicht weiterdruecken
                    return False, state
                if time.monotonic() > end:
                    raise RuntimeError("Fahrt dauert zu lange")
            time.sleep(settle)
            state = self.get_state() or self.hold
            return max(abs(g - s) for g, s in zip(goal, state)) <= tol, state
        finally:
            self.busy.release()

    def move_smooth(self, target, seconds, joints=None, settle=0.3, lag=250, tol=80):
        """Fluessige Fahrt: alle Gelenke starten und kommen gleichzeitig an, weiches Anfahren und Abbremsen
        (Minimum-Jerk-Profil). Gibt (erreicht, ist_stellung) zurueck; bleibt der Arm zurueck (Hindernis), haelt er."""
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("Auf diesem Arm laeuft schon eine Bewegung")
        try:
            if self.hold is None:
                state = self.get_state()
                if state is None:
                    raise RuntimeError("Keine aktuelle Stellung vom Arm (faehrt er noch hoch?)")
                self.hold = list(state)
            start = list(self.hold)
            goal = [float(t) if joints is None or i in joints else float(h)
                    for i, (t, h) in enumerate(zip(target, start))]
            n = max(1, int(round(float(seconds) / self.period)))
            t0 = time.monotonic()
            for i in range(1, n + 1):
                if self.halt.is_set():
                    raise RuntimeError("Sitzung beendet (Stop)")
                s = i / n
                a = s * s * s * (10 - 15 * s + 6 * s * s)
                self.hold = [int(round(st + (g - st) * a)) for st, g in zip(start, goal)]
                pause = t0 + i * self.period - time.monotonic()      # fester Takt, ohne Aufsummieren
                if pause > 0:
                    time.sleep(pause)
                state = self.get_state()
                if state is not None and max(abs(h - x) for h, x in zip(self.hold[:5], state[:5])) > lag:
                    self.hold = list(state)
                    return False, state
            time.sleep(settle)
            state = self.get_state() or self.hold
            # tol grosszuegig: Schulter/Ellbogen haengen unter Last ein paar Grad durch (z. B. 2047 -> 2095)
            return max(abs(g - x) for g, x in zip(goal[:5], state[:5])) <= tol, state
        finally:
            self.busy.release()

    def stop(self):
        self.halt.set()
        c = self.client
        if c is not None:
            threading.Thread(target=c.stop, daemon=True).start()

    def info(self):
        return {"arm": self.key, "von": self.who, "aktiv": not self.halt.is_set(),
                "faehrt_modell": self.driving(), "haelt": not self.driving(), "laeufe": self.runs,
                "seit_s": round(time.time() - self.started)}
