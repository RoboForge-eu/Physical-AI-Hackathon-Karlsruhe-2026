"""Kamerabilder per WebRTC (LiveKit Cloud) ins Internet senden. Kein Zugriff auf die Arme.

Zugangsdaten stehen NUR lokal in livekit.json (Vorlage: livekit.example.json):
  {"url": "wss://<projekt>.livekit.cloud", "api_key": "...", "api_secret": "...", "room": "roboforge"}
Das Geheimnis verlaesst den Rechner nie; zur Cloud geht nur ein daraus erzeugtes, befristetes Token.

Jeder der vier Kamera-Plaetze wird eine eigene Videospur (Name = Platzname). Fehlt eine Kamera,
sendet die Spur ein graues Ersatzbild, damit Zuschauer den Zustand sehen.
"""
import asyncio, json, threading, time
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "livekit.json"
VIEWER = HERE / "viewer.html"
DEFAULTS = {"room": "roboforge", "width": 640, "height": 360, "fps": 15, "max_kbps": 700}


def load_config(path=CONFIG):
    """dict oder (None, Grund)."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "livekit.json fehlt (Vorlage livekit.example.json kopieren und ausfuellen)"
    except ValueError as exc:
        return None, f"livekit.json ist kein gueltiges JSON ({exc})"
    for key in ("url", "api_key", "api_secret"):
        if not str(cfg.get(key, "")).strip() or "<" in str(cfg.get(key)):
            return None, f"livekit.json: '{key}' fehlt noch"
    if not str(cfg["url"]).startswith(("wss://", "ws://")):
        return None, "livekit.json: 'url' muss mit wss:// beginnen"
    return {**DEFAULTS, **cfg}, None


def make_token(cfg, identity, publish, hours=12, data=False, subscribe=None):
    """publish: Video senden. data: Steuerdaten senden (Bediener, Roboter-Steuerung).
    Zuschauer bekommen weder publish noch data und koennen daher nicht steuern."""
    from livekit import api
    grants = api.VideoGrants(room_join=True, room=cfg["room"], can_publish=publish,
                             can_subscribe=(not publish) if subscribe is None else subscribe,
                             can_publish_data=data)
    return (api.AccessToken(cfg["api_key"], cfg["api_secret"]).with_identity(identity)
            .with_name(identity).with_grants(grants).with_ttl(timedelta(hours=hours)).to_jwt())


def viewer_link(cfg, hours=12):
    """Lokale Zuschauer-Seite; Adresse und Nur-Ansehen-Token stehen im #-Teil (wird nie an Server gesendet)."""
    from urllib.parse import quote
    token = make_token(cfg, f"zuschauer-{int(time.time())}", publish=False, hours=hours)
    return VIEWER.as_uri() + f"#url={quote(cfg['url'], safe='')}&token={token}"


