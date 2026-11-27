"""Lokale Harness-Schnittstelle: der Harness-Kern bietet sein Befehlsverzeichnis (Skills) den Modulen an
(VLA-Studio, Agentic-Skill-Studio, Orchestrator). Nur auf diesem PC erreichbar (127.0.0.1).

Protokoll (WebSocket, JSON):
  -> {"t": "hallo", "modul": "workflow"}
  <- {"t": "hallo", "ros": "RoboForge Harness", "version": 1}
  -> {"t": "skill", "id": 7, "name": "modelle.liste", "args": {}}
  <- {"t": "skill_result", "id": 7, "ok": true, "result": ...}   oder  "ok": false, "error": "..."
  -> {"t": "skill", "id": 8, "name": "skills.liste"}               Werkzeugliste mit Beschreibungen

Befehle laufen im Thread-Pool; langsame Befehle (z. B. ein Modell 15 s fahren lassen) blockieren
andere Module nicht. Bewegungen prueft die Registry (Arbeitssitzung vor Ort freigegeben).
"""
import asyncio, json, threading
from concurrent.futures import ThreadPoolExecutor

PORT = 8770
VERSION = 1


class KernAPI:
    def __init__(self, registry, log=print, port=PORT):
        self.registry, self.log, self.port = registry, log, port
        self.clients = {}            # id -> modulname
        self.next_id = 1
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="kern-befehl")
        self.loop = None
        self.error = None

    async def handler(self, ws):
        cid = self.next_id
        self.next_id += 1
        self.clients[cid] = "?"
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("t") == "hallo":
                    self.clients[cid] = str(msg.get("modul", "?"))[:40]
                    self.log(f"Modul verbunden: {self.clients[cid]}")
                    await ws.send(json.dumps({"t": "hallo", "ros": "RoboForge Harness", "version": VERSION}))
                elif msg.get("t") == "skill":
                    asyncio.ensure_future(self._answer(ws, msg, self.clients[cid]))
        except Exception:
            pass
        finally:
            name = self.clients.pop(cid, "?")
            self.log(f"Modul getrennt: {name}")

    async def _answer(self, ws, msg, modul):
        reply = {"t": "skill_result", "id": msg.get("id"), "name": msg.get("name")}
        try:
            if msg.get("name") == "skills.liste":
                result = self.registry.tool_schemas(source="modul")
            else:
                result = await asyncio.get_running_loop().run_in_executor(
                    self.pool, lambda: self.registry.call(msg.get("name"), msg.get("args") or {}, source="modul"))
            reply.update(ok=True, result=result)
        except Exception as exc:
            reply.update(ok=False, error=str(exc))
        try:
            await ws.send(json.dumps(reply, default=str))
        except Exception:
            pass

    def start(self):
        from websockets.asyncio.server import serve
        ready = threading.Event()

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            async def main():
                async with serve(self.handler, "127.0.0.1", self.port, max_size=16 * 1024 * 1024):
                    ready.set()
                    await asyncio.Future()
            try:
                self.loop.run_until_complete(main())
            except Exception as exc:
                self.error = exc
                ready.set()
        threading.Thread(target=run, daemon=True, name="kern-api").start()
        ready.wait(5)
        if self.error:
            raise self.error
        return self

    def modules(self):
        return sorted(set(self.clients.values()))
