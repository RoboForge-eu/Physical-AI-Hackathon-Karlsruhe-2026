"""RoboForge Harness - Roboter Operation System: Bedienoberflaeche fuer die SO-101-Arme.
Die Oberflaeche besitzt nie den Servo-Bus; das macht lab_worker.py.
Start: python ros.py   (oder "RoboForge Harness.cmd" im Projektordner doppelklicken)

Zwei Follower (Setup 1, Setup 2), ein Leader. Ein gemeinsamer Worker (lab_worker.py --multi) liest
den Leader und fuehrt jeden Arm in einem eigenen Strang: Wechsel laufen
parallel. Remote (Internet) ist vorerst ein Trockenlauf: der Fernsteuer-Server laeuft im Fenster,
rechnet Ziele aus und zeigt sie an, bewegt aber keinen Arm."""
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# SIMULATION statt echter Arme: 'python ros.py --sim' (oder ROBOFORGE_SIM=1). Dann startet sim_worker.py statt
# lab_worker.py; kein COM-Port wird geoeffnet. Titel, Kopfzeile und jedes Arm-Feld zeigen deutlich SIMULATION.
SIM = "--sim" in sys.argv or os.environ.get("ROBOFORGE_SIM") == "1"
SIM_BACKEND = os.environ.get("ROBOFORGE_SIM_BACKEND", "kinsim")
from tkinter.scrolledtext import ScrolledText

HERE = Path(__file__).resolve().parent
MODULES = (("VLA-Studio", "modul_vla.py", "#6a3fb5"),                              # Daten, Training, Modelle
           ("Agentic-Skill-\nStudio", "modul_agentic.py", "#1f6f8b"),           # Agent mit Werkzeugen
           ("Orchestrator", "modul_workflow.py", "#b5651d"))  # Ablaeufe aus Faehigkeiten und Agenten
from ki import KI_PYTHON            # Windows: ki-env/Scripts/python.exe, Mac: ki-env/bin/python
REMOTE_PORT = 8765


def _remote_cfg():
    from remote_core import Config
    # Erstversuche: langsam (Spitze 8 cm/s, Hand 1 rad/s, Drehung 1,5 rad/s). Spaeter schneller stellen.
    return Config(v_max=0.08, phi_rate=1.0, roll_rate=1.5)


REMOTE_CFG = _remote_cfg()
ACCESS_FILE = HERE / "fernzugriff.json"   # Hoechstdauer und gemerkte Geraete (keine Geheimnisse)
LINE = re.compile(r"\[(follower\w*)\] (.*)", re.S)


def load_arms():
    """[(schluessel, anzeigename, usb_serial, kamera_plaetze 0-basiert)] aller Follower aus config.json."""
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    arms = []
    for key in sorted(k for k in cfg if k.startswith("follower")):
        c = cfg[key]
        arms.append((key, c.get("label") or key, (c.get("usb_serial") or "").upper(),
                     [int(n) - 1 for n in c.get("cameras", [])]))
    return arms, (cfg.get("leader", {}).get("usb_serial") or "").upper()


def connected_serials():
    try:
        from serial.tools import list_ports
        return {(p.serial_number or "").upper(): p.device for p in list_ports.comports() if p.serial_number}
    except Exception:
        return {}


def port_of(serials, want):
    for sn, dev in serials.items():
        if want and (sn.startswith(want) or want.startswith(sn)):
            return dev
    return None


def parse_line(line):
    """('follower2', 'Text') fuer Arm-Zeilen, (None, 'Text') fuer Worker-Zeilen."""
    m = LINE.match(line)
    return (m.group(1), m.group(2)) if m else (None, line)


def arm_status(text):
    """Statuszeile eines Arms aus einer Worker-Zeile (oder None)."""
    for prefix, status in (("BEWEGUNG: Hochfahren", "Hochfahren · Gelenke einzeln"),
                           ("BEWEGUNG: Gemeinsam", "Angleichen → direktes Folgen"),
                           ("TELEOP:", "Folgt dem Leader · Stop zum Ablegen"),
                           ("BEENDET:", "Folgen beendet · Grund im Protokoll"),
                           ("BEWEGUNG: Aktuelle Positionen halten", "Legt ab · folgt dem Leader jetzt nicht mehr"),
                           ("ABGELEGT", "Abgelegt · Motoren frei"),
                           ("ABLAGE NICHT BESTAETIGT", "ABLAGE NICHT BESTAETIGT · Arm vor Ort sichern"),
                           ("VERBINDUNGSFEHLER", "Verbindungsfehler · Arm vor Ort sichern")):
        if text.startswith(prefix):
            return status
    return None


SAFETY_TEXT = ("Follower liegt sicher in seiner Ablage (Hand nach oben geklappt); Arbeitsbereich frei. "
               "Leader ungefaehr in Mittelstellung halten.\n\n"
               "Der Follower faehrt einzeln hoch und gleicht sich in 0,75 Sekunden an den Leader an.\n"
               "Stop und normales Fensterschliessen fordern das Ablegen an.\n"
               "Bei Strom-/Verbindungsverlust ist automatisches Ablegen nicht garantiert.")