def placeholder(width, height, text):
    import cv2, numpy as np
    img = np.full((height, width, 3), 40, np.uint8)
    cv2.putText(img, text, (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2, cv2.LINE_AA)
    return img


def _stats_dict(stats):
    """Sendestatistik aus den WebRTC-Statistiken einer Spur (bytesSent, Bildrate, Begrenzung)."""
    from google.protobuf.json_format import MessageToDict
    out = {}
    for s in stats or []:
        d = MessageToDict(s)
        o = d.get("outboundRtp")
        if not o:
            continue
        sent = o.get("sent", {})
        out_ = o.get("outbound", {})
        out["bytes"] = out.get("bytes", 0) + int(sent.get("bytesSent", 0))
        out["fps"] = max(out.get("fps", 0), float(out_.get("framesPerSecond", 0) or 0))
        out["width"] = max(out.get("width", 0), int(out_.get("frameWidth", 0) or 0))
        reason = out_.get("qualityLimitationReason")
        reason = str(reason or "").lower().replace("quality_limitation_reason_", "").replace("limitation_", "")
        if reason and reason != "none":
            out["limit"] = {"bandwidth": "Bandbreite", "cpu": "CPU"}.get(reason, reason)
    return out


class Streamer:
    """Sendet die Kamera-Plaetze eines CameraManager in einen LiveKit-Raum (eigener Thread)."""

    def __init__(self, manager, cfg, slots=None):
        self.manager, self.cfg = manager, cfg
        self.slots = list(range(len(manager.slots))) if slots is None else slots
        self.state = "aus"
        self.error = None
        self.viewers = 0
        self.tracks = {}            # platz -> {"sent": Bilder/s, "kbps": .., "fps": .., "limit": ..}
        self._loop = None
        self._stop = None
        self._thread = None

    # --- Steuerung aus dem Fenster ---
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.state, self.error = "verbinde ...", None
        self._thread = threading.Thread(target=self._run, daemon=True, name="livekit")
        self._thread.start()

    def stop(self):
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def summary(self):
        kbps = sum(t.get("kbps", 0) for t in self.tracks.values())
        return {"state": self.state, "error": self.error, "viewers": self.viewers, "kbps": kbps,
                "tracks": dict(self.tracks)}

    # --- Ablauf im eigenen Thread ---
    def _run(self):
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:
            self.state, self.error = "Fehler", f"{type(exc).__name__}: {exc}"
        finally:
            self._loop.close()
            if self.state != "Fehler":
                self.state = "aus"
            self.tracks = {}
            self.viewers = 0

    async def _main(self):
        import cv2
        from livekit import rtc
        self._stop = asyncio.Event()
        cfg = self.cfg
        w, h, fps = int(cfg["width"]), int(cfg["height"]), float(cfg["fps"])
        room = rtc.Room()

        def count(*_):
            self.viewers = len(room.remote_participants)
        room.on("participant_connected", count)
        room.on("participant_disconnected", count)
        await room.connect(cfg["url"], make_token(cfg, "roboter-pc", publish=True))
        count()
        sources, published = {}, {}
        try:
            for slot in self.slots:
                name = self.manager.slots[slot]["name"]
                src = rtc.VideoSource(w, h)
                track = rtc.LocalVideoTrack.create_video_track(name, src)
                opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False,
                                               video_encoding=rtc.VideoEncoding(max_bitrate=int(cfg["max_kbps"]) * 1000,
                                                                                max_framerate=fps))
                await room.local_participant.publish_track(track, opts)
                sources[slot], published[slot] = src, track
                self.tracks[slot] = {"name": name, "sent": 0.0, "kbps": 0.0}
            self.state = "live"
            sent = {s: 0 for s in sources}
            last_bytes = {s: None for s in sources}
            t_stat = time.monotonic()
            next_frame = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                for slot, src in sources.items():
                    text, cam = self.manager.status(slot, now)
                    frame = cam.latest()[0] if cam is not None and text.startswith("live") else None
                    if frame is None:
                        img = placeholder(w, h, f"{self.manager.slots[slot]['name']}: {text}")
                    else:
                        img = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
                    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
                    src.capture_frame(rtc.VideoFrame(w, h, rtc.VideoBufferType.RGBA, rgba.tobytes()))
                    sent[slot] += 1
                if now - t_stat >= 2:
                    dt = now - t_stat
                    for slot, track in published.items():
                        info = self.tracks[slot]
                        info["sent"] = sent[slot] / dt
                        sent[slot] = 0
                        try:
                            st = _stats_dict(await asyncio.wait_for(track.get_stats(), 1))
                        except Exception:
                            st = {}
                        if "bytes" in st:
                            if last_bytes[slot] is not None:
                                info["kbps"] = max(0.0, (st["bytes"] - last_bytes[slot]) * 8 / 1000 / dt)
                            last_bytes[slot] = st["bytes"]
                        info["fps"], info["limit"] = st.get("fps"), st.get("limit")
                    t_stat = now
                next_frame += 1 / fps
                delay = next_frame - time.monotonic()
                if delay < -0.5:
                    next_frame = time.monotonic()
                try:
                    await asyncio.wait_for(self._stop.wait(), max(0.0, delay))
                except asyncio.TimeoutError:
                    pass
        finally:
            await room.disconnect()


def operator_access(cfg, identity=None, hours=12):
    """(url, token) fuer einen Bediener (Steuerdaten senden + Video ansehen, kein eigenes Video)."""
    identity = identity or f"bediener-{int(time.time())}"
    return cfg["url"], make_token(cfg, identity, publish=False, data=True, subscribe=True, hours=hours)


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] != ["bediener"]:
        raise SystemExit("python stream_livekit.py bediener   -> URL und 12-h-Bediener-Token zum Testen der App")
    cfg, why = load_config()
    if cfg is None:
        raise SystemExit(why)
    url, token = operator_access(cfg)
    print("Nur an eigene Test-Geraete geben; 12 h gueltig, darf steuern (Trockenlauf) und Video sehen.")
    print("URL:  ", url)
    print("Token:", token)
