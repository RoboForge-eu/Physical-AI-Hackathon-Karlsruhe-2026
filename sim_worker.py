"""SIMULATIONS-Worker: dasselbe stdin/stdout-Protokoll wie 'lab_worker.py --multi', aber ohne Hardware.

  python sim_worker.py [--backend kinsim|isaac] [--zufall] [--seed N] [--schnell]

Oeffnet NIE einen COM-Port und importiert keinen Servo-Bus. Jede Statuszeile traegt 'SIMULATION'.
stdin:  start <arm> [lokal|remote|ki] · stop <arm> · rec <arm> on|off · target j1..j6 · ktarget <arm> j1..j6 · quit
stdout: '[<arm>] ' + Zeile; OBS <ist> | <soll> (50 Hz bei Aufnahme/KI), LAST <6 Lasten> (10 Hz),
        TELEOP: ... (laeuft), BEWEGUNG: Aktuelle Positionen halten / ABGELEGT / ARMENDE <rc>,
        ohne Praefix: BEREIT ..., LEADER: SIMULATION ... (alle 2 s), WORKER ENDE.
Kamerabilder: ki_daten/sim_kameras/<arm>_<kamera>.jpg (10 Hz, atomar ersetzt) und Zeile 'BILD <kamera> <pfad>'
einmal beim Start. 'lokal' heisst in der Simulation: Stellung halten (es gibt keinen Leader).
"""
import json, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CAMDIR = os.path.join(HERE, "ki_daten", "sim_kameras")
OBS_S, LAST_S, BILD_S, STEP_S = 1 / 50, 0.1, 0.1, 0.01
MAX_TICKS_PRO_S = 1200      # Ziele werden wie am echten Arm begrenzt nachgefuehrt (keine Spruenge)


def make_backend(name, seed=0, zufall=False):
    if name == "kinsim":
        from sim.welt import Welt
        return Welt(seed=seed, zufall=zufall)
    if name == "isaac":
        from sim.isaac.backend import IsaacBackend
        return IsaacBackend(seed=seed, zufall=zufall)
    raise SystemExit(f"Unbekanntes Backend {name!r}")


def rest_pose(key):
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        r = cfg[key]["rest_pose"]
        return [int(r[str(s)]) for s in range(1, 7)]
    except (OSError, ValueError, KeyError):
        return [2047, 846, 3095, 902, 2047, 1418]


class SimArmLauf:
    """Ein simulierter Arm: eigene Welt (Backend), eigener Takt-Thread."""
    def __init__(self, key, backend, out, mode):
        self.key, self.w, self.out, self.mode = key, backend, out, mode
        self.ziel = list(backend.stellung())
        self.stop = threading.Event()
        self.rec = threading.Event()
        if mode == "ki":
            self.rec.set()
        self.thread = threading.Thread(target=self.run, daemon=True, name=key)

    def say(self, text):
        self.out(f"[{self.key}] {text}")

    def setze_ziel(self, values):
        if len(values) != 6 or not all(0 <= v <= 4095 for v in values):
            raise ValueError(f"ungueltige Ziele {values}")
        self.ziel = [int(v) for v in values]

    def _fahre(self, dt):
        soll = list(self.w.soll)
        for i in range(6):
            d = self.ziel[i] - soll[i]
            soll[i] += max(-MAX_TICKS_PRO_S * dt, min(MAX_TICKS_PRO_S * dt, d))
        self.w.setze_soll(soll)
        self.w.schritt(1)

    def run(self):
        self.say(f"QUELLE: SIMULATION ({'KI-Fahrer' if self.mode == 'ki' else 'Fernsteuerung' if self.mode == 'remote' else 'haelt Stellung'})")
        self.say("TELEOP: SIMULATION laeuft (kein echter Arm)")
        t_obs = t_last = 0.0
        threading.Thread(target=self.bild_schleife, daemon=True, name=self.key + "-kamera").start()
        nxt = time.monotonic()
        while not self.stop.is_set():
            self._fahre(STEP_S)
            now = time.monotonic()
            if self.rec.is_set() and now - t_obs >= OBS_S:
                t_obs = now
                self.say("OBS " + " ".join(str(v) for v in self.w.stellung()) + " | "
                         + " ".join(str(int(round(v))) for v in self.w.soll))
            if now - t_last >= LAST_S:
                t_last = now
                self.say("LAST " + " ".join(str(v) for v in self.w.last()))
            nxt += STEP_S
            time.sleep(max(0.0, nxt - time.monotonic()))
        self.say("BEWEGUNG: Aktuelle Positionen halten (SIMULATION, Ablegen)")
        self.ziel = rest_pose(self.key)
        for _ in range(int(4 / STEP_S)):
            self._fahre(STEP_S)
            if max(abs(a - b) for a, b in zip(self.w.stellung(), self.ziel)) < 10:
                break
        self.say("ABGELEGT (SIMULATION)")
        self.say("ARMENDE 0")

    def bild_schleife(self):
        """Kamerabilder im eigenen Thread: Rendern dauert ~0,1 s und darf den 100-Hz-Takt nicht bremsen."""
        while not self.stop.wait(BILD_S):
            self.bilder()

    def bilder(self):
        try:
            import cv2
            os.makedirs(CAMDIR, exist_ok=True)
            for cam in ("arm", "turm"):
                path = os.path.join(CAMDIR, f"{self.key}_{cam}.jpg")
                cv2.imwrite(path + ".tmp.jpg", self.w.bild(cam))
                os.replace(path + ".tmp.jpg", path)
        except Exception as exc:       # Bilder sind Beiwerk; der Takt darf daran nicht scheitern
            self.say(f"Bildfehler: {exc}")