class ArmPanel(ttk.Frame):
    def __init__(self, parent, lab, key, label, serial, slots, cams):
        super().__init__(parent)
        self.lab, self.key, self.label, self.serial = lab, key, label, serial
        self.running = False        # Worker meldet diesen Arm als laufend (bis ARMENDE)
        self.stopping = False
        self.mode = "lokal"         # Quelle des laufenden Arms: "lokal" (Leader) oder "remote"
        head = ttk.Frame(self)
        head.pack(fill="x")
        ttk.Label(head, text=label, font=("Segoe UI", 18, "bold")).pack(side="left")
        self.badge = tk.Label(head, text="", font=("Segoe UI", 10, "bold"), padx=8, pady=2)
        self.badge.pack(side="left", padx=12)
        self.board = tk.StringVar(value="Board: suche ...")
        ttk.Label(head, textvariable=self.board, font=("Segoe UI", 9)).pack(side="right")
        src = ttk.Frame(self)
        src.pack(fill="x", pady=(6, 0))
        ttk.Label(src, text="Steuerung:", font=("Segoe UI", 10)).pack(side="left")
        self.source = tk.StringVar(value="lokal")
        self.source_buttons = []
        self.ki_model = None        # gewaehltes KI-Modell (Ordner), gesetzt im VLA-Studio
        self.ki_task = ""
        for value, text in (("lokal", "Lokal (Leader-Arm)"), ("remote", "Remote (Internet)"), ("ki", "KI (Modell)")):
            b = tk.Radiobutton(src, text=text, value=value, variable=self.source, indicatoron=0, padx=10, pady=3,
                               font=("Segoe UI", 9, "bold"), selectcolor="#2f6fb5", command=lab.update_buttons)
            b.pack(side="left", padx=(8, 0))
            self.source_buttons.append(b)
        self.status = tk.StringVar(value="Bereit")
        ttk.Label(self, textvariable=self.status, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(6, 4))
        self.remote_info = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.remote_info, font=("Consolas", 9), foreground="#2f6fb5").pack(anchor="w")
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(4, 0))
        self.take_button = ttk.Button(buttons, text="Leader uebernehmen", command=lambda: lab.take_leader(key))
        self.take_button.pack(side="left", padx=(0, 10))
        self.stop_button = ttk.Button(buttons, text="Stop · ablegen", command=lambda: lab.stop(key), state="disabled")
        self.stop_button.pack(side="left")
        ttk.Button(buttons, text="⛶ Steuermodus", command=lambda: ControlView(lab, key)).pack(side="right")
        # Fernzugriff: wer steuert diesen Arm gerade, wie lange noch (nur bei Quelle "Remote")
        self.ctl_box = tk.Frame(self, background="#eef4fb", padx=8, pady=4)
        self.ctl_text = tk.StringVar(value="")
        tk.Label(self.ctl_box, textvariable=self.ctl_text, background="#eef4fb", font=("Segoe UI", 9, "bold"),
                 justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Button(self.ctl_box, text="Fernzugriff verwalten …",
                   command=lambda: AccessDialog(lab, key)).pack(side="right")
        self.ctl_anchor = buttons
        self.slots = list(slots)
        tiles = ttk.Frame(self)
        tiles.pack(fill="x", pady=(8, 0))
        for n, slot in enumerate(slots):
            cams.add_tile(tiles, slot).grid(row=0, column=n, sticky="nw", padx=(0, 8))
        self.log = ScrolledText(self, font=("Consolas", 9), state="disabled", wrap="word", height=10)
        self.log.pack(fill="both", expand=True, pady=(8, 0))

    def set_compact(self, compact, height_px=None):
        """Untereinander-Ansicht: Protokoll nur so hoch wie die Kamerabilder, damit beide Setups ins Fenster passen."""
        import tkinter.font as tkfont
        self.log.pack_forget()
        if compact:
            line = tkfont.Font(font=("Consolas", 9)).metrics("linespace")
            self.log.configure(height=max(3, int((height_px or 180) / line)))
            self.log.pack(fill="x", expand=False, pady=(8, 0))
        else:
            self.log.configure(height=10)
            self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.set_active(False)

    def set_active(self, active):
        if active and self.mode == "ki":
            self.badge.configure(text="● KI STEUERT", background="#6a3fb5", foreground="white")
        elif not active and self.source.get() == "ki":
            self.badge.configure(text="◌ KI · bereit" if self.ki_model else "◌ KI · kein Modell gewaehlt",
                                 background="#8e74c4", foreground="white")
        elif active and self.mode == "remote":
            self.badge.configure(text="● REMOTE STEUERT", background="#b3261e", foreground="white")
        elif active:
            self.badge.configure(text="● LEADER AKTIV", background="#1f7a3a", foreground="white")
        elif self.source.get() == "remote":
            self.badge.configure(text="◌ REMOTE · PROBELAUF", background="#2f6fb5", foreground="white")
        else:
            self.badge.configure(text="ohne Leader", background="#ddd", foreground="#444")

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")
        if int(self.log.index("end-1c").split(".")[0]) > 10000:
            self.log.configure(state="normal")
            self.log.delete("1.0", "1001.0")
            self.log.configure(state="disabled")


class Lab:
    BOARD_POLL_S = 2.0

    def __init__(self, root):
        self.root = root
        self.process = None
        self.quitting = False       # Worker wurde zum Beenden aufgefordert
        self.queued = []            # Startbefehle, die auf einen neuen Worker warten
        self.events = queue.Queue()
        self.closing = False
        self.serials = {}
        self.logfile = None
        self.remote = None          # (server, stop, url)
        self.send_lock = threading.Lock()
        self.recorders = {}         # arm -> ki.recorder.Recorder
        self.ki_state = {}          # arm -> (Ist-Stellung, Zeit) aus den OBS-Zeilen
        self.ki_load = {}           # arm -> [6 Servolasten] aus den LAST-Zeilen
        self.kontakt = {}           # arm -> regel.kontakt.KontaktMelder
        self.live_pose = {}         # arm -> ({gelenk: Ist}, Zeit) aus den TRACE-Zeilen (Arbeitsbereich-Ansicht)
        self.ki_clients = {}        # arm -> ki.client.DriverClient
        self.ki_queue = None        # Trainings-Warteschlange (erst bei Bedarf)
        self.sessions = {}          # arm -> ki.session.ArmSession (Arbeitssitzung fuer Module)
        self.kern = None            # lokale Harness-Schnittstelle fuer die Module
        root.title("RoboForge Harness · SIMULATION (kein echter Arm)" if SIM else "RoboForge Harness")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1560, sw - 20)}x{min(980, sh - 80)}+0+0")
        try:
            root.state("zoomed")            # Windows: maximiert, damit beide Spalten ganz sichtbar sind
        except tk.TclError:
            pass
        outer = ttk.Frame(root, padding=(16, 12))
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="RoboForge Harness", font=("Segoe UI", 20, "bold")).pack(side="left")
        if SIM:
            tk.Label(top, text="  SIMULATION  ", bg="#d9822b", fg="white",
                     font=("Segoe UI", 16, "bold")).pack(side="left", padx=12)
        ttk.Label(top, text="  Harness fuer Roboter-Skills · SO-101", font=("Segoe UI", 11)).pack(side="left", pady=(8, 0))
        self.restart_button = ttk.Button(top, text="↻ Harness neu starten", command=self.restart)
        self.restart_button.pack(side="right")
        self.sim_button = ttk.Button(top, text="⏻ Zurück zu echten Armen" if SIM else "🧪 Simulation starten",
                                     command=self.sim_umschalten)
        self.sim_button.pack(side="right", padx=8)
        self.update_note = tk.StringVar(value="")
        tk.Label(top, textvariable=self.update_note, font=("Segoe UI", 10, "bold"), foreground="#b3261e").pack(side="right", padx=10)
        self.code_stamp = code_stamp()
        ttk.Label(outer, text="Ein Leader fuer beide Arme. Wechsel: der alte Arm legt sich ab, waehrend der neue hochfaehrt. "
                  "Nur mit freiem Arbeitsbereich und Aufsicht vor Ort. Stop = kontrolliert ablegen, kein Not-Halt.").pack(anchor="w")
        self.leader_state = tk.StringVar(value="Leader: suche ...")
        ttk.Label(outer, textvariable=self.leader_state, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
        net = ttk.LabelFrame(outer, text=" Netz · Fernsteuerung und Uebertragung ", padding=(10, 4))
        net.pack(fill="x", pady=(6, 10))
        self.net_server = tk.StringVar(value="Remote-Server: aus (startet, sobald ein Arm auf Remote steht)")
        self.net_down = tk.StringVar(value="Download (Steuerdaten → Roboter): –")
        self.net_up = tk.StringVar(value="Upload (Roboter → Bediener): –")
        self.net_video = tk.StringVar(value="Video ins Internet (LiveKit): aus")
        for var in (self.net_server, self.net_down, self.net_up):
            ttk.Label(net, textvariable=var, font=("Consolas", 9)).pack(anchor="w")
        vrow = ttk.Frame(net)
        vrow.pack(fill="x", pady=(2, 0))
        self.stream_button = ttk.Button(vrow, text="▶ Video-Streaming starten", command=self.toggle_stream)
        self.stream_button.pack(side="left")
        self.viewer_button = ttk.Button(vrow, text="Zuschauer-Ansicht oeffnen", command=self.open_viewer, state="disabled")
        self.viewer_button.pack(side="left", padx=(8, 4))
        ttk.Button(vrow, text="Fernzugang erstellen", command=self.remote_access).pack(side="left", padx=(4, 12))
        ttk.Label(vrow, textvariable=self.net_video, font=("Consolas", 9)).pack(side="left")
        self.streamer = None
        # 4 Kacheln nebeneinander + Mittelspalte (~150 px) + Raender; 16:9, hoechstens 320 px breit
        tile_w = max(200, min(320, (sw - 150 - 32 - 40) // 4))
        self.cams = CameraHub(root, (tile_w, tile_w * 9 // 16))
        self.cams.on_reassign = lambda slot: CameraWizard(self, [slot])
        arms, self.leader_serial = load_arms()
        # Scrollbare Flaeche: untereinander passt Setup 2 oft nicht mehr ins Fenster
        scroller = ttk.Frame(outer)
        scroller.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(scroller, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(scroller, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        cols = ttk.Frame(self.canvas)
        self.cols_item = self.canvas.create_window(0, 0, window=cols, anchor="nw")
        self.panels = {}
        center = ttk.Frame(cols, padding=(10, 60, 10, 0))
        for n, (key, label, serial, slots) in enumerate(arms[:2]):
            panel = ArmPanel(cols, self, key, ("SIMULATION · " + label) if SIM else label, serial, slots, self.cams)
            panel.grid(row=0, column=2 * n, sticky="nsew")
            cols.columnconfigure(2 * n, weight=1, uniform="arm")
            self.panels[key] = panel
        center.grid(row=0, column=1, sticky="n")
        self.stop_all_button = tk.Button(center, text="■ ALLE\nABLEGEN\n(F12)", font=("Segoe UI", 11, "bold"),
                                         width=10, background="#b3261e", foreground="white",
                                         activebackground="#8c1d17", command=self.emergency_all)
        self.stop_all_button.pack()
        ttk.Label(center, text="Greifer auf,\ndann ablegen", justify="center", font=("Segoe UI", 8)).pack(pady=(2, 0))
        ttk.Button(center, text="Kameras\nzuordnen", command=lambda: CameraWizard(self)).pack(pady=(24, 0))
        self.volt = None            # offene Spannungsmessung (belegt alle drei Ports)
        self.volt_button = ttk.Button(center, text="Spannung\nmessen", command=self.open_voltage)
        self.volt_button.pack(pady=(10, 0))
        self.calib = None           # offene Anschlag-Kalibrierung (belegt einen Port)
        self.calib_button = ttk.Button(center, text="Arme\nkalibrieren", command=self.open_calib)
        self.calib_button.pack(pady=(10, 0))
        ttk.Button(center, text="Arbeits-\nbereich", command=lambda: AreaWindow(self)).pack(pady=(10, 0))
        ttk.Label(center, text="Module", font=("Segoe UI", 9, "bold")).pack(pady=(18, 2))
        for label, script, color in MODULES:
            tk.Button(center, text=label, font=("Segoe UI", 10, "bold"), width=12, background=color,
                      foreground="white", activebackground="#333",
                      command=lambda sc=script: self.launch_module(sc)).pack(pady=(4, 0))
        self.module_state = tk.StringVar(value="")
        ttk.Label(center, textvariable=self.module_state, font=("Segoe UI", 8), justify="center",
                  wraplength=120).pack(pady=(6, 0))
        self.cols, self.center, self.tile_w = cols, center, tile_w
        self.layout = None
        self.canvas.bind("<Configure>", lambda e: self.fit_canvas())
        cols.bind("<Configure>", lambda e: self.fit_canvas(resized=False))
        root.bind_all("<MouseWheel>", self.on_wheel)
        self.relayout(sw)
        self.cams.start()
        self.start_kern_api()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<F12>", lambda e: self.emergency_all())     # Not-Ablage, in jedem Harness-Fenster
        root.bind("<Destroy>", lambda e: self._shutdown() if e.widget is root else None)
        threading.Thread(target=self._board_loop, daemon=True, name="board-poll").start()
        root.after(100, self.poll)
        root.after(300, self.update_buttons)
        root.after(1000, self.update_network)
        root.after(3000, self.check_update)

    # --- Boards (nur USB-Liste, kein Buszugriff) ---
    def _board_loop(self):
        stop = threading.Event()
        while not self.closing:
            self.events.put(("boards", connected_serials()))
            stop.wait(self.BOARD_POLL_S)

    def running(self):
        return [k for k, p in self.panels.items() if p.running]

    def update_buttons(self):
        leader_port = port_of(self.serials, self.leader_serial)
        if not self.leader_state.get().startswith(("LEADER", "Leader ausgefallen")):
            self.leader_state.set(f"Leader: {leader_port} verbunden" if leader_port else
                                  f"Leader nicht angeschlossen (USB {self.leader_serial}) · Anschluss pruefen")
        free = not self.closing and leader_port is not None and self.volt is None and self.calib is None
        idle = self.process is None and not self.running()
        self.volt_button.configure(state="normal" if idle and self.calib is None else "disabled")
        self.calib_button.configure(state="normal" if idle and self.volt is None else "disabled")
        for key, p in self.panels.items():
            port = port_of(self.serials, p.serial)
            p.board.set(f"Board {port}" if port else f"Board fehlt (USB {p.serial}) · Anschluss pruefen")
            p.set_active(p.running)
            source = p.source.get()
            local = source == "lokal"
            remote_ok = self.remote is not None and self.remote[0] is not None
            ki_ok = p.ki_model is not None and os.path.exists(KI_PYTHON)
            can_take = free and not p.running and port is not None and (
                local or (source == "remote" and remote_ok) or (source == "ki" and ki_ok))
            p.take_button.configure(state="normal" if can_take else "disabled",
                                    text={"lokal": "Leader uebernehmen", "remote": "Remote uebernehmen (langsam)",
                                          "ki": "KI uebernehmen (langsam)"}[source])
            p.stop_button.configure(state="normal" if p.running and not p.stopping else "disabled")
            for b in p.source_buttons:
                b.configure(state="disabled" if p.running else "normal")
            if not p.running and p.status.get() in ("Bereit", "Board nicht angeschlossen"):
                p.status.set("Bereit" if port else "Board nicht angeschlossen")
            if source == "ki" and not p.running:
                p.remote_info.set(f"Modell: {os.path.basename(p.ki_model)} · Aufgabe: {p.ki_task or '-'}"
                                  if p.ki_model else "KI: im VLA-Studio ein Modell fuer diesen Arm waehlen")
            if source == "remote" and not p.running and p.status.get() in ("Bereit", "Board nicht angeschlossen"):
                p.status.set("Remote-Probelauf · Arm bewegt sich nicht")   # Fehlermeldungen bleiben stehen
            elif source != "remote" and p.status.get().startswith("Remote-Probelauf"):
                p.status.set("Bereit")
                p.remote_info.set("")
        self.stop_all_button.configure(state="normal" if self.running() else "disabled")
        if any(p.source.get() == "remote" for p in self.panels.values()):
            self.ensure_remote()

    # --- Worker ---
    def open_voltage(self):
        """Spannungsmessung (nur Lesen). Braucht alle Ports, also nur ohne laufenden Worker."""
        if self.volt is not None:
            self.volt[0].lift()
            return
        if self.process is not None or self.running():
            messagebox.showinfo("Spannung messen", "Erst alle Arme ablegen. Die Messung braucht die Ports "
                                "der Boards, die gerade der Steuerung gehoeren.")
            return
        import voltmon
        labels = {"leader": "Leader", **{k: p.label for k, p in self.panels.items()}}
        def closed():
            self.volt = None
            self.update_buttons()
        self.volt = voltmon.window(self.root, labels, on_close=closed)
        self.update_buttons()

    def on_ui(self, fn):
        """fn im Fenster-Thread ausfuehren (fuer Befehle aus Fernzugriff oder Agent)."""
        self.events.put(("call", fn))

    def skills(self):
        """Gemeinsames Befehlsverzeichnis fuer Oberflaeche, Fernzugriff und spaeter einen Agenten."""
        if getattr(self, "_skills", None) is None:
            from ki import ros_skills
            self._skills = ros_skills.build(self)
        return self._skills

    # --- Anordnung: nebeneinander, oder untereinander, wenn die Kameras sonst nicht ganz zu sehen sind ---
    LAYOUT_HYSTERESIS = 30          # px: kein Hin- und Herspringen an der Grenze

    def fit_canvas(self, resized=True):
        """Inhalt so breit wie das Fenster; so hoch wie noetig, mindestens so hoch wie das Fenster.
        Bildlaufleiste nur, wenn der Inhalt hoeher ist als das Fenster."""
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 50:
            return
        if resized:
            before = self.layout
            self.relayout(w)
            if self.layout != before:
                # neue Anordnung: Groesse erst nach dem Neuzeichnen bekannt -> dann nochmal anpassen
                self.root.after_idle(lambda: self.fit_canvas(resized=False))
        self.cols.update_idletasks()
        need = self.cols.winfo_reqheight()
        c.itemconfigure(self.cols_item, width=w, height=max(h, need))
        c.configure(scrollregion=(0, 0, w, max(h, need)))
        show = need > h + 2
        if show and not self.vbar.winfo_ismapped():
            self.vbar.pack(side="right", fill="y", before=c)
        elif not show and self.vbar.winfo_ismapped():
            self.vbar.pack_forget()
            c.yview_moveto(0)

    def on_wheel(self, event):
        """Mausrad scrollt die Ansicht - ausser ueber einem Protokoll oder einer Liste, die selbst scrollen."""
        w = event.widget
        try:
            if w.winfo_toplevel() is not self.root or w.winfo_class() in ("Text", "Treeview", "Listbox", "TCombobox"):
                return
        except (tk.TclError, AttributeError, KeyError):
            return
        if self.vbar.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

    def wide_enough(self, width):
        """Passen beide Setups mit je allen Kameras in voller Groesse nebeneinander?"""
        cams = max(len(p.slots) for p in self.panels.values()) if self.panels else 2
        panel = cams * (self.tile_w + 8) + 16
        return width >= 2 * panel + self.center.winfo_reqwidth()

    def relayout(self, width):
        want = "nebeneinander" if self.wide_enough(width - (self.LAYOUT_HYSTERESIS if self.layout == "untereinander" else 0)) \
            else "untereinander"
        if want == self.layout:
            return
        self.layout = want
        cols, panels = self.cols, list(self.panels.values())
        for w in panels + [self.center]:
            w.grid_forget()
        for i in range(3):
            cols.columnconfigure(i, weight=0, uniform="")
            cols.rowconfigure(i, weight=0, uniform="")
        if want == "nebeneinander":
            for n, p in enumerate(panels):
                p.grid(row=0, column=2 * n, sticky="nsew")
                cols.columnconfigure(2 * n, weight=1, uniform="arm")
                p.set_compact(False)
            self.center.grid(row=0, column=1, sticky="n")
            cols.rowconfigure(0, weight=1)
        else:
            for n, p in enumerate(panels):
                p.grid(row=n, column=0, sticky="nsew", pady=(0, 10))
                p.set_compact(True, self.cams.PREVIEW[1])
            cols.columnconfigure(0, weight=1)
            self.center.grid(row=0, column=1, rowspan=max(1, len(panels)), sticky="ne")

    def launch_module(self, script):
        """Startet ein Modul als eigenes Programm. Es verbindet sich ueber die lokale Harness-Schnittstelle."""
        try:
            subprocess.Popen([sys.executable, str(HERE / script)], cwd=HERE,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            messagebox.showerror("Modul", f"{script} startet nicht: {exc}", parent=self.root)

    def start_kern_api(self):
        import kern_api
        try:
            self.kern = kern_api.KernAPI(self.skills(),
                                         log=lambda m: self.events.put(("call", lambda: None))).start()
        except Exception as exc:
            self.kern = None
            self.module_state.set(f"Harness-Schnittstelle aus: {exc}")

    # --- Arbeitssitzungen fuer Module ---
    def session_ok(self, key):
        s = self.sessions.get(key)
        return s is not None and not s.halt.is_set()

    def dialog_parent(self, key=None):
        """Fenster fuer Freigabe-Dialoge: ist der Steuermodus offen, dort (sonst sieht man den Dialog nicht)."""
        for k, p in self.panels.items():
            if key is not None and k != key:
                continue
            cv = getattr(p, "control_view", None)
            try:
                if cv is not None and cv.win.winfo_exists() and cv.win.winfo_viewable():
                    return cv.win
            except tk.TclError:
                pass
        return self.root

    def session_text(self, key, who):
        p = self.panels[key]
        return (f"Das Modul '{who}' moechte {p.label} bewegen.\n\n"
                f"{p.label} faehrt hoch und haelt dann seine Stellung. Das Modul bewegt den Arm danach selbst: "
                "fest programmierte Fahrten (langsam, vorher mit dem Hoehenmodell geprueft) und gelernte "
                "Faehigkeiten (hoechstens 45 Grad/s je Gelenk). Stop legt den Arm jederzeit ab und beendet die Sitzung.\n\n"
                f"Bist du vor Ort, hast den Arbeitsbereich im Blick und stimmst zu?\n\n{SAFETY_TEXT}")

    def session_open(self, key, who):
        """Sitzung starten (Zustimmung liegt schon vor: Dialog hier oder im lokalen Modul)."""
        from ki.session import ArmSession
        p = self.panels[key]
        if self.session_ok(key) or p.running:
            return
        def state():
            v = self.ki_state.get(key)
            return v[0] if v is not None and time.monotonic() - v[1] < 0.2 else None
        self.sessions[key] = ArmSession(key, who, lambda t: self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in t)),
                                        state)
        p.append(f"ARBEITSSITZUNG fuer Modul '{who}' freigegeben (Zustimmung vor Ort)\n")
        self._start(key, "ki")
        self.update_buttons()

    def session_request(self, key, who):
        """Im Fenster-Thread: Freigabe vor Ort fragen, dann Arm hochfahren und halten lassen."""
        from ki.session import ArmSession
        p = self.panels[key]
        if self.session_ok(key) or p.running:
            return
        if not messagebox.askokcancel("Arbeitssitzung freigeben",
                f"Das Modul '{who}' moechte {p.label} bewegen.\n\n"
                f"{p.label} faehrt hoch und haelt dann seine Stellung. Bewegungen gibt es nur, wenn das Modul eine "
                "Faehigkeit (trainiertes Modell) ausfuehren laesst, langsam (hoechstens 45 Grad/s je Gelenk). "
                "Stop legt den Arm jederzeit ab und beendet die Sitzung.\n\n"
                f"Bist du vor Ort, hast den Arbeitsbereich im Blick und stimmst zu?\n\n{SAFETY_TEXT}", parent=self.dialog_parent(key)):
            return
        def state():
            v = self.ki_state.get(key)
            return v[0] if v is not None and time.monotonic() - v[1] < 0.2 else None
        self.sessions[key] = ArmSession(key, who, lambda t: self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in t)),
                                        state)
        p.append(f"ARBEITSSITZUNG fuer Modul '{who}' freigegeben\n")
        self._start(key, "ki")
        self.update_buttons()

    def session_run_model(self, key, model, seconds, task=None):
        """Aus einem Befehls-Thread: Modell fahren lassen (blockiert `seconds`)."""
        from ki.client import DriverClient
        from ki.episodes import load_json
        from ki import MODELS
        s = self.sessions.get(key)
        if s is None or s.halt.is_set():
            raise RuntimeError("Keine freigegebene Arbeitssitzung auf diesem Arm")
        deadline = time.monotonic() + 60
        while not self.panels[key].status.get().startswith("ARBEITSSITZUNG") and time.monotonic() < deadline:
            if s.halt.is_set():
                raise RuntimeError("Sitzung beendet")
            time.sleep(0.2)                      # Arm faehrt noch hoch
        model_dir = os.path.join(MODELS, model)
        meta = load_json(os.path.join(model_dir, "modell.json"))
        if meta is None:
            raise ValueError(f"Modell {model!r} nicht gefunden")
        p = self.panels[key]
        mine = [self.cam_key(sl) for sl in p.slots]
        missing = [c for c in meta.get("cameras") or [] if c not in mine]
        if missing:
            raise ValueError(f"Modell braucht Kameras {meta['cameras']}, {p.label} hat {mine} (fehlt: {missing})")
        def log(text):
            self.events.put(("line", f"[{key}] {text}\n"))
        def make():
            pre = getattr(self, "preloaded", {}).pop(key, None)
            if pre is not None:
                name, c = pre
                if name == model and c.error is None and not c.halt.is_set():
                    log("FAEHIGKEIT: vorgeladenes Modell uebernimmt")
                    c.task = task or c.task
                    c.get_state = s.get_state
                    return c                             # run_model hebt die Pause auf
                c.halt.set()
                threading.Thread(target=c.stop, daemon=True).start()
            return DriverClient(model_dir, task or meta.get("task") or "", lambda: self.arm_frames(key),
                                s.get_state, lambda t: self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in t)),
                                log=log, cv2=self.cams.cameras.cv2).start()
        log(f"FAEHIGKEIT: {model} fuer {seconds} s")
        return s.run_model(make, seconds)

    def preload_model(self, key, model, task=None):
        """VLA-Modell im Hintergrund laden (eigener Prozess), pausiert - es sendet erst, wenn eine Faehigkeit startet."""
        from ki.client import DriverClient
        from ki.episodes import load_json
        from ki import MODELS
        if not hasattr(self, "preloaded"):
            self.preloaded = {}
        old = self.preloaded.get(key)
        if old is not None and old[0] == model and old[1].error is None and not old[1].halt.is_set():
            if task:
                old[1].task = task
            return {"modell": model, "zustand": "bereit" if old[1].ready.is_set() else "laedt"}
        if old is not None:
            old[1].halt.set()
            threading.Thread(target=old[1].stop, daemon=True).start()
        model_dir = os.path.join(MODELS, model)
        meta = load_json(os.path.join(model_dir, "modell.json"))
        if meta is None:
            raise ValueError(f"Modell {model!r} nicht gefunden")
        def log(text):
            self.events.put(("line", f"[{key}] {text}\n"))
        c = DriverClient(model_dir, task or meta.get("task") or "", lambda: self.arm_frames(key),
                         lambda: self.arm_state(key),
                         lambda t: self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in t)),
                         log=log, cv2=self.cams.cameras.cv2)
        c.paused.set()                          # laden ja, fahren nein
        c.start()
        self.preloaded[key] = (model, c)
        log(f"VLA-Modell {model} wird vorgeladen")
        return {"modell": model, "zustand": "laedt"}

    def arm_state(self, key):
        """Aktuelle Ist-Stellung [j1..j6] aus den OBS-Zeilen (nur waehrend der Arm laeuft), sonst None."""
        v = self.ki_state.get(key)
        return list(v[0]) if v is not None and time.monotonic() - v[1] < 0.3 else None

    def ready_session(self, key, wait=60):
        """Freigegebene Sitzung, deren Arm oben steht; wartet notfalls, bis er hochgefahren ist."""
        s = self.sessions.get(key)
        if s is None or s.halt.is_set():
            raise RuntimeError("Keine freigegebene Arbeitssitzung auf diesem Arm (sitzung.anfragen)")
        deadline = time.monotonic() + wait
        while not self.panels[key].status.get().startswith("ARBEITSSITZUNG"):
            if s.halt.is_set() or time.monotonic() > deadline:
                raise RuntimeError("Arm ist nicht bereit (Sitzung beendet oder faehrt noch hoch)")
            time.sleep(0.2)
        return s

    def session_end(self, key):
        s = self.sessions.pop(key, None)
        if s is not None:
            s.stop()


    def open_calib(self):
        """Anschlag-Kalibrierung (nur Lesen). Braucht den Port des Arms, also nur ohne laufenden Worker."""
        if self.calib is not None:
            self.calib.win.lift()
            return
        if self.process is not None or self.running() or self.volt is not None:
            messagebox.showinfo("Arme kalibrieren", "Erst alle Arme ablegen und die Spannungsmessung schliessen.")
            return
        self.calib = CalibWizard(self)
        self.update_buttons()

    def ensure_worker(self):
        if self.process is not None:
            return True
        if self.volt is not None or self.calib is not None:
            messagebox.showinfo("Messfenster offen", "Bitte zuerst das Fenster der Spannungsmessung bzw. "
                                "Kalibrierung schliessen. Es belegt die Ports der Boards.")
            return False
        command = ([sys.executable, "-u", str(HERE / "sim_worker.py"), "--multi", "--backend", SIM_BACKEND] if SIM
                   else [sys.executable, "-u", str(HERE / "lab_worker.py"), "--multi"])
        try:
            logdir = HERE / "logs"
            logdir.mkdir(exist_ok=True)
            logpath = logdir / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-multi.log")
            logfile = logpath.open("w", encoding="utf-8", buffering=1)
            process = subprocess.Popen(command, cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            messagebox.showerror("Start fehlgeschlagen", str(exc))
            return False
        self.process, self.quitting = process, False
        for p in self.panels.values():
            p.append(f"\n--- Worker gestartet · Logdatei: {logpath} ---\n")
        def read():
            try:
                for line in process.stdout:
                    if "] OBS " in line:          # Aufnahme-Zeilen sofort weitergeben, nicht ins Protokoll
                        self._obs_line(line)
                        continue
                    if "] LAST " in line:         # Servolast fuer die Kontakterkennung, 10 Hz: nicht ins Protokoll
                        self._last_line(line)
                        continue
                    if "] POSE " in line:         # 3D-Ansicht, 25 Hz: nicht ins Protokoll
                        self._trace_line(line)
                        continue
                    if "] TRACE IDs" in line:
                        self._trace_line(line)
                    try:
                        logfile.write(datetime.now().isoformat(timespec="milliseconds") + " " + line)
                    except OSError:
                        pass  # Disk errors must not break the controller's stdout pipe.
                    self.events.put(("line", line))
                self.events.put(("done", process.wait()))
            finally:
                logfile.close()
        threading.Thread(target=read, daemon=True).start()
        return True

    def send(self, command):
        with self.send_lock:                    # Fenster-Thread und Ziel-Thread schreiben beide
            process = self.process
            if process is None or process.poll() is not None:
                return False
            try:
                process.stdin.write(command + "\n")
                process.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                return False

    def _start(self, key, mode="lokal"):
        p = self.panels[key]
        command = f"start {key}" + (f" {mode}" if mode in ("remote", "ki") else "")
        if self.quitting:
            self.queued.append((key, mode))     # alter Worker beendet sich gerade
        elif not self.ensure_worker() or not self.send(command):
            return
        p.running, p.stopping, p.mode = True, False, mode
        p.status.set("Vorpruefung → Hochfahren" + (" · danach Fernsteuerung (langsam)" if mode == "remote" else ""))
        p.append(f"\n--- Start {p.label} ({ {'remote': 'Fernsteuerung', 'ki': 'KI-Modell'}.get(mode, 'Leader') }) ---\n")

    def _target_loop(self):
        """Schickt die Ziele der Fernsteuerung mit ~50 Hz an den Worker, solange ein Arm remote laeuft.
        Eigener Thread, damit z. B. Fensterziehen (blockiert Tk) die Ziele nicht anhaelt."""
        tick = threading.Event()
        while not self.closing:
            srv = self.remote[0] if self.remote else None
            arms = {}
            for key, p in list(self.panels.items()):
                live = p.running and p.mode == "remote"
                arms[key] = (p.label, p.source.get() == "remote" or live, live)
            if srv is not None:
                srv.set_arms_threadsafe(arms)    # jeder Arm hat seinen eigenen Fernsteuerer
            sent = False
            for key, (_, _, live) in arms.items():
                ln = srv.lanes.get(key) if srv is not None else None
                if live and ln is not None:      # App sieht dry_run=false, solange der Arm folgt
                    self.send(f"target {key} " + " ".join(str(int(v)) for v in ln.state["joints"]))
                    sent = True
            tick.wait(0.02 if sent else 0.1)

    def take_remote(self, key):
        panel = self.panels[key]
        srv = self.remote[0] if self.remote else None
        if srv is None:
            return
        if not messagebox.askokcancel("Fernsteuerung freigeben",
                f"{panel.label} wird von der FERNSTEUERUNG bewegt (WLAN oder Internet), langsam: "
                f"Greiferspitze hoechstens {REMOTE_CFG.v_max * 100:.0f} cm/s.\n\n"
                "Der Arm faehrt zuerst einzeln hoch in die Mittelstellung. Danach bewegt er sich nur, solange "
                "der Bediener die Kupplung haelt. Kommen 1 s keine Ziele mehr, legt er sich ab.\n\n"
                f"Bist du vor Ort, hast den Arbeitsbereich im Blick und stimmst zu?\n\n{SAFETY_TEXT}", parent=self.dialog_parent(key)):
            return
        try:
            srv.reset_threadsafe(arm=key)        # Ziel = Mittelstellung, Kupplung neu druecken
        except Exception as exc:
            messagebox.showerror("Fernsteuerung", f"Remote-Server antwortet nicht: {exc}", parent=self.root)
            return
        self._start(key, "remote")
        self.update_buttons()

    def take_leader(self, key):
        panel = self.panels[key]
        if panel.running:
            return
        if panel.source.get() == "remote":
            self.take_remote(key)
            return
        if panel.source.get() == "ki":
            self.take_ki(key)
            return
        others = [k for k in self.running() if k != key and self.panels[k].mode == "lokal"]
        names = ", ".join(self.panels[k].label for k in others)
        if others:
            text = (f"Leader von {names} zu {panel.label} wechseln?\n\n"
                    f"{names} legt sich kontrolliert ab, GLEICHZEITIG faehrt {panel.label} hoch und folgt dem Leader.\n\n"
                    f"Bist du vor Ort und stimmst der Bewegung beider Arme zu?\n\n{SAFETY_TEXT}")
        else:
            text = f"{panel.label}: Bist du vor Ort und stimmst der schnellen Bewegung zu?\n\n{SAFETY_TEXT}\n\nJetzt Bewegung starten?"
        if not messagebox.askokcancel("Bewegung freigeben", text, parent=self.dialog_parent(key)):
            return
        for k in others:
            self.stop(k)
        self._start(key)
        self.update_buttons()

    def emergency_all(self):
        """Not-Ablage (F12, auch aus der Fernsteuerung): alle laufenden Arme sofort stoppen, Greifer oeffnen
        (verklemmte Teile loslassen) und kontrolliert ablegen. Kein Not-Aus: der trennt den Servo-Strom (Hardware)."""
        self.queued = []
        for key, p in self.panels.items():
            if p.running and self.send(f"stop {key} frei"):
                p.stopping = True
                self.ki_stop(key)
                self.session_end(key)
                p.status.set("NOT-ABLAGE · Greifer oeffnen, ablegen")
                p.append("NOT-ABLAGE ausgeloest\n")
        self.update_buttons()

    def stop(self, key):
        p = self.panels[key]
        queued = [q for q in self.queued if q[0] == key]
        if queued:
            self.queued.remove(queued[0])
            p.running = False
            p.status.set("Start abgebrochen")
        elif p.running and self.send(f"stop {key}"):
            p.stopping = True
            self.ki_stop(key)
            self.session_end(key)
            p.status.set("Stop angefordert · Ablage abwarten")
        self.update_buttons()

    def stop_all(self):
        for key in self.running():
            self.stop(key)

    def _worker_line(self, line):
        key, text = parse_line(line)
        if key in self.panels:
            p = self.panels[key]
            if text.startswith("ARMENDE"):
                rc = text.split()[-1]
                p.running = p.stopping = False
                rec = self.recorders.get(key)
                if rec is not None and rec.state == "nimmt_auf":
                    rec.stop()
                self.ki_stop(key)
                self.session_end(key)
                if rc != "0":
                    p.status.set("Fehler · Zustand vor Ort pruefen, Protokoll beachten")
                elif not p.status.get().startswith("Abgelegt"):
                    p.status.set("Lauf beendet")
                if not self.running() and not self.queued:
                    self.quitting = self.send("quit")   # Leader-Port wieder freigeben
                return
            p.append(text if text.endswith("\n") else text + "\n")
            status = arm_status(text)
            if status:
                if p.mode == "remote" and status.startswith("Folgt dem Leader"):
                    status = "Folgt der FERNSTEUERUNG (langsam) · Stop zum Ablegen"
                elif p.mode == "ki" and status.startswith("Folgt dem Leader") and key in self.sessions:
                    status = f"ARBEITSSITZUNG ({self.sessions[key].who}) · Stop zum Ablegen"
                elif p.mode == "ki" and status.startswith("Folgt dem Leader"):
                    status = "KI STEUERT (langsam) · Stop zum Ablegen"
                p.status.set(status)
            return
        if text.startswith("LEADER:"):
            self.leader_state.set(text.strip())
            return
        if text.startswith("Remote:"):                 # Meldungen des Fernsteuer-Servers (Fenster selbst)
            for p in self.panels.values():
                if p.source.get() == "remote":
                    p.append(text)
            return
        if text.startswith(("LEADER FEHLER", "LEADER AUSGEFALLEN")):
            self.leader_state.set("Leader ausgefallen: " + text.split(":", 1)[-1].strip())
        for p in self.panels.values():
            p.append("[Worker] " + text)

    # --- KI-Aufnahme ---
    def cam_key(self, slot):
        """Kurzname einer Kamera fuer Datensaetze: 'Setup 1 · Arm' -> 'arm'."""
        from ki.episodes import slug
        return slug(self.cams.manager.slots[slot]["name"].split("·")[-1])

    def recorder(self, key):
        from ki.recorder import Recorder
        rec = self.recorders.get(key)
        if rec is None:
            slots = self.panels[key].slots
            def frames():
                now = time.monotonic()
                out = {}
                for slot in slots:
                    _, cam = self.cams.manager.status(slot, now)
                    out[self.cam_key(slot)] = cam.latest() if cam is not None else (None, None)
                return out
            rec = self.recorders[key] = Recorder(self.cams.cameras.cv2, frames)
        return rec

    def _trace_line(self, line):
        m = re.search(r"\[(\w+)\] TRACE IDs.*\| Ist \[([^\]]*)\]", line) or \
            re.search(r"\[(\w+)\] POSE ([\d ]+)", line)
        if m:
            try:
                vals = [int(v) for v in m.group(2).replace(",", " ").split()]
                self.live_pose[m.group(1)] = ({i + 1: v for i, v in enumerate(vals)}, time.monotonic())
            except ValueError:
                pass

    def _last_line(self, line):
        key, text = parse_line(line)
        try:
            self.ki_load[key] = [int(v) for v in text.split()[1:7]]
        except ValueError:
            pass

    def kontakt_melder(self, key):
        """Kontakt ohne Kraftsensor (regel.kontakt) - wird mit jeder OBS-Zeile gefuettert."""
        from regel.kontakt import KontaktMelder
        if key not in self.kontakt:
            self.kontakt[key] = KontaktMelder()
        return self.kontakt[key]

    def _obs_line(self, line):
        from ki.recorder import parse_obs
        key, text = parse_line(line)
        rec = self.recorders.get(key)
        parsed = parse_obs(text.strip())
        if parsed:
            self.ki_state[key] = (parsed[0], time.monotonic())
            if key in self.kontakt:
                try:
                    self.kontakt[key].probe(time.monotonic(), parsed[1], parsed[0], self.ki_load.get(key))
                except Exception:
                    pass
        if rec is not None and parsed:
            rec.obs(*parsed)

    def arm_frames(self, key):
        """Neueste Bilder der Kameras dieses Arms: {kurzname: bild oder None}."""
        if SIM:                                # Simulation: Bilder schreibt sim_worker.py
            import cv2
            out = {}
            for cam in ("arm", "turm"):
                path = HERE / "ki_daten" / "sim_kameras" / f"{key}_{cam}.jpg"
                fresh = path.exists() and time.time() - path.stat().st_mtime < 1.0
                out[cam] = cv2.imread(str(path)) if fresh else None
            return out
        now = time.monotonic()
        out = {}
        for slot in self.panels[key].slots:
            _, cam = self.cams.manager.status(slot, now)
            img, t = cam.latest() if cam is not None else (None, None)
            out[self.cam_key(slot)] = img if img is not None and t is not None and now - t < 0.25 else None
        return out

    def take_ki(self, key):
        from ki.client import DriverClient, SLOW_DEG_S
        from ki.episodes import load_json
        p = self.panels[key]
        if not p.ki_model:
            return
        meta = load_json(os.path.join(p.ki_model, "modell.json")) or {}
        mine = [self.cam_key(s) for s in p.slots]
        missing = [c for c in meta.get("cameras") or [] if c not in mine]
        if missing:   # Modell darf weniger Kameras nutzen als der Arm hat, aber keine fehlende
            messagebox.showerror("KI", f"Das Modell braucht die Kameras {meta['cameras']}, {p.label} hat {mine} "
                                       f"(fehlt: {', '.join(missing)}).",
                                 parent=self.root)
            return
        warn = ""
        if meta.get("arm") and meta["arm"] != key:
            warn = f"\n\nACHTUNG: Das Modell wurde an {meta['arm']} aufgenommen, nicht an {p.label}."
        if not messagebox.askokcancel("KI-Steuerung freigeben",
                f"{p.label} wird vom KI-Modell {os.path.basename(p.ki_model)} ({meta.get('method', '?')}) bewegt, "
                f"hoechstens {SLOW_DEG_S:.0f} Grad/s je Gelenk. Haelt das Modell nach der Aufgabe still oder ist eine Minute um, legt sich der Arm ab.\n\nAufgabe: {p.ki_task or meta.get('task') or '-'}"
                f"\n\nDer Arm faehrt zuerst einzeln hoch und haelt dann seine Stellung, bis das Modell Ziele liefert. "
                f"Kommen 1 s keine Ziele, legt er sich ab. Ein KI-Modell kann sich unerwartet bewegen.{warn}\n\n"
                f"Bist du vor Ort, hast den Arbeitsbereich im Blick und stimmst zu?\n\n{SAFETY_TEXT}", parent=self.dialog_parent(key)):
            return
        def state():
            v = self.ki_state.get(key)
            return v[0] if v is not None and time.monotonic() - v[1] < 0.2 else None
        def log(text):
            self.events.put(("line", f"[{key}] {text}\n"))
        def done(reason):
            # VLA haelt nach der Aufgabe still (wie am Ende jeder Aufnahme) -> fertig; danach ablegen
            log("KI: Aufgabe erledigt (Modell haelt still). Arm wird abgelegt." if reason == "fertig" else
                "KI: Zeitgrenze erreicht. Arm wird abgelegt.")
            self.on_ui(lambda: self.stop(key))
        client = DriverClient(p.ki_model, p.ki_task or meta.get("task") or "", lambda: self.arm_frames(key), state,
                              lambda t: self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in t)), log=log,
                              cv2=self.cams.cameras.cv2, on_done=done)
        from ki import poses
        # Startpose des Modells (aus seinen Episoden); aeltere Modelle ohne Angabe: Startpose des Arms
        start = meta.get("startpose")
        if start is None and meta.get("dataset"):
            from ki import jobs, episodes as ep_mod, DATASETS
            start = jobs.start_pose(ep_mod.Dataset(os.path.join(DATASETS, meta["dataset"])))
        start = start or poses.load().get(key, {}).get("_start")
        if start is not None:
            client.paused.set()                  # Modell uebernimmt erst in der Startpose (wie bei der Aufnahme)
            threading.Thread(target=self._ki_to_start, args=(key, client, start), daemon=True,
                             name=f"ki-start-{key}").start()
        self.ki_clients[key] = client.start()
        p.append("KI-Fahrer startet (Modell wird geladen) ...\n")
        self._start(key, "ki")
        self.update_buttons()

    def _ki_to_start(self, key, client, start, deg_per_s=30.0):
        """Nach dem Hochfahren langsam in die Startpose der Aufnahmen fahren, dann das Modell freigeben.
        Laeuft im eigenen Thread; sendet die Ziele selbst, bis das Modell uebernimmt."""
        from ki import poses
        def log(text):
            self.events.put(("line", f"[{key}] {text}\n"))
        deadline = time.monotonic() + 90
        while not self.panels[key].status.get().startswith("KI STEUERT") or self.arm_state(key) is None:
            if client.halt.is_set() or time.monotonic() > deadline:
                return
            time.sleep(0.1)
        hold = self.arm_state(key)
        ok, why = poses.check_path(hold, start)
        if not ok:
            log(f"KI: Fahrt in die Startpose abgelehnt ({why}). Arm wird abgelegt.")
            self.on_ui(lambda: self.stop(key))
            return
        log("KI: fahre langsam in die Startpose der Aufnahmen ...")
        step = poses.steps_per_tick(deg_per_s)
        hold = list(hold)
        while hold != list(start):
            if client.halt.is_set():
                return
            hold = [h + max(-step, min(step, g - h)) for h, g in zip(hold, start)]
            self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in hold))
            time.sleep(1 / 30)
        end = time.monotonic() + 3
        while time.monotonic() < end and not client.halt.is_set():   # kurz ausregeln lassen
            self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in hold))
            st = self.arm_state(key)
            if st and max(abs(a - b) for a, b in zip(st[:5], start[:5])) <= 25:
                break
            time.sleep(1 / 30)
        # Das Modell laedt oft laenger (30-40 s) als Hochfahren und Startpose dauern: bis dahin Startpose halten
        wait_until = time.monotonic() + 120
        if not client.ready.is_set():
            log("KI: Startpose erreicht, warte auf das Modell (wird noch geladen) ...")
        while not client.ready.is_set():
            if client.halt.is_set() or time.monotonic() > wait_until:
                if not client.halt.is_set():
                    log("KI: Modell nicht rechtzeitig geladen. Arm wird abgelegt.")
                    self.on_ui(lambda: self.stop(key))
                return
            self.send(f"ktarget {key} " + " ".join(str(int(v)) for v in hold))
            time.sleep(1 / 30)
        if client.error:
            log(f"KI: Modell meldet Fehler ({client.error}). Arm wird abgelegt.")
            self.on_ui(lambda: self.stop(key))
            return
        client.last_sent = list(hold)
        client.paused.clear()
        log("KI: Startpose erreicht, Modell uebernimmt.")

    def ki_stop(self, key):
        client = self.ki_clients.pop(key, None)
        if client is not None:
            threading.Thread(target=client.stop, daemon=True).start()

    def record_start(self, key, name, task):
        """Startet eine Episode. Nur waehrend der Arm dem Leader folgt."""
        from ki import episodes
        import stopcal
        p = self.panels[key]
        if not (p.running and p.mode == "lokal" and p.status.get().startswith("Folgt")):
            raise RuntimeError("Aufnahme geht nur, waehrend der Arm dem Leader folgt.")
        if not name.strip() or not task.strip():
            raise RuntimeError("Bitte Datensatz-Name und Aufgabe eintragen.")
        m = stopcal.load(stopcal.map_path(key))
        ds = episodes.open_dataset(name.strip(), task.strip(), key, [self.cam_key(s) for s in p.slots],
                                   calibration=m.get("time") if m else None)
        rec = self.recorder(key)
        self.send(f"rec {key} on")
        rec.start(ds, task.strip())
        p.append(f"AUFNAHME: Episode {len(ds.episodes()) + 1} von '{ds.meta['name']}' laeuft\n")
        return ds

    def record_start_plan(self, key, dataset, task, cameras, required, rename):
        """Episode fuer einen Aufnahmeplan: feste Kameranamen (rename), nur 'required' ist Pflicht."""
        p = self.panels[key]
        if not (p.running and p.mode == "lokal" and p.status.get().startswith("Folgt")):
            raise RuntimeError("Aufnahme geht nur, waehrend der Arm dem Leader folgt.")
        rec = self.recorder(key)
        self.send(f"rec {key} on")
        rec.start(dataset, task, cameras=cameras, required=required, rename=rename)
        p.append(f"AUFNAHME (Plan): Episode {len(dataset.episodes()) + 1} · {task}\n")
        return dataset

    def record_stop(self, key):
        rec = self.recorders.get(key)
        if rec is not None:
            rec.stop()
        self.send(f"rec {key} off")

    def record_decide(self, key, keep, extra=None):
        rec = self.recorders.get(key)
        if rec is None or rec.state != "wartet_entscheidung":
            return None
        frames, dropped = rec.frames, rec.dropped
        path = rec.keep(extra) if keep else rec.discard()
        self.panels[key].append(f"AUFNAHME: {'behalten' if keep else 'verworfen'} ({frames} Bilder, "
                                f"{dropped} Luecken)\n")
        return path

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "boards":
                    self.serials = value
                elif kind == "line":
                    self._worker_line(value)
                elif kind == "call":
                    value()
                else:
                    self._worker_done(value)
                    if self.closing and self.process is None and value == 0:
                        self.root.destroy()
                        return
                self.update_buttons()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def _worker_done(self, rc):
        try:
            self.process.stdin.close()
            self.process.stdout.close()
        except OSError:
            pass
        self.process, self.quitting = None, False
        for p in self.panels.values():
            if p.running:                       # Worker weg, ohne ARMENDE (z. B. Leader-Fehler)
                p.running = p.stopping = False
                self.ki_stop(p.key)
                self.session_end(p.key)
                p.status.set("Worker beendet · Zustand vor Ort pruefen, Protokoll beachten")
        if self.leader_state.get().startswith("LEADER:"):
            self.leader_state.set("Leader: frei")
        if self.closing:
            if rc != 0:
                self.closing = False
                messagebox.showwarning("Nicht sicher beendet", "Mindestens ein Arm meldet einen Fehler. "
                                       "Zustand vor Ort pruefen, Protokoll beachten.", parent=self.root)
            return
        queued, self.queued = self.queued, []
        for key, mode in queued:
            self.panels[key].running = False
            self._start(key, mode)

    # --- Remote (Trockenlauf) ---
    def ensure_remote(self):
        if self.remote is not None:
            return
        try:
            import remote_server, stream_livekit
            lk, why = stream_livekit.load_config()       # ohne livekit.json nur WLAN
            self.remote_note = "" if lk else f" · Internet aus ({why})"
            self.remote = remote_server.run_in_thread(REMOTE_PORT, cfg=REMOTE_CFG,
                                                      log=self._remote_log,
                                                      livekit_cfg=lk)
            if self.remote[0] is not None:
                self.remote[0].skills = self.skills()    # Befehle (Training, Modelle, ...) auch ueber das Netz
                self._load_access(self.remote[0])
            threading.Thread(target=self._target_loop, daemon=True, name="remote-targets").start()
            self.root.after(1000, self.refresh_control)
        except Exception as exc:
            self.remote = (None, None, None)
            self.net_server.set(f"Remote-Server: Start fehlgeschlagen ({exc})")

    # --- Fernzugriff: wer steuert, wie lange, gemerkte Geraete ---
    def _load_access(self, srv):
        try:
            data = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        srv.devices.update(data.get("geraete", {}))
        if data.get("max_min"):
            srv.set_max_min(int(data["max_min"]))

        def save():
            try:
                ACCESS_FILE.write_text(json.dumps({"max_min": srv.lane.desk.max_min, "geraete": srv.devices},
                                                  indent=1, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        srv.on_desk_change = save

    def refresh_control(self):
        """Jede Sekunde: bei Remote-Armen anzeigen, wer steuert und wie lange noch."""
        srv = self.remote[0] if self.remote else None
        if srv is None or self.closing:
            return
        try:
            view = srv.control_overview()
        except RuntimeError:                 # Dict waehrend des Lesens geaendert: naechstes Mal
            view = {}
        for key, p in self.panels.items():
            v = view.get(key)
            if p.source.get() != "remote" or v is None:
                p.ctl_box.pack_forget()
                continue
            if not p.ctl_box.winfo_ismapped():
                p.ctl_box.pack(fill="x", pady=(4, 0), after=p.ctl_anchor)
            if v["holder"] is not None:
                left = v["left_s"] or 0
                text = f"🎮 Bediener: {v['holder_name']} · noch {left // 60}:{left % 60:02d} min"
            else:
                text = "🎮 Niemand steuert · der Erste mit 'Steuern' bekommt den Arm"
            others = [c["name"] for c in v["clients"] if c["role"] != "Bediener"]
            text += f"\nLimit {v['max_min']} min · Zuschauer/Warteschlange: {', '.join(others) or '-'}"
            if v.get("extend_wanted"):
                text += "\n⚠ Bediener bittet um Verlaengerung → 'Fernzugriff verwalten'"
            p.ctl_text.set(text)
        self.root.after(1000, self.refresh_control)

    # --- Video ins Internet (LiveKit) ---
    def toggle_stream(self):
        import stream_livekit
        if self.streamer is not None and self.streamer.running:
            self.streamer.stop()
            self.stream_button.configure(text="▶ Video-Streaming starten")
            return
        cfg, why = stream_livekit.load_config()
        if cfg is None:
            messagebox.showinfo("LiveKit noch nicht eingerichtet", why, parent=self.root)
            self.net_video.set(f"Video ins Internet (LiveKit): {why}")
            return
        self.stream_cfg = cfg
        self.streamer = stream_livekit.Streamer(self.cams.manager, cfg)
        self.streamer.start()
        self.stream_button.configure(text="■ Video-Streaming stoppen")

    def _remote_log(self, m):
        """Remote-Meldungen ins Fenster und in logs/remote-JJJJMMTT.log (fuer die Fehlersuche)."""
        self.events.put(("line", f"Remote: {m}\n"))
        try:
            (HERE / "logs").mkdir(exist_ok=True)
            with open(HERE / "logs" / time.strftime("remote-%Y%m%d.log"), "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {m}\n")
        except OSError:
            pass

    def remote_access(self):
        """Zugangscode fuer die Fernsteuerungs-App (RoboForge Fernsteuerung): Video sehen, Steuerdaten senden.
        Der Code enthaelt nur ein zeitlich begrenztes Token, nie den LiveKit-Schluessel."""
        import stream_livekit, remote_access
        cfg, why = stream_livekit.load_config()
        if cfg is None:
            messagebox.showinfo("Fernzugang", f"LiveKit ist nicht eingerichtet: {why}", parent=self.root)
            return
        hours = 12
        code = remote_access.make_code(cfg, hours=hours)
        self.ensure_remote()                     # Steuer-Server im Raum, damit die App antworten bekommt
        win = tk.Toplevel(self.root)
        win.title("Fernzugang")
        ttk.Label(win, text="Zugangscode fuer die App „RoboForge Fernsteuerung“", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=16, pady=(14, 4))
        ttk.Label(win, wraplength=560, justify="left", text=(
            f"Gueltig {hours} Stunden. Wer den Code hat, sieht die Kameras, kann Training starten und darf einen Arm "
            "steuern, sobald du hier am Arm 'Remote (Internet)' waehlst und freigibst. Nur an Vertrauenspersonen geben.")
        ).pack(anchor="w", padx=16)
        box = tk.Text(win, height=6, width=70, font=("Consolas", 8), wrap="char")
        box.insert("1.0", code)
        box.configure(state="disabled")
        box.pack(padx=16, pady=8)
        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            copied.set("kopiert ✔")
        row = ttk.Frame(win)
        row.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(row, text="In die Zwischenablage kopieren", command=copy).pack(side="left")
        copied = tk.StringVar()
        ttk.Label(row, textvariable=copied, foreground="#1f7a3a").pack(side="left", padx=8)
        if self.streamer is None or not self.streamer.running:
            ttk.Label(win, text="Hinweis: Video-Streaming laeuft noch nicht. Die App kann es auch selbst starten.",
                      foreground="#b36b00").pack(anchor="w", padx=16, pady=(0, 12))

    def open_viewer(self):
        import stream_livekit, webbrowser
        webbrowser.open(stream_livekit.viewer_link(self.stream_cfg))

    def video_status(self):
        st = self.streamer
        if st is None:
            return
        s = st.summary()
        live = s["state"] == "live"
        self.viewer_button.configure(state="normal" if live else "disabled")
        if not st.running:
            self.stream_button.configure(text="▶ Video-Streaming starten")
        if s["state"] == "Fehler":
            self.net_video.set(f"Video ins Internet (LiveKit): FEHLER {s['error']}")
            return
        if not live:
            self.net_video.set(f"Video ins Internet (LiveKit): {s['state']}")
            return
        parts = []
        for slot, t in sorted(s["tracks"].items()):
            limit = f" ({t['limit']})" if t.get("limit") else ""
            parts.append(f"{slot + 1}: {t.get('kbps', 0):4.0f} kbit/s {t.get('fps') or t.get('sent', 0):.0f} fps{limit}")
        self.net_video.set(f"Video LIVE · Raum {self.stream_cfg['room']} · Zuschauer {s['viewers']} · Upload gesamt "
                           f"{s['kbps'] / 1000:4.2f} Mbit/s · " + " | ".join(parts))

    def update_network(self):
        if self.kern is not None:
            mods = [m for m in self.kern.modules() if m != "?"]
            sess = [f"{self.panels[k].label}: {s.who}" for k, s in self.sessions.items() if not s.halt.is_set()]
            self.module_state.set(("verbunden: " + ", ".join(mods) if mods else "kein Modul verbunden")
                                  + ("\nSitzung " + "; ".join(sess) if sess else ""))
        self.video_status()
        srv, _, url = self.remote or (None, None, None)
        if srv is not None:
            s = srv.snapshot()
            op = s["operator_way"] or "keiner"
            mode = "STEUERT ARM" if getattr(srv, "live", False) else "TROCKENLAUF"
            self.net_server.set(f"Remote {mode} · WLAN {url} ({s['wlan']}) · Internet LiveKit: {s['livekit']} "
                                f"({s['internet']}){getattr(self, 'remote_note', '')} · Bediener: {op}")
            age = "–" if s["pose_age_ms"] is None else f"{s['pose_age_ms']:.0f} ms"
            self.net_down.set(f"Download (Steuerdaten → Roboter): {s['pose_hz']:5.1f} Posen/s · {s['rx_kbs']:5.1f} kB/s · "
                              f"groesste Luecke {s['gap_ms']:4.0f} ms · letzte Pose vor {age}")
            self.net_up.set(f"Upload (Roboter → Bediener): {s['state_hz']:5.1f} Nachr./s · {s['tx_kbs']:5.1f} kB/s "
                            f"(Video siehe unten)")
            st, last = s["state"], s["last_pose"]
            clutch = "Kupplung GEDRUECKT" if last and last.get("clutch") else "Kupplung los"
            grip = f"Greifer {last.get('grip', 0):.2f}" if last else ""
            reason = f" · Grund {st['reason']}" if st.get("reason") else ""
            for p in self.panels.values():
                if p.source.get() == "remote":
                    verb = "faehrt zu" if p.running and p.mode == "remote" else "wuerde fahren zu"
                    p.remote_info.set(f"Remote: {clutch} {grip}{reason}\n{verb} {st['joints']} · Spitze {st['ee']}")
        self.root.after(1000, self.update_network)

    # --- Neu starten (z. B. nach einer Aenderung am Programm) ---
    def check_update(self):
        if code_stamp() != self.code_stamp:
            self.update_note.set("Neue Programmversion gespeichert → neu starten")
        self.root.after(3000, self.check_update)

    def restart(self, sim=None):
        """Neu starten; sim=True/False wechselt zwischen Simulation und echten Armen (sonst bleibt der Modus)."""
        sim = SIM if sim is None else sim
        if self.process is not None:
            messagebox.showinfo("Neu starten", "Erst alle Arme ablegen (Stop), dann neu starten.", parent=self.root)
            return
        # Trainings laufen im eigenen Trainings-Dienst weiter (ki/trainer.py) - kein Grund zu warten
        start_detached(["--after", str(os.getpid())] + (["--sim"] if sim else []))
        self.close()

    def sim_umschalten(self):
        if SIM:
            frage = "Simulation beenden und mit den echten Armen neu starten?"
        else:
            frage = ("Harness im Simulationsmodus neu starten?" + chr(10) * 2 + "Kein echter Arm bewegt sich, kein COM-Port wird "
                     "geöffnet. Zurück geht es mit demselben Knopf.")
        if messagebox.askyesno("Simulation", frage, parent=self.root):
            self.restart(sim=not SIM)

    # --- Schliessen ---
    def close(self):
        self.closing = True
        self.queued = []
        if self.process is not None:
            for key in self.running():
                self.panels[key].status.set("Fenster schliesst · Ablage abwarten")
            if not self.send("quit"):
                self.root.destroy()
        else:
            self.root.destroy()

    def _shutdown(self):
        self.closing = True
        if self.volt is not None:
            self.volt[1].stop()     # Ports freigeben, damit ein Neustart sie sofort bekommt
        if self.calib is not None:
            self.calib.release()
        if self.streamer is not None:
            self.streamer.stop()
        self.cams.stop()
        if self.remote and self.remote[1]:
            self.remote[1]()


class AccessDialog:
    """Fernzugriff eines Arms verwalten: Limit, Geraete entfernen, Zeit verlaengern, Geraete merken."""
    def __init__(self, lab, key):
        self.lab, self.key = lab, key
        self.srv = lab.remote[0] if lab.remote else None
        if self.srv is None:
            messagebox.showinfo("Fernzugriff", "Remote-Server laeuft nicht.", parent=lab.root)
            return
        w = self.win = tk.Toplevel(lab.root)
        w.title(f"Fernzugriff · {lab.panels[key].label}")
        w.geometry("640x420")
        top = ttk.Frame(w, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Hoechstdauer pro Bediener (Minuten):").pack(side="left")
        self.max_min = tk.StringVar(value=str(self.srv.lane.desk.max_min))
        ttk.Spinbox(top, from_=1, to=600, width=6, textvariable=self.max_min).pack(side="left", padx=6)
        ttk.Button(top, text="Uebernehmen", command=self.set_max).pack(side="left")
        self.info = tk.StringVar()
        ttk.Label(w, textvariable=self.info, padding=(10, 0), font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.tree = ttk.Treeview(w, columns=("name", "rolle", "limit", "gemerkt"), show="headings", height=8)
        for c, t, wd in (("name", "Geraet", 220), ("rolle", "Rolle", 150), ("limit", "Limit (min)", 90),
                         ("gemerkt", "gemerkt", 80)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wd)
        self.tree.pack(fill="both", expand=True, padx=10, pady=6)
        row = ttk.Frame(w, padding=10)
        row.pack(fill="x")
        ttk.Button(row, text="✖ Entfernen (kicken)", command=self.kick).pack(side="left")
        ttk.Label(row, text="  Verlaengern um").pack(side="left")
        self.ext = tk.StringVar(value="15")
        ttk.Spinbox(row, from_=1, to=600, width=5, textvariable=self.ext).pack(side="left", padx=4)
        ttk.Button(row, text="min", command=self.extend).pack(side="left")
        ttk.Label(row, text="  Merken mit Limit").pack(side="left")
        self.mem = tk.StringVar(value="120")
        ttk.Spinbox(row, from_=1, to=1440, width=5, textvariable=self.mem).pack(side="left", padx=4)
        ttk.Button(row, text="min", command=self.remember).pack(side="left")
        self.rows = {}
        self.refresh()

    def _sel(self):
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def set_max(self):
        try:
            self.srv.set_max_min(int(self.max_min.get()))
        except ValueError:
            pass

    def kick(self):
        cid = self._sel()
        if cid is not None:
            self.srv.admin(lambda d, t: d.kick(cid, t), arm=self.key)

    def extend(self):
        try:
            m = float(self.ext.get())
        except ValueError:
            return
        self.srv.admin(lambda d, t: d.extend(m), arm=self.key)

    def remember(self):
        cid = self._sel()
        try:
            m = int(self.mem.get())
        except ValueError:
            return
        if cid is not None:
            self.srv.admin(lambda d, t: d.remember(cid, m), arm=self.key)

    def refresh(self):
        if not self.win.winfo_exists():
            return
        try:
            v = self.srv.control_overview().get(self.key)
        except RuntimeError:
            v = None
        if v is not None:
            left = v["left_s"] or 0
            self.info.set((f"Bediener: {v['holder_name']} · noch {left // 60}:{left % 60:02d} min"
                           if v["holder"] is not None else "Niemand steuert")
                          + (" · ⚠ bittet um Verlaengerung" if v.get("extend_wanted") else ""))
            sel = self._sel()
            self.tree.delete(*self.tree.get_children())
            self.rows = {}
            for c in v["clients"]:
                iid = self.tree.insert("", "end", values=(c["name"], c["role"], c["limit"],
                                                          "ja" if c["remembered"] else ""))
                self.rows[iid] = c["cid"]
                if c["cid"] == sel:
                    self.tree.selection_set(iid)
        self.win.after(1000, self.refresh)


class ControlView:
    """Steuermodus: eigenes, maximiertes Fenster mit den beiden Kameras eines Arms gross nebeneinander,
    dazu Status, Leader/Remote-Uebernahme und Stop. Bedient dieselben Funktionen wie die Arm-Spalte."""
    def __init__(self, lab, key):
        self.lab, self.key = lab, key
        panel = self.panel = lab.panels[key]
        old = getattr(panel, "control_view", None)
        if old is not None and old.win.winfo_exists():
            old.win.lift()
            old.win.focus_force()
            return
        panel.control_view = self
        self.win = tk.Toplevel(lab.root)
        self.win.title(f"Steuermodus · {panel.label}")
        self.win.configure(background="#111")
        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.geometry(f"{lab.root.winfo_screenwidth()}x{lab.root.winfo_screenheight()}+0+0")
        head = tk.Frame(self.win, background="#111")
        head.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(head, text=panel.label, font=("Segoe UI", 20, "bold"), foreground="white",
                 background="#111").pack(side="left")
        self.badge = tk.Label(head, text="", font=("Segoe UI", 11, "bold"), padx=8, pady=2)
        self.badge.pack(side="left", padx=12)
        tk.Label(head, textvariable=panel.status, font=("Segoe UI", 12, "bold"), foreground="#ddd",
                 background="#111").pack(side="left", padx=8)
        tk.Button(head, text="✕ Steuermodus verlassen (Esc)", font=("Segoe UI", 10),
                  command=self.close).pack(side="right")
        self.stop_button = tk.Button(head, text="■ Stop · ablegen", font=("Segoe UI", 13, "bold"),
                                     background="#b3261e", foreground="white", activebackground="#8c1d17",
                                     padx=14, command=lambda: lab.stop(key))
        self.stop_button.pack(side="right", padx=(0, 16))
        self.take_button = tk.Button(head, text="", font=("Segoe UI", 12, "bold"), padx=12,
                                     command=lambda: panel.take_button.invoke())
        self.take_button.pack(side="right", padx=(0, 10))
        self._build_record_bar()
        self.body = tk.Frame(self.win, background="#111")
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.views = []
        cols = max(1, len(panel.slots))
        for n, slot in enumerate(panel.slots):
            self.body.columnconfigure(n, weight=1, uniform="cam")
            name = lab.cams.manager.slots[slot]["name"]
            tk.Label(self.body, text=f"{slot + 1} · {name}", font=("Segoe UI", 12, "bold"), foreground="white",
                     background="#111").grid(row=0, column=n, sticky="w", padx=4)
            img = tk.Label(self.body, text="suche ...", background="#000", foreground="#ddd",
                           font=("Segoe UI", 14, "bold"))
            img.grid(row=1, column=n, sticky="nsew", padx=4, pady=(2, 0))
            self.views.append(lab.cams.add_view(slot, img, (0, 0)))
        self.body.rowconfigure(1, weight=1)
        self.cols = cols
        self.body.bind("<Configure>", self._resize)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Destroy>", lambda e: self._forget() if e.widget is self.win else None)
        self._sync()

    def _resize(self, event):
        # Platz je Kamera: Spaltenbreite x (Hoehe minus Namenszeile); Bild wird darin eingepasst
        size = ((event.width - 8 * self.cols) // self.cols, event.height - 34)
        for vid in self.views:
            if vid in self.lab.cams.views:
                self.lab.cams.views[vid]["size"] = size

    def _sync(self):
        """Badge und Knoepfe spiegeln die Arm-Spalte, damit beide Ansichten immer dasselbe zeigen."""
        if not self.win.winfo_exists():
            return
        p = self.panel
        self.badge.configure(text=p.badge.cget("text"), background=p.badge.cget("background"),
                             foreground=p.badge.cget("foreground"))
        self.take_button.configure(text=p.take_button.cget("text"),
                                   state=str(p.take_button.cget("state")))
        self.stop_button.configure(state=str(p.stop_button.cget("state")))
        self._sync_record()
        self.win.after(200, self._sync)

    # --- KI-Aufnahme ---
    def _build_record_bar(self):
        bar = tk.Frame(self.win, background="#1d1d1d")
        bar.pack(fill="x", padx=16, pady=(0, 8))
        style = {"background": "#1d1d1d", "foreground": "#ddd", "font": ("Segoe UI", 10)}
        tk.Label(bar, text="KI-Aufnahme", font=("Segoe UI", 11, "bold"), foreground="white",
                 background="#1d1d1d").pack(side="left", padx=(8, 12), pady=6)
        tk.Label(bar, text="Datensatz:", **style).pack(side="left")
        from ki import history, episodes as ep_mod
        hist = history.load()
        sets = ep_mod.datasets()
        self.rec_name = tk.StringVar(value=getattr(self.panel, "rec_name", ""))
        self.name_box = ttk.Combobox(bar, textvariable=self.rec_name, width=20, font=("Segoe UI", 10),
                                     values=history.options("datensatz", [d.meta.get("name") for d in sets]))
        self.name_box.pack(side="left", padx=(4, 2))
        self._last_button(bar, self.rec_name, "datensatz").pack(side="left", padx=(0, 10))
        tk.Label(bar, text="Aufgabe:", **style).pack(side="left")
        self.rec_task = tk.StringVar(value=getattr(self.panel, "rec_task", ""))
        self.task_box = ttk.Combobox(bar, textvariable=self.rec_task, width=36, font=("Segoe UI", 10),
                                     values=history.options("aufgabe", [d.meta.get("task") for d in sets]))
        self.task_box.pack(side="left", padx=(4, 2))
        self._last_button(bar, self.rec_task, "aufgabe").pack(side="left", padx=(0, 10))
        # Datensatz aus der Liste gewaehlt -> passende Aufgabe dazu eintragen
        self.name_box.bind("<<ComboboxSelected>>", lambda e: self._task_for_dataset())
        btn = {"font": ("Segoe UI", 10, "bold"), "padx": 10}
        self.rec_start = tk.Button(bar, text="● Start", background="#b3261e", foreground="white",
                                   command=self._rec_start, **btn)
        self.rec_start.pack(side="left", padx=2)
        self.rec_stop = tk.Button(bar, text="■ Stop", command=self._rec_stop, **btn)
        self.rec_stop.pack(side="left", padx=2)
        self.rec_keep = tk.Button(bar, text="✔ Behalten", background="#1f7a3a", foreground="white",
                                  command=lambda: self._rec_decide(True), **btn)
        self.rec_keep.pack(side="left", padx=2)
        self.rec_drop = tk.Button(bar, text="✖ Verwerfen", command=lambda: self._rec_decide(False), **btn)
        self.rec_drop.pack(side="left", padx=2)
        self.rec_info = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.rec_info, font=("Consolas", 10, "bold"), foreground="#f2c14e",
                 background="#1d1d1d").pack(side="left", padx=10)
        srow = tk.Frame(self.win, background="#1d1d1d")
        srow.pack(fill="x", padx=16, pady=(0, 8), after=bar)
        tk.Label(srow, text="Startpose", font=("Segoe UI", 10, "bold"), foreground="white",
                 background="#1d1d1d").pack(side="left", padx=(8, 8), pady=4)
        self.start_info = tk.StringVar(value="")
        self.start_label = tk.Label(srow, textvariable=self.start_info, font=("Consolas", 10, "bold"),
                                    foreground="#ddd", background="#1d1d1d")
        self.start_label.pack(side="left")
        tk.Button(srow, text="Aktuelle Stellung als Startpose festlegen", font=("Segoe UI", 9),
                  command=self._set_start).pack(side="right", padx=8, pady=3)
        # Aufnahmeplan: fuehrt durch Runden und Griffe (planui.PlanPanel ersetzt dann die Kamera-Ansicht)
        from aufnahme import plan as plan_mod
        self.plan_defs = plan_mod.definitions()
        self.plan_choice = tk.StringVar(value="(ohne Plan)")
        tk.Label(srow, text="Aufnahmeplan:", font=("Segoe UI", 10, "bold"), foreground="white",
                 background="#1d1d1d").pack(side="right", padx=(8, 4))
        box = ttk.Combobox(srow, textvariable=self.plan_choice, state="readonly", width=28,
                           values=["(ohne Plan)"] + [name for _, name in self.plan_defs])
        box.pack(side="right")
        box.bind("<<ComboboxSelected>>", lambda e: self._choose_plan())
        self.plan_panel = None
        self.win.bind("<F5>", lambda e: self._rec_start())     # Tasten: Hand bleibt am Leader
        self.win.bind("<F6>", lambda e: self._rec_stop())
        self.win.bind("<F7>", lambda e: self._rec_decide(True))
        self.win.bind("<F8>", lambda e: self._rec_decide(False))
        self.win.bind("<F3>", lambda e: self.plan_panel and self.plan_panel.key_ready())      # Aufnahmeplan
        self.win.bind("<F4>", lambda e: self.plan_panel and self.plan_panel.not_graspable())
        for n in range(1, 10):                                   # Lage beim spezifischen Griff (Ziffernblock)
            for k in (str(n), f"KP_{n}"):
                self.win.bind(f"<KeyPress-{k}>", lambda e, n=n: self._plan_digit(e, n))

    def _last_button(self, parent, var, key):
        """Kleiner runder Knopf: setzt den zuletzt benutzten Wert ein."""
        c = tk.Canvas(parent, width=22, height=22, background="#1d1d1d", highlightthickness=0, cursor="hand2")
        c.create_oval(2, 2, 20, 20, fill="#3a3a3a", outline="#888", tags="b")
        c.create_text(11, 11, text="↺", fill="white", font=("Segoe UI", 9, "bold"), tags="b")
        def use(_e=None):
            from ki import history
            last = history.load()[key]
            if last:
                var.set(last[0])
                if key == "datensatz":
                    self._task_for_dataset()
        c.tag_bind("b", "<Button-1>", use)
        return c

    def _task_for_dataset(self):
        from ki import episodes as ep_mod
        name = self.rec_name.get().strip()
        d = next((d for d in ep_mod.datasets() if d.meta.get("name") == name or d.name == name), None)
        if d is not None and d.meta.get("task"):
            self.rec_task.set(d.meta["task"])

    def _choose_plan(self):
        """Plan an: Plan-Ansicht statt der Kamera-Kacheln. Plan aus: zurueck zur normalen Ansicht."""
        name = self.plan_choice.get()
        if self.plan_panel is not None:
            self.plan_panel.destroy()
            self.plan_panel = None
        plan_id = next((pid for pid, n in self.plan_defs if n == name), None)
        if plan_id is None:
            self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            return
        import planui
        self.body.pack_forget()
        try:
            self.plan_panel = planui.PlanPanel(self.win, self, plan_id)
        except Exception as exc:
            messagebox.showerror("Aufnahmeplan", f"Plan laesst sich nicht laden: {exc}", parent=self.win)
            self.plan_choice.set("(ohne Plan)")
            self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
            return
        self.plan_panel.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    def _plan_digit(self, event, n):
        if self.plan_panel is not None and not isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Spinbox, ttk.Combobox)):
            self.plan_panel.key_lage(n)

    def _rec_start(self):
        if self.plan_panel is not None:
            self.plan_panel.key_start()
            return
        from ki import history
        self.panel.rec_name, self.panel.rec_task = self.rec_name.get(), self.rec_task.get()
        history.remember(self.rec_name.get(), self.rec_task.get())
        self.name_box["values"] = history.options("datensatz")
        self.task_box["values"] = history.options("aufgabe")
        try:
            self.dataset = self.lab.record_start(self.key, self.rec_name.get(), self.rec_task.get())
        except (RuntimeError, ValueError) as exc:
            self.rec_info.set(str(exc))

    def _rec_stop(self):
        if self.plan_panel is not None:
            self.plan_panel.key_stop()
            return
        self.lab.record_stop(self.key)

    def _rec_decide(self, keep):
        if self.plan_panel is not None:
            self.plan_panel.decide(keep)
            return
        self.lab.record_decide(self.key, keep)

    START_TOL_DEG = 4.0             # so nah muss jedes Gelenk an der Startpose sein (Greifer: 10 Grad)

    def _set_start(self):
        from ki import poses
        state = self.lab.arm_state(self.key)
        if state is None:
            messagebox.showinfo("Startpose", "Keine aktuelle Stellung: der Arm muss dem Leader folgen.", parent=self.win)
            return
        if messagebox.askyesno("Startpose", f"Aktuelle Stellung von {self.panel.label} als Startpose speichern?\n\n"
                               "Neue Episoden sollten danach von hier beginnen. Aeltere Episoden mit anderer "
                               "Startpose am besten im VLA-Studio loeschen.", parent=self.win):
            poses.save_pose(self.key, "_start", state)

    def _sync_start(self):
        from ki import poses
        start = poses.load().get(self.key, {}).get("_start")
        state = self.lab.arm_state(self.key)
        if start is None:
            self.start_info.set("noch keine festgelegt")
            self.start_label.configure(foreground="#ddd")
            return
        if state is None:
            self.start_info.set("Abstand erst sichtbar, wenn der Arm dem Leader folgt")
            self.start_label.configure(foreground="#ddd")
            return
        deg = [abs(a - b) * 360 / 4096 for a, b in zip(state, start)]
        ok = all(d <= self.START_TOL_DEG for d in deg[:5]) and deg[5] <= 10
        names = ("Bas", "Sch", "Ell", "HdB", "HdD", "Gr")
        self.start_info.set(("✔ in Startpose  " if ok else "✖ nicht in Startpose  ")
                            + "  ".join(f"{n} {d:4.1f}°" for n, d in zip(names, deg)))
        self.start_label.configure(foreground="#3fbf6a" if ok else "#f2c14e")

    def _sync_record(self):
        self._sync_start()
        rec = self.lab.recorders.get(self.key)
        state = rec.state if rec else "bereit"
        following = self.panel.running and self.panel.mode == "lokal" and self.panel.status.get().startswith("Folgt")
        self.rec_start.configure(state="normal" if state == "bereit" and following else "disabled")
        self.rec_stop.configure(state="normal" if state == "nimmt_auf" else "disabled")
        for b in (self.rec_keep, self.rec_drop):
            b.configure(state="normal" if state == "wartet_entscheidung" else "disabled")
        ds = getattr(self, "dataset", None)
        count = f"{len(ds.episodes())} Episoden" if ds is not None else ""
        if state == "nimmt_auf":
            self.rec_info.set(f"● AUFNAHME {rec.frames / 30:5.1f} s · {count}  (F6 = Stop)")
        elif state == "wartet_entscheidung":
            self.rec_info.set(f"{rec.frames / 30:.1f} s aufgenommen · F7 behalten / F8 verwerfen")
        elif not self.rec_info.get().startswith(("Aufnahme geht", "Bitte", "Datensatz")):
            self.rec_info.set(count + ("  (F5 = Start)" if following else "  · Aufnahme nur waehrend der Arm dem Leader folgt"))

    def _forget(self):
        for vid in self.views:
            self.lab.cams.remove_view(vid)
        self.views = []
        if getattr(self.panel, "control_view", None) is self:
            self.panel.control_view = None

    def close(self):
        """Nur die Ansicht schliessen; ein laufender Arm laeuft unveraendert weiter."""
        self._forget()
        self.win.destroy()


class AreaWindow:
    """Arbeitsbereich je Arm in 3D: echtes SO-101-Modell (live, wenn der Arm laeuft), Waende an den Kanten des
    Plans, Hindernisse als Koerper. Maus ziehen = drehen, Rad = Zoom. Durchsetzung im Worker (arbeitsbereich.Fence)."""
    W, H = 760, 560
    WALL_H = 0.35                     # gezeichnete Wandhoehe (gedacht: unendlich)
    COLORS = {"base_link": "#8a8f98", "shoulder_link": "#c9ccd2", "upper_arm_link": "#e9e9ec", "lower_arm_link": "#e9e9ec",
              "wrist_link": "#d8dadf", "gripper_link": "#f2f2f4", "moving_jaw_so101_v1_link": "#f2f2f4"}

    def __init__(self, lab):
        import arbeitsbereich, stopcal
        import numpy as np
        self.A, self.K, self.np, self.lab = arbeitsbereich, stopcal, np, lab
        self.win = tk.Toplevel(lab.root)
        self.win.title("Arbeitsbereich 3D · Waende je Arm")
        self.win.geometry("1080x640")
        top = ttk.Frame(self.win, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Arm:").pack(side="left")
        self.arm = tk.StringVar(value=next(iter(lab.panels)))
        for key, p in lab.panels.items():
            ttk.Radiobutton(top, text=p.label, value=key, variable=self.arm, command=self.load).pack(side="left", padx=6)
        self.both = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="beide Arme zeigen", variable=self.both, command=self.toggle_both).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="SVG / DXF laden ...", command=self.import_file).pack(side="left", padx=(20, 6))
        ttk.Button(top, text="Speichern", command=self.save).pack(side="left")
        ttk.Button(top, text="3D", command=lambda: self.set_view(-30, 35)).pack(side="left", padx=(20, 2))
        ttk.Button(top, text="Von oben", command=lambda: self.set_view(0, 89.9)).pack(side="left", padx=2)
        ttk.Button(top, text="Von der Seite", command=lambda: self.set_view(90, 0.1)).pack(side="left", padx=2)
        body = ttk.Frame(self.win, padding=(12, 0))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, width=self.W, height=self.H, background="#f7f7f5", highlightthickness=1,
                                highlightbackground="#bbb")
        self.canvas.pack(side="left")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<MouseWheel>", self._wheel)
        side = ttk.Frame(body, padding=(14, 0))
        side.pack(side="left", fill="y")
        self.vars = {}
        for key, label in (("x", "Basis x [m] (entlang der Kante)"), ("y", "Basis y [m] (Mitte der Basis)"),
                           ("basis_grad", "Basis zeigt nach [Grad]"), ("richtung_grad", "Arm-Mitte zeigt nach [Grad]"),
                           ("drehsinn", "Drehsinn (+1 / -1)"), ("abstand_cm", "Abstand zur Wand [cm]")):
            ttk.Label(side, text=label).pack(anchor="w", pady=(5, 0))
            v = tk.StringVar()
            e = ttk.Entry(side, textvariable=v, width=12)
            e.pack(anchor="w")
            e.bind("<Return>", lambda _e: self.apply_fields())
            self.vars[key] = v
        ttk.Button(side, text="Basis buendig an Tischkante (y = 0)", command=self.flush_base).pack(anchor="w", pady=(8, 0))
        self.active = tk.BooleanVar()
        ttk.Checkbutton(side, text="Waende aktiv (speichert sofort)", variable=self.active,
                        command=self.save).pack(anchor="w", pady=(10, 0))
        ttk.Button(side, text="Uebernehmen und speichern", command=self.save).pack(anchor="w", pady=(6, 0))
        self.status = tk.StringVar()
        ttk.Label(side, textvariable=self.status, wraplength=270, justify="left").pack(anchor="w", pady=(10, 0))
        ttk.Label(side, wraplength=270, justify="left", foreground="#555", text=(
            "Gruen: erlaubter Bereich mit Waenden, rot: Hindernis, roter Punkt: engste Stelle. Der Arm ist das echte "
            "SO-101-Modell, live wenn er laeuft (sonst Ablage-Stellung). In SVG/DXF ist die groesste Flaeche der "
            "erlaubte Bereich, alle anderen sind Hindernisse.")).pack(anchor="w", pady=(10, 0))
        self.az, self.el, self.zoom = -30.0, 35.0, 1.0
        self.karte = None
        self.load()
        self.tick()

    # --- Ansicht ---
    def toggle_both(self):
        self.zoom = 0.55 if self.both.get() else 1.0
        self.draw()

    def set_view(self, az, el):
        self.az, self.el = az, el
        self.draw()

    def _press(self, e):
        self._drag_from = (e.x, e.y, self.az, self.el)

    def _drag(self, e):
        x0, y0, az, el = self._drag_from
        self.az = az - (e.x - x0) * 0.4
        self.el = max(0.1, min(89.9, el + (e.y - y0) * 0.4))
        self.draw()

    def _wheel(self, e):
        self.zoom = max(0.3, min(6.0, self.zoom * (1.1 if e.delta > 0 else 1 / 1.1)))
        self.draw()

    def _projector(self):
        np = self.np
        bases = [k["basis"] for k in self.shown()]
        center = np.array([np.mean([b["x"] for b in bases]), np.mean([b["y"] for b in bases]), 0.12])
        a, el = math.radians(self.az), math.radians(self.el)
        right = np.array([math.cos(a), math.sin(a), 0.0])
        fwd = np.array([-math.sin(a), math.cos(a), 0.0])
        up = np.array([fwd[0] * math.sin(el), fwd[1] * math.sin(el), math.cos(el)])
        depth = np.cross(up, right)
        sc = 900 * self.zoom

        def proj(P):
            Q = np.atleast_2d(P) - center
            return (self.W / 2 + Q @ right * sc, self.H / 2 - Q @ up * sc, Q @ depth)
        return proj, depth

    # --- Daten ---
    def shown(self):
        """Karten, die gezeichnet werden: die bearbeitete und (bei 'beide') die der anderen Arme."""
        out = [self.karte]
        if self.both.get():
            for key in self.lab.panels:
                if key != self.arm.get():
                    k = self.A.load(key)
                    if k:
                        out.append(k)
        return out

    def base_center(self, key):
        d = self.K.load(self.K.stops_path(key)) or {}
        j = (d.get("joints") or {}).get("1")
        return int(round((j["lo"] + j["hi"]) / 2)) if j else 2047

    def rest_pose(self, key):
        try:
            cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        rp = (cfg.get(key) or {}).get("rest_pose")
        if rp:
            return {int(k): v for k, v in rp.items()}
        return {1: self.base_center(key), 2: 846, 3: 3095, 4: 902, 5: 2047, 6: 1418}

    def load(self):
        key = self.arm.get()
        self.karte = self.A.load(key) or self.A.from_polygons(key, [])
        b = self.karte["basis"]
        b.setdefault("basis_grad", 90)
        b.setdefault("drehsinn", -1)
        for k in ("x", "y", "basis_grad", "richtung_grad", "drehsinn"):
            self.vars[k].set(str(b.get(k, "")))
        self.vars["abstand_cm"].set(f"{self.karte.get('abstand_m', self.A.DEFAULT_ABSTAND) * 100:.1f}")
        self.active.set(bool(self.karte.get("aktiv")))
        self.draw()

    def apply_fields(self):
        try:
            b = self.karte["basis"]
            for k in ("x", "y", "basis_grad", "richtung_grad"):
                b[k] = float(self.vars[k].get().replace(",", "."))
            b["drehsinn"] = 1 if float(self.vars["drehsinn"].get()) >= 0 else -1
            self.karte["abstand_m"] = max(0.0, float(self.vars["abstand_cm"].get().replace(",", ".")) / 100)
        except ValueError:
            messagebox.showerror("Arbeitsbereich", "Bitte Zahlen eintragen.", parent=self.win)
            return False
        self.karte["aktiv"] = bool(self.active.get())
        self.draw()
        return True

    def flush_base(self):
        """Hintere Kante der Basis (aus dem 3D-Modell) genau auf die Tischkante y = 0."""
        self.vars["basis_grad"].set("90")
        self.vars["y"].set(f"{self.A.base_back_offset():.4f}")
        self.apply_fields()

    def import_file(self):
        from tkinter import filedialog
        fn = filedialog.askopenfilename(parent=self.win, title="Plan laden",
                                        filetypes=[("Vektor / CAD", "*.svg *.dxf"), ("Alle", "*.*")])
        if not fn:
            return
        try:
            text = open(fn, encoding="utf-8", errors="replace").read()
            polys = self.A.import_dxf(text) if fn.lower().endswith(".dxf") else self.A.import_svg(text)
        except Exception as exc:
            messagebox.showerror("Arbeitsbereich", f"Datei nicht lesbar: {exc}", parent=self.win)
            return
        if not polys:
            messagebox.showerror("Arbeitsbereich", "Keine geschlossenen Flaechen gefunden.", parent=self.win)
            return
        old = self.karte or {}
        self.karte = self.A.from_polygons(self.arm.get(), polys, basis=old.get("basis"),
                                          abstand=old.get("abstand_m", self.A.DEFAULT_ABSTAND))
        self.karte["aktiv"] = False
        self.active.set(False)
        self.status.set(f"{len(polys)} Flaechen geladen. Basis-Lage pruefen, dann 'Waende aktiv' und Speichern.")
        self.draw()

    def save(self):
        if not self.apply_fields():
            return
        if self.karte.get("aktiv") and not self.karte.get("erlaubt"):
            messagebox.showerror("Arbeitsbereich", "Ohne erlaubte Flaeche kann nichts aktiv sein.", parent=self.win)
            return
        self.A.save(self.karte, self.arm.get())
        self.status.set("Gespeichert" + (" - Waende AKTIV" if self.karte.get("aktiv") else " - Waende aus") +
                        ". Ein laufender Arm uebernimmt es innerhalb von 1 s.")

    # --- Zeichnen ---
    def draw(self):
        np, c, A = self.np, self.canvas, self.A
        c.delete("all")
        if not self.karte:
            return
        A.forget(self.karte)
        proj, depth = self._projector()
        polys = []                                         # (tiefe, punkte, fuellung, rand)

        def prism(poly, lo, hi, fill, line):
            P = np.array(poly, dtype=float)
            n = len(P)
            bot = np.column_stack([P, np.full(n, lo)])
            topz = np.column_stack([P, np.full(n, hi)])
            for k in range(n):
                quad = np.vstack([bot[k], bot[(k + 1) % n], topz[(k + 1) % n], topz[k]])
                x, y, d = proj(quad)
                polys.append((d.mean(), [v for pt in zip(x, y) for v in pt], "", line))   # Seiten durchsichtig
            x, y, d = proj(topz)
            polys.append((d.mean(), [v for pt in zip(x, y) for v in pt], fill, line))
        main = self.karte
        for poly in main.get("erlaubt") or []:
            x, y, _ = proj(np.column_stack([np.array(poly, float), np.zeros(len(poly))]))
            c.create_polygon(*[v for pt in zip(x, y) for v in pt], fill="#e3f2e1", outline="#3a8f3a", width=2)
            P = np.array(poly, float)
            for k in range(len(P)):
                quad = np.array([[*P[k], 0], [*P[(k + 1) % len(P)], 0], [*P[(k + 1) % len(P)], self.WALL_H], [*P[k], self.WALL_H]])
                x, y, d = proj(quad)
                polys.append((d.mean(), [v for pt in zip(x, y) for v in pt], "", "#7fbf7f"))
        for poly, lo, hi in A._obstacles(main):
            prism(poly, max(0.0, lo), hi if hi is not None else self.WALL_H, "#f3c4c4", "#b33")
        marks, lines = [], []
        for karte in self.shown():
            key = karte.get("arm") or self.arm.get()
            center = self.base_center(key)
            live = self.lab.live_pose.get(key)
            fresh = live is not None and time.monotonic() - live[1] < 1.0
            pose = dict(live[0]) if fresh else self.rest_pose(key)
            karte["_grip"] = A.grip_range(karte)
            for name, verts, faces in A.model().teile(A.pan_fk(karte, pose, center), center, karte["_grip"]):
                W = A.to_plan(karte, verts)
                x, y, d = proj(W)
                base = name.split("#")[0]
                col = ("#2a2a2a" if name.endswith("#linse") else "#3f6f3f" if name.endswith("#platine")
                       else "#d9822b" if "camera_mount" in base else self.COLORS.get(base, "#dddddd"))
                F = self.np.asarray(faces)
                n = np.cross(W[F[:, 1]] - W[F[:, 0]], W[F[:, 2]] - W[F[:, 0]])
                vis = n @ depth <= 0                       # Rueckseiten weglassen
                F, n = F[vis], n[vis]
                shade = 0.55 + 0.45 * np.abs(n[:, 2]) / (np.linalg.norm(n, axis=1) + 1e-12)
                base_rgb = np.array([int(col[i:i + 2], 16) for i in (1, 3, 5)])
                rgb = (shade[:, None] * base_rgb).astype(int)
                dm = d[F].mean(axis=1)
                xy = np.stack([x[F], y[F]], axis=2).reshape(len(F), 6)
                for k in range(len(F)):
                    polys.append((dm[k], xy[k].tolist(), "#%02x%02x%02x" % tuple(rgb[k]), ""))
            if karte is main:
                d, i = A.clearance(karte, pose, center, exact=True)
                pts = A.arm_points(karte, pose, center)
                k = int(np.argmin(A.clearance_points(karte, pts)))
                marks.append(proj(pts[k]))
                margin = karte.get("abstand_m", A.DEFAULT_ABSTAND)
                state = "live" if fresh else "Ablage-Stellung (Arm laeuft nicht)"
                if karte.get("erlaubt"):
                    bc = A.base_clearance(karte)
                    lines.append(f"Arm ({state}): engste Stelle {d * 100:.1f} cm" +
                                 ("  ✔" if d >= margin else "  ✖ zu nah / dahinter") +
                                 f"\nBasis: {'steht im Bereich' if bc >= -0.002 else f'ragt {-bc * 100:.1f} cm ueber eine Wand'}")
        polys.sort(key=lambda p: -p[0])
        for _, pts, fill, line in polys:
            c.create_polygon(*pts, fill=fill, outline=line)
        for x, y, _ in marks:
            c.create_oval(x[0] - 5, y[0] - 5, x[0] + 5, y[0] + 5, fill="#d22", outline="")
        if lines:
            self.status.set("\n".join(lines))

    def tick(self):
        if not self.win.winfo_exists():
            return
        keys = list(self.lab.panels) if self.both.get() else [self.arm.get()]
        now = time.monotonic()
        if any(self.lab.live_pose.get(k) is not None and now - self.lab.live_pose[k][1] < 1.5 for k in keys):
            self.draw()
        self.win.after(60, self.tick)


