"""Ablauf-Motor des Orchestrators.

Ein Ablauf ist ein Graph aus Knoten (JSON):
  {"name": "...", "start": "k1",
   "nodes": {"k1": {"type": "start", "title": "Start", "next": "k2", "x": 80, "y": 80, "params": {}}, ...}}

Jeder Knoten hat einen Ausgang "next"; Bedingung und Wiederholen haben zusaetzlich "sonst".
Ergebnisse landen unter ihrem Knoten und koennen spaeter eingesetzt werden: {{k3.ergebnis.schritte}}.
Bewegungen laufen ueber ROS (Arbeitssitzung vor Ort freigegeben, Tempo-Grenze, Stop) - wie beim Agenten.
"""
import json, re, threading, time

TYPES = {
    "start":       {"label": "Start",        "color": "#444444", "params": {}},
    "sitzung":     {"label": "Sitzung",      "color": "#2f6fb5", "params": {"arm": "follower", "warten_s": 120}},
    "skill":       {"label": "Skill",        "color": "#8b1f6f", "params": {"name": "", "arm": "follower", "parameter": "{}"}},
    "entscheidung": {"label": "LLM-Entscheidung", "color": "#1f7a3a", "params": {"frage": "", "optionen": "ja, nein", "kamera": "turm", "arm": "follower"}},
    "faehigkeit":  {"label": "VLA-Faehigkeit",   "color": "#6a3fb5", "params": {"arm": "follower", "modell": "", "sekunden": 10, "aufgabe": ""}},
    "befehl":      {"label": "Befehl",       "color": "#1f6f8b", "params": {"name": "arme.liste", "args": "{}"}},
    "agent":       {"label": "Agent",        "color": "#1f7a3a", "params": {"aufgabe": "", "arm": "follower"}},
    "warten":      {"label": "Warten",       "color": "#777777", "params": {"sekunden": 2}},
    "bedingung":   {"label": "Bedingung",    "color": "#b5651d", "params": {"wert": "", "vergleich": "==", "mit": ""}},
    "wiederholen": {"label": "Wiederholen",  "color": "#b5651d", "params": {"mal": 3}},
    "ende":        {"label": "Ende",         "color": "#444444", "params": {"sitzung_beenden": True, "arm": "follower"}},
}
BRANCHING = {"bedingung", "wiederholen", "skill"}
VERGLEICHE = ["==", "!=", ">", "<", ">=", "<=", "enthaelt", "ist wahr"]
MAX_STEPS = 1000
VAR = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


class PipelineError(Exception):
    pass


def new_node(kind, nid, x=100, y=100):
    t = TYPES[kind]
    return {"type": kind, "title": t["label"], "x": x, "y": y, "next": None,
            **({"sonst": None} if kind in BRANCHING else {}), "params": dict(t["params"])}


def new_pipeline(name="Neuer Ablauf"):
    return {"name": name, "start": "k1", "nodes": {"k1": new_node("start", "k1", 60, 60)}}


def next_id(p):
    n = 1
    while f"k{n}" in p["nodes"]:
        n += 1
    return f"k{n}"


def lookup(ctx, path):
    """'k3.ergebnis.schritte' -> Wert aus dem Kontext (Listen mit Zahlen: k3.ergebnis.0.name)."""
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise PipelineError(f"Variable {{{{{path}}}}} gibt es nicht (an '{part}')")
    return cur


def fill(value, ctx):
    """Setzt {{...}} ein. Ist der ganze Text genau eine Variable, bleibt der Typ erhalten (Zahl, Liste ...)."""
    if not isinstance(value, str):
        return value
    m = VAR.fullmatch(value.strip())
    if m:
        return lookup(ctx, m.group(1))
    return VAR.sub(lambda mm: str(lookup(ctx, mm.group(1))), value)


