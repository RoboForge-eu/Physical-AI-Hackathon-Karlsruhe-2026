"""Trainings-Warteschlange: 1) Aufnahmen ins LeRobot-Format umwandeln, 2) trainieren (KI-Umgebung ki-env).
Immer nur ein Training gleichzeitig (eine Grafikkarte); weitere warten.

Unabhaengig vom Harness: Der Harness (DetachedQueue) legt nur Auftragsdateien in ki_daten/training_auftraege/ an
und startet bei Bedarf den Trainings-Dienst (python -m ki.trainer, eigener Prozess ohne Fenster). Der Dienst
arbeitet die Auftraege ab und schreibt Zustand, Schritt und Fehlerwert laufend in die Datei. Harness, VLA-Studio
und die anderen Programme koennen also neu starten oder geaendert werden, ohne das Training zu stoeren.
"""
import json, os, re, subprocess, sys, threading, time
from . import DATA, DATASETS, MODELS, KI_PYTHON, HERE, methods
from .episodes import Dataset, slug
from . import auswahl

STEP_RE = re.compile(r"\bstep:\s*([\d.]+)([KMB]?)\b", re.I)
LOSS_RE = re.compile(r"\bloss:\s*([\d.eE+-]+)")
SCALE = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
AUGMENT_ARG = "--dataset.image_transforms.enable=true"   # Bild-Variation: Helligkeit, Kontrast, Farbe, Schaerfe, leicht verschoben
QUIET_PAUSE = 1.0     # Leise: nach jedem Lernschritt so lange Pause wie der Schritt gedauert hat (~halbe Last)
STORE = os.path.join(DATA, "training_auftraege")      # <name>.json je Auftrag, <name>.abbrechen / .pause = Wuensche
ACTIVE = ("wartet", "umwandeln", "training", "pausiert")


_CAFFEINATE = None


def keep_awake(on):
    """Ruhezustand verhindern, solange trainiert wird (Bildschirm darf aus).
    Windows: fuer den aufrufenden Thread. macOS: ueber 'caffeinate' (endet spaetestens mit diesem Prozess)."""
    global _CAFFEINATE
    if sys.platform == "darwin":
        try:
            if on and (_CAFFEINATE is None or _CAFFEINATE.poll() is not None):
                _CAFFEINATE = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            elif not on and _CAFFEINATE is not None:
                _CAFFEINATE.terminate()
                _CAFFEINATE = None
            return True
        except Exception:
            return False
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
        return True
    except Exception:                       # anderes Betriebssystem: nichts tun
        return False


def parse_progress(line):
    """LeRobot-Logzeile -> (schritt, loss) oder None."""
    m = STEP_RE.search(line)
    if not m:
        return None
    step = int(float(m.group(1)) * SCALE[m.group(2).upper()])
    l = LOSS_RE.search(line)
    return step, (float(l.group(1)) if l else None)