def main(argv=None, commands=None, out=None):
    argv = sys.argv[1:] if argv is None else argv
    backend = argv[argv.index("--backend") + 1] if "--backend" in argv else "kinsim"
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 0
    zufall = "--zufall" in argv
    lock = threading.Lock()
    real = out or sys.stdout

    def emit(text):
        with lock:
            real.write(text + "\n")
            real.flush()

    commands = sys.stdin if commands is None else commands
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        arme = sorted(k for k in cfg if k.startswith("follower"))
    except (OSError, ValueError):
        arme = ["follower"]
    laeufe = {}
    halt = threading.Event()

    def status():
        while not halt.wait(2):
            aktiv = [k for k, l in laeufe.items() if l.thread.is_alive()]
            emit(f"LEADER: SIMULATION ({backend}) | aktiv {aktiv}")

    threading.Thread(target=status, daemon=True).start()
    emit(f"BEREIT: SIMULATION ({backend}) - kein echter Arm, keine COM-Ports. Arme: {arme}")
    for line in commands:
        parts = line.split()
        if not parts:
            continue
        cmd, key = parts[0], (parts[1] if len(parts) > 1 else "")
        if cmd == "quit":
            break
        if cmd == "target":
            for l in laeufe.values():
                if l.mode == "remote" and l.thread.is_alive():
                    try:
                        l.setze_ziel([int(v) for v in parts[1:]])
                    except ValueError as exc:
                        emit(f"Fernsteuerung: {exc}")
            continue
        if cmd == "ktarget":
            l = laeufe.get(key)
            try:
                if l is None or l.mode != "ki" or not l.thread.is_alive():
                    raise ValueError(f"kein KI-Lauf fuer {key!r}")
                l.setze_ziel([int(v) for v in parts[2:]])
            except ValueError as exc:
                emit(f"[{key}] KI-Fahrer: {exc}")
            continue
        if key not in arme:
            emit(f"Unbekannter Arm: {key!r}")
            continue
        if cmd == "start":
            if key in laeufe and laeufe[key].thread.is_alive():
                emit(f"[{key}] {key} laeuft bereits.")
                continue
            mode = parts[2] if len(parts) > 2 else "lokal"
            w = make_backend(backend, seed + len(laeufe), zufall)
            w.ist = [float(v) for v in rest_pose(key)]
            w.soll = list(w.ist)
            laeufe[key] = SimArmLauf(key, w, emit, mode)
            laeufe[key].thread.start()
        elif cmd == "rec":
            l = laeufe.get(key)
            if l is not None:
                (l.rec.set if len(parts) > 2 and parts[2] == "on" else l.rec.clear)()
                emit(f"[{key}] AUFNAHME {'AN' if l.rec.is_set() else 'AUS'}")
        elif cmd == "stop":
            if key in laeufe:
                emit(f"[{key}] STOP: {key} (Bedienknopf)")
                laeufe[key].stop.set()
    emit("STOP: alle Arme (Fenster geschlossen oder quit)")
    for l in laeufe.values():
        l.stop.set()
    for l in laeufe.values():
        l.thread.join(timeout=10)
    halt.set()
    emit("WORKER ENDE")
    return 0


if __name__ == "__main__":
    if "--multi" in sys.argv:
        sys.argv.remove("--multi")
    raise SystemExit(main())
