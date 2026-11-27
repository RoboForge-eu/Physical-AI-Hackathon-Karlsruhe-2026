"""Webserver der Plattform (nur 127.0.0.1). Liefert die Seite aus static/ und eine JSON-Schnittstelle /api/...

Sicherheit:
  - nur lokal erreichbar; Host-Kopfzeile wird geprueft (gegen DNS-Rebinding)
  - jede aendernde Anfrage braucht die Kopfzeile 'X-RF: 1' (fremde Webseiten koennen sie nicht setzen)
  - Bewegungen entscheidet weiter der Harness (Freigabe-Dialog vor Ort); Tokens gehen nie an den Browser
"""
import base64, json, mimetypes, os, subprocess, sys, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import KIT, STATIC, PORT, DATEN, kern

sys.path.insert(0, KIT)


class Harness:
    """Verbindung zum Harness-Kern; Zustand der Arme wird im Hintergrund alle 2 s abgefragt."""

    def __init__(self):
        from ros_client import RosClient
        self.client = RosClient("plattform", timeout=30)
        self.state = {"verbunden": False, "arme": [], "fehler": "", "zeit": 0}
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="harness-status").start()

    def _loop(self):
        while True:
            try:
                arme = self.client.call("arme.liste", timeout=5)
                st = {"verbunden": True, "arme": arme, "fehler": "", "zeit": time.time()}
            except Exception as exc:
                st = {"verbunden": False, "arme": [], "fehler": str(exc)[:200], "zeit": time.time()}
            with self.lock:
                self.state = st
            time.sleep(2.0 if st["verbunden"] else 4.0)

    def status(self):
        with self.lock:
            return dict(self.state)

    def call(self, name, args=None, timeout=60):
        return self.client.call(name, timeout=timeout, **(args or {}))

    def starten(self):
        if self.status()["verbunden"]:
            return {"laeuft": True}
        from ki.geraet import popen_detached_kwargs
        exe = sys.executable
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        subprocess.Popen([pyw if os.path.exists(pyw) else exe, os.path.join(KIT, "ros.py")], cwd=KIT,
                         close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **popen_detached_kwargs())
        return {"gestartet": True}


