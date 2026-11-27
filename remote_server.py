"""Fernsteuer-Server, Protokoll v1 - TROCKENLAUF.

Greift NICHT auf die Arme zu. Er rechnet nur die Zielgelenke aus und schickt sie als
'state' an die App (Geister-Arm). Die Anbindung an den Follower kommt erst nach Freigabe.

Zwei Wege, ein Controller (nur einer steuert, alle anderen schauen zu):
  WLAN:     WebSocket ws://<pc>:8765/teleop
  Internet: LiveKit-Datenkanal im Raum aus livekit.json, Thema "teleop". Steuern darf nur, wer ein
            Token mit Daten-Recht hat (Bediener-Token); Zuschauer-Tokens koennen keine Daten senden.

Start:  python remote_server.py [--port 8765] [--livekit]
Test:   python remote_sim_client.py ws://127.0.0.1:8765/teleop
        python remote_sim_client.py --livekit
"""
import argparse, asyncio, json, socket, threading, time
from websockets.asyncio.server import serve
from remote_core import RemoteController, Config
from remote_control import ControlDesk

TICK_S = 0.01
STATE_EVERY = 3          # 100 Hz Takt -> ca. 33 Hz state
TOPIC = "teleop"
ROBOT_IDENTITY = "roboter-steuerung"
LOSSY = {"state"}        # haeufige Zustandsmeldungen duerfen verloren gehen, alles andere zuverlaessig


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # sendet nichts, waehlt nur die Schnittstelle
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Lane:
    """Ein Arm, den man fernsteuern kann: eigene Steuerung, eigener Bediener, eigene Warteschlange."""
    def __init__(self, key, cfg, label=None, devices=None, max_min=None):
        self.key, self.label = key, label or key
        self.ctl = RemoteController(cfg, now=time.monotonic())
        self.desk = ControlDesk(devices=devices) if max_min is None else ControlDesk(max_min, devices)
        self.ctl.desk = self.desk
        self.state = self.ctl.state()
        self.live = False             # ein echter Arm folgt diesen Zielen
        self.released = True          # im Harness auf "Remote" freigegeben
        self.sent = -1

    def info(self, now):
        d = self.desk
        return {"arm": self.key, "label": self.label, "frei": self.released, "live": self.live,
                "holder": d.name(d.holder) if d.holder is not None else None,
                "left_s": max(0, round(d.until - now)) if d.holder is not None and d.until else None,
                "queue": len(d.queue)}


