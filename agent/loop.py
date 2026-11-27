"""Agent-Schleife: Claude plant, ruft Werkzeuge von RoboForge Harness auf, sieht die Ergebnisse, plant weiter.

Sicherheit liegt NICHT hier, sondern im Harness-Kern: Bewegungen gehen nur in einer vor Ort freigegebenen
Arbeitssitzung, mit Tempo-Grenze und Stop. Der Agent kann eine Sitzung nur anfragen.
"""
import json, threading
from . import config, tools as T

SYSTEM = """Du steuerst ueber Werkzeuge einen oder zwei Roboterarme (SO-101, 6 Gelenke mit Greifer) in einer \
Werkstatt. Ein Mensch ist vor Ort und gibt Bewegungen frei.

So arbeitest du:
- Verschaff dir zuerst einen Ueberblick: arme__liste, und wenn es um Gegenstaende geht, kamera__bild.
- Der Arm bewegt sich nur ueber gelernte Faehigkeiten (Werkzeuge 'faehigkeit_...'). Jede laeuft eine von dir \
gewaehlte Zeit, danach haelt der Arm seine Stellung. Waehle die Zeit passend zur Aufgabe der Faehigkeit.
- Vor der ersten Bewegung braucht der Arm eine Arbeitssitzung: sitzung__anfragen, dann mit sitzung__status pruefen, \
bis 'bereit' wahr ist. Lehnt der Mensch ab, bewegst du nichts und sagst das.
- Feste Orte (z. B. ueber der Kiste) faehrst du mit pose__anfahren an (pose__liste zeigt sie), den Greifer steuerst du mit greifer__setzen. Ob ein Teil im Greifer steckt, sagt greifer__pruefen - zuverlaessiger als die Kamera.
- Pruefe nach jeder Faehigkeit mit kamera__bild, ob es geklappt hat, bevor du weitermachst.
- Gibt es fuer einen Schritt keine passende Faehigkeit, sag das klar, statt zu raten.
- Wenn du fertig bist (oder nicht weiterkommst), beende die Sitzung mit sitzung__beenden, damit der Arm sich ablegt, \
und fasse in wenigen Saetzen auf Deutsch zusammen, was passiert ist."""


class AgentRun:
    """Ein Lauf des Agenten. log(kind, text) mit kind in: text, werkzeug, ergebnis, fehler, info, ende."""
    def __init__(self, ros, task, log, cfg=None, client=None):
        self.ros, self.task, self.log = ros, task, log
        self.cfg = cfg or config.load()
        self.stop = threading.Event()
        self.client = client
        self.messages = []
        self.result = None

    def _client(self):
        if self.client is None:
            import anthropic
            key = self.cfg.get("api_key")
            self.client = anthropic.Anthropic(api_key=key) if key and "<" not in key else anthropic.Anthropic()
        return self.client

    def _tool_result(self, block, route):
        try:
            result = T.call(self.ros, route, block.name, dict(block.input or {}))
        except Exception as exc:
            self.log("fehler", f"{block.name}: {exc}")
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Fehler: {exc}", "is_error": True}
        if isinstance(result, dict) and "jpeg_base64" in result:      # Kamerabild als Bild zurueckgeben
            self.log("ergebnis", f"{block.name}: Bild")
            return {"type": "tool_result", "tool_use_id": block.id, "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": result["jpeg_base64"]}}]}
        text = json.dumps(result, ensure_ascii=False, default=str)
        self.log("ergebnis", f"{block.name}: {text[:300]}")
        return {"type": "tool_result", "tool_use_id": block.id, "content": text}

    def run(self):
        arms = [a["arm"] for a in self.ros.call("arme.liste")]
        tools, route = T.build(self.ros.tools(), self.ros.call("modelle.liste"), arms)
        self.log("info", f"{len(tools)} Werkzeuge, davon {sum(1 for k, _ in route.values() if k == 'modell')} "
                         f"gelernte Faehigkeiten · Modell {self.cfg['model']}")
        self.messages = [{"role": "user", "content": self.task}]
        client = self._client()
        for turn in range(int(self.cfg.get("max_turns", 30))):
            if self.stop.is_set():
                self.log("ende", "Vom Menschen angehalten.")
                return "angehalten"
            response = client.beta.messages.create(
                model=self.cfg["model"], max_tokens=16000, system=SYSTEM, tools=tools, messages=self.messages,
                output_config={"effort": self.cfg.get("effort", "high")},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            self.messages.append({"role": "assistant", "content": response.content})
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    self.log("text", block.text.strip())
            if response.stop_reason == "refusal":
                self.log("ende", "Claude hat die Anfrage abgelehnt.")
                return "abgelehnt"
            if response.stop_reason == "pause_turn":
                continue
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                self.result = next((b.text for b in response.content if b.type == "text"), "")
                self.log("ende", "Fertig.")
                return "fertig"
            results = []
            for block in calls:                       # nacheinander: der Arm macht immer nur eins
                if self.stop.is_set():
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": "Abgebrochen: der Mensch hat den Agenten angehalten.", "is_error": True})
                    continue
                self.log("werkzeug", f"{block.name} {json.dumps(block.input, ensure_ascii=False)}")
                results.append(self._tool_result(block, route))
            self.messages.append({"role": "user", "content": results})
        self.log("ende", f"Nach {self.cfg.get('max_turns', 30)} Runden beendet (Grenze).")
        return "grenze"
