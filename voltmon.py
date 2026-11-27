"""Spannungsmessung: liest Spannung und Status aller Servos laufend aus, ohne je etwas zu schreiben.

Nur Lesebefehle (READ ab Register 62: Spannung, Temperatur, -, Status). Kein Drehmoment, keine
Bewegung, kein EEPROM. Gedacht zum Finden von Wackelkontakten: Arm in der Ablage lassen und am
Kabel wackeln; jeder Einbruch und jede ausbleibende Antwort wird mitgezaehlt.

Start allein:  python voltmon.py        (ROS muss geschlossen sein oder darf keinen Arm steuern)
"""
import threading, time
import so101

VOLT_ADDR = so101.VOLT          # 62: Spannung (0,1 V), 63: Temperatur, 64: -, 65: Status
LOW_V = 4.0                     # darunter bricht ein Lauf ab
WARN_V = 4.5


def decode(raw):
    """4 Bytes ab Register 62 -> (Spannung V, Temperatur °C, Status)."""
    return raw[0] / 10.0, raw[1], raw[3]


class Tracker:
    """Merkt sich je Servo aktuellen Wert, Minimum, Einbrueche (< LOW_V) und Aussetzer (keine Antwort).
    Ein Einbruch zaehlt einmal pro Unterschreitung, nicht pro Messung."""
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.cells = {}

    def _cell(self, key):
        return self.cells.setdefault(key, {"v": None, "min": None, "drops": 0, "lost": 0, "low": False,
                                           "status": 0, "temp": None, "n": 0, "last_drop": None})

    def sample(self, key, v, temp=None, status=0, now=None):
        with self.lock:
            c = self._cell(key)
            c["v"], c["temp"], c["status"], c["n"] = v, temp, status, c["n"] + 1
            c["min"] = v if c["min"] is None else min(c["min"], v)
            if v < LOW_V and not c["low"]:
                c["drops"] += 1
                c["last_drop"] = now if now is not None else time.monotonic()
            c["low"] = v < LOW_V

    def missing(self, key):
        with self.lock:
            c = self._cell(key)
            c["lost"] += 1
            c["v"] = None

    def snapshot(self):
        with self.lock:
            return {k: dict(c) for k, c in self.cells.items()}


def level(v):
    if v is None:
        return "lost"
    return "bad" if v < LOW_V else "warn" if v < WARN_V else "ok"


class Monitor:
    """Ein Lesefaden je Board. bus_factory(arm) liefert ein Objekt mit read(sid, addr, n) und close()."""
    def __init__(self, arms=("leader", "follower", "follower2"), bus_factory=None, ids=range(1, 7)):
        self.arms, self.ids = list(arms), list(ids)
        self.bus_factory = bus_factory or (lambda arm: so101.Bus(so101.find_port(arm)))
        self.tracker = Tracker()
        self.state = {a: "verbinde ..." for a in self.arms}
        self.rate = {a: 0.0 for a in self.arms}
        self.halt = threading.Event()
        self.threads = []

    def start(self):
        for arm in self.arms:
            t = threading.Thread(target=self._run, args=(arm,), daemon=True, name=f"volt-{arm}")
            t.start()
            self.threads.append(t)
        return self

    def _run(self, arm):
        try:
            bus = self.bus_factory(arm)
        except SystemExit as exc:              # find_port: Board nicht angesteckt
            self.state[arm] = f"Board fehlt ({str(exc).split('.')[0]})"
            return
        except Exception as exc:               # z. B. Port belegt
            self.state[arm] = f"Port nicht frei: {exc}"
            return
        self.state[arm] = "misst"
        n, t0 = 0, time.monotonic()
        try:
            while not self.halt.is_set():
                for sid in self.ids:
                    raw = bus.read(sid, VOLT_ADDR, 4)
                    if raw is None:
                        self.tracker.missing((arm, sid))
                    else:
                        v, temp, status = decode(raw)
                        self.tracker.sample((arm, sid), v, temp, status)
                n += 1
                now = time.monotonic()
                if now - t0 >= 1:
                    self.rate[arm], n, t0 = n / (now - t0), 0, now
        except Exception as exc:
            self.state[arm] = f"Lesefehler: {exc}"
        finally:
            try:
                bus.close()
            except Exception:
                pass

    def stop(self, timeout=2):
        self.halt.set()
        for t in self.threads:
            t.join(timeout)

    @property
    def stopped(self):
        return all(not t.is_alive() for t in self.threads)


