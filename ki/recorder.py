"""Aufnahme-Takt: tastet mit 30 Hz die neuesten Kamerabilder und die neueste Gelenkzeile ab
und schreibt sie in eine Episode. Unabhaengig von der Oberflaeche (testbar)."""
import threading, time
from .episodes import FPS, EpisodeWriter

OBS_MAX_AGE_S = 0.15        # aeltere Gelenkdaten gelten als fehlend
FRAME_MAX_AGE_S = 0.25


def parse_obs(text):
    """'OBS 1 2 3 4 5 6 | 7 8 9 10 11 12' -> (state, action) oder None."""
    if not text.startswith("OBS "):
        return None
    try:
        left, right = text[4:].split("|")
        state, action = [int(v) for v in left.split()], [int(v) for v in right.split()]
    except ValueError:
        return None
    if len(state) != 6 or len(action) != 6:
        return None
    return state, action


class Recorder:
    """get_frames() -> {kamera: (bild, t_monotonic)}; Gelenkdaten kommen ueber obs()."""
    def __init__(self, cv2, get_frames, clock=time.monotonic):
        self.cv2, self.get_frames, self.clock = cv2, get_frames, clock
        self.latest = None              # (state, action, t)
        self.writer = None
        self.state = "bereit"           # bereit | nimmt_auf | wartet_entscheidung
        self.dropped = 0
        self.rename = {}
        self.first_frames = None
        self.halt = threading.Event()
        self.thread = None

    def obs(self, state, action):
        self.latest = (state, action, self.clock())

    def start(self, dataset, task, cameras=None, required=None, rename=None):
        """rename: {kurzname in get_frames: kameraname im Datensatz}, z. B. {"arm": "wrist"}."""
        if self.state != "bereit":
            raise RuntimeError("Aufnahme laeuft bereits oder wartet auf Behalten/Verwerfen")
        self.rename = dict(rename or {})
        self.writer = EpisodeWriter(dataset, task, self.cv2, cameras=cameras, required=required)
        self.first_frames = None
        self.dropped = 0
        self.state = "nimmt_auf"
        self.halt.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="ki-aufnahme")
        self.thread.start()

    def _loop(self):
        period = 1.0 / FPS
        nxt = self.clock()
        while not self.halt.is_set():
            self.tick()
            nxt += period
            delay = nxt - self.clock()
            if delay < -period:          # zu weit hinten: nicht nachholen
                nxt = self.clock()
            elif delay > 0:
                self.halt.wait(delay)

    def tick(self):
        now = self.clock()
        latest = self.latest
        frames = {}
        for cam, (img, t) in (self.get_frames() or {}).items():
            cam = getattr(self, "rename", {}).get(cam, cam)
            frames[cam] = img if img is not None and t is not None and now - t <= FRAME_MAX_AGE_S else None
        if latest is None or now - latest[2] > OBS_MAX_AGE_S:
            self.dropped += 1
            return False
        ok = self.writer.add(now, latest[0], latest[1], frames)
        if ok and self.first_frames is None:
            self.first_frames = {c: f for c, f in frames.items() if f is not None}    # Startbild (3x3-Raster)
        self.dropped += 0 if ok else 1
        return ok

    def stop(self):
        """Aufnahme beenden; danach keep() oder discard()."""
        if self.state != "nimmt_auf":
            return
        self.halt.set()
        if self.thread:
            self.thread.join(2)
        self.state = "wartet_entscheidung"

    def keep(self, extra=None):
        path = self.writer.finish(True, extra) if self.writer else None
        self.writer, self.state = None, "bereit"
        return path

    def discard(self):
        if self.writer:
            self.writer.finish(False)
        self.writer, self.state = None, "bereit"

    @property
    def frames(self):
        return self.writer.frames if self.writer else 0