class Server:
    DEFAULT = "follower"

    def __init__(self, cfg=None, log=print):
        self.cfg = cfg or Config()
        self.devices = {}              # gemerkte Geraete, fuer alle Arme gleich
        self.lanes = {self.DEFAULT: Lane(self.DEFAULT, self.cfg, devices=self.devices)}
        self.sel = {}                  # cid -> gewaehlter Arm
        self._arms_version = 0
        self.senders = {}              # cid -> (async senden(raw, msg), Weg "WLAN"/"Internet")
        self.next_id = 1
        self.log = log
        self.stats = {"n": 0, "max_gap": 0.0, "last": None}
        # Zaehler fuer die Netz-Anzeige im Testfenster (nur lesen, aus anderem Thread)
        self.rx_bytes = self.tx_bytes = self.rx_msgs = self.tx_msgs = self.poses = 0
        self.last_pose = None          # (Zeit, Nachricht) der letzten Pose des Bedieners
        self.gap_max = 0.0             # groesste Pausenluecke seit letztem snapshot()
        self.livekit_state = "aus"
        self.skills = None             # ki.skills.Registry von ROS: benannte Befehle (Training, Modelle, ...)
        self._prev = None
        self.seen = {}                 # cid -> Zeit der letzten Nachricht (stumme Bediener abloesen)
        self.on_desk_change = None     # Harness: z. B. gemerkte Geraete speichern

    # --- Arme (Spuren) ---
    @property
    def lane(self):
        return self.lanes.get(self.DEFAULT) or next(iter(self.lanes.values()))

    # Kompatibel: ctl/desk/state/live meinen den ersten Arm
    ctl = property(lambda self: self.lane.ctl)
    desk = property(lambda self: self.lane.desk)
    state = property(lambda self: self.lane.state)

    @property
    def live(self):
        return self.lane.live

    @live.setter
    def live(self, v):
        self.lane.live = bool(v)

    def set_arms(self, arms):
        """arms: {key: (Anzeigename, freigegeben, live)}. Neue Arme bekommen eine Spur; Spuren bleiben bestehen."""
        changed = False
        for key, (label, released, live) in arms.items():
            ln = self.lanes.get(key)
            if ln is None:
                ln = self.lanes[key] = Lane(key, self.cfg, label, self.devices, self.lane.desk.max_min)
                for c in self.lane.ctl.clients:
                    ln.ctl.connect(c)
                    ln.desk.join(c, self.lane.desk.device(c), self.lane.desk.name(c))
                changed = True
            if (ln.label, ln.released) != (label, bool(released)):
                changed = True
            ln.label, ln.released, ln.live = label, bool(released), bool(live)
        if changed:
            self._arms_version += 1

    def set_arms_threadsafe(self, arms):
        loop = getattr(self, "_loop", None)
        if loop is None:
            self.set_arms(arms)
        else:
            loop.call_soon_threadsafe(lambda: self.set_arms(arms))

    def lane_of(self, cid):
        return self.lanes.get(self.sel.get(cid)) or self.lane

    def _auto_select(self, cid):
        """Standard: ein freigegebener Arm, der gerade frei ist (sonst der erste freigegebene)."""
        ok = [ln for ln in self.lanes.values() if ln.released]
        free = [ln for ln in ok if ln.desk.holder is None]
        pick = (free or ok or [self.lane])[0]
        self.sel[cid] = pick.key

    def reset(self, arm=None):
        """Ziel zurueck auf die Mittelstellung (dort steht der Arm nach dem Hochfahren). Bediener und
        Zuschauer bleiben verbunden; weiter erst nach Loslassen und erneutem Druecken der Kupplung."""
        ln = self.lanes.get(arm) or self.lane
        old = ln.ctl
        new = RemoteController(old.cfg, now=time.monotonic())
        new.clients = list(old.clients)
        new.desk = old.desk
        new.need_release = True
        ln.ctl = new
        ln.state = new.state()
        self.log(f"{ln.label}: Ziel auf Mittelstellung zurueckgesetzt; Kupplung neu druecken")

    def reset_threadsafe(self, timeout=1.0, arm=None):
        """Aus einem anderen Thread: reset() im Server-Thread ausfuehren und darauf warten."""
        loop = getattr(self, "_loop", None)
        if loop is None:
            self.reset(arm)
            return
        done = threading.Event()
        loop.call_soon_threadsafe(lambda: (self.reset(arm), done.set()))
        if not done.wait(timeout):
            raise TimeoutError("Remote-Server reagiert nicht")

    # --- gemeinsamer Empfangs- und Sendeweg ---
    async def _send(self, cid, msg):
        entry = self.senders.get(cid)
        if entry is None:
            return
        try:
            raw = json.dumps(msg)
            await asyncio.wait_for(entry[0](raw, msg), 0.05)
            self.tx_bytes += len(raw)
            self.tx_msgs += 1
        except Exception:
            pass

    async def receive(self, cid, raw):
        now = time.monotonic()
        self.seen[cid] = now
        self.rx_bytes += len(raw)
        self.rx_msgs += 1
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            msg = None
        ln = self.lane_of(cid)
        if isinstance(msg, dict) and msg.get("t") == "joints" and cid == ln.ctl.operator:
            self._rx_gap(now, msg)
        if isinstance(msg, dict) and msg.get("t") == "pose" and cid == ln.ctl.operator:
            st = self.stats
            if st["last"] is not None:
                st["max_gap"] = max(st["max_gap"], now - st["last"])
                self.gap_max = max(self.gap_max, now - st["last"])
            st["last"] = now
            st["n"] += 1
            self.poses += 1
            self.last_pose = (now, msg)
        if isinstance(msg, dict) and msg.get("t") == "skill":
            await self._send(cid, await self.run_skill(msg))
            return
        if isinstance(msg, dict) and msg.get("t") == "select":
            arm = msg.get("arm")
            if arm in self.lanes and self.lane_of(cid).key != arm:
                for other in self.lanes.values():       # beim Wechsel: drueben abgeben und abmelden
                    if other.key != arm:
                        before = other.desk.holder
                        other.desk.release(cid, now)
                        other.desk.dequeue(cid)
                        self._holder_check(before, other)
                self.sel[cid] = arm
                self._arms_version += 1
            return
        if isinstance(msg, dict) and msg.get("t") == "hello":
            dev, name = str(msg.get("device") or "")[:64] or None, str(msg.get("name") or "")[:40] or None
            if cid not in self.sel:
                self._auto_select(cid)
                self._arms_version += 1
            ln = self.lane_of(cid)
            for other in self.lanes.values():
                if other is not ln:
                    other.ctl.connect(cid)
                other.desk.join(cid, dev, name)
        before = ln.desk.holder
        if isinstance(msg, dict) and self._control(cid, msg, now, ln):
            self._holder_check(before, ln)
            return
        if (isinstance(msg, dict) and msg.get("t") in ("pose", "joints") and msg.get("clutch") is True
                and ln.desk.holder is None and cid in ln.ctl.clients):
            ln.desk.claim(cid, None, now)           # aeltere Apps ohne "claim": wer zuerst steuert
            self._holder_check(before, ln)
        for reply in ln.ctl.handle(cid, msg, now):
            await self._send(cid, reply)

    def _control(self, cid, m, now, ln=None):
        """Nachrichten zur Kontrolle. True, wenn erledigt."""
        t, d = m.get("t"), (ln or self.lane).desk
        if t == "claim":
            d.claim(cid, m.get("min"), now)
        elif t == "release":
            d.release(cid, now)
        elif t == "request":
            d.request(cid, m.get("min"))
        elif t == "answer":
            d.answer(cid, bool(m.get("accept")), now)
        elif t == "queue":
            d.enqueue(cid, m.get("min"))
        elif t == "unqueue":
            d.dequeue(cid)
        elif t == "extend":
            d.ask_extend(cid)
        else:
            return False
        return True

    def _holder_check(self, before, ln=None):
        ln = ln or self.lane
        if ln.desk.holder != before:
            ln.ctl.operator_changed()
            self._arms_version += 1
            self.log(f"Kontrolle {ln.label}: {ln.desk.name(ln.desk.holder) if ln.desk.holder else 'niemand'}")
            if self.on_desk_change:
                self.on_desk_change()

    # --- Admin (Harness, anderer Thread) ---
    def admin(self, fn, arm=None):
        """fn(desk, jetzt) im Server-Thread ausfuehren, z. B. lambda d, t: d.kick(cid, t)."""
        def run():
            ln = self.lanes.get(arm) or self.lane
            before = ln.desk.holder
            fn(ln.desk, time.monotonic())
            self._holder_check(before, ln)
            if self.on_desk_change:
                self.on_desk_change()
        loop = getattr(self, "_loop", None)
        if loop is None:
            run()
        else:
            loop.call_soon_threadsafe(run)

    def control_overview(self):
        """Fuer das Harness-Panel: je Arm Bediener, Restzeit, Clients."""
        now = time.monotonic()
        return {key: dict(ln.desk.overview(now), label=ln.label, frei=ln.released, live=ln.live)
                for key, ln in list(self.lanes.items())}

    def set_max_min(self, minutes):
        self.admin(lambda d, t: [ln.desk.set_max(minutes) for ln in self.lanes.values()])

    async def run_skill(self, msg):
        """{"t":"skill","id":7,"name":"training.start","args":{...}} -> {"t":"skill_result","id":7,...}.
        Laeuft im Thread-Pool, damit Befehle die Steuerung nicht aufhalten. Bewegungen sind von
        aussen gesperrt (Freigabe nur vor Ort), das prueft die Registry."""
        reply = {"t": "skill_result", "id": msg.get("id"), "name": msg.get("name")}
        if self.skills is None:
            return {**reply, "ok": False, "error": "Befehle nicht verfuegbar"}
        if msg.get("name") == "skills.liste":
            return {**reply, "ok": True, "result": self.skills.tool_schemas(source="remote")}
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.skills.call(msg.get("name"), msg.get("args") or {}, source="remote"))
            self.log(f"Befehl {msg.get('name')} ausgefuehrt")
            return {**reply, "ok": True, "result": result}
        except Exception as exc:
            return {**reply, "ok": False, "error": str(exc)}

    def add_client(self, cid, sender, way):
        self.senders[cid] = (sender, way)
        self.seen.setdefault(cid, time.monotonic())
        self.log(f"Client {cid} verbunden ({way})")

    def remove_client(self, cid):
        if self.senders.pop(cid, None) is not None:
            for ln in self.lanes.values():
                before = ln.desk.holder
                ln.ctl.disconnect(cid)
                ln.desk.leave(cid, time.monotonic())
                self._holder_check(before, ln)
            self.sel.pop(cid, None)
            self.log(f"Client {cid} getrennt")

    # --- WLAN: WebSocket ---
    async def handler(self, ws):
        if ws.request.path.split("?")[0] != "/teleop":
            await ws.close(1008, "Pfad /teleop erwartet")
            return
        cid = self.next_id
        self.next_id += 1
        self.add_client(cid, lambda raw, msg: ws.send(raw), f"WLAN {ws.remote_address[0]}")
        try:
            async for raw in ws:
                await self.receive(cid, raw)
        finally:
            self.remove_client(cid)

    # --- Internet: LiveKit-Datenkanal ---
    async def livekit(self, lk_cfg):
        """Haelt die Verbindung zum LiveKit-Raum; bei Abbruch neuer Versuch nach 5 s."""
        from livekit import rtc
        import stream_livekit as S
        while True:
            room = rtc.Room()
            gone = asyncio.Event()

            def on_data(packet):
                if packet.topic != TOPIC or packet.participant is None:
                    return
                identity = packet.participant.identity
                cid = "lk:" + identity
                if cid not in self.senders:
                    async def sender(raw, msg, identity=identity):
                        await room.local_participant.publish_data(
                            raw, reliable=msg.get("t") not in LOSSY, destination_identities=[identity], topic=TOPIC)
                    self.add_client(cid, sender, f"Internet {identity}")
                asyncio.ensure_future(self.receive(cid, packet.data))

            room.on("data_received", on_data)
            room.on("participant_disconnected", lambda p: self.remove_client("lk:" + p.identity))
            room.on("disconnected", lambda *_: gone.set())
            try:
                self.livekit_state = "verbinde ..."
                await room.connect(lk_cfg["url"], S.make_token(lk_cfg, ROBOT_IDENTITY, publish=False, data=True),
                                   rtc.RoomOptions(auto_subscribe=False))
                self.livekit_state = f"verbunden · Raum {lk_cfg['room']}"
                self.log(f"Internet: verbunden mit LiveKit-Raum {lk_cfg['room']}")
                await gone.wait()
                self.livekit_state = "getrennt · neuer Versuch in 5 s"
            except asyncio.CancelledError:
                await room.disconnect()
                raise
            except Exception as exc:
                self.livekit_state = f"Fehler: {type(exc).__name__}: {exc}"
            for cid in [c for c in self.senders if str(c).startswith("lk:")]:
                self.remove_client(cid)
            await asyncio.sleep(5)

    def _rx_gap(self, now, msg):
        """Diagnose: Empfangsluecke und Seq-Sprung der Bediener-Pakete (nur Zahlen, keine Inhalte)."""
        last = getattr(self, "_rx_last", None)
        seq = msg.get("seq")
        if last is not None and now - last[0] > 0.15:
            jump = seq - last[1] if isinstance(seq, int) and isinstance(last[1], int) else None
            self.log(f"EMPFANG: Luecke {(now - last[0]) * 1000:.0f} ms, Seq-Sprung {jump}, "
                     f"Takt-Luecke max {getattr(self, '_loop_gap', 0) * 1000:.0f} ms")
        self._rx_last = (now, seq)
        st = self.stats
        st["n"] += 1
        self.poses += 1

    def drop_silent_operator(self, now, silent_s=3.0):
        """Ein Bediener, der seit 3 s nichts sendet, waehrend ein anderer Client aktiv ist, ist eine tote
        Verbindung (z. B. App hart beendet). Er wird entfernt, die Kontrolle wird frei."""
        return any([self._drop_silent(ln, now, silent_s) for ln in list(self.lanes.values())])

    def _drop_silent(self, ln, now, silent_s):
        op = ln.ctl.operator
        if op is None or now - self.seen.get(op, now) <= silent_s:
            return False
        if not any(c != op and now - self.seen.get(c, -1e9) < 1.0 for c in ln.ctl.clients):
            return False
        self.log(f"Bediener {op} sendet nichts mehr - abgeloest")
        self.seen.pop(op, None)
        if op in self.senders:
            self.remove_client(op)
        else:
            before = ln.desk.holder
            ln.ctl.disconnect(op)
            ln.desk.leave(op, now)
            self._holder_check(before, ln)
        return True

    async def loop(self):
        i = 0
        t_stat = time.monotonic()
        prev = time.monotonic()
        while True:
            await asyncio.sleep(TICK_S)
            now = time.monotonic()
            gap, prev = now - prev, now
            self._loop_gap = max(getattr(self, "_loop_gap", 0.0), gap)
            if gap > 0.1:
                self.log(f"TAKT: Server-Schleife stockte {gap * 1000:.0f} ms")
            if now - t_stat >= 2.0:
                self._loop_gap = 0.0
            self.drop_silent_operator(now)
            arms_changed = False
            for ln in list(self.lanes.values()):
                before = ln.desk.holder
                ln.desk.tick(now)
                self._holder_check(before, ln)
                for cid, msg in ln.desk.pop_notices():
                    await self._send(cid, dict(msg, arm=ln.key, label=ln.label))
                if ln.desk.version != ln.sent:
                    ln.sent = ln.desk.version
                    arms_changed = True
                was = ln.ctl.reason
                st = ln.ctl.tick(now)
                if st.get("reason") != was and st.get("reason") == "watchdog":
                    rx = ln.ctl.last_rx
                    self.log(f"WATCHDOG {ln.label}: {((now - rx) * 1000) if rx else -1:.0f} ms ohne Paket, "
                             f"letzte Seq {ln.ctl.last_seq}")
                if ln.live:                       # ein Arm folgt diesen Zielen wirklich
                    st = dict(st, dry_run=False)
                ln.state = dict(st, arm=ln.key)
                for cid, msg in ln.ctl.pop_events():
                    if self.lane_of(cid) is ln:
                        await self._send(cid, msg)
            if arms_changed or self._arms_version != getattr(self, "_arms_sent", -1) or i % 100 == 0:
                self._arms_sent = self._arms_version
                arms = [ln.info(now) for ln in self.lanes.values()]
                for cid in list(self.senders):
                    ln = self.lane_of(cid)
                    await self._send(cid, dict(ln.desk.view(cid, now), arm=ln.key, label=ln.label, arms=arms))
            state = self.state
            i += 1
            if i % STATE_EVERY == 0:
                for cid in list(self.senders):
                    await self._send(cid, self.lane_of(cid).state)
            if now - t_stat >= 2.0:
                st = self.stats
                if st["n"]:
                    self.log(f"Posen {st['n'] / (now - t_stat):5.1f} Hz, groesste Luecke "
                             f"{st['max_gap'] * 1000:4.0f} ms, aktiv={state['active']}, "
                             f"Grund={state['reason']}, Spitze={state['ee']}")
                st["n"], st["max_gap"] = 0, 0.0
                t_stat = now

    def snapshot(self):
        """Raten seit dem letzten Aufruf: Download (App -> Roboter-PC) und Upload."""
        now = time.monotonic()
        cur = (now, self.rx_bytes, self.tx_bytes, self.poses, self.tx_msgs)
        prev, self._prev = self._prev, cur
        gap, self.gap_max = self.gap_max, 0.0
        dt = (now - prev[0]) if prev else 0
        rate = lambda i: (cur[i] - prev[i]) / dt if dt > 0 else 0.0
        last = self.last_pose
        ways = [w for _, w in self.senders.values()]
        op = self.ctl.operator
        return {"clients": len(self.ctl.clients), "operator": op,
                "operator_way": self.senders[op][1] if op in self.senders else None,
                "wlan": sum(w.startswith("WLAN") for w in ways), "internet": sum(w.startswith("Internet") for w in ways),
                "livekit": self.livekit_state,
                "rx_kbs": rate(1) / 1000, "tx_kbs": rate(2) / 1000, "pose_hz": rate(3), "state_hz": rate(4),
                "gap_ms": gap * 1000, "pose_age_ms": (now - last[0]) * 1000 if last else None,
                "last_pose": last[1] if last else None, "state": self.state}


