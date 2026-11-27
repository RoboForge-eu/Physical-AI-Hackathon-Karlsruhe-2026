"""Verbindung eines Moduls zum Harness-Kern (lokale Harness-Schnittstelle, siehe kern_api.py).

    ros = RosClient("workflow")
    ros.call("modelle.liste")
    ros.call("modell.ausfuehren", arm="follower", modell="...", sekunden=10)

Jeder Thread bekommt eine eigene Verbindung: ein langer Befehl blockiert keine anderen.
Faellt ROS weg, verbindet sich der naechste Aufruf neu.
"""
import itertools, json, threading

PORT = 8770


class RosError(Exception):
    pass


class RosNotConnected(RosError):
    pass


class RosClient:
    def __init__(self, modul, url=None, timeout=120):
        self.modul, self.url, self.timeout = modul, url or f"ws://127.0.0.1:{PORT}", timeout
        self.local = threading.local()
        self.ids = itertools.count(1)

    def _conn(self):
        ws = getattr(self.local, "ws", None)
        if ws is None:
            from websockets.sync.client import connect
            try:
                ws = connect(self.url, open_timeout=2, max_size=16 * 1024 * 1024)
                ws.send(json.dumps({"t": "hallo", "modul": self.modul}))
                json.loads(ws.recv(timeout=5))
            except Exception as exc:
                raise RosNotConnected(f"ROS nicht erreichbar ({self.url}): {exc}") from None
            self.local.ws = ws
        return ws

    def _drop(self):
        ws = getattr(self.local, "ws", None)
        self.local.ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def call(self, name, /, timeout=None, **args):     # "/": Befehle duerfen selbst ein Argument "name" haben
        mid = next(self.ids)
        for attempt in (1, 2):                    # einmal neu verbinden, falls ROS neu gestartet wurde
            ws = self._conn()
            try:
                ws.send(json.dumps({"t": "skill", "id": mid, "name": name, "args": args}))
                while True:
                    reply = json.loads(ws.recv(timeout=timeout or self.timeout))
                    if reply.get("t") == "skill_result" and reply.get("id") == mid:
                        break
                break
            except RosError:
                raise
            except Exception as exc:
                self._drop()
                if attempt == 2:
                    raise RosNotConnected(f"Verbindung zu ROS verloren: {exc}") from None
        if not reply.get("ok"):
            raise RosError(reply.get("error") or "unbekannter Fehler")
        return reply.get("result")

    def tools(self):
        return self.call("skills.liste")

    def connected(self):
        try:
            self._conn()
            return True
        except RosNotConnected:
            return False

    def close(self):
        self._drop()