class Job:
    taken = set()      # vergebene Namen in dieser Sitzung (mehrere Trainings in derselben Minute)

    def __init__(self, dataset, method_key, steps=None, name=None, quiet=False, augment=False, cameras=None,
                 filters=None, export=None, fixed_name=False, store=None):
        self.dataset = dataset if isinstance(dataset, Dataset) else Dataset(
            dataset if os.path.isabs(dataset) else os.path.join(DATASETS, dataset))
        self.method = methods.get(method_key)
        self.steps = int(steps or self.method.default_steps)
        self.quiet = bool(quiet)
        self.augment = bool(augment)
        # Kamerawahl und Filter (Aufnahmeplaene); ohne Angabe: alle Kameras, alle Episoden wie bisher
        self.filters = {**auswahl.EXPORTE.get(export, {}), **(filters or {})} if (filters or export) else None
        self.filters_in = dict(filters) if filters else None
        self.cameras_in = list(cameras) if cameras else None
        self.export = export
        self.cameras = list(cameras) if cameras else list(self.dataset.meta.get("cameras") or [])
        self.episodes, self.excluded = (auswahl.select(self.dataset, self.cameras, self.filters)
                                        if (cameras or self.filters) else (self.dataset.episodes(), {}))
        stamp = time.strftime("%Y%m%d-%H%M")
        base = name or f"{slug(self.dataset.name)}-{export + '-' if export else ''}{self.method.key}-{stamp}"
        self.name, n = base, 2
        while not fixed_name and (os.path.exists(os.path.join(MODELS, self.name)) or self.name in Job.taken
                                  or (store and os.path.exists(os.path.join(store, self.name + ".json")))):
            self.name, n = f"{base}-{n}", n + 1
        Job.taken.add(self.name)
        self.dir = os.path.join(MODELS, self.name)
        self.state = "wartet"          # wartet | umwandeln | training | fertig | fehler | abgebrochen
        self.step = 0
        self.loss = None
        self.started = None
        self.message = ""
        self.process = None
        self.cancelled = False
        self.store = store             # Ordner der Auftragsdateien (None: nur im Speicher, z. B. Tests)
        self.created = time.time()
        self.resume = False            # True: beim letzten Zwischenstand weitertrainieren (nach Neustart/Fehler)
        self._saved = 0.0

    # --- Auftragsdatei (Dienst <-> Harness) ---
    def spec(self):
        return {"name": self.name, "dataset_path": self.dataset.path, "method": self.method.key, "steps": self.steps,
                "quiet": self.quiet, "augment": self.augment, "cameras": self.cameras_in,
                "filters": self.filters_in, "export": self.export, "created": self.created, "resume": self.resume}

    def save(self, force=True):
        """Zustand in die Auftragsdatei (atomar). force=False: hoechstens alle 2 s (Fortschritt)."""
        if not self.store or (not force and time.time() - self._saved < 2.0):
            return
        self._saved = time.time()
        os.makedirs(self.store, exist_ok=True)
        data = {**self.spec(), "state": self.state, "step": self.step, "loss": self.loss, "started": self.started,
                "message": self.message, "episodes_n": len(self.episodes), "step0": getattr(self, "step0", 0), "cameras_used": self.cameras,
                "pid": os.getpid(),
                "updated": time.time()}
        path = os.path.join(self.store, self.name + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        # Windows: Ersetzen scheitert kurz, solange ein Leser (VLA-Studio, Harness) die Datei offen hat (25.11.:
        # Training brach bei Schritt 1000 mit 'Zugriff verweigert' ab). Kurz wiederholen; Fortschritt notfalls auslassen.
        for i in range(40 if force else 5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (1 + i % 5))
        if force:
            os.replace(tmp, path)

    @classmethod
    def load(cls, path, store=None):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        job = cls(d["dataset_path"], d["method"], d["steps"], name=d["name"], quiet=d.get("quiet"),
                  augment=d.get("augment"), cameras=d.get("cameras"), filters=d.get("filters"),
                  export=d.get("export"), fixed_name=True, store=store)
        job.state, job.step, job.loss = d.get("state", "wartet"), d.get("step", 0), d.get("loss")
        job.started, job.message, job.created = d.get("started"), d.get("message", ""), d.get("created", 0)
        job.resume = bool(d.get("resume"))
        return job

    def pause_requested(self):
        return bool(self.store and os.path.exists(os.path.join(self.store, self.name + ".pause")))

    def cancel_requested(self):
        return self.cancelled or bool(self.store and os.path.exists(os.path.join(self.store, self.name + ".abbrechen")))

    def info(self):
        eta = None
        if self.state == "training" and self.step > 0 and self.started:
            rate = (self.step - getattr(self, "step0", 0)) / max(1e-6, time.time() - self.started)
            eta = (self.steps - self.step) / rate if rate > 0 else None
        return {"name": self.name, "dataset": self.dataset.name, "method": self.method.key, "state": self.state,
                "step": self.step, "steps": self.steps, "loss": self.loss, "eta_s": eta, "message": self.message,
                "quiet": self.quiet, "augment": self.augment, "cameras": self.cameras,
                "episodes": len(self.episodes), "export": self.export}


class Queue:
    """Arbeitet Auftraege ab. Mit store: Auftraege kommen auch als Dateien (vom Harness) und der Zustand wird
    laufend dorthin geschrieben - so laeuft es im Trainings-Dienst (ki.trainer)."""

    def __init__(self, python=KI_PYTHON, log=print, popen=subprocess.Popen, store=None):
        self.python, self.log, self.popen, self.store = python, log, popen, store
        self.jobs = []
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.busy = False
        if store:
            self._adopt(startup=True)
        threading.Thread(target=self._loop, daemon=True, name="ki-jobs").start()

    def add(self, dataset, method_key, steps=None, quiet=False, augment=False, cameras=None, filters=None, export=None):
        job = Job(dataset, method_key, steps, quiet=quiet, augment=augment, cameras=cameras, filters=filters,
                  export=export, store=self.store)
        if not job.episodes:
            raise ValueError(f"Datensatz {job.dataset.name} hat noch keine Episoden")
        job.save()
        with self.lock:
            self.jobs.append(job)
        self.wake.set()
        return job

    def _adopt(self, startup=False):
        """Neue Auftragsdateien uebernehmen. Beim Start: was als laufend gespeichert ist, wurde unterbrochen."""
        if not os.path.isdir(self.store):
            return
        known = {j.name: j for j in self.jobs}
        for f in sorted(os.listdir(self.store)):
            old = known.get(f[:-5])
            if not f.endswith(".json") or (old is not None and old.state in ACTIVE):
                continue
            path = os.path.join(self.store, f)
            try:
                with open(path, encoding="utf-8") as fh:
                    state = json.load(fh).get("state")
                if state not in ACTIVE or (old is not None and state != "wartet"):
                    continue
                job = Job.load(path, self.store)
            except Exception as exc:          # kaputte Datei: Auftrag als Fehler markieren, Rest weiter
                self.log(f"Auftrag {f} nicht lesbar: {exc}")
                continue
            if startup and job.state in ("umwandeln", "training", "pausiert"):
                job.state, job.message = "fehler", "unterbrochen (PC oder Trainings-Dienst wurde beendet)"
                cp = resume_checkpoint(os.path.join(job.dir, "lauf"))
                if cp:
                    job.message += f" · Weitertrainieren ab Schritt {cp[0]} moeglich"
                job.save()
                continue
            with self.lock:
                if old is not None:
                    self.jobs.remove(old)
                self.jobs.append(job)

    def cancel(self, name):
        for job in self.jobs:
            if job.name == name and job.state in ACTIVE:
                job.cancelled = True
                if job.process and job.process.poll() is None:
                    job.process.terminate()
                if job.state == "wartet":
                    job.state = "abgebrochen"
                    job.save()
                return True
        return False

    def snapshot(self):
        with self.lock:
            return [j.info() for j in self.jobs]

    def active(self):
        return self.busy or any(j.state in ACTIVE for j in self.jobs)

    def _loop(self):
        while True:
            self.wake.wait(2)
            self.wake.clear()
            if self.store:
                self._adopt()
            job = next((j for j in self.jobs if j.state == "wartet" and not j.cancelled and not j.pause_requested()), None)
            if job is not None and job.cancel_requested():
                job.state, job.message = "abgebrochen", "abgebrochen bevor es losging"
                job.save()
                job = None
                self.wake.set()
            if job is not None:
                self.busy = True
                try:
                    self._run(job)
                except Exception as e:       # ein kaputtes Training darf die Nacht-Warteschlange nicht stoppen
                    job.state, job.message = "fehler", f"{type(e).__name__}: {e}"
                finally:
                    self.busy = False
                job.save()
                self.wake.set()              # gleich das naechste

    def _run(self, job):
        """Waehrend Umwandeln/Training darf der PC nicht in den Ruhezustand (Windows: pro Thread)."""
        keep_awake(True)
        try:
            self._run_job(job)
        finally:
            keep_awake(False)

    def _run_job(self, job):
        if not os.path.exists(self.python):
            job.state, job.message = "fehler", "KI-Umgebung (ki-env) fehlt"
            return
        os.makedirs(job.dir, exist_ok=True)
        lerobot_root = os.path.join(job.dir, "lerobot_datensatz")
        repo = f"roboforge/{slug(job.dataset.name)}"
        logpath = os.path.join(job.dir, "training.log")
        cams = job.cameras
        names = job.method.camera_names
        if names and len(cams) > len(names):
            job.state, job.message = "fehler", f"{job.method.label} kennt hoechstens {len(names)} Kameras"
            return
        camera_map = dict(zip(cams, names)) if names else {}
        sel_path = os.path.join(job.dir, "auswahl.json")
        cp = resume_checkpoint(os.path.join(job.dir, "lauf")) if job.resume else None
        if cp and os.path.isdir(lerobot_root):
            # Weitertrainieren: Daten sind schon umgewandelt; LeRobot laedt Gewichte, Optimierer und Schritt
            cfg = os.path.join(cp[1], "pretrained_model", "train_config.json")
            steps = [("training", [self.python, "-m", "ki.train", f"--config_path={cfg}", "--resume=true",
                                   f"--steps={job.steps}"])]
            job.step = cp[0]
            job.message = f"weiter ab Schritt {cp[0]}"
        else:
            if job.resume:
                job.message = "kein Zwischenstand gefunden - startet von vorn"
            steps = None
        job.resume = False
        if steps is None:
            job.step, job.loss = 0, None
            auswahl.write(sel_path, cams, job.episodes)
            steps = [("umwandeln", [self.python, "-m", "ki.convert", job.dataset.path, lerobot_root, repo,
                                json.dumps(camera_map), sel_path]),
                 ("training", job.method.train_command(self.python, lerobot_root, repo,
                                                       os.path.join(job.dir, "lauf"), job.steps, job=job.name)
                  + ([AUGMENT_ARG] if job.augment else []))]
        with open(logpath, "a" if job.step else "w", encoding="utf-8") as log:
            for state, cmd in steps:
                if job.cancel_requested():
                    job.state = "abgebrochen"
                    return
                job.state = state
                if state == "training":
                    job.started = time.time()
                    job.step0 = job.step          # Restzeit nur aus den Schritten dieses Laufs
                job.save()
                log.write(f"$ {' '.join(cmd)}\n")
                log.flush()
                job.process = self.popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace",
                                         env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                                              "ROBOFORGE_LEISE": str(QUIET_PAUSE if job.quiet else 0),
                                              "ROBOFORGE_ZUSTAND_RAUSCHEN": str(job.method.state_noise_deg or 0)},
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                done = threading.Event()
                if job.store:                    # Abbruch-/Pausewunsch per Datei auch ohne neue Logzeilen
                    threading.Thread(target=_watch, args=(job, done, state), daemon=True).start()
                try:
                    for line in job.process.stdout:
                        log.write(line)
                        p = parse_progress(line)
                        if p:
                            job.step = p[0]
                            job.loss = p[1] if p[1] is not None else job.loss
                        if line.strip():
                            job.message = line.strip()[-160:]
                        job.save(force=False)
                    rc = job.process.wait()
                finally:
                    done.set()
                if job.cancel_requested():
                    job.cancelled = True
                if job.cancelled:
                    job.state = "abgebrochen"
                    return
                if rc != 0:
                    job.state = "fehler"
                    job.message = f"{state} fehlgeschlagen (Code {rc}) · Details in {logpath}"
                    return
        meta = {"name": job.name, "method": job.method.key, "dataset": job.dataset.name,
                "task": job.dataset.meta.get("task"), "arm": job.dataset.meta.get("arm"),
                "steps": job.steps, "episodes": len(job.episodes), "leise": job.quiet, "bildvariation": job.augment,
                "startpose": start_pose(job.dataset),
                "calibration": job.dataset.meta.get("calibration"),
                "checkpoint": latest_checkpoint(os.path.join(job.dir, "lauf")),
                "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        # Harness-Kameras (arm/turm) -> Namen im Modell; Datensatz-Namen (wrist/overview) dazwischen
        slots = auswahl.slot_map(job.dataset)
        meta.update({"cameras": [slots.get(c, c) for c in cams],
                     "camera_map": {slots.get(c, c): camera_map.get(c, c) for c in cams} if (camera_map or slots) else {},
                     "dataset_cameras": cams, "filter": job.filters, "export": job.export,
                     "episoden_liste": job.episodes, "ausgeschlossen": job.excluded,
                     "plan": job.dataset.meta.get("plan"), "git": auswahl.git_commit()})
        with open(os.path.join(job.dir, "modell.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)
        job.message = "fertig"
        job.state, job.step = "fertig", job.steps     # erst wenn modell.json da ist


def _suspend(proc, on):
    """Trainingsprozess samt Kindprozessen (Daten-Lader) anhalten/weiterlaufen lassen. Speicher bleibt belegt."""
    import psutil
    try:
        root = psutil.Process(proc.pid)
        for p in [root] + root.children(recursive=True):
            try:
                p.suspend() if on else p.resume()
            except psutil.Error:
                pass
    except psutil.Error:
        pass


def _watch(job, done, state):
    paused_at = None
    while not done.wait(1.0):
        if job.cancel_requested():
            job.cancelled = True
            if job.process and job.process.poll() is None:
                if paused_at is not None:
                    _suspend(job.process, False)
                job.process.terminate()
            return
        want = job.pause_requested()
        if want and paused_at is None and job.process and job.process.poll() is None:
            _suspend(job.process, True)
            paused_at = time.time()
            job.state, job.message = "pausiert", f"pausiert bei Schritt {job.step} (Grafikkarte frei, Speicher belegt)"
            job.save()
        elif not want and paused_at is not None:
            _suspend(job.process, False)
            if job.started:
                job.started += time.time() - paused_at      # Restzeit ohne die Pause rechnen
            paused_at = None
            job.state, job.message = state, "fortgesetzt"
            job.save()


# --- Harness-Seite: Auftraege nur als Dateien, das Training laeuft im eigenen Dienst -------------------------
LOCK_NAME = "dienst.lock"


def service_running(store=STORE):
    """Laeuft der Trainings-Dienst? Er haelt die Sperrdatei exklusiv, solange er lebt (auch nach Absturz frei)."""
    path = os.path.join(store, LOCK_NAME)
    if not os.path.exists(path):
        return False
    try:
        import msvcrt
    except ImportError:                       # nicht Windows: per fcntl
        import fcntl
        with open(path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    with open(path, "a") as f:
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return False


def start_service(store=STORE, popen=subprocess.Popen):
    """Trainings-Dienst als eigenen Prozess starten (ohne Fenster, losgeloest vom Harness)."""
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    cmd = [pyw if os.path.exists(pyw) else exe, "-m", "ki.trainer", store]
    quiet = dict(cwd=HERE, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform != "win32":                  # Mac/Linux: eigene Sitzung, keine Windows-Flags
        return popen(cmd, start_new_session=True, **quiet)
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:          # auch aus einem Job-Objekt loesen, sonst endet der Dienst mit dem startenden Programm
        return popen(cmd, creationflags=flags | 0x01000000, **quiet)
    except OSError:
        return popen(cmd, creationflags=flags, **quiet)


def read_jobs(store=STORE):
    out = []
    if os.path.isdir(store):
        for f in os.listdir(store):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(store, f), encoding="utf-8") as fh:
                        out.append(json.load(fh))
                except (OSError, ValueError):
                    pass                     # wird gerade geschrieben
    return sorted(out, key=lambda d: d.get("created", 0))


class DetachedQueue:
    """Wie Queue, aber das Training laeuft im Trainings-Dienst. Harness-Neustart bricht nichts ab."""

    def __init__(self, store=STORE, start=start_service, running=service_running):
        self.store, self._start, self._running = store, start, running
        os.makedirs(store, exist_ok=True)

    def add(self, dataset, method_key, steps=None, quiet=False, augment=False, cameras=None, filters=None, export=None):
        job = Job(dataset, method_key, steps, quiet=quiet, augment=augment, cameras=cameras, filters=filters,
                  export=export, store=self.store)
        if not job.episodes:
            raise ValueError(f"Datensatz {job.dataset.name} hat noch keine Episoden")
        job.save()
        self.ensure_service()
        return job

    def ensure_service(self):
        if any(d.get("state") == "wartet" for d in read_jobs(self.store)) and not self._running(self.store):
            self._start(self.store)

    def cancel(self, name):
        for d in read_jobs(self.store):
            if d.get("name") == name and d.get("state") in ACTIVE:
                open(os.path.join(self.store, name + ".abbrechen"), "w").close()
                return True
        return False

    def resume(self, name):
        """Abgebrochenes/unterbrochenes Training beim letzten Zwischenstand fortsetzen (z. B. nach PC-Neustart)."""
        path = os.path.join(self.store, name + ".json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("state") not in ("fehler", "abgebrochen"):
            raise ValueError(f"{name}: Zustand {d.get('state')} - Weitertrainieren nur nach Abbruch oder Fehler")
        cp = resume_checkpoint(os.path.join(MODELS, name, "lauf"))
        if not cp:
            raise ValueError(f"{name}: noch kein Zwischenstand gespeichert - bitte neu starten")
        for wish in (".abbrechen", ".pause"):
            if os.path.exists(os.path.join(self.store, name + wish)):
                os.remove(os.path.join(self.store, name + wish))
        d.update({"state": "wartet", "resume": True, "step": cp[0], "message": f"wartet - weiter ab Schritt {cp[0]}",
                  "updated": time.time()})
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
        self.ensure_service()
        return {"name": name, "weiter_ab": cp[0]}

    def pause(self, name, on=True):
        """Pausieren (on=True) oder fortsetzen. Wartende starten erst nach dem Fortsetzen."""
        path = os.path.join(self.store, name + ".pause")
        if on:
            open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)
        return True

    def snapshot(self):
        alive = None
        out = []
        for d in read_jobs(self.store):
            state, eta = d.get("state"), None
            if state in ("umwandeln", "training", "pausiert"):
                alive = self._running(self.store) if alive is None else alive
                if not alive:
                    state = "fehler"
                    d["message"] = "Trainings-Dienst laeuft nicht mehr (PC neu gestartet?)"
            if state == "training" and d.get("step") and d.get("started"):
                rate = (d["step"] - (d.get("step0") or 0)) / max(1e-6, time.time() - d["started"])
                eta = (d["steps"] - d["step"]) / rate if rate > 0 else None
            if state == "wartet" and os.path.exists(os.path.join(self.store, d.get("name", "") + ".pause")):
                state = "wartet (pausiert)"
            out.append({"name": d.get("name"), "dataset": os.path.basename(d.get("dataset_path") or ""),
                        "method": d.get("method"), "state": state, "step": d.get("step", 0),
                        "steps": d.get("steps"), "loss": d.get("loss"), "eta_s": eta,
                        "message": d.get("message", ""), "quiet": d.get("quiet"), "augment": d.get("augment"),
                        "cameras": d.get("cameras_used") or d.get("cameras"), "episodes": d.get("episodes_n"),
                        "export": d.get("export"),
                        "weiter_ab": (resume_checkpoint(os.path.join(MODELS, d.get("name", ""), "lauf")) or (None,))[0]
                        if state in ("fehler", "abgebrochen") else None})
        try:
            self.ensure_service()        # Dienst endete zwischendurch (z. B. gerade im Leerlauf beendet)
        except OSError:
            pass
        return out


def start_pose(dataset):
    """Typische Startstellung der Episoden (Median der ersten Stellung): dorthin faehrt der Arm vor dem Modell."""
    import numpy as np
    firsts = []
    for ep in dataset.episodes():
        try:
            with np.load(os.path.join(dataset.path, ep, "daten.npz")) as z:
                firsts.append(z["state"][0])
        except (OSError, KeyError, IndexError):
            pass
    return [int(v) for v in np.median(np.array(firsts), axis=0)] if firsts else None


def resume_checkpoint(run_dir):
    """(schritt, ordner) des letzten VOLLSTAENDIG gespeicherten Zwischenstands. last.txt schreibt ki.train erst
    nach dem Speichern - ein beim Ausschalten halb geschriebener Ordner zaehlt also nicht."""
    base = os.path.join(run_dir, "checkpoints")
    try:
        with open(os.path.join(base, "last.txt"), encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    d = os.path.join(base, name)
    ok = all(os.path.exists(os.path.join(d, *x)) for x in (("pretrained_model", "train_config.json"),
                                                            ("training_state", "training_step.json")))
    return (int(name), d) if ok and name.isdigit() else None


def latest_checkpoint(run_dir):
    """Neuester gespeicherter Stand: lauf/checkpoints/<nummer>/pretrained_model (ohne Windows-Symlink 'last')."""
    base = os.path.join(run_dir, "checkpoints")
    if not os.path.isdir(base):
        return None
    nums = sorted((d for d in os.listdir(base) if d.isdigit()), key=int)
    return os.path.join(base, nums[-1], "pretrained_model") if nums else None


def models(root=None):
    root = root or MODELS
    out = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            p = os.path.join(root, d, "modell.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    out.append(json.load(f))
    return out
