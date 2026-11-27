"""Skill-Autor: ein Agent schreibt einen Code-Skill, testet ihn im Trockenlauf, fragt echte Versuche an,
schaut sich das Ergebnis an und verbessert den Code - Version fuer Version (Agentic Robotics).

Echte Versuche gibt es nur, wenn der Mensch im Agentic-Skill-Studio auf 'Versuch freigeben' klickt
(und eine Arbeitssitzung im Harness freigegeben ist). Der fertige Skill liegt danach in der Bibliothek und
kann vom Orchestrator immer wieder benutzt werden - ohne Agent, der Code laeuft allein.
"""
import json, threading
from skilllib import api as skillapi, check, store
from skilllib.runner import run_skill
from . import config

SYSTEM = """Du bist Robotik-Entwickler. Du schreibst einen Code-Skill fuer einen Roboterarm (SO-101, 6 Gelenke, \
Greifer) und verbesserst ihn so lange, bis er zuverlaessig funktioniert.

Ein Skill ist Python-Code mit einer Funktion run(robot, ...), die ein Dict mit "erfolg" (True/False) und kurz \
"grund" zurueckgibt. Mit dem Arm redest du nur ueber 'robot' (Doku: Werkzeug doku). Kein import, keine Dateien, \
keine Klassen; nur Funktionen, Schleifen, Bedingungen und robot.

Vorgehen:
1. bibliothek aufrufen: welche Posen, gelernten Faehigkeiten (VLA-Modelle) und Code-Skills gibt es? Baue darauf auf. \
Erfinde keine Posen oder Modelle - fehlt etwas Wichtiges, sag am Ende genau, was der Mensch einrichten muss.
2. code_speichern: erste Version.
3. trockenlauf: Ablauf ohne Arm pruefen, auch Fehlerpfade (z. B. greifer haelt beim ersten Mal nichts).
4. echter_versuch: am echten Arm. Der Mensch muss jeden Versuch freigeben. Werte danach Ergebnis, Protokoll und \
Kamerabild aus: Was ging schief? Aendere genau das und speichere eine neue Version.
5. Pruefe den Erfolg im Code selbst (z. B. robot.greifer_haelt(), robot.frage(..., kamera=...)) - der Skill soll \
ehrlich melden, wenn er gescheitert ist, und wo sinnvoll selbst einen neuen Versuch machen.
6. Wenn eine Version in echten Versuchen zuverlaessig ist: aktiv_setzen und fertig mit kurzer Zusammenfassung auf Deutsch.

Praezision (Agentic Robotics): Du planst und schreibst Code, die Feinarbeit macht der Code selbst in einer schnellen Schleife: messen (robot.messen) -> kleine Korrektur (robot.korrektur, max. 5 mm) -> wieder messen, bis die Toleranz erreicht ist. Kontakt ohne Kraftsensor liefert robot.kontakt() (Ereignisse angestossen / abgesackt / frei aus Servo-Soll/Ist und Last). Fertige Regelschleifen als Vorlagen (Werkzeug vorlagen): visuelles_ausrichten, spiralsuche, zugtest, stift_einstecken - per robot.skill(name) aufrufen oder kopieren und anpassen. Jeder Skill gibt am Ende einen kurzen Ereignis-Bericht in Saetzen zurueck (Feld "bericht", z. B. "Kontakt bei 42 mm, nach 1,3 s um 2 mm abgesackt, Zugtest haelt") und, wenn vorhanden, "messbild". Mit simulationslauf testest du ohne Freigabe in der SIMULATION (mehrere zufaellige Startlagen, Licht zufaellig) - erst wenn die Erfolgsquote dort stimmt, frag einen echten Versuch an.

Halte Skills kurz und lesbar. Bewegungen langsam und ueber Posen; robot.frage nur an echten Entscheidungspunkten."""

