"""ROS-Seite des KI-Fahrers: startet ki.driver in der KI-Umgebung, schickt mit 30 Hz Bilder + Ist-Stellung
und gibt begrenzte Gelenkziele weiter. Tempo-Begrenzung hier, Sicherheit (Grenzen, Stop, Ablegen) im Worker."""
import json, os, subprocess, threading, time
from . import HERE, KI_PYTHON
from .episodes import FPS, SIZE

SLOW_DEG_S = 90.0              # hoechstens so schnell je Gelenk. Deutlich langsamer als vorgefuehrt verwirrt
                               # das Modell (es plant fuer das Tempo der Aufnahmen); 45 Grad/s war zu langsam.
DONE_HOLD_S = 2.0              # Modell gilt als fertig, wenn seine Ziele so lange (fast) stillstehen ...
DONE_TOL_DEG = 2.0             # ... innerhalb dieser Schwankung je Gelenk ...
DONE_MOVED_DEG = 15.0          # ... nachdem es sich vorher wirklich bewegt hat
MAX_RUN_S = 60.0               # spaetestens dann ist ein Lauf vorbei
STEPS_PER_DEG = 4096 / 360.0


def limit_step(last, target, max_step):
    """Jedes Gelenk hoechstens max_step Servo-Schritte vom letzten gesendeten Ziel entfernt."""
    if last is None:
        return list(target)
    return [int(l + max(-max_step, min(max_step, t - l))) for l, t in zip(last, target)]


class FinishDetector:
    """Ein VLA weiss nicht, wann es fertig ist; es regelt endlos weiter (Zittern). Erkannt wird das Ende daran,
    dass die Ziele des Modells nach einer echten Bewegung eine Weile stillstehen - so wie am Ende jeder Aufnahme."""
    def __init__(self, hold_s=DONE_HOLD_S, tol_deg=DONE_TOL_DEG, moved_deg=DONE_MOVED_DEG, max_s=MAX_RUN_S):
        self.hold_s, self.tol = hold_s, tol_deg * STEPS_PER_DEG
        self.moved_steps, self.max_s = moved_deg * STEPS_PER_DEG, max_s
        self.first, self.t0, self.moved = None, None, False
        self.window = []

    def feed(self, action, now):
        """Gibt None, 'fertig' oder 'zeitgrenze' zurueck."""
        if self.first is None:
            self.first, self.t0 = list(action), now
        if not self.moved and max(abs(a - b) for a, b in zip(action, self.first)) > self.moved_steps:
            self.moved = True
        self.window.append((now, list(action)))
        while self.window and now - self.window[0][0] > self.hold_s:
            self.window.pop(0)
        if self.max_s and now - self.t0 > self.max_s:
            return "zeitgrenze"
        if self.moved and self.window and now - self.window[0][0] >= self.hold_s * 0.95:
            spread = max(max(v[j] for _, v in self.window) - min(v[j] for _, v in self.window) for j in range(len(action)))
            if spread <= self.tol:
                return "fertig"
        return None


class DriverClient:
    def __init__(self, model_dir, task, get_frames, get_state, send_target, log=print,
                 python=KI_PYTHON, popen=subprocess.Popen, deg_per_s=SLOW_DEG_S, cv2=None, on_done=None,
                 finish=None):
        self.model_dir, self.task = model_dir, task
        self.get_frames, self.get_state, self.send_target, self.log = get_frames, get_state, send_target, log
        self.python, self.popen, self.cv2 = python, popen, cv2
        self.max_step = max(1, int(deg_per_s * STEPS_PER_DEG / FPS))
        self.proc = None
        self.halt = threading.Event()
        self.paused = threading.Event()   # gesetzt: Modell wartet (z. B. bis der Arm in der Startpose steht)
        self.ready = threading.Event()
        self.error = None
        self.last_sent = None
        self.sent_at = None               # monotonic: letztes gesendetes Ziel (die Sitzung haelt, solange keins kommt)
        self.stats = {"requests": 0, "ms": 0.0, "skipped": 0}
        self.on_done = on_done            # on_done(grund): Modell fertig oder Zeitgrenze (einmal)
        self.finish = finish if finish is not None else (FinishDetector() if on_done else None)
        self.done = None

    def start(self):
        self.proc = self.popen([self.python, "-m", "ki.driver", self.model_dir], cwd=HERE, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._run, daemon=True, name="ki-fahrer").start()
        return self

    def _read(self):
        line = self.proc.stdout.readline()
        if not line:
            raise EOFError("KI-Fahrer beendet")
        return json.loads(line)

    def _run(self):
        try:
            hello = self._read()
            if "error" in hello:
                raise RuntimeError(hello["error"])
            self.cameras = hello.get("cameras") or []
            self.ready.set()
            self.log(f"KI-Fahrer bereit ({hello.get('method')}, Kameras {self.cameras})")
            period, nxt = 1.0 / FPS, time.monotonic()
            while not self.halt.is_set():
                if self.paused.is_set():
                    self.halt.wait(period)
                    nxt = time.monotonic()
                    continue
                self.step()
                nxt += period
                delay = nxt - time.monotonic()
                if delay < -period:
                    nxt = time.monotonic()
                elif delay > 0:
                    self.halt.wait(delay)
        except Exception as exc:
            if not self.halt.is_set():
                self.error = str(exc)
                self.log(f"KI-Fahrer FEHLER: {exc} · ohne neue Ziele legt sich der Arm nach 1 s ab")
        finally:
            self.ready.set()

    def step(self):
        state = self.get_state()
        frames = self.get_frames()
        if state is None or any(frames.get(c) is None for c in self.cameras):
            self.stats["skipped"] += 1
            return False
        imgs = []
        for c in self.cameras:
            img = frames[c]
            if (img.shape[1], img.shape[0]) != SIZE and self.cv2 is not None:
                img = self.cv2.resize(img, SIZE, interpolation=self.cv2.INTER_AREA)
            imgs.append((c, img))
        head = {"cmd": "obs", "state": [int(v) for v in state], "task": self.task,
                "images": {c: [img.shape[0], img.shape[1]] for c, img in imgs}}
        self.proc.stdin.write((json.dumps(head) + "\n").encode())
        for _, img in imgs:
            self.proc.stdin.write(img.tobytes())
        self.proc.stdin.flush()
        reply = self._read()
        if "error" in reply:
            raise RuntimeError(reply["error"])
        start = self.last_sent if self.last_sent is not None else list(state)
        target = limit_step(start, reply["action"], self.max_step)
        self.send_target(target)
        self.last_sent = target
        self.sent_at = time.monotonic()
        self.stats["requests"] += 1
        self.stats["ms"] = reply.get("ms", 0.0)
        if self.finish is not None and self.done is None:
            self.done = self.finish.feed(reply["action"], time.monotonic())
            if self.done and self.on_done:
                self.on_done(self.done)
        return True

    def stop(self):
        self.halt.set()
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