class CalibWizard:
    """Anschlag-Kalibrierung Schritt fuer Schritt. Liest nur (Position, Grenzen, Offset, Drehmoment-Schalter).
    Einzige Ausnahme: 'Nullpunkt setzen' fuer die Handgelenk-Drehung schreibt nach Rueckfrage Offset und Grenzen
    dieses einen Gelenks ins EEPROM (vorher Sicherung aller Werte).
    Ergebnis: calibration/stops_<arm>.json; Zuordnung erst nach 'Aktivieren'."""
    TICK_MS = 20

    def __init__(self, lab, opener=None):
        import stopcal, so101
        self.K, self.so101 = stopcal, so101
        self.lab = lab
        self.opener = opener or (lambda arm: so101.Arm(arm))
        self.arm = None             # offene Verbindung
        self.arm_key = None
        self.names = {"leader": "Leader", **{k: p.label for k, p in lab.panels.items()}}
        self.win = tk.Toplevel(lab.root)
        self.win.title("Arme kalibrieren · Anschlaege")
        self.win.geometry("760x640")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        pad = {"padx": 20}
        ttk.Label(self.win, text="Arme kalibrieren", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(14, 2), **pad)
        ttk.Label(self.win, wraplength=700, justify="left", text=(
            "Jedes Gelenk wird von Hand bis zum Anschlag gedrueckt, zweimal hin und her. Kein Motor bewegt sich, "
            "es wird nur gelesen. Die Messung startet von selbst, sobald du am Anschlag ruhig haeltst.")).pack(anchor="w", **pad)
        row = ttk.Frame(self.win)
        row.pack(fill="x", pady=10, **pad)
        ttk.Label(row, text="Welcher Arm:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.choice = tk.StringVar(value="leader")
        for key, name in self.names.items():
            ttk.Radiobutton(row, text=name, value=key, variable=self.choice).pack(side="left", padx=(10, 0))
        self.start_button = ttk.Button(row, text="Messung starten", command=self.start)
        self.start_button.pack(side="left", padx=(16, 0))
        self.title = tk.StringVar(value="")
        ttk.Label(self.win, textvariable=self.title, font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(6, 0), **pad)
        self.hint = tk.StringVar(value="Arm waehlen und 'Messung starten'. Der Arm liegt in der Ablage, ohne Kraft.")
        ttk.Label(self.win, textvariable=self.hint, font=("Segoe UI", 12), wraplength=700, justify="left").pack(anchor="w", pady=(4, 0), **pad)
        self.step = tk.StringVar(value="")
        tk.Label(self.win, textvariable=self.step, font=("Segoe UI", 20, "bold"), foreground="#2f6fb5").pack(anchor="w", pady=(8, 0), **pad)
        self.bar = ttk.Progressbar(self.win, length=700, maximum=1.0)
        self.bar.pack(anchor="w", pady=(6, 0), **pad)
        self.live = tk.StringVar(value="")
        ttk.Label(self.win, textvariable=self.live, font=("Consolas", 11)).pack(anchor="w", pady=(4, 0), **pad)
        self.table = tk.StringVar(value="")
        ttk.Label(self.win, textvariable=self.table, font=("Consolas", 10), justify="left").pack(anchor="w", pady=(10, 0), **pad)
        jrow = ttk.Frame(self.win)
        jrow.pack(fill="x", pady=(8, 0), **pad)
        ttk.Label(jrow, text="Gelenk:").pack(side="left")
        self.all_button = ttk.Button(jrow, text="⟳ Alle", state="disabled", command=self.measure_all)
        self.all_button.pack(side="left", padx=(6, 0))
        self.joint_buttons = {}
        for s in self.K.ORDER:
            b = ttk.Button(jrow, text=self.K.JOINTS[s], state="disabled", command=lambda j=s: self.goto(j))
            b.pack(side="left", padx=(6, 0))
            self.joint_buttons[s] = b
        buttons = ttk.Frame(self.win)
        buttons.pack(fill="x", pady=(8, 0), **pad)
        self.back_button = ttk.Button(buttons, text="◀ Zurueck", command=self.back, state="disabled")
        self.back_button.pack(side="left")
        self.redo_button = ttk.Button(buttons, text="Gelenk wiederholen", command=self.redo, state="disabled")
        self.redo_button.pack(side="left", padx=8)
        self.next_button = ttk.Button(buttons, text="Weiter ▶", command=self.forward, state="disabled")
        self.next_button.pack(side="left")
        self.save_button = ttk.Button(buttons, text="Speichern", command=self.finish, state="disabled")
        self.save_button.pack(side="left", padx=8)
        self.zero_button = ttk.Button(buttons, text="Senkrecht uebernehmen", command=self.zero_action, state="disabled")
        self.zero_kind = None
        self.zero_button.pack(side="left", padx=8)
        self.zero_plan = None
        ttk.Button(buttons, text="Schliessen", command=self.close).pack(side="right")
        mapbox = ttk.LabelFrame(self.win, text=" Zuordnung Leader → Follower ", padding=(10, 6))
        mapbox.pack(fill="x", pady=(12, 14), **pad)
        self.map_text = tk.StringVar(value="")
        ttk.Label(mapbox, textvariable=self.map_text, font=("Consolas", 9), justify="left").pack(anchor="w")
        mrow = ttk.Frame(mapbox)
        mrow.pack(fill="x", pady=(6, 0))
        self.map_buttons = {}
        for key in lab.panels:
            b = ttk.Button(mrow, text="", command=lambda k=key: self.toggle_map(k))
            b.pack(side="left", padx=(0, 8))
            self.map_buttons[key] = b
        grow = ttk.Frame(mapbox)
        grow.pack(fill="x", pady=(8, 0))
        self.grip_vars = {}
        for key in lab.panels:
            fix = self.K.load(self.K.grip_path(key)) or {}
            var = tk.StringVar(value=f"{fix.get('close_deg', 0):.1f}")
            self.grip_vars[key] = var
            ttk.Label(grow, text=f"{self.names[key]} Greifer mehr zu:").pack(side="left")
            ttk.Spinbox(grow, from_=0, to=self.K.GRIP_FIX_MAX_DEG, increment=0.5, width=5,
                        textvariable=var).pack(side="left", padx=(4, 0))
            ttk.Label(grow, text="Grad").pack(side="left", padx=(2, 4))
            ttk.Button(grow, text="Uebernehmen", command=lambda k=key: self.save_grip_fix(k)).pack(side="left", padx=(0, 14))
        arow = ttk.Frame(mapbox)
        arow.pack(fill="x", pady=(6, 0))
        for key in lab.panels:
            ttk.Button(arow, text=f"{self.names[key]}: gleiche Stellung abgleichen",
                       command=lambda k=key: AlignDialog(self, k)).pack(side="left", padx=(0, 8))
        self.refresh_map()

    # --- Verbindung ---
    def start(self):
        self.release()
        key = self.choice.get()
        try:
            arm = self.opener(key)
        except SystemExit as exc:
            self.hint.set(f"Board nicht gefunden: {exc}")
            return
        except Exception as exc:
            self.hint.set(f"Port nicht frei oder Fehler: {exc}")
            return
        so = self.so101
        torque = [arm.rd(s, so.TORQUE, 1) for s in so.JOINTS]
        if None in torque:
            arm.close()
            self.hint.set("Nicht alle Servos antworten. Strom und Kabel pruefen, dann erneut starten.")
            return
        if any(torque):
            arm.close()
            self.hint.set("Die Motoren dieses Arms haben Kraft. Erst im Harness 'Stop · ablegen', dann erneut starten.")
            return
        lim = {s: (arm.rd(s, so.MIN_ANGLE, 2), arm.rd(s, so.MAX_ANGLE, 2)) for s in so.JOINTS}
        offsets = {s: so.usm(arm.rd(s, so.OFFSET, 2)) for s in so.JOINTS}
        self.arm, self.arm_key, self.lim, self.offsets = arm, key, lim, offsets
        self.results, kept = self.load_previous(key, offsets)
        self.order = list(self.K.ORDER)
        self.index = -1
        self.visit = 0
        self.start_button.configure(state="disabled")
        for b in (self.all_button, *self.joint_buttons.values()):
            b.configure(state="normal")
        self.back_button.configure(state="normal")
        self.next_button.configure(state="normal")
        self.redo_button.configure(state="normal")
        todo = [s for s in self.order if s not in self.results]
        self.goto(todo[0] if todo else self.order[0])
        if kept and not todo:
            self.hint.set("Alle Gelenke sind schon gemessen. Oben das Gelenk anklicken, das du neu messen willst; "
                          "danach 'Speichern'. Die anderen Gelenke bleiben, wie sie sind.")
        elif kept:
            self.hint.set(self.K.HINTS[self.joint] + f"  (Uebernommen aus der letzten Messung: "
                          f"{', '.join(self.K.JOINTS[s] for s in kept)})")
        self.win.after(self.TICK_MS, self.tick)

    def load_previous(self, key, offsets):
        """Gespeicherte Anschlaege dieses Arms uebernehmen - je Gelenk nur, wenn dessen Offset noch derselbe ist."""
        old = self.K.load(self.K.stops_path(key)) or {}
        old_off = {int(k): int(v) for k, v in (old.get("offsets") or {}).items()}
        results = {}
        for k, r in (old.get("joints") or {}).items():
            s = int(k)
            if s in offsets and old_off.get(s) == offsets[s]:
                results[s] = {"lo": r["lo"], "hi": r["hi"], "repeat": r["repeat"], "ok": True, "old": True,
                              **({"ref": r["ref"]} if r.get("ref") is not None else {})}
        return results, [s for s in self.K.ORDER if s in results]

    def release(self):
        if self.arm is not None:
            try:
                self.arm.close()
            except Exception:
                pass
        self.arm = None

    # --- Ablauf ---
    def goto(self, s):
        """Gelenk s (neu) messen. Eine alte Messung bleibt, bis die neue gelungen ist."""
        if self.arm is None:
            return
        self.visit += 1                     # spaetere 'weiter von selbst' aus einem frueheren Besuch verfallen
        self.index = self.order.index(s)
        self.joint = s
        self.zero_button.configure(state="disabled")
        self.zero_plan, self.zero_kind = None, None
        self.cap = self.K.JointCapture(self.lim[s], joint=s)
        r = self.results.get(s)
        if s == 5 and r and r.get("ok"):              # Drehung schon gemessen: senkrecht direkt merken
            plan = self.K.rezero_plan(r, self.offsets[s])
            self.zero_plan = plan if plan and plan["needed"] else None
            self.zero_kind = "senkrecht"
            self.zero_button.configure(state="normal")
        self.bar["value"] = 0
        self.title.set(f"{self.names[self.arm_key]} · Gelenk {self.index + 1}/{len(self.order)}: {self.K.JOINTS[s]}")
        self.hint.set(self.K.HINTS[s] + ("  (Schon gemessen - eine neue Messung ersetzt die alte.)"
                                         if s in self.results else ""))
        if self.zero_kind == "senkrecht":
            self.hint.set("Anschlaege sind schon gemessen. Greifer senkrecht stellen (feste Backe nach oben, 90 Grad "
                          "zum Tisch), ruhig halten und 'Senkrecht uebernehmen' druecken. Oder neu messen.")
        self.back_button.configure(state="normal" if self.index > 0 else "disabled")
        self.next_button.configure(text="Weiter ▶" if self.index < len(self.order) - 1 else "Fertig ▶")
        for j, b in self.joint_buttons.items():
            mark = "✔ " if self.results.get(j, {}).get("ok") else ""
            b.configure(text=("▶ " if j == s else "") + mark + self.K.JOINTS[j])
        self.save_button.configure(state="normal" if any(r.get("ok") for r in self.results.values()) else "disabled")
        self.show_table()

    def measure_all(self):
        """Alle Gelenke neu messen, der Reihe nach ab dem ersten. Bis 'Speichern' bleibt die alte Datei."""
        if self.arm is None:
            return
        if self.results and not messagebox.askyesno(
                "Alle Gelenke", "Alle Gelenke neu messen? Die bisherigen Messungen in diesem Fenster werden "
                "verworfen (gespeichert wird erst mit 'Speichern').", parent=self.win):
            return
        self.results = {}
        self.goto(self.order[0])

    def back(self):
        if self.index > 0:
            self.goto(self.order[self.index - 1])

    def forward(self):
        if self.index < len(self.order) - 1:
            self.goto(self.order[self.index + 1])
        else:
            self.finish()

    def redo(self):
        self.goto(self.joint)

    def auto_next(self, visit):
        """Nach einer gelungenen Messung: zum naechsten noch fehlenden Gelenk, sonst speichern."""
        if visit != self.visit or self.arm is None:
            return
        rest = self.order[self.index + 1:] + self.order[:self.index]
        todo = [s for s in rest if not self.results.get(s, {}).get("ok")]
        if todo:
            self.goto(todo[0])
        else:
            self.finish()

    def tick(self):
        if self.arm is None or not self.win.winfo_exists():
            return
        cap = getattr(self, "cap", None)
        if cap is not None and not cap.done and self.index < len(self.order):
            import time as _t
            pos = self.arm.rd(self.joint, self.so101.POS, 2, tries=2)
            got = cap.feed(pos, _t.monotonic())
            n = len(cap.values)
            want = cap.wanted_end()
            if n == 0:
                self.step.set("① An einen Anschlag druecken und ruhig halten")
            elif n == 1:
                self.step.set("② Jetzt zum ANDEREN Anschlag und halten")
            elif n == 2:
                self.step.set("③ Zurueck zum ersten Anschlag und halten")
            else:
                self.step.set("④ Noch einmal zum anderen Anschlag und halten")
            self.bar["value"] = cap.progress()
            deg = "" if pos is None else f"{(pos - 2047) * self.K.STEP_DEG:+7.1f} Grad"
            if cap.short:
                self.step.set(f"Noch etwas weiter druecken (ca. {cap.missing() * self.K.STEP_DEG:.1f} Grad): "
                              "eben warst du an dieser Seite schon weiter")
            if cap.wrapped:
                self.step.set("✖ Bereich laeuft ueber den Nullpunkt (0/4095) · bitte 'Weiter'")
            self.live.set(f"Position {pos if pos is not None else 'keine Antwort'}  {deg}   "
                          f"gemessen: {', '.join(map(str, cap.values)) or '-'}"
                          + ("   · erst vom Anschlag wegbewegen" if cap.need_leave else ""))
            if got is not None:
                self.win.bell()
            if cap.done:
                r = cap.result()
                ok = r["ok"]
                prev = self.results.get(self.joint)
                keep_old = not ok and prev is not None and prev.get("ok")
                if not keep_old:
                    self.results[self.joint] = r
                self.bar["value"] = 1.0
                self.step.set(("✔ " if ok else "✖ ") + f"{self.K.JOINTS[self.joint]}: Wiederholgenauigkeit "
                              f"{r['repeat'] * self.K.STEP_DEG:.2f} Grad" + ("" if ok else " · bitte wiederholen"))
                self.hint.set("Gelenk zurueck in die Ablage legen." + (" Weiter geht es von selbst." if ok else "")
                              + (" Die alte Messung bleibt, bis eine neue gelingt." if keep_old else ""))
                for j, b in self.joint_buttons.items():
                    mark = "✔ " if self.results.get(j, {}).get("ok") else ""
                    b.configure(text=("▶ " if j == self.joint else "") + mark + self.K.JOINTS[j])
                if any(x.get("ok") for x in self.results.values()):
                    self.save_button.configure(state="normal")
                self.show_table()
                if ok and cap.free:
                    plan = self.K.rezero_plan(r, self.offsets[self.joint])
                    self.zero_plan = plan if plan and plan["needed"] else None
                    self.zero_kind = "senkrecht"
                    self.zero_button.configure(state="normal", text="Senkrecht uebernehmen")
                    self.step.set("✔ Anschlaege gemessen · jetzt Greifer senkrecht stellen")
                    self.hint.set("Greifer so drehen, dass die feste Backe genau senkrecht nach oben zeigt (90 Grad zum "
                                  "Tisch). Ruhig halten und 'Senkrecht uebernehmen' druecken. Kein Motor bewegt sich. "
                                  "Diese Stellung ist dann bei Leader und Follower dieselbe.")
                elif ok:
                    self.win.after(2000, lambda v=self.visit: self.auto_next(v))
        self.win.after(self.TICK_MS, self.tick)

    def rezero(self):
        """Offset und Grenzen EINES Gelenks ins EEPROM: Mitte zwischen den Anschlaegen wird 2047.
        Nur nach Rueckfrage; vorher Sicherung aller Gelenke; danach zuruecklesen und pruefen."""
        plan, s, so, K = self.zero_plan, self.joint, self.so101, self.K
        if not plan or self.arm is None:
            return
        name = self.names[self.arm_key]
        if not messagebox.askyesno("Nullpunkt setzen", (
                f"{name} · {K.JOINTS[s]}: Die Mitte zwischen beiden Anschlaegen wird der neue Nullpunkt "
                f"({plan['d'] * K.STEP_DEG:+.1f} Grad), die Anschlaege werden die Grenzen.\n\n"
                "Das schreibt Offset und Grenzen dieses einen Gelenks ins EEPROM des Servos. Kein Motor bewegt sich. "
                "Vorher werden alle Werte gesichert.\n\nJetzt schreiben?"), parent=self.win):
            return
        arm = self.arm
        try:
            backup = {j: {"name": so.JOINTS[j], "min": arm.rd(j, so.MIN_ANGLE, 2), "max": arm.rd(j, so.MAX_ANGLE, 2),
                          "offset": arm.rd(j, so.OFFSET, 2)} for j in so.JOINTS}
            if any(v is None for b in backup.values() for v in (b["min"], b["max"], b["offset"])):
                raise RuntimeError("Sicherung unvollstaendig (Servo antwortet nicht) · nichts geschrieben")
            for b in backup.values():
                b["offset"] = so.usm(b["offset"])
            path = os.path.join(K.CALDIR, f"{self.arm_key}_calibration_{time.strftime('%Y-%m-%d_%H%M%S')}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(backup, f, indent=1)
            if any(arm.rd(j, so.TORQUE, 1) for j in so.JOINTS):
                raise RuntimeError("Motoren haben Kraft · nichts geschrieben")
            before = arm.rd(s, so.POS, 2)
            arm.eeprom(s, [(so.OFFSET, so.sm(plan["offset"])), (so.MIN_ANGLE, plan["lo"]), (so.MAX_ANGLE, plan["hi"])])
            off = arm.rd(s, so.OFFSET, 2)
            got = (None if off is None else so.usm(off), arm.rd(s, so.MIN_ANGLE, 2), arm.rd(s, so.MAX_ANGLE, 2))
            after = arm.rd(s, so.POS, 2)
        except Exception as exc:
            self.step.set("✖ Nullpunkt NICHT gesetzt")
            self.hint.set(str(exc))
            return False
        if got != (plan["offset"], plan["lo"], plan["hi"]):
            self.zero_button.configure(state="disabled")
            self.step.set("✖ Zuruecklesen stimmt nicht")
            self.hint.set(f"Erwartet {plan['offset']}/{plan['lo']}/{plan['hi']}, gelesen {got}. Sicherung: {path} "
                          f"(zurueck mit: python calib.py restore {self.arm_key} \"{path}\")")
            return False
        d = plan["d"]
        self.offsets[s], self.lim[s] = plan["offset"], (plan["lo"], plan["hi"])
        r = self.results[s]
        for k in ("lo", "hi"):
            r[k] -= d
        for k in ("lo_all", "hi_all"):
            if k in r:
                r[k] = [v - d for v in r[k]]
        changed = K.shift_saved_poses(self.arm_key, s, d)
        self.zero_plan = None
        self.zero_button.configure(state="disabled")
        self.show_table()
        self.step.set("✔ Nullpunkt gesetzt")
        moved = "" if before is None or after is None else f" Stellung vorher {before}, jetzt {after}."
        self.hint.set(f"Neuer Offset {plan['offset']}, Grenzen {plan['lo']}-{plan['hi']}.{moved} Sicherung: "
                      f"{os.path.basename(path)}." + (" Ablage-/Startstellung umgerechnet." if changed else ""))
        return True

    def zero_action(self):
        if self.zero_kind == "senkrecht":
            self.take_vertical()

    def take_vertical(self):
        """Handgelenk-Drehung: aktuelle Stellung (Greifer senkrecht) als Bezug merken. Liegt der Bereich ueber
        0/4095, wird vorher der Nullpunkt auf die Anschlag-Mitte gelegt (nach Rueckfrage, EEPROM)."""
        import statistics
        s, K = self.joint, self.K
        reads = [self.arm.rd(s, self.so101.POS, 2, tries=2) for _ in range(5)] if self.arm else []
        reads = [p for p in reads if p is not None]
        if len(reads) < 3 or max(reads) - min(reads) > 6:
            self.step.set("Bitte ruhig halten und nochmal druecken")
            return
        r = self.results[s]
        pos = K.unwrap_into(int(statistics.median(reads)), r["lo"], r["hi"])
        if not (r["lo"] - 30 <= pos <= r["hi"] + 30):
            self.step.set("✖ Stellung liegt nicht zwischen den Anschlaegen")
            return
        plan = self.zero_plan
        if plan:
            if not self.rezero():
                return
            pos -= plan["d"]
        r["ref"] = int(round(pos))
        self.zero_plan, self.zero_kind = None, None
        self.zero_button.configure(state="disabled")
        self.show_table()
        self.step.set("✔ Senkrecht gemerkt")
        self.hint.set(((self.hint.get() + " ") if plan else "") + "Weiter geht es von selbst.")
        self.win.after(3000, lambda v=self.visit: self.auto_next(v))

    def show_table(self):
        lines = ["Gelenk               Anschlag 1   Anschlag 2   Spanne     Wiederholung"]
        for s in self.K.ORDER:
            r = self.results.get(s)
            if r is None:
                lines.append(f"{self.K.JOINTS[s]:20s} -")
                continue
            span = (r["hi"] - r["lo"]) * self.K.STEP_DEG
            lines.append(f"{self.K.JOINTS[s]:20s} {r['lo']:10.1f}   {r['hi']:10.1f}   {span:6.1f} Grad  "
                         f"{r['repeat'] * self.K.STEP_DEG:5.2f} Grad {'✔' if r['ok'] else '✖'}"
                         + ("  (von vorher)" if r.get("old") else ""))
        self.table.set("\n".join(lines))

    def finish(self):
        self.visit += 1
        for b in (self.back_button, self.redo_button, self.next_button, self.save_button, self.zero_button,
                  self.all_button, *self.joint_buttons.values()):
            b.configure(state="disabled")
        for j, b in self.joint_buttons.items():
            b.configure(text=self.K.JOINTS[j])
        self.start_button.configure(state="normal")
        good = {s: {"lo": r["lo"], "hi": r["hi"], "repeat": r["repeat"],
                    **({"ref": r["ref"]} if r.get("ref") is not None else {})}
                for s, r in self.results.items() if r["ok"]}
        self.release()
        if not good:
            self.title.set("Nichts gespeichert")
            self.step.set("")
            self.hint.set("Kein Gelenk wurde gueltig gemessen.")
            return
        self.K.save_stops(self.arm_key, good, self.offsets)
        missing = [self.K.JOINTS[s] for s in self.K.ORDER if s not in good]
        self.title.set(f"{self.names[self.arm_key]}: gespeichert ✔")
        self.step.set("")
        self.hint.set("Gespeichert in calibration/stops_" + self.arm_key + ".json."
                      + (f" Nicht gemessen: {', '.join(missing)} (dort bleibt alles wie bisher)." if missing else "")
                      + " Naechsten Arm waehlen oder unten die Zuordnung aktivieren.")
        self.refresh_map()

    # --- Zuordnung ---
    def refresh_map(self):
        K = self.K
        leader = K.load(K.stops_path("leader"))
        lines = [f"Leader: {'gemessen ' + leader['time'] if leader else 'noch nicht gemessen'}"]
        for key, b in self.map_buttons.items():
            f = K.load(K.stops_path(key))
            active = K.load(K.map_path(key))
            name = self.names[key]
            if not leader or not f:
                lines.append(f"{name}: {'gemessen ' + f['time'] if f else 'noch nicht gemessen'} · Zuordnung braucht beide Messungen")
                b.configure(text=f"{name}: aktivieren", state="disabled" if not active else "normal")
                if active:
                    b.configure(text=f"{name}: deaktivieren")
                continue
            m = K.build_map(leader, f, K.load(K.align_path(key)))
            parts = []
            for s, j in m["joints"].items():
                if j["kind"] == "blocked":
                    parts.append(f"{K.JOINTS[int(s)][:6]} ✖ {j['reason']}")
                elif j["kind"] == "shift" and j.get("source"):
                    parts.append(f"{K.JOINTS[int(s)][:6]} {j['shift'] * K.STEP_DEG:+.1f}° ({j['source']})")
                elif j["kind"] == "shift":
                    parts.append(f"{K.JOINTS[int(s)][:6]} {j['shift'] * K.STEP_DEG:+.2f}° (±{j['mismatch'] * K.STEP_DEG / 2:.2f})")
                else:
                    parts.append("Greifer zu/auf")
            state = f"AKTIV seit {active['time']}" if active else "nicht aktiv"
            lines.append(f"{name}: {state}\n    " + " · ".join(parts))
            b.configure(state="normal", text=f"{name}: {'deaktivieren' if active else 'aktivieren'}")
        self.map_text.set("\n".join(lines))

    def save_grip_fix(self, key):
        """Greifer-Feinkorrektur speichern. Liegt die EEPROM-Untergrenze des Greifers ueber dem neuen tiefsten
        Ziel, wird sie nach Rueckfrage abgesenkt (Servo verweigert sonst das weitere Schliessen)."""
        K, so = self.K, self.so101
        try:
            deg = float(self.grip_vars[key].get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Greifer", "Bitte eine Zahl in Grad eintragen, z. B. 2.5", parent=self.win)
            return
        deg = max(0.0, min(K.GRIP_FIX_MAX_DEG, deg))
        own = self.arm is not None and self.arm_key == key
        if self.arm is not None and not own:
            messagebox.showinfo("Greifer", "Erst die laufende Messung speichern oder schliessen.", parent=self.win)
            return
        try:
            arm = self.arm if own else self.opener(key)
        except BaseException as exc:
            messagebox.showerror("Greifer", f"{self.names[key]}: Port nicht frei oder Board fehlt ({exc}). "
                                 "Laeuft der Arm gerade im Harness?", parent=self.win)
            return
        try:
            lo, hi = arm.rd(6, so.MIN_ANGLE, 2), arm.rd(6, so.MAX_ANGLE, 2)
            if lo is None or hi is None:
                raise RuntimeError("Greifer antwortet nicht")
            old = K.load(K.grip_path(key)) or {}
            closed = old.get("closed") if isinstance(old.get("closed"), int) else lo
            steps = int(round(deg / K.STEP_DEG))
            stops = K.load(K.stops_path(key)) or {}
            ref = min([closed] + [stops["joints"]["6"]["lo"]] if "6" in (stops.get("joints") or {}) else [closed])
            need = int(round(ref - steps)) - K.GRIP_LIMIT_MARGIN
            msg = f"{self.names[key]}: Greifer {deg:.1f} Grad weiter zu gespeichert."
            if steps and lo > need:
                if not messagebox.askyesno("Greifer-Grenze", (
                        f"Damit der Greifer {deg:.1f} Grad weiter zugeht, muss seine Untergrenze im Servo von {lo} "
                        f"auf {need} sinken.\n\nDas schreibt EINEN Wert ins EEPROM des Greifer-Servos. Kein Motor "
                        "bewegt sich. Vorher werden alle Werte gesichert.\n\nJetzt schreiben?"), parent=self.win):
                    return
                if any(arm.rd(j, so.TORQUE, 1) for j in so.JOINTS):
                    raise RuntimeError("Motoren haben Kraft · erst im Harness 'Stop · ablegen'")
                backup = {j: {"name": so.JOINTS[j], "min": arm.rd(j, so.MIN_ANGLE, 2), "max": arm.rd(j, so.MAX_ANGLE, 2),
                              "offset": arm.rd(j, so.OFFSET, 2)} for j in so.JOINTS}
                if any(v is None for b in backup.values() for v in (b["min"], b["max"], b["offset"])):
                    raise RuntimeError("Sicherung unvollstaendig (Servo antwortet nicht) · nichts geschrieben")
                for b in backup.values():
                    b["offset"] = so.usm(b["offset"])
                path = os.path.join(K.CALDIR, f"{key}_calibration_{time.strftime('%Y-%m-%d_%H%M%S')}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(backup, f, indent=1)
                arm.eeprom(6, [(so.MIN_ANGLE, need)])
                if arm.rd(6, so.MIN_ANGLE, 2) != need:
                    raise RuntimeError(f"Zuruecklesen stimmt nicht. Sicherung: {path}")
                if own:
                    self.lim[6] = (need, self.lim[6][1])
                msg += f" Untergrenze im Servo jetzt {need} (Sicherung {os.path.basename(path)})."
            K.save_grip_fix(key, deg, closed)
        except Exception as exc:
            messagebox.showerror("Greifer", f"Nicht gespeichert: {exc}", parent=self.win)
            return
        finally:
            if not own:
                try:
                    arm.close()
                except Exception:
                    pass
        messagebox.showinfo("Greifer", msg + " Gilt ab dem naechsten Start des Arms.", parent=self.win)

    def toggle_map(self, key):
        K = self.K
        if K.load(K.map_path(key)):
            K.deactivate(key)
        else:
            leader, f = K.load(K.stops_path("leader")), K.load(K.stops_path(key))
            if not leader or not f:
                return
            if not messagebox.askyesno("Zuordnung aktivieren", f"Ab dem naechsten Start folgt {self.names[key]} dem Leader "
                                       "mit der gemessenen Zuordnung. Die Gelenkgrenzen bleiben unveraendert. Aktivieren?",
                                       parent=self.win):
                return
            K.activate(K.build_map(leader, f, K.load(K.align_path(key))))
        self.refresh_map()

    def close(self):
        self.release()
        if self.lab.calib is self:
            self.lab.calib = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.lab.update_buttons()


class AlignDialog:
    """'Gleiche Stellung': Leader und Follower von Hand gleich ausrichten, dann uebernehmen.
    Fuer Gelenke, deren Anschlaege bei Leader und Follower an anderer Stelle sitzen (Handgelenk-Drehung:
    der Leader hat einen Griff, der Follower einen Greifer). Liest nur, schreibt nichts auf den Bus."""
    TICK_MS = 40

    def __init__(self, wizard, follower):
        self.w, self.K, self.so = wizard, wizard.K, wizard.so101
        self.follower = follower
        self.arms = {}
        if wizard.arm is not None:
            messagebox.showinfo("Gleiche Stellung", "Erst die laufende Messung speichern oder schliessen.",
                                parent=wizard.win)
            return
        for key in ("leader", follower):
            try:
                self.arms[key] = wizard.opener(key)
            except BaseException as exc:
                self.close()
                messagebox.showerror("Gleiche Stellung", f"{wizard.names[key]}: Port nicht frei oder Board fehlt "
                                     f"({exc}). Laeuft der Arm gerade im Harness?", parent=wizard.win)
                return
        so = self.so
        for key, arm in self.arms.items():
            torque = [arm.rd(s, so.TORQUE, 1) for s in so.JOINTS]
            if None in torque or any(torque):
                self.close()
                messagebox.showerror("Gleiche Stellung", f"{wizard.names[key]}: Servos antworten nicht oder haben Kraft. "
                                     "Erst im Harness 'Stop · ablegen'.", parent=wizard.win)
                return
        self.offsets = {k: {s: so.usm(a.rd(s, so.OFFSET, 2)) for s in so.JOINTS} for k, a in self.arms.items()}
        self.win = tk.Toplevel(wizard.win)
        self.win.title(f"Gleiche Stellung · Leader → {wizard.names[follower]}")
        self.win.geometry("640x380")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        pad = {"padx": 18}
        row = ttk.Frame(self.win)
        row.pack(fill="x", pady=(14, 4), **pad)
        ttk.Label(row, text="Gelenk:").pack(side="left")
        self.joint = tk.IntVar(value=5)
        for s in (5, 1, 2, 3, 4):
            ttk.Radiobutton(row, text=self.K.JOINTS[s], value=s, variable=self.joint,
                            command=self.reset).pack(side="left", padx=(8, 0))
        self.hint = tk.StringVar()
        ttk.Label(self.win, textvariable=self.hint, wraplength=600, justify="left",
                  font=("Segoe UI", 11)).pack(anchor="w", pady=(6, 0), **pad)
        self.live = tk.StringVar()
        ttk.Label(self.win, textvariable=self.live, font=("Consolas", 13)).pack(anchor="w", pady=(12, 0), **pad)
        self.result = tk.StringVar()
        tk.Label(self.win, textvariable=self.result, font=("Segoe UI", 14, "bold"), foreground="#2f6fb5",
                 wraplength=600, justify="left").pack(anchor="w", pady=(12, 0), **pad)
        b = ttk.Frame(self.win)
        b.pack(fill="x", pady=(14, 0), **pad)
        ttk.Button(b, text="Uebernehmen", command=self.take).pack(side="left")
        ttk.Button(b, text="Schliessen", command=self.close).pack(side="right")
        self.reset()
        self.win.after(self.TICK_MS, self.tick)

    def reset(self):
        from collections import deque
        self.hist = deque(maxlen=12)
        s = self.joint.get()
        how = ("beide Greifer gleich drehen, z. B. die feste Backe genau senkrecht nach oben"
               if s == 5 else "beide Gelenke in dieselbe, gut erkennbare Stellung bringen (z. B. genau 90 Grad)")
        self.hint.set(f"{self.K.JOINTS[s]}: Leader und Follower ohne Kraft von Hand ausrichten - {how}. "
                      "Ruhig halten und 'Uebernehmen' druecken. Der Unterschied ersetzt dann fuer dieses Gelenk "
                      "die Anschlag-Mitte.")

    def tick(self):
        if not self.arms or not self.win.winfo_exists():
            return
        s = self.joint.get()
        l = self.arms["leader"].rd(s, self.so.POS, 2, tries=2)
        f = self.arms[self.follower].rd(s, self.so.POS, 2, tries=2)
        if l is not None and f is not None:
            self.hist.append((l, f))
            d = self.K.wrap_diff(f - l)
            self.live.set(f"Leader {l:5d}   Follower {f:5d}   Unterschied {d * self.K.STEP_DEG:+7.1f} Grad")
        else:
            self.live.set("keine Antwort")
        self.win.after(self.TICK_MS, self.tick)

    def take(self):
        import statistics
        if len(self.hist) < 8:
            return
        ls, fs = [h[0] for h in self.hist], [h[1] for h in self.hist]
        if max(ls) - min(ls) > 6 or max(fs) - min(fs) > 6:
            self.result.set("Bitte beide Arme ruhig halten und nochmal.")
            return
        s = self.joint.get()
        l, f = statistics.median(ls), statistics.median(fs)
        a = self.K.save_align(self.follower, s, l, f, self.offsets["leader"][s], self.offsets[self.follower][s])
        txt = f"✔ {self.K.JOINTS[s]}: Versatz {a['shift'] * self.K.STEP_DEG:+.1f} Grad gespeichert."
        K, key = self.K, self.follower
        if K.load(K.map_path(key)):                       # aktive Zuordnung gleich mit aktualisieren
            leader, fo = K.load(K.stops_path("leader")), K.load(K.stops_path(key))
            if leader and fo:
                K.activate(K.build_map(leader, fo, K.load(K.align_path(key))))
                txt += " Aktive Zuordnung aktualisiert (gilt ab dem naechsten Start)."
        else:
            txt += " Gilt, sobald die Zuordnung aktiviert ist."
        self.result.set(txt)
        self.w.refresh_map()

    def close(self):
        for a in self.arms.values():
            try:
                a.close()
            except Exception:
                pass
        self.arms = {}
        try:
            self.win.destroy()
        except Exception:
            pass


class CameraWizard:
    """Ordnet die vier Kamera-Plaetze neu zu: fuer jeden Platz die passende Kamera mit der Hand abdecken;
    erkannt wird das Bild, das deutlich dunkler wird. Danach speichern und Harness neu starten."""
    TICK_MS = 100

    def __init__(self, lab, slots=None):
        """slots: nur diese Plaetze neu zuordnen (z. B. [2] ueber den Knopf an einer Kamerakachel)."""
        import cameras
        self.C, self.lab = cameras, lab
        self.manager = lab.cams.manager
        self.names = [s["name"] for s in self.manager.slots]
        self.order = list(slots) if slots else list(range(len(self.names)))
        self.result = {}
        self.pos = 0
        self.slot = self.order[0]
        self.win = tk.Toplevel(lab.root)
        self.win.title("Kameras zuordnen")
        self.win.geometry("+200+150")
        self.win.attributes("-topmost", True)
        self.title = tk.StringVar()
        self.hint = tk.StringVar()
        self.progress = tk.StringVar()
        ttk.Label(self.win, textvariable=self.title, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=20, pady=(16, 4))
        ttk.Label(self.win, textvariable=self.hint, font=("Segoe UI", 11), wraplength=520, justify="left").pack(anchor="w", padx=20)
        ttk.Label(self.win, textvariable=self.progress, font=("Consolas", 9), justify="left").pack(anchor="w", padx=20, pady=10)
        row = ttk.Frame(self.win)
        row.pack(fill="x", padx=20, pady=(0, 16))
        self.skip_button = ttk.Button(row, text="Ueberspringen (alte Zuordnung behalten)", command=self.skip)
        self.skip_button.pack(side="left")
        self.save_button = ttk.Button(row, text="Jetzt speichern und Harness neu starten", command=self.save, state="disabled")
        self.save_button.pack(side="left", padx=10)
        ttk.Button(row, text="Abbrechen", command=self.win.destroy).pack(side="right")
        self.start_step()
        self.win.after(self.TICK_MS, self.tick)

    def live_values(self):
        import time
        now, out = time.monotonic(), {}
        with self.manager.lock:
            cams = [c for c in self.manager.cams if c is not None]
        for cam in cams:
            frame, t = cam.latest()
            if frame is not None and now - t < 1.0:
                out[cam.device] = self.C.brightness(frame)
        return out

    def start_step(self):
        self.phase, self.samples, self.found = "base", [], None
        name = self.names[self.slot]
        self.title.set(f"{self.pos + 1}/{len(self.order)} · {name}")
        self.hint.set(f"Hand weg von allen Kameras ... gleich: die Kamera fuer »{name}« mit der Hand ganz abdecken.")

    def tick(self):
        import time
        if not self.win.winfo_exists():
            return
        if self.phase == "done":
            return
        values, now = self.live_values(), time.monotonic()
        name = self.names[self.slot] if self.phase != "done" else ""
        if self.phase == "base":
            self.samples.append(values)
            if len(self.samples) >= 6:
                devs = set.intersection(*(set(v) for v in self.samples)) if self.samples else set()
                base = {d: sum(v[d] for v in self.samples) / len(self.samples) for d in devs}
                self.detector = self.C.CoverDetector(base, ignore=self.result.values())
                self.phase = "cover"
                self.hint.set(f"Jetzt die Kamera fuer »{name}« mit der Hand ganz abdecken und halten.")
        elif self.phase == "cover":
            dev = self.detector.update(values, now)
            if dev:
                self.result[self.slot], self.found, self.phase = dev, dev, "release"
                self.release_since = now
                self.hint.set(f"Erkannt: {short(dev)} ist »{name}«. Hand wieder weg.")
        elif self.phase == "release":
            base = self.detector.base.get(self.found, 0)
            if values.get(self.found, 0) > 0.7 * base or now - self.release_since > 4:
                self.next_slot()
        lines = ["Ergebnis beim Speichern:"]
        plan = self.plan(values)
        for i, n in enumerate(self.names):
            dev, old = plan[i], self.manager.slots[i]["device"]
            how = ("neu zugeordnet" if i in self.result else "getauscht/ergaenzt" if dev != old else "bleibt")
            lines.append(f"{i + 1} {n:16s} {short(dev) if dev else '-':14s} {how}")
        lines.append("")
        lines.append("Helligkeit jetzt: " + "  ".join(f"{short(d)} {v:3.0f}" for d, v in sorted(values.items())))
        self.progress.set("\n".join(lines))
        self.win.after(self.TICK_MS, self.tick)

    def plan(self, values=None):
        """Vollstaendige Zuordnung, die beim Speichern geschrieben wird."""
        old = [s["device"] for s in self.manager.slots]
        live = list(values) if values is not None else list(self.live_values())
        return self.C.complete_assignment(old, self.result, live)

    def next_slot(self):
        self.pos += 1
        if self.result:
            self.save_button.configure(state="normal")       # auch nach nur einer Kamera speicherbar
        if self.pos >= len(self.order):
            self.phase = "done"
            self.title.set("Fertig")
            self.hint.set("Zuordnung pruefen und speichern. ROS startet danach neu und zeigt die Kameras am richtigen Platz.")
            self.skip_button.configure(state="disabled")
            self.save_button.configure(state="normal" if self.result else "disabled")
        else:
            self.slot = self.order[self.pos]
            self.start_step()

    def skip(self):
        if self.phase != "done":
            self.next_slot()

    def save(self):
        if len(set(self.result.values())) != len(self.result):
            messagebox.showerror("Kameras zuordnen", "Eine Kamera wurde zwei Plaetzen zugeordnet. Bitte neu zuordnen.", parent=self.win)
            return
        self.C.save_assignment(self.plan())
        self.win.destroy()
        self.lab.restart()


def short(dev):
    """Kurzname einer Kamera: Ende der USB-Geraete-ID."""
    if not dev:
        return "-"
    parts = dev.split("\\")[-1].split("&")          # 7&8D00DAF&0&0000 -> USB 8D00DAF
    return "USB " + (parts[1] if len(parts) > 1 else parts[0])


class CameraHub:
    """Ein CameraManager fuer alle vier Plaetze; die Kacheln sitzen in den Arm-Spalten.
    Laeuft im Fensterprozess, unabhaengig vom Servo-Worker."""
    PREVIEW = (320, 180)
    POLL_S = 2.0

    def __init__(self, root, preview=None):
        import cameras
        if preview:
            self.PREVIEW = preview
        self.cameras = cameras
        self.root = root
        self.manager = cameras.CameraManager()
        self.stop_event = threading.Event()
        self.tiles = []             # (platz, status_var, bild_label)
        self.focus = {}             # platz -> {"meter": FocusMeter oder None, "button", "check"}
        self.on_reassign = None     # Lab setzt: Kamera eines Platzes neu zuordnen
        self.views = {}             # Grossansichten (Steuermodus): id -> {"slot", "img", "size"}

    def add_tile(self, parent, slot):
        tile = ttk.Frame(parent)
        head = ttk.Frame(tile)
        head.pack(fill="x")
        ttk.Label(head, text=f"{slot + 1} · {self.manager.slots[slot]['name']}", font=("Segoe UI", 10, "bold")).pack(side="left")
        check = tk.Label(head, text="", font=("Segoe UI", 14, "bold"), foreground="#1f7a3a")
        check.pack(side="right")
        button = ttk.Button(head, text="Schaerfe pruefen", width=16, command=lambda: self.toggle_focus(slot))
        button.pack(side="right", padx=(0, 4))
        # nur diese eine Kamera neu zuordnen (abdecken, fertig)
        ttk.Button(head, text="⇄", width=3, command=lambda: self.on_reassign and self.on_reassign(slot)).pack(side="right", padx=(0, 4))
        self.focus[slot] = {"meter": None, "button": button, "check": check}
        status = tk.StringVar(value="suche ...")
        ttk.Label(tile, textvariable=status, font=("Segoe UI", 9)).pack(anchor="w")
        blank = tk.PhotoImage(width=self.PREVIEW[0], height=self.PREVIEW[1])
        img = tk.Label(tile, image=blank, text="", compound="center", foreground="#ddd",
                       background="#111", font=("Segoe UI", 11, "bold"))
        img.blank = blank
        img.pack(anchor="w", pady=(2, 0))
        self.tiles.append((slot, status, img))
        return tile

    def add_view(self, slot, img, size):
        """Zusaetzliche grosse Anzeige eines Platzes (Steuermodus). Gibt eine id zum Entfernen zurueck."""
        vid = object()
        self.views[vid] = {"slot": slot, "img": img, "size": size}
        return vid

    def remove_view(self, vid):
        self.views.pop(vid, None)

    def start(self):
        if self.cameras.cv2 is None:
            for _, status, _ in self.tiles:
                status.set("OpenCV fehlt: pip install opencv-python")
            return
        threading.Thread(target=self._poll_loop, daemon=True, name="camera-poll").start()
        self.root.after(66, self._refresh)

    def _poll_loop(self):
        while not self.stop_event.is_set():
            try:
                self.manager.poll()
            except Exception as exc:          # Kamerafehler duerfen das Fenster nie stoeren
                print("Kamera-Abgleich fehlgeschlagen:", exc, file=sys.stderr)
            self.stop_event.wait(self.POLL_S)

    def _refresh(self):
        import base64, time
        if self.stop_event.is_set():
            return
        cv2 = self.cameras.cv2
        now = time.monotonic()
        seen = {}                   # platz -> (text, bild oder None, schaerfe-ergebnis)
        for slot, status, img in self.tiles:
            text, cam = self.manager.status(slot, now)
            frame, t = cam.latest() if cam is not None else (None, None)
            live = text.startswith(self.cameras.LIVE)
            focus = self.focus.get(slot, {})
            meter = focus.get("meter")
            seen[slot] = (text, frame if live else None, None)
            if live and frame is not None:
                small = cv2.resize(frame, self.PREVIEW, interpolation=cv2.INTER_AREA)
                res = None
                if meter is not None:
                    res = meter.update(frame)            # auf dem vollen Bild gemessen, nicht der Vorschau
                    small = self.cameras.draw_focus(small.copy(), res)
                    seen[slot] = (text, frame, res)
                    focus["check"].configure(text="✔" if res["ok"] else "…",
                                             foreground="#1f7a3a" if res["ok"] else "#b36b00")
                ok, png = cv2.imencode(".png", small)
                if ok:
                    photo = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
                    img.configure(image=photo, text="")
                    img.image = photo
                dark = " · sehr dunkel/abgedeckt?" if float(small.mean()) < 8 else ""
                if res is not None:
                    status.set(f"Schaerfe: {res['hint']}")
                else:
                    status.set(f"{text} · {cam.rate:.0f} fps · Alter {max(0.0, 1000 * (now - t)):.0f} ms{dark}")
            else:
                if meter is not None:
                    focus["check"].configure(text="")
                img.configure(image=img.blank, text=text)
                img.image = img.blank
                status.set(text)
        for view in list(self.views.values()):
            self._show_big(view, *seen.get(view["slot"], ("nicht zugeordnet", None, None)))
        self.root.after(66, self._refresh)

    def _show_big(self, view, text, frame, res):
        img, (w, h) = view["img"], view["size"]
        if not img.winfo_exists():                  # Fenster wurde gerade geschlossen
            return
        if frame is None or w < 50 or h < 30:
            img.configure(image="", text=text)
            img.image = None
            return
        cv2 = self.cameras.cv2
        fh, fw = frame.shape[:2]
        scale = min(w / fw, h / fh)                 # Seitenverhaeltnis behalten
        big = cv2.resize(frame, (max(1, int(fw * scale)), max(1, int(fh * scale))),
                         interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        if res is not None:
            big = self.cameras.draw_focus(big, res)
        ok, ppm = cv2.imencode(".ppm", big)         # PPM: viel schneller als PNG bei grossen Bildern
        if ok:
            photo = tk.PhotoImage(data=ppm.tobytes(), format="PPM")   # roh, nicht base64
            img.configure(image=photo, text="")
            img.image = photo

    def lock_settings(self, slots):
        """Kameraeinstellungen fuer eine Aufnahme-Session festsetzen. {Platzname: Werte}; fehlende Kameras
        blockieren nichts."""
        out = {}
        for slot in slots:
            cam = self.manager.cams[slot] if slot < len(self.manager.cams) else None
            name = self.manager.slots[slot]["name"]
            out[name] = cam.lock() if cam is not None and hasattr(cam, "lock") else None
        return out

    def toggle_focus(self, slot):
        """Schaerfe-Test fuer einen Platz an/aus. Neu starten = Bestwert vergessen."""
        f = self.focus[slot]
        if f["meter"] is None:
            f["meter"] = self.cameras.FocusMeter()
            f["button"].configure(text="Test beenden")
        else:
            f["meter"] = None
            f["button"].configure(text="Schaerfe pruefen")
            f["check"].configure(text="")

    def stop(self):
        self.stop_event.set()
        self.manager.stop()


def code_stamp():
    """Aenderungszeit aller Programmdateien und der config.json (Kameras, Arme): zeigt an, wenn ein
    Neustart noetig ist."""
    files = ([p for p in HERE.glob("*.py") if not p.name.startswith("test_")] + list(HERE.glob("ki/*.py"))
             + [HERE / "config.json"])
    return max((p.stat().st_mtime for p in files if p.exists()), default=0)


def start_detached(extra=()):
    """Startet ROS als eigenen Prozess ohne Konsolenfenster."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    env = {k: v for k, v in os.environ.items() if k != "ROBOFORGE_SIM"}   # Modus nur ueber --sim
    subprocess.Popen([str(pyw if pyw.exists() else exe), str(HERE / "ros.py"), *extra], cwd=HERE, env=env,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                     close_fds=True)


def wait_for_exit(pid, timeout=15):
    """Beim Neustart: warten, bis das alte Fenster Kameras und Ports freigegeben hat."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, int(pid))         # SYNCHRONIZE
        if h:
            k.WaitForSingleObject(h, int(timeout * 1000))
            k.CloseHandle(h)
    except Exception:
        import time
        time.sleep(2)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--after" in argv:
        wait_for_exit(argv[argv.index("--after") + 1])
    root = tk.Tk()
    import icons; icons.apply(root, "harness")
    Lab(root)
    root.mainloop()
    # Fenster zu, Arme abgelegt, Ports und Kameras freigegeben (_shutdown). Haengende Hintergrund-Threads
    # (z. B. die Modul-Schnittstelle) duerfen das Beenden nicht blockieren - sonst wartet ein Neustart ewig
    # und die Module reden mit einem sterbenden Harness (17.11. 18:55).
    os._exit(0)


if __name__ == "__main__":
    main()