TOOLS = [
    {"name": "doku", "description": "Beschreibung von 'robot' (alle Methoden).", "input_schema": {"type": "object", "properties": {}}},
    {"name": "bibliothek", "description": "Vorhandene Posen, gelernte Faehigkeiten (VLA-Modelle) und Code-Skills.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "code_ansehen", "description": "Code einer Version dieses Skills (oder eines anderen Skills) lesen.",
     "input_schema": {"type": "object", "properties": {"skill": {"type": "string"}, "version": {"type": "integer"}}}},
    {"name": "code_speichern", "description": "Speichert eine neue Version des Skills (wird vorher geprueft).",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}, "notiz": {"type": "string",
                      "description": "was sich geaendert hat und warum"}}, "required": ["code", "notiz"]}},
    {"name": "trockenlauf", "description": "Fuehrt die neueste Version ohne Arm aus. 'haelt' ist das Drehbuch fuer "
     "robot.greifer_haelt() (z. B. [false, true]), 'antworten' fuer robot.frage().",
     "input_schema": {"type": "object", "properties": {"params": {"type": "object"},
                      "haelt": {"type": "array", "items": {"type": "boolean"}},
                      "antworten": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "echter_versuch", "description": "Fuehrt die neueste Version am echten Arm aus, sobald der Mensch "
     "zustimmt. Gibt Ergebnis, Protokoll und ein Kamerabild danach zurueck.",
     "input_schema": {"type": "object", "properties": {"params": {"type": "object"},
                      "kamera": {"type": "string", "description": "Kamera fuer das Bild danach, Standard turm"}}}},
    {"name": "vorlagen", "description": "Regelschleifen-Vorlagen (Agentic Robotics) mit Code: visuelles_ausrichten, "
     "spiralsuche, zugtest, stift_einstecken, schachtel_auf_palette.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "leer = Liste"}}}},
    {"name": "simulationslauf", "description": "Fuehrt die neueste Version in der SIMULATION aus (kein echter Arm, "
     "keine Freigabe noetig), mehrere zufaellige Startlagen. szenario 'einstecken' = Stift ueber Oeffnung, Pose "
     "'ueber_oeffnung' liegt bis 4 mm daneben; 'standard' = Schachtel/Palette. Gibt Erfolgsquote, Berichte und ein Messbild.",
     "input_schema": {"type": "object", "properties": {"params": {"type": "object"},
                      "szenario": {"type": "string", "enum": ["standard", "einstecken"]},
                      "durchlaeufe": {"type": "integer", "minimum": 1, "maximum": 20}}}},
    {"name": "aktiv_setzen", "description": "Diese Version wird die, die der Orchestrator benutzt.",
     "input_schema": {"type": "object", "properties": {"version": {"type": "integer"}}, "required": ["version"]}},
    {"name": "fertig", "description": "Beendet die Entwicklung mit einer Zusammenfassung.",
     "input_schema": {"type": "object", "properties": {"zusammenfassung": {"type": "string"}}, "required": ["zusammenfassung"]}},
]


class SkillAuthor:
    """log(kind, text); ask_trial(text) -> bool blockiert, bis der Mensch entscheidet; on_version(v) optional."""
    def __init__(self, ros, skill, arm, log, ask_trial, cfg=None, client=None, on_version=None):
        self.ros, self.skill, self.arm, self.log, self.ask_trial = ros, skill, arm, log, ask_trial
        self.cfg = cfg or config.load()
        self.client, self.on_version = client, on_version
        self.stop = threading.Event()
        self.messages, self.result = [], None
        self.real_trials = 0
        self.max_real = int(self.cfg.get("max_echte_versuche", 10))

    def _client(self):
        if self.client is None:
            import anthropic
            key = self.cfg.get("api_key")
            self.client = anthropic.Anthropic(api_key=key) if key and "<" not in key else anthropic.Anthropic()
        return self.client

    def library(self):
        return {"posen": sorted(self.ros.call("pose.liste", arm=self.arm)),
                "faehigkeiten": [{"modell": m["name"], "aufgabe": m.get("task"), "methode": m.get("method")}
                                 for m in self.ros.call("modelle.liste")],
                "code_skills": [{"name": s["name"], "ziel": s.get("ziel"), "aktiv": s.get("aktiv")}
                                for s in store.all_skills() if s["name"] != self.skill]}

    def simulationslauf(self, args):
        v = self._latest()
        n = int(args.get("durchlaeufe") or 5)
        laeufe, bild = [], None
        for seed in range(min(20, max(1, n))):
            lines = []
            res = run_skill(self.skill, args.get("params") or {}, modus="sim", version=v, timeout=120,
                            log=lines.append, sim={"szenario": args.get("szenario") or "standard", "seed": seed})
            laeufe.append({"seed": seed, "erfolg": bool(res.get("erfolg")), "grund": res.get("grund"),
                           "bericht": str(res.get("bericht", ""))[:400], "fehler": res.get("fehler"),
                           "protokoll": lines[-8:]})
            bild = res.get("messbild") or bild
        ok = sum(l["erfolg"] for l in laeufe)
        self.log("ergebnis", f"Simulation v{v}: {ok}/{len(laeufe)} erfolgreich")
        text = json.dumps({"version": v, "erfolgreich": ok, "durchlaeufe": len(laeufe), "laeufe": laeufe},
                          ensure_ascii=False)
        if bild:
            try:
                import base64
                with open(bild, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                return [{"type": "text", "text": text},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}]
            except OSError:
                pass
        return text

    def _latest(self):
        meta = store.get(self.skill)
        if not meta["versionen"]:
            raise ValueError("Noch keine Version gespeichert (code_speichern)")
        return max(int(v) for v in meta["versionen"])

    def tool(self, name, args):
        """Fuehrt ein Werkzeug aus; gibt Inhalt fuer tool_result zurueck (Text oder Liste mit Bild)."""
        if name == "doku":
            return skillapi.__doc__
        if name == "bibliothek":
            return json.dumps(self.library(), ensure_ascii=False)
        if name == "code_ansehen":
            code, v = store.code(args.get("skill") or self.skill, args.get("version"))
            return f"# Version {v}\n{code}"
        if name == "code_speichern":
            problems = check.check(args["code"])
            if problems:
                return "NICHT gespeichert:\n" + "\n".join(problems)
            v = store.add_version(self.skill, args["code"], args.get("notiz", ""))
            self.log("version", f"Version {v} gespeichert: {args.get('notiz', '')}")
            if self.on_version:
                self.on_version(v)
            return f"Gespeichert als Version {v}."
        if name == "trockenlauf":
            v = self._latest()
            lib = self.library()
            lines = []
            res = run_skill(self.skill, args.get("params") or {}, arm=self.arm, modus="trocken", version=v,
                            timeout=30, log=lines.append, posen=lib["posen"],
                            modelle=[f["modell"] for f in lib["faehigkeiten"]],
                            drehbuch={"haelt": args.get("haelt") or [True], "antworten": args.get("antworten")})
            self.log("ergebnis", f"Trockenlauf v{v}: {json.dumps(res, ensure_ascii=False)[:200]}")
            return json.dumps({"version": v, "ergebnis": res, "protokoll": lines[-40:]}, ensure_ascii=False)
        if name == "echter_versuch":
            if self.real_trials >= self.max_real:
                return f"Keine echten Versuche mehr ({self.max_real} verbraucht). Fasse zusammen und beende."
            v = self._latest()
            status = self.ros.call("sitzung.status", arm=self.arm)
            if not status.get("bereit"):
                return ("Keine bereite Arbeitssitzung: Der Mensch muss sie im Studio anfragen und im Harness "
                        "freigeben. Versuche es danach erneut.")
            if not self.ask_trial(f"Echter Versuch {self.real_trials + 1}/{self.max_real}: Version {v} von "
                                  f"'{self.skill}' mit {json.dumps(args.get('params') or {}, ensure_ascii=False)}"):
                return "Der Mensch hat diesen Versuch abgelehnt."
            self.real_trials += 1
            lines = []
            res = run_skill(self.skill, args.get("params") or {}, arm=self.arm, modus="echt", version=v,
                            log=lambda t: (lines.append(t), self.log("info", "  " + t)))
            self.log("ergebnis", f"Echter Versuch v{v}: {json.dumps(res, ensure_ascii=False)[:200]}")
            text = json.dumps({"version": v, "ergebnis": res, "protokoll": lines[-40:],
                               "echte_versuche_uebrig": self.max_real - self.real_trials}, ensure_ascii=False)
            try:
                img = self.ros.call("kamera.bild", arm=self.arm, kamera=args.get("kamera") or "turm")["jpeg_base64"]
                return [{"type": "text", "text": text},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}}]
            except Exception:
                return text
        if name == "vorlagen":
            from skilllib import vorlagen
            if not args.get("name"):
                return json.dumps({n: v[0] for n, v in vorlagen.VORLAGEN.items()}, ensure_ascii=False)
            return vorlagen.code(args["name"])
        if name == "simulationslauf":
            return self.simulationslauf(args)
        if name == "aktiv_setzen":
            store.set_active(self.skill, args["version"])
            self.log("version", f"Version {args['version']} ist jetzt aktiv")
            return "ok"
        if name == "fertig":
            self.result = args["zusammenfassung"]
            return "ok"
        raise ValueError(f"Unbekanntes Werkzeug {name}")

    def run(self, auftrag):
        meta = store.get(self.skill)
        start = (f"Skill: {self.skill}\nZiel: {meta.get('ziel')}\nErfolgskriterium: {meta.get('kriterium')}\n"
                 f"Parameter: {json.dumps(meta.get('params') or {}, ensure_ascii=False)}\nArm: {self.arm}\n"
                 f"Hoechstens {self.max_real} echte Versuche.\n\n{auftrag}")
        if meta["versionen"]:
            start += f"\n\nEs gibt schon Versionen: {sorted(int(v) for v in meta['versionen'])}. Verbessere die neueste."
        self.messages = [{"role": "user", "content": start}]
        client = self._client()
        for _ in range(int(self.cfg.get("max_turns_autor", 60))):
            if self.stop.is_set():
                self.log("ende", "Angehalten.")
                return "angehalten"
            r = client.beta.messages.create(model=self.cfg["model"], max_tokens=16000, system=SYSTEM, tools=TOOLS,
                                            messages=self.messages, output_config={"effort": self.cfg.get("effort", "high")},
                                            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            self.messages.append({"role": "assistant", "content": r.content})
            for b in r.content:
                if b.type == "text" and b.text.strip():
                    self.log("text", b.text.strip())
            if r.stop_reason == "refusal":
                self.log("ende", "Abgelehnt.")
                return "abgelehnt"
            if r.stop_reason == "pause_turn":
                continue
            calls = [b for b in r.content if b.type == "tool_use"]
            if not calls:
                self.log("ende", "Fertig.")
                return "fertig"
            results = []
            for b in calls:
                self.log("werkzeug", f"{b.name} " + (json.dumps({k: v for k, v in (b.input or {}).items() if k != "code"},
                                                                ensure_ascii=False) if b.input else ""))
                try:
                    content, err = self.tool(b.name, dict(b.input or {})), False
                except Exception as exc:
                    content, err = f"Fehler: {exc}", True
                    self.log("fehler", f"{b.name}: {exc}")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": content, **({"is_error": True} if err else {})})
            self.messages.append({"role": "user", "content": results})
            if self.result is not None:
                self.log("ende", "Fertig: " + self.result)
                return "fertig"
        self.log("ende", "Rundengrenze erreicht.")
        return "grenze"