class App:
    def __init__(self):
        self.zustand = kern.Zustand()
        self.teams = kern.Teams()
        self.hackathon = kern.Hackathon()
        self.aufgaben = kern.Aufgaben()
        self.orch = kern.Orchestrator()
        self.harness = Harness()
        self._geraet = None
        threading.Thread(target=self._geraet_laden, daemon=True).start()

    def _geraet_laden(self):
        try:
            self._geraet = kern.geraet()
        except Exception as exc:
            self._geraet = {"geraet": "?", "text": f"nicht ermittelt: {exc}"}

    # --- Daten fuer die Seite ---
    def team(self):
        return self.teams.aktiv()

    def team_ordner(self):
        t = self.team()
        return self.teams.team_ordner(t) if t else None

    def queue(self):
        from ki import jobs
        return jobs.DetachedQueue()

    def zustand_api(self):
        t = self.team()
        return {"team": kern.public(t) if t else None, "harness": self.harness.status(),
                "start": self.zustand.startpunkt(), "zustand": self.zustand.get(),
                "hackathon": self.hackathon.jetzt(), "geraet": self._geraet,
                "training": self._safe(lambda: self.queue().snapshot(), []),
                "aufgaben": self.aufgaben.status(), "orchestrator": {"laeuft": self.orch.laeuft()},
                "pakete": len(self.teams.pakete_liste()), "system": sys.platform}

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    def daten(self):
        from ki import episodes, jobs, methods
        from aufnahme import plan as P
        self._team_plaene_uebernehmen()
        sets = []
        for d in episodes.datasets():
            sets.append({"name": d.name, "task": d.meta.get("task", ""), "episoden": len(d.episodes()),
                         "arm": d.meta.get("arm"), "kameras": d.meta.get("cameras")})
        return {"datensaetze": sets, "modelle": jobs.models(),
                "methoden": [m.info() for m in methods.all_methods()],
                "plaene": [{"id": i, "name": n} for i, n in P.definitions()]}

    def _team_plaene_uebernehmen(self):
        """Plaene aus teams/<ordner>/plaene/ in den Plan-Ordner kopieren (dort findet sie der Steuermodus)."""
        ordner = self.team_ordner()
        if not ordner:
            return
        from aufnahme import PLAENE
        src = os.path.join(ordner, "plaene")
        if not os.path.isdir(src):
            return
        for f in os.listdir(src):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(src, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                if d.get("id") and d["id"] + ".json" == f:
                    dst = os.path.join(PLAENE, f)
                    if not os.path.exists(dst) or open(dst, encoding="utf-8").read() != json.dumps(d):
                        with open(dst, "w", encoding="utf-8") as out:
                            json.dump(d, out, ensure_ascii=False, indent=1)
            except (OSError, ValueError):
                continue

    def plan(self, plan_id):
        """Plan mit allen Platzierungen (fuer die Karte). Vorhandener Fortschritt, sonst eine Vorschau."""
        import tempfile
        from aufnahme import plan as P, geometrie as G
        defn = P.load_definition(plan_id)
        path = os.path.join(P.runs_root(), plan_id, "plan.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            vorschau = False
        else:
            data = P.create(defn, root=tempfile.mkdtemp(prefix="plan_vorschau_")).data
            vorschau = True
        runden = []
        for r in data["runden"]:
            p = r.get("platzierung") or {}
            g = defn["geometrie"]
            ecken = G.corners(p["x"], p["y"], p["winkel"], g["laenge"], g["breite"]) if p else []
            runden.append({"runde": r["runde"], "status": r.get("status"), "x": p.get("x"), "y": p.get("y"),
                           "winkel": p.get("winkel"), "ausrichtung": p.get("ausrichtung"), "ecken": ecken,
                           "behalten": len(r.get("behalten") or [])})
        return {"id": plan_id, "name": defn.get("name"), "beschreibung": defn.get("beschreibung"),
                "geometrie": defn["geometrie"], "methode": defn.get("methode"), "datensatz": defn.get("datensatz"),
                "objekt": defn.get("objekt"), "bauteile": defn.get("bauteile"), "runden": runden,
                "aktuell": data.get("aktuelle_runde"), "vorschau": vorschau,
                "fertig": sum(1 for r in runden if r["status"] == "fertig")}

    # --- Teilen ---
    def modell_teilen(self, modell, mit_datensatz):
        from ki import jobs, MODELS, DATASETS
        team = self.team()
        if not team:
            raise ValueError("Bitte zuerst mit dem Team-Code anmelden.")
        meta = next((m for m in jobs.models() if m.get("name") == modell), None)
        if meta is None:
            raise ValueError(f"Modell {modell!r} nicht gefunden (noch nicht fertig trainiert?)")
        ckpt = meta.get("checkpoint") or jobs.latest_checkpoint(os.path.join(MODELS, modell, "lauf"))
        if not ckpt or not os.path.isdir(ckpt):
            raise ValueError("Kein fertiger Modellstand gefunden.")
        hf = team.get("huggingface") or {}
        repo = hf.get("modell_repo") or f"{hf.get('org', 'RoboForge')}/{team['ordner']}-modelle"
        drepo = hf.get("datensatz_repo") or f"{hf.get('org', 'RoboForge')}/{team['ordner']}-daten"
        karte = kern.modell_karte(meta, team)

        def job(log):
            res = kern.hf_hochladen(team, ckpt, repo, modell, "model", karte, log)
            if mit_datensatz and meta.get("dataset"):
                ds = os.path.join(DATASETS, os.path.basename(meta["dataset"]))
                if os.path.isdir(ds):
                    log("Jetzt der Datensatz ...")
                    kern.hf_hochladen(team, ds, drepo, os.path.basename(ds), "dataset",
                                      f"# {os.path.basename(ds)}\n\nAufgenommen von {team.get('team')} mit dem "
                                      "Physical AI Harness by RoboForge (RoboForge-Format: mp4 + npz je Episode).\n",
                                      log)
            self.zustand.arbeit("teilen", f"Modell {modell} geteilt")
            return res
        return self.aufgaben.start("modell", job)

    def code_teilen(self, nachricht):
        team = self.team()
        if not team:
            raise ValueError("Bitte zuerst mit dem Team-Code anmelden.")

        def job(log):
            r = kern.git_teilen(team, nachricht, log)
            self.zustand.arbeit("teilen", "Code geteilt")
            return r
        return self.aufgaben.start("code", job)

    def code_holen(self):
        team = self.team()
        if not team:
            raise ValueError("Bitte zuerst mit dem Team-Code anmelden.")
        return self.aufgaben.start("holen", lambda log: kern.git_holen(team, log))


APP = None


class Handler(BaseHTTPRequestHandler):
    server_version = "PhysicalAIHarness/1"

    def log_message(self, fmt, *args):
        pass

    # --- Hilfen ---
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)) or body is None:
            body = json.dumps(body, default=str, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5 * 2**20:
            raise ValueError("zu gross")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, {"fehler": "nicht gefunden"})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # --- GET ---
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"fehler": "nur lokal"})
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            p = url.path
            if p in ("/", "/index.html"):
                return self._file(os.path.join(STATIC, "index.html"))
            if p.startswith("/static/"):
                return self._file(kern.sicherer_pfad(STATIC, p[len("/static/"):]))
            if p.startswith("/team-ui/"):
                ordner = APP.team_ordner()
                if not ordner:
                    return self._send(404, "Kein Team angemeldet", "text/plain; charset=utf-8")
                rel = p[len("/team-ui/"):] or "index.html"
                return self._file(kern.sicherer_pfad(os.path.join(ordner, "ui"), rel))
            if p == "/api/zustand":
                return self._send(200, APP.zustand_api())
            if p == "/api/daten":
                return self._send(200, APP.daten())
            if p == "/api/plan":
                return self._send(200, APP.plan(q["id"]))
            if p == "/api/kamera":
                r = APP.harness.call("kamera.bild", {"arm": q["arm"], "kamera": q["kamera"]}, timeout=5)
                return self._send(200, base64.b64decode(r["jpeg_base64"]), "image/jpeg")
            if p == "/api/skills":
                return self._send(200, APP.harness.call("skills.liste", timeout=10))
            if p == "/api/orchestrator":
                ordner = APP.team_ordner()
                return self._send(200, {**APP.orch.status(),
                                        "dateien": kern.team_dateien(ordner) if ordner else []})
            if p == "/api/datei":
                ordner = APP.team_ordner()
                path = kern.sicherer_pfad(ordner, q["pfad"])
                with open(path, encoding="utf-8", errors="replace") as f:
                    return self._send(200, {"pfad": q["pfad"], "inhalt": f.read()})
            if p == "/api/git":
                return self._send(200, kern.git_info(APP.team()) if APP.team() else {"klon": False,
                                                                                    "grund": "nicht angemeldet"})
            if p == "/api/geraet":
                APP._geraet = kern.geraet(refresh=q.get("neu") == "1")
                return self._send(200, APP._geraet)
            return self._send(404, {"fehler": "unbekannt"})
        except Exception as exc:
            return self._send(400, {"fehler": str(exc)})

    # --- POST ---
    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-RF") != "1":
            return self._send(403, {"fehler": "nur aus der Plattform-Seite"})
        p = urlparse(self.path).path
        try:
            b = self._json()
            if p == "/api/ansehen":
                APP.zustand.ansehen(str(b.get("abschnitt", "start"))[:40], b.get("scroll"))
                return self._send(200, {"ok": True})
            if p == "/api/arbeit":
                APP.zustand.arbeit(str(b.get("abschnitt"))[:40], str(b.get("was"))[:120])
                return self._send(200, {"ok": True})
            if p == "/api/login":
                paket, notes = APP.teams.login(b.get("code"))
                APP.zustand.arbeit("start", f"angemeldet als {paket.get('team')}")
                return self._send(200, {"team": kern.public(paket), "hinweise": notes})
            if p == "/api/logout":
                APP.teams.logout()
                return self._send(200, {"ok": True})
            if p == "/api/harness/starten":
                return self._send(200, APP.harness.starten())
            if p == "/api/skill":
                res = APP.harness.call(str(b["name"]), b.get("args") or {}, timeout=b.get("timeout") or 60)
                if str(b["name"]).startswith("station."):
                    APP.zustand.arbeit(b.get("abschnitt") or "harness", f"{b['name']} {b.get('args', {}).get('was', '')}")
                return self._send(200, {"ok": True, "ergebnis": res})
            if p == "/api/training/start":
                job = APP.queue().add(b["datensatz"], b["methode"], int(b["schritte"]) if b.get("schritte") else None)
                APP.zustand.arbeit("trainieren", f"Training {job.name} gestartet")
                return self._send(200, {"name": job.name})
            if p == "/api/training/aktion":
                q, name, was = APP.queue(), b["name"], b["was"]
                if was == "pause":
                    q.pause(name, True)
                elif was == "fortsetzen":
                    q.pause(name, False)
                elif was == "abbrechen":
                    q.cancel(name)
                elif was == "weiter":
                    q.resume(name)
                else:
                    raise ValueError("unbekannte Aktion")
                APP.zustand.arbeit("trainieren", f"Training {name}: {was}")
                return self._send(200, {"ok": True})
            if p == "/api/datei":
                ordner = APP.team_ordner()
                if not ordner:
                    raise ValueError("Bitte zuerst anmelden.")
                path = kern.sicherer_pfad(ordner, b["pfad"])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(b.get("inhalt", ""))
                APP.zustand.arbeit(b.get("abschnitt") or "orchestrator", f"{b['pfad']} gespeichert")
                return self._send(200, {"ok": True})
            if p == "/api/orchestrator/start":
                ordner = APP.team_ordner()
                if not ordner:
                    raise ValueError("Bitte zuerst anmelden.")
                APP.orch.start(ordner, b.get("datei") or "orchestrator.py")
                APP.zustand.arbeit("orchestrator", "Orchestrator gestartet")
                return self._send(200, {"ok": True})
            if p == "/api/orchestrator/stop":
                APP.orch.stop()
                return self._send(200, {"ok": True})
            if p == "/api/teilen/modell":
                APP.modell_teilen(b["modell"], bool(b.get("datensatz")))
                return self._send(200, {"ok": True})
            if p == "/api/teilen/code":
                APP.code_teilen(b.get("nachricht") or "")
                return self._send(200, {"ok": True})
            if p == "/api/teilen/holen":
                APP.code_holen()
                return self._send(200, {"ok": True})
            return self._send(404, {"fehler": "unbekannt"})
        except Exception as exc:
            if not isinstance(exc, (ValueError, KeyError)):
                traceback.print_exc()
            return self._send(400, {"fehler": str(exc) or exc.__class__.__name__})


def serve(port=PORT, open_browser=True):
    global APP
    APP = App()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Physical AI Harness laeuft: {url}", flush=True)
    if open_browser:
        from .fenster import oeffnen
        threading.Timer(0.8, lambda: oeffnen(url)).start()
    httpd.serve_forever()
