"""Logik der Plattform ohne Oberflaeche (testbar): Zustand merken, Team-Anmeldung, Hackathon-Plan,
Orchestrator starten, Ergebnisse teilen (Hugging Face, GitHub).

Geheimnisse (Tokens) bleiben im Stationspaket bzw. in plattform_daten/team.json und gehen nie an den Browser.
"""
import datetime, json, os, re, shutil, subprocess, sys, threading, time
from . import DATEN, KIT, PAKETE, TEAMS, HIER

SECRET_KEYS = ("token",)


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    for i in range(20):                       # Windows: Leser kann die Datei kurz offen halten
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    os.replace(tmp, path)


def public(d):
    """Kopie ohne Geheimnisse (fuer den Browser)."""
    if isinstance(d, dict):
        return {k: ("•••" if k in SECRET_KEYS and v else public(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [public(x) for x in d]
    return d


# --- Zustand: wo hat man zuletzt gearbeitet? --------------------------------------------------------------
class Zustand:
    """Merkt sich den Abschnitt, in dem zuletzt etwas passiert ist (Training gestartet, Code gespeichert ...),
    und den zuletzt angesehenen. Beim Start springt die Oberflaeche dorthin."""

    def __init__(self, root=DATEN):
        self.path = os.path.join(root, "zustand.json")
        self.lock = threading.Lock()

    def get(self):
        return _read(self.path, {}) or {}

    def ansehen(self, abschnitt, scroll=None):
        with self.lock:
            d = self.get()
            d["angesehen"] = {"abschnitt": abschnitt, "scroll": scroll, "zeit": time.time()}
            _write(self.path, d)

    def arbeit(self, abschnitt, was):
        with self.lock:
            d = self.get()
            d["gearbeitet"] = {"abschnitt": abschnitt, "was": was, "zeit": time.time()}
            log = d.setdefault("verlauf", [])
            log.append({"abschnitt": abschnitt, "was": was, "zeit": time.time()})
            del log[:-50]
            d.setdefault("erledigt", {})[abschnitt] = True
            _write(self.path, d)

    def startpunkt(self):
        """Abschnitt zum Starten: der zuletzt bearbeitete, ausser man hat danach laenger woanders gelesen."""
        d = self.get()
        g, a = d.get("gearbeitet"), d.get("angesehen")
        if g and (not a or a["zeit"] - g["zeit"] < 600):
            return {"abschnitt": g["abschnitt"], "scroll": None, "grund": f"zuletzt: {g['was']}"}
        if a:
            return {"abschnitt": a["abschnitt"], "scroll": a.get("scroll"), "grund": "zuletzt angesehen"}
        return {"abschnitt": "start", "scroll": 0, "grund": "erster Start"}


# --- Team und Station ------------------------------------------------------------------------------------
def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
               .replace("ß", "ss")).strip("-")
    return s or "team"


# Die sechs Hackathon-Teams. Code = Anmeldung, Farbe = Akzentfarbe der App. Ein Paket mit gleichem Code
# (stationspakete/*.json) ergaenzt Zugaenge und Station.
STANDARD_TEAMS = [
    {"code": "BLUE-1", "team": "Team Blue", "farbe": "#3d8bfd"},
    {"code": "RED-2", "team": "Team Red", "farbe": "#e5484d"},
    {"code": "GREEN-3", "team": "Team Green", "farbe": "#3fb950"},
    {"code": "YELLOW-4", "team": "Team Yellow", "farbe": "#e8b230"},
    {"code": "ORANGE-5", "team": "Team Orange", "farbe": "#f0883e"},
    {"code": "PURPLE-6", "team": "Team Purple", "farbe": "#a371f7"},
]


class Teams:
    """Anmeldung mit Team-Code. Ein Paket (stationspakete/*.json) bringt mit:
    Teamname, Ordner, Hugging-Face- und GitHub-Daten, optional die Kalibrierung der Station."""

    def __init__(self, pakete=PAKETE, daten=DATEN, kit=KIT, teams=TEAMS):
        self.pakete, self.daten, self.kit, self.teams = pakete, daten, kit, teams
        self.path = os.path.join(daten, "team.json")

    def aktiv(self):
        return _read(self.path)

    def pakete_liste(self):
        out = []
        if os.path.isdir(self.pakete):
            for f in sorted(os.listdir(self.pakete)):
                if f.endswith(".json"):
                    p = _read(os.path.join(self.pakete, f))
                    if isinstance(p, dict) and p.get("code"):
                        out.append(p)
        codes = {str(p["code"]).strip().upper(): p for p in out}
        for s in STANDARD_TEAMS:
            if s["code"] in codes:
                codes[s["code"]].setdefault("farbe", s["farbe"])
            else:
                out.append(dict(s))
        return out

    def auswahl(self):
        """Teams fuer die Auswahl oben rechts (ohne Zugangsdaten)."""
        return [{"code": p["code"], "team": p.get("team", p["code"]), "farbe": p.get("farbe")}
                for p in self.pakete_liste()]

    def login(self, code):
        code = str(code or "").strip().upper()
        if not code:
            raise ValueError("Bitte den Team-Code eingeben.")
        paket = next((p for p in self.pakete_liste() if str(p["code"]).strip().upper() == code), None)
        if paket is None:
            raise ValueError("Unbekannter Team-Code. Liegt das Stationspaket im Ordner 'stationspakete'?")
        paket = dict(paket)
        paket.setdefault("ordner", slug(paket.get("team", "team")))
        paket["ordner"] = slug(paket["ordner"])
        paket["angemeldet"] = time.strftime("%Y-%m-%d %H:%M:%S")
        notes = []
        station = paket.get("station") or {}
        if station.get("kalibrierung") or station.get("config"):
            notes.append(self.install_station(station))
        ordner = self.team_ordner(paket)
        if not os.path.isdir(ordner):
            vorlage = os.path.join(self.teams, "_vorlage")
            if os.path.isdir(vorlage):
                shutil.copytree(vorlage, ordner)
                notes.append(f"Team-Ordner teams/{paket['ordner']} aus der Vorlage angelegt.")
            else:
                os.makedirs(ordner, exist_ok=True)
        _write(self.path, paket)
        return paket, notes

    def logout(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def team_ordner(self, paket=None):
        paket = paket or self.aktiv()
        return os.path.join(self.teams, paket["ordner"]) if paket else None

    def install_station(self, station):
        """Kalibrierung und Arm-Zuordnung der Station uebernehmen. Bisheriges wird vorher gesichert."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(self.daten, "sicherung", stamp)
        cal_dir = os.path.join(self.kit, "calibration")
        os.makedirs(backup, exist_ok=True)
        written = []
        for name, content in (station.get("kalibrierung") or {}).items():
            name = os.path.basename(name)
            if not name.endswith(".json"):
                continue
            dst = os.path.join(cal_dir, name)
            if os.path.exists(dst):
                shutil.copy2(dst, os.path.join(backup, name))
            _write(dst, content)
            written.append(name)
        if station.get("config"):
            cfg_path = os.path.join(self.kit, "config.json")
            if os.path.exists(cfg_path):
                shutil.copy2(cfg_path, os.path.join(backup, "config.json"))
            _write(cfg_path, station["config"])
            written.append("config.json")
        return (f"Station '{station.get('name', '?')}' eingerichtet ({len(written)} Dateien, Sicherung in "
                f"plattform_daten/sicherung/{stamp}). Harness danach neu starten.")


# --- Hackathon-Plan -------------------------------------------------------------------------------------
def _hm(text):
    h, m = str(text).split(":")
    return int(h) * 60 + int(m)


class Hackathon:
    def __init__(self, path=os.path.join(HIER, "hackathon_plan.json")):
        self.path = path

    def plan(self):
        return _read(self.path, {}) or {}

    def jetzt(self, now=None):
        """Aktuelle Phase, naechste Phase, faellige Erinnerungen (nur am Hackathon-Tag)."""
        p = self.plan()
        now = now or datetime.datetime.now()
        heute = now.strftime("%Y-%m-%d") == p.get("datum")
        minute = now.hour * 60 + now.minute
        phasen = p.get("phasen", [])
        akt = nxt = None
        for i, ph in enumerate(phasen):
            if _hm(ph["start"]) <= minute < _hm(ph["ende"]):
                akt = i
            if nxt is None and _hm(ph["start"]) > minute:
                nxt = i
        erinnerungen = []
        for e in p.get("erinnerungen", []):
            delta = _hm(e["zeit"]) - minute
            if heute and -30 <= delta <= 20:
                erinnerungen.append({**e, "in_min": delta})
        return {"heute": heute, "datum": p.get("datum"), "titel": p.get("titel"), "aufgabe": p.get("aufgabe"), "phasen": phasen,
                "aktuell": akt if heute else None, "naechste": nxt if heute else None,
                "erinnerungen": erinnerungen, "minute": minute}


# --- Hintergrund-Aufgaben (Hochladen, Git) mit Fortschritt ---------------------------------------------------
class Aufgaben:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def start(self, key, fn):
        with self.lock:
            cur = self.items.get(key)
            if cur and cur["laeuft"]:
                raise ValueError("Laeuft schon.")
            st = {"laeuft": True, "zeilen": [], "ok": None, "ergebnis": None, "start": time.time()}
            self.items[key] = st

        def log(line):
            with self.lock:
                st["zeilen"].append(str(line).rstrip())
                del st["zeilen"][:-200]

        def run():
            try:
                st["ergebnis"] = fn(log)
                st["ok"] = True
            except Exception as exc:
                log(f"FEHLER: {exc}")
                st["ok"] = False
            finally:
                st["laeuft"] = False
        threading.Thread(target=run, daemon=True, name=f"aufgabe-{key}").start()
        return st

    def status(self):
        with self.lock:
            return {k: {**v, "zeilen": v["zeilen"][-40:]} for k, v in self.items.items()}


def run_lines(cmd, log, env=None, cwd=KIT, popen=subprocess.Popen):
    """Befehl ausfuehren, Ausgabe zeilenweise loggen. Fehler -> Exception."""
    proc = popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                 encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 if sys.platform == "win32" else 0)
    out = []
    for line in proc.stdout:
        out.append(line)
        log(line)
    if proc.wait() != 0:
        raise RuntimeError(f"{os.path.basename(str(cmd[0]))} endete mit Fehler {proc.returncode}")
    return "".join(out)


# --- Hugging Face ----------------------------------------------------------------------------------------
def modell_karte(meta, team, plattform="Physical AI Harness by RoboForge"):
    """README (Model Card) fuer ein Modell, mit Schlagwoertern fuer die Community."""
    m = meta or {}
    name = m.get("name", "modell")
    lines = ["---", "library_name: lerobot", "license: apache-2.0", "tags:", "  - lerobot", "  - robotics",
             "  - so101", "  - physical-ai-harness", "  - hackathon-karlsruhe-2026",
             f"  - {m.get('method', 'act')}", "---", "",
             f"# {name}", "",
             f"Trainiert von **{team.get('team', '?')}** beim Physical AI Hackathon Karlsruhe (28.11.2026) "
             f"mit dem [{plattform}](https://roboforge.eu).", "",
             "| | |", "|---|---|",
             f"| Methode | {m.get('method', '?')} |",
             f"| Datensatz | {m.get('dataset', '?')} |",
             f"| Aufgabe | {m.get('task', '-')} |",
             f"| Episoden | {m.get('episodes') or m.get('episodes_n') or '?'} |",
             f"| Trainingsschritte | {m.get('steps', '?')} |",
             f"| Roboter | SO-101 (LeRobot) |", "",
             "## Benutzen", "",
             "Im Physical AI Harness unter *VLA trainieren -> Modell testen* den Repo-Namen eintragen, oder mit "
             "LeRobot: `--policy.path=<repo>/<ordner>`.", ""]
    return "\n".join(lines)


def hf_hochladen(team, ordner, ziel_repo, unterordner, typ, karte, log, python=None, popen=subprocess.Popen):
    """Laedt einen Ordner in ein Hugging-Face-Repo (Unterordner) hoch. Laeuft in der KI-Umgebung
    (dort ist huggingface_hub installiert). Der Token geht nur ueber die Umgebung, nie in die Befehlszeile."""
    from ki import KI_PYTHON
    hf = team.get("huggingface") or {}
    token = hf.get("token")
    if not token:
        raise ValueError("Im Team-Paket fehlt der Hugging-Face-Token.")
    env = dict(os.environ, HF_TOKEN=token, PYTHONIOENCODING="utf-8")
    karte_path = os.path.join(DATEN, "karte_tmp.md")
    os.makedirs(DATEN, exist_ok=True)
    with open(karte_path, "w", encoding="utf-8") as f:
        f.write(karte or "")
    cmd = [python or KI_PYTHON, "-u", os.path.join(HIER, "hf_hochladen.py"), "--repo", ziel_repo, "--ordner", ordner,
           "--unterordner", unterordner, "--typ", typ, "--karte", karte_path]
    run_lines(cmd, log, env=env, popen=popen)
    url = f"https://huggingface.co/{'datasets/' if typ == 'dataset' else ''}{ziel_repo}/tree/main/{unterordner}"
    log(f"Fertig: {url}")
    return {"url": url}


# --- GitHub (Team-Ordner teilen) -------------------------------------------------------------------------
def git(args, log=None, cwd=KIT, env=None, check=True):
    p = subprocess.run(["git"] + args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                       if sys.platform == "win32" else 0)
    if log:
        for line in (p.stdout + p.stderr).splitlines():
            if line.strip():
                log(line)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {(p.stderr or p.stdout).strip()[-300:]}")
    return p


def git_env(team):
    """Token als HTTP-Kopfzeile ueber Umgebungsvariablen (nicht in der Befehlszeile, nicht in .git/config)."""
    import base64
    gh = team.get("github") or {}
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if gh.get("token"):
        basic = base64.b64encode(f"x-access-token:{gh['token']}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}")
    return env


def git_info(team, cwd=KIT):
    """Ist diese Kopie ein Klon des Hackathon-Repos? Welcher Zweig?"""
    gh = (team or {}).get("github") or {}
    try:
        top = git(["rev-parse", "--show-toplevel"], cwd=cwd).stdout.strip()
        url = git(["remote", "get-url", "origin"], cwd=cwd, check=False).stdout.strip()
        zweig = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()
    except Exception:
        return {"klon": False, "grund": "kein Git-Ordner"}
    want = (gh.get("repo") or "").rstrip("/").removesuffix(".git").lower()
    passt = bool(want) and url.rstrip("/").removesuffix(".git").lower() == want
    return {"klon": passt, "url": url, "zweig": zweig, "soll_zweig": gh.get("zweig"), "top": top,
            "grund": "" if passt else ("Diese Kopie ist nicht das Hackathon-Repo" if want else "kein GitHub im Paket")}


def git_teilen(team, nachricht, log, cwd=KIT):
    """Team-Ordner committen und in den Team-Zweig hochladen (mit Holen der Aenderungen der Teamkollegen).
    Es wird nur teams/<ordner>/ hinzugefuegt. Der Waechter auf GitHub uebernimmt nur diesen Ordner nach main."""
    gh = team.get("github") or {}
    info = git_info(team, cwd)
    if not info["klon"]:
        raise ValueError(info["grund"])
    zweig = gh.get("zweig") or f"team/{team['ordner']}"
    env = git_env(team)
    ordner = f"teams/{team['ordner']}"
    if info["zweig"] != zweig:
        log(f"Wechsle auf den Team-Zweig {zweig} ...")
        git(["fetch", "origin"], log, cwd, env)
        exists = git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{zweig}"], cwd=cwd, check=False)
        base = f"origin/{zweig}" if exists.returncode == 0 else "origin/main"
        git(["checkout", "-B", zweig, base], log, cwd, env)
    git(["add", "--", ordner], log, cwd, env)
    who = ["-c", f"user.name={team.get('team', 'Team')}", "-c", f"user.email={team['ordner']}@hackathon.roboforge.eu"]
    changed = git(["diff", "--cached", "--quiet"], cwd=cwd, check=False).returncode != 0
    if changed:
        git(who + ["commit", "-m", nachricht or f"{team.get('team')}: Stand {time.strftime('%H:%M')}", "--", ordner],
            log, cwd, env)
    else:
        log("Keine neuen Aenderungen im Team-Ordner.")
    git(who + ["pull", "--rebase", "--autostash", "origin", zweig], log, cwd, env, check=False)
    git(["push", "origin", f"HEAD:refs/heads/{zweig}"], log, cwd, env)
    log(f"Hochgeladen in {zweig}. Der Waechter uebernimmt den Ordner in wenigen Minuten nach main.")
    return {"zweig": zweig, "neu": changed}


def git_holen(team, log, cwd=KIT):
    """Aenderungen der Teamkollegen holen (Team-Zweig)."""
    gh = team.get("github") or {}
    info = git_info(team, cwd)
    if not info["klon"]:
        raise ValueError(info["grund"])
    zweig = gh.get("zweig") or f"team/{team['ordner']}"
    env = git_env(team)
    git(["fetch", "origin"], log, cwd, env)
    if info["zweig"] != zweig:
        exists = git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{zweig}"], cwd=cwd, check=False)
        git(["checkout", "-B", zweig, f"origin/{zweig}" if exists.returncode == 0 else "origin/main"], log, cwd, env)
    who = ["-c", f"user.name={team.get('team', 'Team')}", "-c", f"user.email={team['ordner']}@hackathon.roboforge.eu"]
    git(who + ["pull", "--rebase", "--autostash", "origin", zweig], log, cwd, env, check=False)
    return {"zweig": zweig}


# --- Orchestrator des Teams ------------------------------------------------------------------------------
class Orchestrator:
    """Startet teams/<ordner>/orchestrator.py als eigenen Prozess. Stuerzt er ab, bleibt der Arm sicher
    (Harness laeuft getrennt). Ausgabe landet in plattform_daten/orchestrator.log."""

    def __init__(self, daten=DATEN):
        self.proc = None
        self.log_path = os.path.join(daten, "orchestrator.log")
        self.started = None

    def laeuft(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, ordner, datei="orchestrator.py"):
        if self.laeuft():
            raise ValueError("Der Orchestrator laeuft schon.")
        script = os.path.join(ordner, datei)
        if not os.path.exists(script):
            raise ValueError(f"{datei} fehlt im Team-Ordner.")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        logf = open(self.log_path, "w", encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=KIT + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-u", script], cwd=ordner, env=env, stdout=logf,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                     if sys.platform == "win32" else 0)
        self.started = time.time()
        return True

    def stop(self):
        if self.laeuft():
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return True

    def status(self):
        tail = ""
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-6000:]
        except OSError:
            pass
        return {"laeuft": self.laeuft(), "seit": self.started, "log": tail,
                "code": None if self.proc is None else self.proc.poll()}


# --- Dateien im Team-Ordner (einfacher Editor) --------------------------------------------------------------
TEXT_ENDUNGEN = (".py", ".md", ".json", ".html", ".js", ".css", ".txt", ".yaml", ".yml", ".toml")


def team_dateien(ordner):
    out = []
    for root, dirs, files in os.walk(ordner):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ordner).replace(os.sep, "/")
            out.append({"pfad": rel, "groesse": os.path.getsize(p), "text": f.endswith(TEXT_ENDUNGEN),
                        "geaendert": os.path.getmtime(p)})
    return sorted(out, key=lambda x: x["pfad"])


def sicherer_pfad(ordner, rel):
    """Pfad innerhalb des Team-Ordners, sonst Fehler."""
    p = os.path.realpath(os.path.join(ordner, rel))
    if not (p == os.path.realpath(ordner) or p.startswith(os.path.realpath(ordner) + os.sep)):
        raise ValueError("Nur Dateien im eigenen Team-Ordner.")
    return p


# --- Rechenwerk (einmal in der KI-Umgebung ermitteln, dann merken) --------------------------------------------
def geraet(daten=DATEN, refresh=False, run=subprocess.run):
    path = os.path.join(daten, "geraet.json")
    d = None if refresh else _read(path)
    if d and time.time() - d.get("zeit", 0) < 7 * 86400:
        return d
    from ki import KI_PYTHON, geraet as G
    dev, name, mem = "cpu", "", None
    if os.path.exists(KI_PYTHON):
        code = ("import json,torch;from ki.geraet import detect;d=detect(torch);n='';m=None\n"
                "if d=='cuda':\n p=torch.cuda.get_device_properties(0);n=p.name;m=round(p.total_memory/2**30)\n"
                "print(json.dumps({'d':d,'n':n,'m':m}))")
        try:
            out = run([KI_PYTHON, "-c", code], cwd=KIT, capture_output=True, text=True, timeout=120,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
            j = json.loads(out.stdout.strip().splitlines()[-1])
            dev, name, mem = j["d"], j["n"], j["m"]
        except Exception:
            pass
        ki_ok = True
    else:
        ki_ok = False
    methode, text = G.empfehlung(dev)
    d = {"geraet": dev, "name": name or G.beschreibung(dev), "speicher_gb": mem, "empfehlung": methode,
         "text": text, "ki_umgebung": ki_ok, "system": sys.platform, "zeit": time.time()}
    _write(path, d)
    return d