def window(parent, labels, on_close=None):
    """Tk-Fenster mit Tabelle Arm x Servo. labels: {arm: anzeigename}."""
    import tkinter as tk
    from tkinter import ttk
    mon = Monitor(arms=list(labels)).start()
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    win.title("Spannungsmessung · nur Lesen")
    colors = {"ok": "#1f7a3a", "warn": "#b36b00", "bad": "#b3261e", "lost": "#666"}
    ttk.Label(win, text="Spannungsmessung", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=7,
                                                                                 sticky="w", padx=16, pady=(12, 0))
    ttk.Label(win, justify="left", wraplength=900, text=(
        "Nur Lesen: kein Motor wird angesteuert, die Arme bleiben kraftlos. Arme in der Ablage lassen.\n"
        "Am Kabel zwischen Handgelenk-Drehung (5) und Greifer (6) wackeln und die Drehung von Hand bewegen. "
        "Gezaehlt werden Einbrueche unter 4,0 V und Aussetzer (Servo antwortet nicht).\n"
        "Hinweis: ohne Last fliesst kaum Strom. Ein schlechter Kontakt zeigt sich dann eher als Aussetzer "
        "als als Spannungseinbruch.")).grid(row=1, column=0, columnspan=7, sticky="w", padx=16, pady=(4, 10))
    for n, sid in enumerate(range(1, 7)):
        ttk.Label(win, text=f"{sid} · {so101.JOINTS[sid]}", font=("Segoe UI", 9, "bold")).grid(
            row=2, column=n + 1, padx=6)
    cells, states = {}, {}
    for r, (arm, name) in enumerate(labels.items()):
        box = ttk.Frame(win)
        box.grid(row=3 + r, column=0, sticky="w", padx=(16, 8), pady=4)
        ttk.Label(box, text=name, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        states[arm] = tk.StringVar(value="")
        ttk.Label(box, textvariable=states[arm], font=("Segoe UI", 8)).pack(anchor="w")
        for n, sid in enumerate(range(1, 7)):
            cell = tk.Label(win, text="–", width=14, height=3, font=("Consolas", 10, "bold"),
                            foreground="white", background="#666", justify="center")
            cell.grid(row=3 + r, column=n + 1, padx=3, pady=4)
            cells[(arm, sid)] = cell
    row = ttk.Frame(win)
    row.grid(row=4 + len(labels), column=0, columnspan=7, sticky="ew", padx=16, pady=(8, 14))
    ttk.Button(row, text="Zaehler zuruecksetzen", command=mon.tracker.reset).pack(side="left")
    closed = []

    def close():
        if closed:
            return
        closed.append(True)
        mon.stop()
        win.destroy()
        if on_close:
            on_close()

    ttk.Button(row, text="Schliessen", command=close).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)

    def refresh():
        if closed:
            return
        snap = mon.tracker.snapshot()
        for arm in labels:
            rate = mon.rate[arm]
            states[arm].set(mon.state[arm] + (f" · {rate:.0f} Durchlaeufe/s" if rate else ""))
            for sid in range(1, 7):
                c = snap.get((arm, sid))
                cell = cells[(arm, sid)]
                if c is None:
                    cell.configure(text="–", background="#666")
                    continue
                now = f"{c['v']:.1f} V" if c["v"] is not None else "keine Antwort"
                mn = f"{c['min']:.1f}" if c["min"] is not None else "–"
                worst = "bad" if c["drops"] else ("warn" if c["lost"] or (c["min"] or 9) < WARN_V else level(c["v"]))
                cell.configure(text=f"{now}\nmin {mn} V\nEinbr. {c['drops']} · Auss. {c['lost']}",
                               background=colors[worst])
        win.after(100, refresh)

    refresh()
    return win, mon, close


if __name__ == "__main__":
    import tkinter as tk
    names = {"leader": "Leader"}
    for key in ("follower", "follower2"):
        if key in so101.CFG:
            names[key] = so101.CFG[key].get("label", key)
    root = tk.Tk()
    root.withdraw()
    win, mon, close = window(root, names, on_close=root.destroy)
    root.mainloop()