def compare(a, op, b):
    if op == "ist wahr":
        return bool(a) and str(a).lower() not in ("false", "0", "nein", "")
    if op == "enthaelt":
        return str(b) in (json.dumps(a, ensure_ascii=False) if not isinstance(a, str) else a)
    try:
        fa, fb = float(a), float(b)
        a, b = fa, fb
    except (TypeError, ValueError):
        a, b = str(a), str(b)
    return {"==": a == b, "!=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


def validate(p):
    """Liste von Problemen (leer = ausfuehrbar)."""
    problems = []
    nodes = p.get("nodes", {})
    if p.get("start") not in nodes:
        problems.append("Kein Startknoten")
    for nid, n in nodes.items():
        if n["type"] not in TYPES:
            problems.append(f"{nid}: unbekannte Art {n['type']}")
        for out in ("next", "sonst"):
            if n.get(out) and n[out] not in nodes:
                problems.append(f"{nid} ({n['title']}): Ausgang '{out}' zeigt auf fehlenden Knoten {n[out]}")
        if n["type"] == "faehigkeit" and not n["params"].get("modell"):
            problems.append(f"{nid} ({n['title']}): kein Modell gewaehlt")
        if n["type"] == "skill" and not n["params"].get("name"):
            problems.append(f"{nid} ({n['title']}): kein Skill gewaehlt")
        if n["type"] == "entscheidung" and not n["params"].get("frage"):
            problems.append(f"{nid} ({n['title']}): keine Frage")
        if n["type"] == "agent" and not n["params"].get("aufgabe"):
            problems.append(f"{nid} ({n['title']}): keine Aufgabe fuer den Agenten")
    return problems


class Runner:
    """Fuehrt einen Ablauf aus. on_node(knoten_id, zustand) mit zustand: laeuft | ok | fehler.
    agent_factory(aufgabe, log) -> Objekt mit run() und .result/.stop (siehe agent.loop.AgentRun)."""
    def __init__(self, pipeline, ros, log=print, on_node=None, agent_factory=None, sleep=time.sleep,
                 run_skill=None, decide=None, confirm=None):
        self.p, self.ros, self.log = pipeline, ros, log
        self.confirm = confirm           # confirm(titel, text) -> bool: Zustimmung vor Ort direkt im Modul
        self.on_node = on_node or (lambda nid, state: None)
        self.agent_factory, self.sleep = agent_factory, sleep
        self.stop = threading.Event()
        self.ctx = {"zaehler": {}}
        self.agent = None
        self.steps = 0
        if run_skill is None:
            from skilllib.runner import run_skill
        self.run_skill, self.decide = run_skill, decide

    def _wait(self, seconds):
        end = time.monotonic() + float(seconds)
        while time.monotonic() < end and not self.stop.is_set():
            self.sleep(min(0.1, max(0.0, end - time.monotonic())))

    def execute(self, nid, n):
        """Ein Knoten. Gibt (ergebnis, ausgang) zurueck; ausgang 'next' oder 'sonst'."""
        kind = n["type"]
        # 'args' (JSON-Text) erst nach dem Einlesen fuellen, sonst zerbrechen Anfuehrungszeichen in Werten das JSON
        prm = {k: (v if k == "args" else fill(v, self.ctx)) for k, v in n.get("params", {}).items()}
        if kind in ("start",):
            return None, "next"
        if kind == "ende":
            if prm.get("sitzung_beenden") and prm.get("arm"):
                self.ros.call("sitzung.beenden", arm=prm["arm"])
            return None, None
        if kind == "warten":
            self._wait(prm.get("sekunden", 1))
            return {"gewartet_s": prm.get("sekunden", 1)}, "next"
        if kind == "sitzung":
            arm = prm["arm"]
            st = self.ros.call("sitzung.status", arm=arm)
            if not st.get("bereit"):
                if not st.get("freigegeben"):
                    if self.confirm is not None:     # Hinweis direkt hier zeigen, kein Wechsel in den Harness
                        h = self.ros.call("sitzung.hinweis", arm=arm, modul="Orchestrator")
                        if not self.confirm(h["titel"], h["text"]):
                            raise PipelineError("Freigabe vor Ort abgelehnt")
                        self.ros.call("sitzung.freigeben", arm=arm, modul="Orchestrator", zustimmung=True)
                        self.log(f"Freigabe fuer {arm} erteilt - Arm faehrt hoch")
                    else:
                        self.ros.call("sitzung.anfragen", arm=arm, modul="Orchestrator")
                        self.log(f"Freigabe fuer {arm} im Harness angefragt - bitte vor Ort bestaetigen")
                end = time.monotonic() + float(prm.get("warten_s", 120))
                while not self.stop.is_set():
                    st = self.ros.call("sitzung.status", arm=arm)
                    if st.get("bereit"):
                        break
                    if time.monotonic() > end:
                        raise PipelineError(f"Sitzung fuer {arm} nicht bereit (abgelehnt oder Zeit abgelaufen)")
                    self._wait(1)
            return st, "next"
        if kind == "faehigkeit":
            args = {"arm": prm["arm"], "modell": prm["modell"], "sekunden": float(prm.get("sekunden", 10))}
            if prm.get("aufgabe"):
                args["aufgabe"] = prm["aufgabe"]
            return self.ros.call("modell.ausfuehren", timeout=300, **args), "next"
        if kind == "skill":
            from skilllib.runner import run_skill
            params = prm.get("parameter") or {}
            if isinstance(params, str):
                try:
                    params = json.loads(params or "{}")
                except ValueError as exc:
                    raise PipelineError(f"Parameter sind kein JSON: {exc}") from None
            params = {k: fill(v, self.ctx) for k, v in params.items()}
            res = self.run_skill(prm["name"], params, arm=prm["arm"], modus="echt",
                                 log=lambda t: self.log("  " + t))
            return res, "next" if res.get("erfolg") else "sonst"
        if kind == "entscheidung":
            from skilllib.runner import make_decider
            from agent import config
            optionen = [o.strip() for o in str(prm.get("optionen", "")).split(",") if o.strip()]
            if not optionen:
                raise PipelineError("Keine Optionen angegeben")
            bild = None
            if prm.get("kamera"):
                bild = self.ros.call("kamera.bild", arm=prm.get("arm"), kamera=prm["kamera"])["jpeg_base64"]
            antwort = (self.decide or make_decider(config.load()))(prm["frage"], optionen, bild)
            return {"antwort": antwort}, "next"
        if kind == "befehl":
            args = prm.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError as exc:
                    raise PipelineError(f"Angaben sind kein JSON: {exc}") from None
            return self.ros.call(prm["name"], timeout=300, **{k: fill(v, self.ctx) for k, v in args.items()}), "next"
        if kind == "agent":
            if self.agent_factory is None:
                raise PipelineError("Kein Agent verfuegbar")
            task = prm["aufgabe"] + (f"\n\n(Standardarm: {prm['arm']})" if prm.get("arm") else "")
            self.agent = self.agent_factory(task, lambda kind, text: self.log(f"  Agent · {text}"))
            outcome = self.agent.run()
            res = {"ausgang": outcome, "antwort": self.agent.result}
            self.agent = None
            if outcome not in ("fertig",):
                raise PipelineError(f"Agent endete mit '{outcome}'")
            return res, "next"
        if kind == "bedingung":
            ok = compare(prm.get("wert"), prm.get("vergleich", "=="), prm.get("mit"))
            return {"erfuellt": ok}, "next" if ok else "sonst"
        if kind == "wiederholen":
            count = self.ctx["zaehler"].get(nid, 0)
            if count < int(prm.get("mal", 1)):
                self.ctx["zaehler"][nid] = count + 1
                return {"durchlauf": count + 1}, "next"
            self.ctx["zaehler"][nid] = 0           # fuer einen spaeteren erneuten Eintritt
            return {"durchlauf": count, "fertig": True}, "sonst"
        raise PipelineError(f"Unbekannte Knotenart {kind}")

    def vorladen(self):
        """VLA-Modelle schon jetzt laden (dauert 10-30 s), damit die Faehigkeit spaeter sofort startet."""
        gesehen = set()
        for n in self.p["nodes"].values():
            prm = n.get("params", {})
            if n["type"] != "faehigkeit" or not prm.get("modell") or "{{" in str(prm.get("modell")):
                continue
            key = (prm.get("arm"), prm["modell"])
            if key in gesehen:
                continue
            gesehen.add(key)
            try:
                self.ros.call("modell.vorladen", arm=prm.get("arm"), modell=prm["modell"],
                              aufgabe=prm.get("aufgabe") or "")
                self.log(f"VLA-Modell {prm['modell']} wird im Hintergrund geladen")
            except Exception as exc:
                self.log(f"(Vorladen nicht moeglich: {exc})")

    def run(self):
        problems = validate(self.p)
        if problems:
            raise PipelineError("; ".join(problems))
        nid = self.p["start"]
        self.log(f"Ablauf '{self.p['name']}' startet")
        self.vorladen()
        while nid is not None:
            if self.stop.is_set():
                self.log("Angehalten.")
                return "angehalten"
            self.steps += 1
            if self.steps > MAX_STEPS:
                raise PipelineError(f"Mehr als {MAX_STEPS} Schritte - Endlosschleife?")
            n = self.p["nodes"][nid]
            self.on_node(nid, "laeuft")
            self.log(f"▶ {n['title']} ({TYPES[n['type']]['label']})")
            try:
                result, out = self.execute(nid, n)
            except Exception as exc:
                self.on_node(nid, "fehler")
                self.log(f"✖ {n['title']}: {exc}")
                raise
            self.ctx[nid] = {"ergebnis": result}
            self.on_node(nid, "ok")
            if result is not None:
                zeigen = ({k: v for k, v in result.items() if not k.endswith("_base64") and k != "protokoll"}
                          if isinstance(result, dict) else result)       # Bilddaten nicht ins Protokoll
                self.log(f"   ← {json.dumps(zeigen, ensure_ascii=False, default=str)[:400]}")
                if isinstance(result, dict) and result.get("grund"):
                    self.log(f"   Grund: {result['grund']}")
            nid = n.get(out) if out else None
        self.log("Ablauf fertig.")
        return "fertig"

    def halt(self):
        self.stop.set()
        if self.agent is not None:
            self.agent.stop.set()
