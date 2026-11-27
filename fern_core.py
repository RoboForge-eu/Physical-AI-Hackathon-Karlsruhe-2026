"""RoboForge Fernsteuerung - Logik ohne Oberflaeche (testbar).

  LeaderReader  liest einen eigenen SO-101-Leader-Arm per USB (nur Lesen, nie Motoren)
  Link          Verbindung zum Roboter ueber LiveKit: Video empfangen, Steuerdaten senden,
                Harness-Befehle (Training, Status, Stop) aufrufen
"""
import asyncio, itertools, json, threading, time, logging, logging.handlers, os
from concurrent.futures import Future

TOPIC = "teleop"                 # wie remote_server.TOPIC
ROBOT_IDENTITY = "roboter-steuerung"
VIDEO_IDENTITY = "roboter-pc"
HELLO = {"t": "hello", "v": 1, "client": "fernsteuerung"}
POS, MIN_ANGLE, MAX_ANGLE = 56, 9, 11
BAUD = 1_000_000


_DIAG = logging.getLogger("roboforge.timing")

def timing(event, **values):
    """Nur technische Zeitwerte, keine Tokens, Adressen oder Nachrichteninhalte."""
    if not _DIAG.handlers:
        path = os.path.expanduser("~/Library/Logs/RoboForge") if __import__("sys").platform == "darwin" else os.path.expanduser("~/.roboforge/logs")
        try:
            os.makedirs(path, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(os.path.join(path, "timing.log"), maxBytes=1000000, backupCount=2)
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            _DIAG.addHandler(handler)
            _DIAG.setLevel(logging.INFO)
        except OSError:
            _DIAG.addHandler(logging.NullHandler())
    _DIAG.info("%s %s", event, json.dumps(values))


def list_ports():
    from serial.tools import list_ports as lp
    return [(p.device, f"{p.device} · {p.description}" + (f" · {p.serial_number}" if p.serial_number else ""))
            for p in lp.comports()]


class LeaderReader:
    """Eigener Leader-Arm des Bedieners. Liest nur Positionen und einmal die Greifergrenzen."""
    def __init__(self, port, bus_factory=None):
        self.port = port
        self.bus_factory = bus_factory or (lambda p: __import__("fast_bus").FastBus(p, BAUD))
        self.bus = None
        self.grip_lo = self.grip_hi = None
        self.errors = 0

    def open(self):
        self.bus = self.bus_factory(self.port)
        lo, hi = self.bus.read(6, MIN_ANGLE, 2), self.bus.read(6, MAX_ANGLE, 2)
        if lo is None or hi is None:
            self.close()
            raise RuntimeError("Greifer (ID 6) antwortet nicht - Strom am Leader-Arm?")
        self.grip_lo, self.grip_hi = int.from_bytes(lo, "little"), int.from_bytes(hi, "little")
        if self.grip_hi - self.grip_lo < 100:
            self.grip_lo, self.grip_hi = 0, 4095               # keine Grenzen gesetzt: ganzer Bereich
        return self

    def read(self):
        """-> (j1..j5 Ticks, Greifer 0 = offen .. 1 = zu) oder None."""
        r = self.bus.sync_read(range(1, 7), POS, 2)
        if r is None:
            self.errors += 1
            return None
        pos = {s: int.from_bytes(r[s][1][:2], "little") for s in r}
        span = self.grip_hi - self.grip_lo
        grip = min(1.0, max(0.0, (self.grip_hi - pos[6]) / span))   # unteres Ende = zu
        return [pos[s] for s in range(1, 6)], grip

    def close(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
        self.bus = None


def deviation_deg(leader, robot):
    """Groesste Abweichung (Grad) zwischen Leader-Gelenken 1..5 und Roboter-Gelenken."""
    return max(abs(a - b) for a, b in zip(leader[:5], robot[:5])) * 360 / 4096


class Link:
    """LiveKit-Verbindung in einem eigenen Thread. Ereignisse gehen an on_event(art, daten):
    'status' (text), 'welcome', 'state', 'error', 'haptic', 'video' (name -> neues Bild verfuegbar)."""
    def __init__(self, url, token, on_event=None):
        self.url, self.token = url, token
        self.on_event = on_event or (lambda kind, data: None)
        self.loop = None
        self.room = None
        self.frames = {}                     # Spurname -> (RGB-numpy, Zeit)
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.welcome = None
        self.hello = dict(HELLO)             # die App ergaenzt Geraete-ID und Namen
        self.control = None                  # letzte {"t":"control"}: wer steuert, Restzeit, Warteschlange
        self.state = None
        self.state_times = []
        self.rtt_ms = None
        self.ids = itertools.count(1)
        self.pending = {}                    # Befehls-id -> Future
        self.seq = itertools.count(1)
        self.bytes_rx = 0
        self.last_joint_send = self.last_state_rx = 0.0
        self.last_diag = 0.0
        timing("session_start")

    # --- Thread ---
    def start(self):
        threading.Thread(target=self._thread, daemon=True, name="livekit-fern").start()
        return self

    def _thread(self):
        self.loop = asyncio.new_event_loop()
        try:
            self.loop.run_until_complete(self._main())
        except Exception as exc:
            self.on_event("status", f"Verbindung beendet: {type(exc).__name__}: {exc}")
        finally:
            self.closed.set()

    async def _main(self):
        from livekit import rtc
        room = self.room = rtc.Room()

        def on_data(packet):
            if packet.topic != TOPIC:
                return
            self.bytes_rx += len(packet.data)
            try:
                m = json.loads(packet.data)
            except ValueError:
                return
            self._message(m)

        tasks = []

        def on_track(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_VIDEO:
                tasks.append(asyncio.ensure_future(self._video(track, publication.name or track.sid)))

        room.on("data_received", on_data)
        room.on("track_subscribed", on_track)
        room.on("disconnected", lambda *a: self.on_event("status", "Verbindung getrennt"))
        self.on_event("status", "verbinde ...")
        await room.connect(self.url, self.token, rtc.RoomOptions(auto_subscribe=True))
        self.connected.set()
        self.on_event("status", "im Raum - warte auf den Roboter ...")
        while self.welcome is None and not self.closed.is_set():
            await self._send(self.hello, reliable=True)
            for _ in range(10):
                if self.welcome is not None:
                    break
                await asyncio.sleep(0.1)
        ping = 0
        while not self.closed.is_set():
            ping += 1
            await self._send({"t": "ping", "id": ping, "ts": time.monotonic()}, reliable=True)
            for _ in range(20):
                if self.closed.is_set():
                    break
                await asyncio.sleep(0.1)
        for t in tasks:                               # Video-Empfang sauber beenden
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await room.disconnect()
        except Exception:
            pass

    async def _video(self, track, name):
        from livekit import rtc
        import numpy as np
        stream = rtc.VideoStream(track, format=rtc.VideoBufferType.RGB24)
        async for event in stream:
            f = event.frame
            img = np.frombuffer(f.data, dtype=np.uint8).reshape(f.height, f.width, 3).copy()
            self.frames[name] = (img, time.monotonic())
            if self.closed.is_set():
                break

    def _message(self, m):
        t = m.get("t")
        if t == "welcome":
            first = self.welcome is None
            self.welcome = m
            if first:
                self.on_event("welcome", m)
        elif t == "state":
            now = time.monotonic()
            gap = now - self.last_state_rx if self.last_state_rx else 0
            previous = self.state or {}
            if gap > 0.15 or previous.get("active") != m.get("active") or now - self.last_diag > 2:
                timing("state", gap_ms=round(gap * 1000), ack=m.get("ack"), active=m.get("active"), reason=m.get("reason"), rtt_ms=self.rtt_ms)
                self.last_diag = now
            self.last_state_rx = now
            self.state = m
            now = time.monotonic()
            self.state_times = [x for x in self.state_times if now - x < 1.0] + [now]
            self.on_event("state", m)
        elif t == "pong":
            if isinstance(m.get("ts"), (int, float)):
                self.rtt_ms = (time.monotonic() - m["ts"]) * 1000
        elif t == "skill_result":
            fut = self.pending.pop(m.get("id"), None)
            if fut is not None and not fut.done():
                fut.set_result(m)
        elif t == "control":
            self.control = m
            self.on_event("control", m)
        elif t == "notice":
            self.on_event("notice", m)
        elif t in ("error", "haptic"):
            self.on_event(t, m)

    async def _send(self, m, reliable=False):
        if self.room is None:
            return
        await self.room.local_participant.publish_data(json.dumps(m), reliable=reliable, topic=TOPIC,
                                                       destination_identities=[ROBOT_IDENTITY])

    async def _timed_send(self, m, reliable, queued):
        started = time.monotonic()
        try:
            await self._send(m, reliable)
        except Exception as exc:
            timing("send_error", kind=m.get("t"), error_type=type(exc).__name__)
        finally:
            finished = time.monotonic()
            if finished - queued > 0.1:
                timing("send_delay", seq=m.get("seq"), queue_ms=round((started-queued)*1000), publish_ms=round((finished-started)*1000))

    def send(self, m, reliable=False):
        if self.loop is not None and self.connected.is_set() and not self.closed.is_set():
            asyncio.run_coroutine_threadsafe(self._timed_send(m, reliable, time.monotonic()), self.loop)

    # --- Steuern ---
    def send_joints(self, joints, grip, clutch):
        now = time.monotonic()
        gap = now - self.last_joint_send if self.last_joint_send else 0
        if clutch and gap > 0.1:
            timing("control_gap", gap_ms=round(gap*1000))
        self.last_joint_send = now
        self.send({"t": "joints", "seq": next(self.seq), "clutch": bool(clutch),
                   "j": [int(v) for v in joints], "grip": round(float(grip), 3)}, reliable=False)

    def send_stop(self):
        self.send({"t": "stop"}, reliable=True)

    # --- Harness-Befehle (Training, Status, ...) ---
    def call(self, name, timeout=15, **args):
        """Ruft einen Harness-Befehl auf und wartet auf die Antwort (nicht aus dem Fenster-Thread aufrufen)."""
        mid = next(self.ids)
        fut = Future()
        self.pending[mid] = fut
        self.send({"t": "skill", "id": mid, "name": name, "args": args}, reliable=True)
        try:
            reply = fut.result(timeout)
        except Exception:
            self.pending.pop(mid, None)
            raise TimeoutError(f"Keine Antwort auf {name} (Harness erreichbar?)") from None
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "Fehler")
        return reply.get("result")

    def state_rate(self):
        return len(self.state_times)

    def close(self):
        """Beendet die Verbindung; der Verbindungs-Thread raeumt Video-Empfang und Raum selbst auf."""
        self.closed.set()
