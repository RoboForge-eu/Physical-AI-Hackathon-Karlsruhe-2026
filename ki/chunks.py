"""Vorausrechnen von Bewegungsstuecken (Action Chunks), unabhaengig vom Modell.

Modelle wie ACT und SmolVLA berechnen auf einmal ein ganzes Stueck Bewegung (z. B. 50 Schritte = 1,7 s).
Ohne Vorausrechnen steht der Arm waehrend jeder neuen Rechnung kurz still (SmolVLA ~0,45 s).
Hier wird das naechste Stueck im Hintergrund berechnet, solange der Arm das aktuelle noch abfaehrt.
Wenn es fertig ist, werden die Schritte uebersprungen, die waehrend der Rechnung schon vergangen sind,
damit die neue Planung zeitlich passt.

compute(obs) -> Liste von Aktionen (jede Aktion: Liste von Zahlen). Laeuft in einem Hintergrund-Thread.
"""
import math, threading, time
from collections import deque

FPS = 30


class ChunkScheduler:
    def __init__(self, compute, fps=FPS, margin=1.5, min_left=4, blend=10, clock=time.monotonic):
        self.compute, self.fps, self.margin, self.min_left, self.clock = compute, fps, margin, min_left, clock
        self.blend = blend              # so viele Schritte vom alten ins neue Stueck ueberblenden
        self.queue = deque()
        self.tick = 0
        self.compute_s = 0.5            # Schaetzung, wird nach jeder Rechnung angepasst
        self.chunk_len = None
        self.pending = None             # (thread, start_tick, ergebnis-dict)
        self.stats = {"chunks": 0, "waits": 0, "skipped": 0}

    def reset(self):
        self._join()
        self.queue.clear()
        self.tick = 0

    def _start(self, obs):
        box = {}
        start_tick = self.tick
        def run():
            t = self.clock()
            try:
                box["actions"] = list(self.compute(obs))
            except Exception as exc:          # Fehler an den Aufrufer weitergeben
                box["error"] = exc
            box["seconds"] = self.clock() - t
        th = threading.Thread(target=run, daemon=True, name="ki-vorausrechnen")
        self.pending = (th, start_tick, box)
        th.start()

    def _join(self):
        if self.pending is not None:
            self.pending[0].join()
            self.pending = None

    def _take_pending(self, wait):
        th, start_tick, box = self.pending
        if th.is_alive():
            if not wait:
                return False
            self.stats["waits"] += 1
            th.join()
        self.pending = None
        if "error" in box:
            raise box["error"]
        actions = box["actions"]
        self.compute_s = 0.5 * self.compute_s + 0.5 * box["seconds"]
        self.chunk_len = len(actions)
        skip = min(self.tick - start_tick, max(0, len(actions) - 1))
        self.stats["skipped"] += skip
        self.stats["chunks"] += 1
        new = [list(a) for a in actions[skip:]]
        old = list(self.queue)
        n = min(self.blend, len(old), len(new))
        for i in range(n):                    # weicher Uebergang statt Sprung an der Stueckgrenze
            w = (i + 1) / (n + 1)
            new[i] = [o * (1 - w) + v * w for o, v in zip(old[i], new[i])]
        self.stats["blended"] = self.stats.get("blended", 0) + n
        self.queue = deque(new)
        return True

    def threshold(self):
        """Ab so wenigen uebrigen Schritten wird das naechste Stueck angefangen."""
        need = math.ceil(self.compute_s * self.fps * self.margin) + self.min_left
        return min(need, (self.chunk_len or need + 1) - 1)

    def next(self, obs):
        """Eine Aktion fuer jetzt; obs ist die aktuelle Beobachtung."""
        if self.pending is not None:
            self._take_pending(wait=not self.queue)
        if not self.queue and self.pending is None:   # ganz am Anfang oder nach reset: warten muss sein
            self._start(obs)
            self._take_pending(wait=True)
        if self.pending is None and len(self.queue) <= self.threshold():
            self._start(obs)
        self.tick += 1
        return self.queue.popleft()