def run_in_thread(port=8765, cfg=None, log=print, livekit_cfg=None):
    """Startet den Server (Trockenlauf) im Hintergrund, mit livekit_cfg auch uebers Internet.
    Gibt (server, stop_funktion, url) zurueck."""
    srv = Server(cfg, log=log)
    loop = asyncio.new_event_loop()
    srv._loop = loop
    ready = threading.Event()
    errors = []

    async def run():
        try:
            async with serve(srv.handler, "0.0.0.0", port, max_size=4096, compression=None):
                ready.set()
                tasks = [srv.loop()] + ([srv.livekit(livekit_cfg)] if livekit_cfg else [])
                await asyncio.gather(*tasks)
        except OSError as exc:
            errors.append(exc)
            ready.set()

    def target():
        try:
            loop.run_until_complete(run())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    threading.Thread(target=target, daemon=True, name="remote-server").start()
    ready.wait(5)
    if errors:
        raise errors[0]

    def stop():
        for task in asyncio.all_tasks(loop):
            loop.call_soon_threadsafe(task.cancel)

    return srv, stop, f"ws://{local_ip()}:{port}/teleop"


async def main(port, cfg=None, livekit_cfg=None):
    srv = Server(cfg)
    async with serve(srv.handler, "0.0.0.0", port, max_size=4096, compression=None):
        print("TROCKENLAUF - keine Verbindung zu den Armen.")
        print(f"App-URL (WLAN):  ws://{local_ip()}:{port}/teleop")
        if livekit_cfg:
            print(f"Internet: LiveKit-Raum {livekit_cfg['room']}, Thema '{TOPIC}'")
        await asyncio.gather(srv.loop(), *([srv.livekit(livekit_cfg)] if livekit_cfg else []))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--livekit", action="store_true", help="auch ueber LiveKit (livekit.json) erreichbar")
    a = ap.parse_args()
    lk = None
    if a.livekit:
        import stream_livekit
        lk, why = stream_livekit.load_config()
        if lk is None:
            raise SystemExit(why)
    try:
        asyncio.run(main(a.port, Config(scale=a.scale), lk))
    except KeyboardInterrupt:
        pass
