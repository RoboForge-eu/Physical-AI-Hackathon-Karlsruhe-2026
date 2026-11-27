"""RoboForge Fernsteuerung - Desktop-App (Windows und macOS) fuer die Arbeit am Roboter aus der Ferne.

  - Kameras des Roboters live sehen (LiveKit, WebRTC)
  - Arm mit dem eigenen Leader-Arm (USB) steuern - nur wenn vor Ort 'Remote (Internet)' freigegeben ist
  - Training, Datensaetze und Modelle bedienen, Arme ablegen, Video an/aus

Start:  python fernsteuerung.py      Zugang: Code aus dem Harness ('Fernzugang erstellen') einfuegen.
Die App speichert den letzten Code lokal (Datei ~/.roboforge_fern.json); er laeuft nach 12 h ab.
"""
import json, os, platform, queue, threading, time, uuid
import tkinter as tk
from tkinter import ttk, messagebox
import remote_access
from fern_core import Link, LeaderReader, list_ports, deviation_deg
from fern_sim import KeyTeleop, SimView, HELP as KEY_HELP

SETTINGS = os.path.join(os.path.expanduser("~"), ".roboforge_fern.json")
ENGAGE_TOL_DEG = 20            # wie remote_core.Config.engage_tol
SEND_HZ = 50


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


class App:
    def __init__(self):
        self.root = tk.Tk()
        import icons; icons.apply(self.root, "fernsteuerung")
        self.root.title("RoboForge Fernsteuerung")
        self.root.geometry("1400x900")
        self.inbox = queue.Queue()
        self.link = None
        self.leader = None
        self.leader_vals = None
        self.steering = False
        self.limit_feedback_until = 0.0
        self.remote_was_active = False
        self.halt = threading.Event()
        self.settings = load_settings()

        top = ttk.Frame(self.root, padding=(14, 10))
        top.pack(fill="x")
        ttk.Label(top, text="RoboForge Fernsteuerung", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, text="   Zugangscode:").pack(side="left")
        self.code = tk.StringVar(value=self.settings.get("code", ""))
        ttk.Entry(top, textvariable=self.code, width=40, show="•").pack(side="left", padx=4)
        self.connect_button = ttk.Button(top, text="Verbinden", command=self.connect)
        self.connect_button.pack(side="left")
        self.status = tk.StringVar(value="nicht verbunden")
        ttk.Label(top, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(side="left", padx=12)
        self.net = tk.StringVar()
        ttk.Label(top, textvariable=self.net, font=("Consolas", 9)).pack(side="right")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.tab_control = ttk.Frame(nb, padding=8)
        self.tab_train = ttk.Frame(nb, padding=8)
        self.tab_arms = ttk.Frame(nb, padding=8)
        nb.add(self.tab_control, text="Steuern")
        nb.add(self.tab_train, text="Training")
        nb.add(self.tab_arms, text="Arme & Video")
        self._build_control()
        self._build_train()
        self._build_arms()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<space>", lambda e: self.toggle_steer())
        self.root.bind("<Escape>", lambda e: self.stop())
        self.root.bind_all("<F12>", lambda e: self.emergency())
        self.root.after(50, self._drain)
        self.root.after(70, self._refresh_video)
        self.root.after(500, self._refresh_status)
        threading.Thread(target=self._control_loop, daemon=True, name="steuern").start()

    # ---------- Aufbau ----------
    def _build_control(self):
        f = self.tab_control
        self.video = ttk.Frame(f)
        # (gepackt erst NACH der rechten Spalte, damit diese immer ihren Platz behaelt)
        self.video_labels = {}
        self.video_hint = tk.StringVar(value="Noch nicht verbunden.")
        self.video_hint_box = ttk.Frame(self.video)
        self.video_hint_box.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(self.video_hint_box, textvariable=self.video_hint, font=("Segoe UI", 12), justify="center").pack()
        ttk.Button(self.video_hint_box, text="Video im Harness starten",
                   command=lambda: self.call_bg("video.starten")).pack(pady=8)
        side = ttk.Frame(f, padding=(12, 0), width=360)
        side.pack(side="right", fill="y")
        self.side = side
        self.video.pack(side="left", fill="both", expand=True)
        src = ttk.Frame(side)
        src.pack(fill="x")
        ttk.Label(src, text="Steuern mit:", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.source = tk.StringVar(value=self.settings.get("quelle", "tastatur"))
        for value, text in (("tastatur", "Tastatur"), ("leader", "Leader-Arm")):
            ttk.Radiobutton(src, text=text, value=value, variable=self.source,
                            command=self._source_changed).pack(side="left", padx=6)
        self.practice = tk.BooleanVar(value=False)
        ttk.Checkbutton(side, text="Uebungsmodus: nur Simulation, nichts an den Roboter senden",
                        variable=self.practice, command=self._source_changed).pack(anchor="w", pady=(2, 6))
        ttk.Label(side, text="Eigener Leader-Arm (USB)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        row = ttk.Frame(side)
        row.pack(fill="x", pady=4)
        self.port = tk.StringVar(value=self.settings.get("port", ""))
        self.port_box = ttk.Combobox(row, textvariable=self.port, width=30)
        self.port_box.pack(side="left")
        ttk.Button(row, text="↻", width=3, command=self.refresh_ports).pack(side="left", padx=2)
        self.leader_button = ttk.Button(side, text="Leader verbinden", command=self.toggle_leader)
        self.leader_button.pack(anchor="w")
        self.leader_info = tk.StringVar(value="kein Leader verbunden")
        ttk.Label(side, textvariable=self.leader_info, font=("Consolas", 9), justify="left").pack(anchor="w", pady=4)
        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="Steuern", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        arm_row = ttk.Frame(side)
        arm_row.pack(fill="x", pady=(2, 2))
        ttk.Label(arm_row, text="Arm:").pack(side="left")
        self.arm_choice = tk.StringVar()
        self.arm_box = ttk.Combobox(arm_row, textvariable=self.arm_choice, width=34, state="readonly")
        self.arm_box.pack(side="left", padx=4)
        self.arm_box.bind("<<ComboboxSelected>>", lambda e: self._arm_selected())
        self.arm_keys = {}
        min_row = ttk.Frame(side)
        min_row.pack(fill="x", pady=(0, 2))
        ttk.Label(min_row, text="Steuern fuer").pack(side="left")
        self.minutes = tk.StringVar(value=str(self.settings.get("minuten", 10)))
        self.min_box = ttk.Spinbox(min_row, from_=1, to=30, width=5, textvariable=self.minutes)
        self.min_box.pack(side="left", padx=4)
        self.min_hint = tk.StringVar(value="Minuten (1-30)")
        ttk.Label(min_row, textvariable=self.min_hint).pack(side="left")
        ttk.Label(side, wraplength=330, justify="left", font=("Segoe UI", 9), text=(
            "Vor Ort waehlt jemand am Arm 'Remote (Internet)' und gibt frei. Mit Leader-Arm: erst so hinstellen "
            "wie der Roboterarm (unter 20°). Leertaste = Steuern an/aus, Esc = Stop.")).pack(anchor="w")
        ttk.Label(side, text=KEY_HELP, wraplength=330, justify="left", font=("Segoe UI", 8),
                  foreground="#2f6fb5").pack(anchor="w", pady=(4, 0))
        self.match = tk.StringVar()
        self.match_label = tk.Label(side, textvariable=self.match, font=("Consolas", 10, "bold"), justify="left")
        self.match_label.pack(anchor="w", pady=6)
        # Hinweis ueber dem Steuern-Knopf (Anfrage, Entzug, Zeit um, ...)
        self.notice_box = tk.Frame(side, background="#fff3c4", padx=6, pady=4)
        self.notice_text = tk.StringVar()
        tk.Label(self.notice_box, textvariable=self.notice_text, background="#fff3c4", wraplength=320,
                 justify="left", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.notice_buttons = tk.Frame(self.notice_box, background="#fff3c4")
        self.notice_buttons.pack(anchor="w")
        self.ctl_text = tk.StringVar()
        self.ctl_label = tk.Label(side, textvariable=self.ctl_text, font=("Segoe UI", 9, "bold"), justify="left",
                                  wraplength=330)
        self.ctl_label.pack(anchor="w")
        self.steer_button = tk.Button(side, text="▶ Steuern (Leertaste)", font=("Segoe UI", 12, "bold"),
                                      background="#1f7a3a", foreground="white", command=self.toggle_steer)
        self.steer_button.pack(fill="x", pady=4)
        self.notice_anchor = self.ctl_label
        self.op_row = ttk.Frame(side)          # Bediener: Verlaengerung anfragen
        ttk.Button(self.op_row, text="Verlaengerung beim Admin anfordern",
                   command=lambda: self._send_ctl({"t": "extend"})).pack(fill="x")
        self.spec_row = ttk.Frame(side)        # Zuschauer: anfragen oder anstellen
        ttk.Button(self.spec_row, text="Steuerung anfragen",
                   command=lambda: self._send_ctl({"t": "request", "min": self._minutes()})).pack(side="left", fill="x",
                                                                                                expand=True)
        self.queue_button = ttk.Button(self.spec_row, text="In die Warteschlange gehen", command=self._toggle_queue)
        self.queue_button.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.steer_anchor = self.steer_button
        tk.Button(side, text="❚❚ Anhalten (Esc) · Arm bleibt stehen", font=("Segoe UI", 10, "bold"),
                  background="#b36b00", foreground="white", command=self.stop).pack(fill="x", pady=(4, 2))
        tk.Button(side, text="■ ALLE ABLEGEN (F12)", font=("Segoe UI", 13, "bold"), background="#b3261e",
                  foreground="white", activebackground="#8c1d17", command=self.emergency).pack(fill="x", pady=(2, 4))
        self.robot_info = tk.StringVar()
        ttk.Label(side, textvariable=self.robot_info, font=("Consolas", 9), justify="left",
                  wraplength=330).pack(anchor="w", pady=4)
        ttk.Label(side, text="Mini-Simulation (auf diesem PC)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.sim_canvas = tk.Canvas(side, width=340, height=260, background="#fbfbfb", highlightthickness=1,
                                    highlightbackground="#ccc")
        self.sim_canvas.pack(anchor="w", pady=4)
        self.sim = SimView(self.sim_canvas)
        self.teleop = KeyTeleop()
        self.sim_robot = None                 # Uebungsmodus: simulierter Arm folgt dem Ziel
        self.keys = set()
        self.src_mode, self.practice_on = self.source.get(), False
        self.root.bind("<KeyPress>", self._key_down)
        self.root.bind("<KeyRelease>", self._key_up)
        self.refresh_ports()

    def _tree(self, parent, cols, widths, height=8):
        frame = ttk.Frame(parent)
        t = ttk.Treeview(frame, columns=cols, show="headings", height=height)
        for c, w in zip(cols, widths):
            t.heading(c, text=c)
            t.column(c, width=w, anchor="w")
        t.pack(fill="both", expand=True)
        return frame, t

    def _build_train(self):
        f = self.tab_train
        ttk.Label(f, text="Datensaetze", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        fr, self.ds_tree = self._tree(f, ("Datensatz", "Aufgabe", "Arm", "Episoden"), (200, 360, 100, 80), 6)
        fr.pack(fill="x")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="Methode:").pack(side="left")
        self.method = tk.StringVar(value="act")
        self.method_box = ttk.Combobox(row, textvariable=self.method, values=["act", "smolvla", "smolvla_robust"], width=10, state="readonly")
        self.method_box.pack(side="left", padx=4)
        ttk.Label(row, text="Schritte:").pack(side="left", padx=(12, 0))
        self.steps = tk.StringVar(value="40000")
        ttk.Entry(row, textvariable=self.steps, width=8).pack(side="left", padx=4)
        ttk.Button(row, text="▶ Training starten (markierter Datensatz)", command=self.start_training).pack(side="left", padx=8)
        ttk.Button(row, text="Aktualisieren", command=self.refresh_lists).pack(side="right")
        ttk.Label(f, text="Trainings", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        fr, self.job_tree = self._tree(f, ("Name", "Zustand", "Schritt", "Fehler", "Restzeit"), (320, 100, 140, 80, 100), 5)
        fr.pack(fill="x")
        ttk.Button(f, text="Markiertes Training abbrechen", command=self.cancel_training).pack(anchor="w", pady=4)
        ttk.Label(f, text="Fertige Modelle", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        fr, self.model_tree = self._tree(f, ("Modell", "Methode", "Aufgabe", "fertig"), (320, 80, 360, 150), 6)
        fr.pack(fill="both", expand=True)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Markiertes Modell einem Arm zuweisen (Quelle 'KI' im Harness):").pack(side="left")
        self.assign_arm = tk.StringVar()
        self.assign_box = ttk.Combobox(row, textvariable=self.assign_arm, width=12, state="readonly")
        self.assign_box.pack(side="left", padx=4)
        ttk.Button(row, text="Zuweisen", command=self.assign_model).pack(side="left")

    def _build_arms(self):
        f = self.tab_arms
        fr, self.arm_tree = self._tree(f, ("Arm", "Name", "laeuft", "Quelle", "Status", "Sitzung"),
                                       (100, 120, 60, 80, 420, 200), 4)
        fr.pack(fill="x")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="Markierten Arm ablegen (Stop)", command=self.park_arm).pack(side="left")
        ttk.Button(row, text="Video starten", command=lambda: self.call_bg("video.starten")).pack(side="left", padx=12)
        ttk.Button(row, text="Video stoppen", command=lambda: self.call_bg("video.stoppen")).pack(side="left")
        ttk.Label(f, wraplength=900, justify="left", foreground="#555", text=(
            "Sicherheit: Aus der Ferne kann niemand einen Arm ohne Freigabe vor Ort bewegen. Ablegen (Stop) geht immer. "
            "Fahrt eine Verbindung weg oder kommen 0,2 s keine Steuerdaten, haelt der Arm an; nach 1 s legt er sich ab.")
        ).pack(anchor="w", pady=10)

    # ---------- Hilfen ----------
    def ui(self, fn):
        self.inbox.put(fn)

    def _drain(self):
        # Auch bei vielen Netzmeldungen regelmaessig an Tk zurueckgeben,
        # damit KeyRelease, Stop und Mausereignisse verarbeitet werden.
        deadline = time.monotonic() + 0.008
        for _ in range(32):
            try:
                fn = self.inbox.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:
                pass
            except Exception as exc:
                print("Fehler im Fenster:", exc)
            if time.monotonic() >= deadline:
                break
        self.root.after(10 if not self.inbox.empty() else 50, self._drain)

    def call_bg(self, name, done=None, quiet=False, **args):
        if self.link is None:
            if not quiet:
                messagebox.showinfo("Nicht verbunden", "Erst mit dem Zugangscode verbinden.", parent=self.root)
            return
        link = self.link
        def run():
            try:
                r = link.call(name, **args)
            except Exception as exc:
                if quiet:
                    self.ui(lambda e=str(exc): self.status.set(f"{name}: {e}"))
                else:
                    self.ui(lambda e=str(exc): messagebox.showerror(name, e, parent=self.root))
                return
            if done:
                self.ui(lambda: done(r))
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _fill(tree, rows):
        sel = tree.selection()
        tree.delete(*tree.get_children())
        for iid, vals in rows:
            tree.insert("", "end", iid=iid, values=vals)
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])

    # ---------- Verbindung ----------
    def connect(self):
        if self.link is not None:
            self.steering = False
            self.link.close()
            self.link = None
            self.connect_button.configure(text="Verbinden")
            self.status.set("getrennt")
            return
        try:
            data = remote_access.read_code(self.code.get())
        except ValueError as exc:
            messagebox.showerror("Zugangscode", str(exc), parent=self.root)
            return
        self.settings["code"] = self.code.get().strip()
        save_settings(self.settings)
        if not self.settings.get("geraet"):
            self.settings["geraet"] = uuid.uuid4().hex[:16]
            save_settings(self.settings)
        link = Link(data["url"], data["token"], on_event=self._event)
        link.hello.update(device=self.settings["geraet"], name=(platform.node() or "Geraet")[:40])
        self.link = link.start()
        self.connect_button.configure(text="Trennen")
        left = (data.get("bis", 0) - time.time()) / 3600
        self.status.set(f"verbinde ... (Code noch {left:.1f} h gueltig)")

    def _event(self, kind, data):
        if kind == "status":
            self.ui(lambda: self.status.set(data))
        elif kind == "welcome":
            self.ui(lambda: (self.status.set("verbunden"), self.refresh_lists(), self.ensure_video()))
        elif kind == "control":
            self.ui(self._control_changed)
        elif kind == "notice":
            self.ui(lambda: self._notice(data))
        elif kind == "error":
            self.ui(lambda: self.robot_info.set("Roboter meldet: " + str(data.get("msg"))))
        elif kind == "haptic":
            # Desktop hat keine Haptik. Wiederholtes Tk/macOS-Systemlaeuten
            # gehoert nicht in den Eingabe-Thread; stattdessen kurz anzeigen.
            self.limit_feedback_until = time.monotonic() + 0.6
        elif kind == "state":
            if data.get("active"):
                self.remote_was_active = True
            elif self.remote_was_active or data.get("reason") == "watchdog":
                self.remote_was_active = False
                self.ui(self._remote_halted)

    def _remote_halted(self):
        """Nach Remote-Abbruch Kupplung loesen; Neustart nur durch den Bediener."""
        if not self.steering or self.practice_on:
            return
        self.steering = False
        self.keys.clear()
        self.shift = False
        link = self.link
        if link is not None and link.state:
            j = link.state["joints"]
            self.teleop.reset(j)
            link.send_joints(j[:5], self.teleop.grip, False)
        self.status.set("Steuerung unterbrochen - zum Fortsetzen erneut Steuern einschalten")

    # ---------- Wer steuert ----------
    def _send_ctl(self, m):
        if self.link is not None:
            self.link.send(m, reliable=True)

    def _minutes(self):
        try:
            return max(1, int(float(self.minutes.get())))
        except ValueError:
            return 10

    def _is_operator(self):
        c = self.link.control if self.link is not None else None
        return bool(c and c.get("role") == "operator")

    def _arm_selected(self):
        key = self.arm_keys.get(self.arm_choice.get())
        if key and self.link is not None:
            self.steering = False
            self._send_ctl({"t": "select", "arm": key})

    def _toggle_queue(self):
        c = (self.link.control if self.link is not None else None) or {}
        self._send_ctl({"t": "unqueue"} if c.get("queue_pos") else {"t": "queue", "min": self._minutes()})

    def _notice(self, n):
        kind = n.get("kind")
        self.notice_text.set(n.get("text", ""))
        for w in self.notice_buttons.winfo_children():
            w.destroy()
        if kind == "request":
            ttk.Button(self.notice_buttons, text="Ja, abgeben",
                       command=lambda: self._answer(True)).pack(side="left", padx=(0, 4), pady=(4, 0))
            ttk.Button(self.notice_buttons, text="Nein, behalten",
                       command=lambda: self._answer(False)).pack(side="left", pady=(4, 0))
        else:
            ttk.Button(self.notice_buttons, text="OK", command=self.notice_box.pack_forget).pack(side="left",
                                                                                              pady=(4, 0))
        if not self.notice_box.winfo_ismapped():
            self.notice_box.pack(fill="x", pady=(4, 2), before=self.notice_anchor)
        if kind in ("kicked", "expired"):
            self.steering = False                 # Kontrolle weg: lokal nicht weiter senden
            self.keys.clear()

    def _answer(self, accept):
        self._send_ctl({"t": "answer", "accept": accept})
        self.notice_box.pack_forget()
        if accept:
            self.steering = False

    def _control_changed(self):
        c = (self.link.control if self.link is not None else None) or {}
        arms = c.get("arms") or []
        labels = {}
        for a in arms:
            busy = (f"belegt ({a['holder']})" if a.get("holder") else "frei") if a.get("frei") else "nicht freigegeben"
            labels[f"{a['label']} · {busy}"] = a["arm"]
        self.arm_keys = labels
        self.arm_box["values"] = list(labels)
        for text, key in labels.items():
            if key == c.get("arm"):
                self.arm_choice.set(text)
        mx = int(c.get("max_min") or 30)
        self.min_box.configure(to=mx)
        self.min_hint.set(f"Minuten (1-{mx})")
        if self._minutes() > mx:
            self.minutes.set(str(mx))
        op = c.get("role") == "operator"
        self.status.set("verbunden als " + ("Bediener" if op else "Zuschauer"
                                           + (f" ({c['holder']} steuert)" if c.get("holder") else "")))
        if op:
            left = int(c.get("left_s") or 0)
            self.ctl_text.set(f"Du steuerst noch {left // 60}:{left % 60:02d} min")
        elif c.get("queue_pos"):
            w = int(c.get("wait_s") or 0)
            self.ctl_text.set(f"Warteschlange Platz {c['queue_pos']} · ca. {w // 60}:{w % 60:02d} min warten")
        elif c.get("holder"):
            left = int(c.get("holder_left_s") or 0)
            self.ctl_text.set(f"{c['holder']} steuert noch {left // 60}:{left % 60:02d} min")
        else:
            self.ctl_text.set("Arm ist frei - 'Steuern' klicken")
        self.queue_button.configure(text="Warteschlange verlassen" if c.get("queue_pos")
                                    else "In die Warteschlange gehen")
        busy = bool(c.get("holder")) and not op
        self.op_row.pack_forget()
        self.spec_row.pack_forget()
        if op:
            self.op_row.pack(fill="x", pady=(0, 4), after=self.steer_anchor)
        elif busy:
            self.spec_row.pack(fill="x", pady=(0, 4), after=self.steer_anchor)
        self.steer_blocked = busy and not self.practice_on

    def ensure_video(self):
        """Nach dem Verbinden: laeuft im Harness kein Video-Streaming, wird es gestartet."""
        def got(st):
            if (st or {}).get("state") not in ("live", "verbinde"):
                self.video_hint.set("Der Harness streamt noch keine Kameras.\nStarte das Video-Streaming ...")
                self.call_bg("video.starten", quiet=True)
            else:
                self.video_hint.set("Warte auf Kamerabilder ...")
        self.call_bg("video.status", got, quiet=True)

    # ---------- Leader ----------
    def refresh_ports(self):
        try:
            ports = list_ports()
        except Exception:
            ports = []
        self.port_labels = {label: dev for dev, label in ports}
        self.port_box["values"] = [label for _, label in ports]
        if ports and self.port.get() not in self.port_labels and self.port.get() not in [d for d, _ in ports]:
            self.port.set(ports[0][1])

    def toggle_leader(self):
        if self.leader is not None:
            self.steering = False
            self.leader.close()
            self.leader = None
            self.leader_vals = None
            self.leader_button.configure(text="Leader verbinden")
            self.leader_info.set("kein Leader verbunden")
            return
        port = getattr(self, "port_labels", {}).get(self.port.get(), self.port.get().split(" ")[0])
        try:
            self.leader = LeaderReader(port).open()
        except Exception as exc:
            self.leader = None
            busy = "Zugriff verweigert" in str(exc) or "PermissionError" in str(exc) or "Access is denied" in str(exc)
            messagebox.showerror("Leader", f"{port}: {exc}\n\n" + (
                "Der Anschluss ist belegt. Laeuft auf diesem PC der Harness? Dann gehoert der Leader ihm - "
                "zum Fernsteuern braucht es einen zweiten Leader-Arm am Bediener-Rechner." if busy else
                "Ist das wirklich der Leader-Arm (USB-Board) und hat er Strom?"), parent=self.root)
            return
        self.settings["port"] = self.port.get()
        save_settings(self.settings)
        self.leader_button.configure(text="Leader trennen")

    # ---------- Steuern ----------
    def _key_down(self, e):
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox)):
            return                              # beim Tippen im Zugangscode nicht steuern
        self.keys.add((e.keysym or "").lower())
        self.shift = bool(e.state & 0x1)

    def _key_up(self, e):
        self.keys.discard((e.keysym or "").lower())
        self.shift = bool(e.state & 0x1) and e.keysym not in ("Shift_L", "Shift_R")

    def _source_changed(self):
        self.steering = False
        self.src_mode, self.practice_on = self.source.get(), self.practice.get()   # fuer den Steuer-Thread
        self.settings["quelle"] = self.source.get()
        save_settings(self.settings)

    def robot_joints(self):
        """Gelenke des Roboters: gemeldet (verbunden) oder simuliert (Uebungsmodus)."""
        if self.practice_on:
            return self.sim_robot
        st = self.link.state if self.link is not None else None
        return st["joints"] if st else None

    def toggle_steer(self):
        if self.steering:
            self.steering = False
            if not self.practice_on and self._is_operator():
                self._send_ctl({"t": "release"})      # Steuern beenden = Kontrolle abgeben
            return
        practice = self.practice.get()
        if not practice and getattr(self, "steer_blocked", False):
            return                                    # ein anderer steuert: anfragen oder anstellen
        if not practice and self.link is not None and not self._is_operator():
            self.settings["minuten"] = self._minutes()
            save_settings(self.settings)
            self._send_ctl({"t": "claim", "min": self._minutes()})
        if not practice and self.link is None:
            messagebox.showinfo("Steuern", "Erst verbinden - oder den Uebungsmodus einschalten.", parent=self.root)
            return
        if self.source.get() == "leader" and self.leader is None:
            messagebox.showinfo("Steuern", "Kein Leader-Arm verbunden. Waehle 'Tastatur' oder verbinde den Leader.",
                                parent=self.root)
            return
        if self.source.get() == "tastatur":
            start = self.robot_joints()
            if start is None and not practice:
                messagebox.showinfo("Steuern", "Noch keine Stellung vom Roboter empfangen.", parent=self.root)
                return
            self.teleop.reset(start or [2047] * 5 + [1430])   # Ziel = aktuelle Stellung: kein Sprung
            if practice and self.sim_robot is None:
                self.sim_robot = list(self.teleop.joints) + [1430]
        self.steering = True
        self.remote_was_active = False

    def stop(self):
        self.steering = False
        if self.link is not None:
            self.link.send_stop()

    def emergency(self):
        """Not-Ablage: Steuern aus, alle laufenden Arme Greifer oeffnen und ablegen (ohne Rueckfrage)."""
        self.stop()
        if self.link is None:
            return
        link = self.link
        def run():
            err = "keine Antwort"
            for attempt in range(3):                         # wichtig genug fuer Wiederholung
                try:
                    link.call("notablage", timeout=4)
                    self.ui(lambda: self.status.set("NOT-ABLAGE ausgeloest - Arme legen sich ab"))
                    return
                except Exception as exc:
                    err = str(exc)
            self.ui(lambda: messagebox.showerror("Not-Ablage", f"Nicht bestaetigt: {err}\nVor Ort stoppen!",
                                                 parent=self.root))
        threading.Thread(target=run, daemon=True).start()

    def _control_loop(self):
        """50 Hz: Leader lesen, Gelenkwerte senden (mit Kupplung = steering). Ohne Daten haelt der Roboter an."""
        period = 1.0 / SEND_HZ
        nxt = time.monotonic()
        last_idle = 0.0
        last = time.monotonic()
        while not self.halt.is_set():
            leader, link = self.leader, self.link
            now = time.monotonic()
            dt, last = min(now - last, 0.1), now
            vals = None
            if leader is not None:
                try:
                    vals = leader.read()
                except Exception:
                    vals = None
                self.leader_vals = vals
            if self.src_mode == "tastatur":
                if self.steering:
                    self.teleop.apply({k for k in list(self.keys) if len(k) == 1}, dt, getattr(self, "shift", False))
                if self.steering:
                    vals = self.teleop.values()
                else:
                    # Nicht steuern = Kupplung losgelassen melden (der Harness verlangt das nach jeder Freigabe,
                    # sonst nimmt er keine Bewegung an). Werte = aktuelle Roboterstellung, sie werden ignoriert.
                    st = link.state if link is not None else None
                    vals = (list(st["joints"][:5]), 0.0) if st else None
            self.target_vals = vals
            if self.practice_on:
                if self.steering and vals is not None:      # simulierter Arm folgt sofort
                    self.sim_robot = list(vals[0]) + [int(1430 + (2880 - 1430) * (1 - vals[1]))]
                link = None                                 # Uebungsmodus: nichts senden
            if link is not None and vals is not None and link.welcome is not None:
                now = time.monotonic()
                if self.steering or now - last_idle > 0.1:      # ohne Kupplung nur 10x/s
                    link.send_joints(vals[0], vals[1], self.steering)
                    last_idle = now
            nxt += period
            delay = nxt - time.monotonic()
            if delay < -period:
                nxt = time.monotonic()
            elif delay > 0:
                time.sleep(delay)

    # ---------- Anzeige ----------
    def _refresh_status(self):
        link = self.link
        if link is not None:
            rtt = f"{link.rtt_ms:.0f} ms" if link.rtt_ms is not None else "-"
            self.net.set(f"Antwortzeit {rtt} · Zustand {link.state_rate()}/s · Video {len(link.frames)} Spuren")
            st = link.state
            if st:
                active = "STEUERT" if st.get("active") else "haelt"
                reason = {"watchdog": "Verbindung zu langsam", "stopped": "gestoppt", "too_far":
                          "Leader zu weit weg - erst angleichen",
                          "funkloch": "Aussetzer - Arm wartet auf Signal"}.get(st.get("reason"), st.get("reason") or "")
                # Aussetzer zaehlen: nur bei vielen (ab 5 in 30 s) deutlich warnen
                n, now = st.get("funkloch") or 0, time.monotonic()
                hist = [x for x in getattr(self, "_drops", []) if now - x[0] < 30]
                if not hist or hist[-1][1] != n:
                    hist.append((now, n))
                self._drops = hist
                if n - hist[0][1] >= 5:
                    reason = "⚠ SCHLECHTE VERBINDUNG - Arm stockt oft" + (f" · {reason}" if reason else "")
                self.robot_info.set(f"Roboter: {active} · Modus {st.get('mode', '-')}"
                                    + (f" · {reason}" if reason else "") + "\n"
                                    + ("Probelauf: Arm bewegt sich nicht (vor Ort ist kein Arm auf Remote freigegeben)"
                                       if st.get("dry_run") else
                                       "Arm folgt deinen Zielen" if st.get("active") else
                                       "Arm freigegeben, aber Steuerung pausiert"))
        blocked = getattr(self, "steer_blocked", False) and not self.steering
        self.steer_button.configure(state="disabled" if blocked else "normal")
        tv = getattr(self, "target_vals", None)
        note = ""
        if self.source.get() == "tastatur" and self.steering and self.teleop.blocked:
            note = "Grenze erreicht - andere Richtung oder Handneigung waehlen"
        elif self.steering and time.monotonic() < self.limit_feedback_until:
            note = "Roboter begrenzt die Bewegung - andere Richtung waehlen"
        if self.practice.get():
            note = (note + " · " if note else "") + "UEBUNGSMODUS - nichts wird gesendet"
        self.sim.draw(tv[0] if tv else None, self.robot_joints(), note)
        vals = self.leader_vals
        if self.leader is not None:
            if vals is None:
                self.leader_info.set(f"{self.leader.port}: keine Antwort (Strom?)")
            else:
                self.leader_info.set(f"{self.leader.port}\nGelenke {vals[0]}\nGreifer {vals[1] * 100:.0f} % zu")
        if self.source.get() == "tastatur":
            vals = None                                    # Tastatur startet immer an der Roboterstellung
        if vals is not None and link is not None and link.state:
            dev = deviation_deg(vals[0], link.state["joints"])
            ok = dev <= ENGAGE_TOL_DEG
            self.match.set(f"Abstand Leader ↔ Arm: {dev:5.1f}°  " + ("✔ bereit" if ok else "✖ erst angleichen"))
            self.match_label.configure(foreground="#1f7a3a" if ok else "#b36b00")
        else:
            self.match.set("")
        self.steer_button.configure(text="■ Steuern beenden (Leertaste)" if self.steering else "▶ Steuern (Leertaste)",
                                    background="#b36b00" if self.steering else "#1f7a3a")
        self.root.after(200, self._refresh_status)

    def _refresh_video(self):
        link = self.link
        if link is None:
            self.video_hint.set("Noch nicht verbunden.")
        elif not link.frames:
            if not self.video_hint.get().startswith(("Der Harness", "Warte")):
                self.video_hint.set("Warte auf Kamerabilder ...")
        if link is not None and link.frames:
            self.video_hint_box.place_forget()
            import cv2, base64
            names = sorted(link.frames)
            cols = 2 if len(names) > 1 else 1
            # Platz aus dem Fenster berechnen, nicht aus dem Videobereich (sonst waechst er mit jedem Bild)
            rows = (len(names) + cols - 1) // cols
            free_w = self.tab_control.winfo_width() - self.side.winfo_reqwidth() - 30
            free_h = self.tab_control.winfo_height() - 30 * rows - 10
            w = max(200, free_w // cols - 8)
            w = min(w, max(200, int(free_h / rows * 16 / 9)))      # alle Bilder passen auch in der Hoehe
            for i, name in enumerate(names):
                img, t = link.frames[name]
                if name not in self.video_labels:
                    box = ttk.Frame(self.video)
                    box.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="nw")
                    ttk.Label(box, text=name, font=("Segoe UI", 9, "bold")).pack(anchor="w")
                    lbl = tk.Label(box, background="#000")
                    lbl.pack()
                    self.video_labels[name] = lbl
                h = int(img.shape[0] * w / img.shape[1])
                small = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
                ok, ppm = cv2.imencode(".ppm", cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
                if ok:
                    photo = tk.PhotoImage(data=ppm.tobytes(), format="PPM")
                    self.video_labels[name].configure(image=photo)
                    self.video_labels[name].image = photo
        self.root.after(70, self._refresh_video)

    # ---------- Training / Arme ----------
    def refresh_lists(self):
        def ds(r):
            self._fill(self.ds_tree, [(d["name"], (d["name"], d.get("task"), d.get("arm"), d.get("episodes"))) for d in r])
        def models(r):
            self._fill(self.model_tree, [(m["name"], (m["name"], m.get("method"), m.get("task"), m.get("created"))) for m in r])
        def arms(r):
            self.assign_box["values"] = [a["arm"] for a in r]
            if r and not self.assign_arm.get():
                self.assign_arm.set(r[0]["arm"])
            self._fill(self.arm_tree, [(a["arm"], (a["arm"], a["label"], "ja" if a["running"] else "-",
                                                   a.get("mode") or "-", a["status"],
                                                   (a.get("sitzung") or {}).get("von", "-"))) for a in r])
        self.call_bg("datensaetze.liste", ds)
        self.call_bg("modelle.liste", models)
        self.call_bg("arme.liste", arms)
        self.call_bg("training.status", self._jobs)

    def _jobs(self, r):
        rows = []
        for j in r or []:
            eta = j.get("eta_s")
            rows.append((j["name"], (j["name"], j["state"], f"{j['step']}/{j['steps']}",
                                     f"{j['loss']:.3f}" if j.get("loss") is not None else "-",
                                     f"{int(eta // 60)} min" if eta else "-")))
        self._fill(self.job_tree, rows)

    def start_training(self):
        sel = self.ds_tree.selection()
        if not sel:
            messagebox.showinfo("Training", "Bitte einen Datensatz markieren.", parent=self.root)
            return
        try:
            steps = int(self.steps.get())
        except ValueError:
            return
        if messagebox.askokcancel("Training", f"{self.method.get()} mit '{sel[0]}', {steps} Schritte starten?\n"
                                  "Es laeuft auf dem Roboter-PC (Grafikkarte).", parent=self.root):
            self.call_bg("training.start", lambda r: self.refresh_lists(), datensatz=sel[0],
                         methode=self.method.get(), schritte=steps)

    def cancel_training(self):
        sel = self.job_tree.selection()
        if sel and messagebox.askyesno("Abbrechen", f"Training {sel[0]} abbrechen?", parent=self.root):
            self.call_bg("training.abbrechen", lambda r: self.refresh_lists(), name=sel[0])

    def assign_model(self):
        sel = self.model_tree.selection()
        if sel and self.assign_arm.get():
            self.call_bg("ki.modell_waehlen", lambda r: self.refresh_lists(), arm=self.assign_arm.get(), modell=sel[0])

    def park_arm(self):
        sel = self.arm_tree.selection()
        if sel:
            self.call_bg("arm.ablegen", lambda r: self.refresh_lists(), arm=sel[0])

    def close(self):
        self.halt.set()
        self.steering = False
        if self.link is not None:
            self.link.send_stop()
            self.link.close()
        if self.leader is not None:
            self.leader.close()
        self.root.destroy()

    def run(self):
        def poll_lists():
            if self.link is not None and self.link.welcome is not None:
                self.call_bg("training.status", self._jobs, quiet=True)
                self.call_bg("arme.liste", lambda r: self._fill(self.arm_tree, [
                    (a["arm"], (a["arm"], a["label"], "ja" if a["running"] else "-", a.get("mode") or "-",
                                a["status"], (a.get("sitzung") or {}).get("von", "-"))) for a in r]), quiet=True)
            self.root.after(3000, poll_lists)
        self.root.after(3000, poll_lists)
        self.root.mainloop()


def selbsttest(path):
    """Fuer das fertige Programm: pruefen, ob alle Teile geladen werden (ohne Fenster, ohne Netz)."""
    lines = []
    try:
        from livekit import rtc
        import cv2, numpy, serial
        import fern_core, remote_access, fast_bus                     # noqa: F401
        lines.append("livekit " + str(rtc.Room is not None))
        lines.append("ports " + str(len(list_ports())))
        lines.append("OK")
    except Exception as exc:
        lines.append(f"FEHLER {type(exc).__name__}: {exc}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--selbsttest":
        selbsttest(sys.argv[2])
    else:
        App().run()
