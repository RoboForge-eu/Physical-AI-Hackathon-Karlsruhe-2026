"""Orchestrator: Ablaeufe aus gelernten Faehigkeiten, Harness-Befehlen und Agenten zusammenstecken (wie n8n).

Eigenes Programm. Knoten mit der Maus verschieben; vom runden Ausgang (rechts = weiter, unten = sonst)
auf einen anderen Knoten ziehen, um zu verbinden. Rechts stehen die Einstellungen des gewaehlten Knotens.
Bewegungen nur in einer Arbeitssitzung, die vor Ort im Harness freigegeben wird.

  python modul_workflow.py
"""
import copy, json, threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from modul_basis import Modul
from workflow import engine as E, store
from ki import jobs

W, H = 180, 64                     # Knotengroesse
STATE_COLORS = {"laeuft": "#f2c14e", "ok": "#1f7a3a", "fehler": "#b3261e"}
OUT_LABELS = {"bedingung": ("ja", "nein"), "wiederholen": ("nochmal", "danach"), "skill": ("erfolg", "fehlschlag")}


def summary(n):
    p = n.get("params", {})
    k = n["type"]
    if k == "faehigkeit":
        return f"{p.get('modell') or '(Modell waehlen)'} · {p.get('sekunden')} s · {p.get('arm')}"
    if k == "befehl":
        return p.get("name", "")
    if k == "skill":
        return f"{p.get('name') or '(Skill waehlen)'} · {p.get('arm')}"
    if k == "entscheidung":
        return (p.get("frage") or "(Frage eintragen)")[:34]
    if k == "agent":
        return (p.get("aufgabe") or "(Aufgabe eintragen)")[:34]
    if k == "warten":
        return f"{p.get('sekunden')} s"
    if k == "sitzung":
        return f"Freigabe {p.get('arm')}"
    if k == "bedingung":
        return f"{p.get('wert')} {p.get('vergleich')} {p.get('mit')}"[:34]
    if k == "wiederholen":
        return f"{p.get('mal')} mal"
    if k == "ende":
        return "Arm ablegen" if p.get("sitzung_beenden") else ""
    return ""


class WorkflowModul(Modul):
    def __init__(self):
        super().__init__("Orchestrator", "Ablaeufe aus VLA-Faehigkeiten, Harness-Befehlen und Agenten (wie n8n)", size="1300x860")
        self.p = E.new_pipeline()
        self.sel = None
        self.drag = None
        self.link = None                 # (knoten, ausgang) beim Verbinden
        self.zoom, self.off = 1.0, [0.0, 0.0]   # Ansicht: Bildschirm = Welt * zoom + off
        self.pan = None                  # (x, y) beim Verschieben der Ansicht
        self.moved = False
        self.states = {}
        self.runner = None
        self.skill_names = []
        self.arm_keys = []

        bar = ttk.Frame(self.root, padding=(16, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Ablauf:").pack(side="left")
        self.name = tk.StringVar(value=self.p["name"])
        ttk.Entry(bar, textvariable=self.name, width=26).pack(side="left", padx=4)
        ttk.Button(bar, text="Neu", command=self.new).pack(side="left", padx=2)
        ttk.Button(bar, text="Speichern", command=self.save).pack(side="left", padx=2)
        self.open_choice = tk.StringVar()
        self.open_box = ttk.Combobox(bar, textvariable=self.open_choice, state="readonly", width=24)
        self.open_box.pack(side="left", padx=(12, 2))
        self.open_box.bind("<<ComboboxSelected>>", lambda e: self.open())
        self.run_button = ttk.Button(bar, text="▶ Ablauf starten", command=self.start)
        self.run_button.pack(side="left", padx=(16, 2))
        self.halt_button = ttk.Button(bar, text="■ Anhalten", command=self.halt, state="disabled")
        self.halt_button.pack(side="left", padx=2)
        self.status = tk.StringVar()
        ttk.Label(bar, textvariable=self.status, font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)

        pal = ttk.Frame(self.root, padding=(16, 0))
        pal.pack(fill="x")
        ttk.Label(pal, text="Knoten:").pack(side="left")
        for kind, t in E.TYPES.items():
            if kind != "start":
                tk.Button(pal, text="+ " + t["label"], background=t["color"], foreground="white", relief="flat",
                          padx=8, command=lambda k=kind: self.add(k)).pack(side="left", padx=2, pady=4)
        ttk.Label(pal, text="  Entf = Knoten loeschen", font=("Segoe UI", 8)).pack(side="left")
        ttk.Button(pal, text="Einpassen", width=9, command=self.fit).pack(side="right", padx=2)
        ttk.Button(pal, text="+", width=3, command=lambda: self.zoom_at(1.2)).pack(side="right")
        self.zoom_text = tk.StringVar(value="100 %")
        ttk.Button(pal, textvariable=self.zoom_text, width=6, command=self.zoom_reset).pack(side="right")
        ttk.Button(pal, text="−", width=3, command=lambda: self.zoom_at(1 / 1.2)).pack(side="right")

        mid = ttk.Panedwindow(self.root, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=16)
        self.canvas = tk.Canvas(mid, background="#fafafa", highlightthickness=0)
        mid.add(self.canvas, weight=4)
        self.props = ttk.Frame(mid, padding=8, width=330)
        mid.add(self.props, weight=1)
        self.log_box = ScrolledText(self.root, height=8, font=("Consolas", 9), state="disabled", wrap="word")
        self.log_box.pack(fill="x", padx=16, pady=(6, 12))

        c = self.canvas
        c.bind("<Button-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        for b in (2, 3):                                  # mittlere Taste (Mac: 3) ziehen = Ansicht schieben
            c.bind(f"<Button-{b}>", self.pan_start)
            c.bind(f"<B{b}-Motion>", self.pan_move)
            c.bind(f"<ButtonRelease-{b}>", lambda e: setattr(self, "pan", None))
        c.bind("<MouseWheel>", self.on_wheel)             # Windows und Mac (auch Trackpad mit zwei Fingern)
        c.bind("<Shift-MouseWheel>", lambda e: self.on_wheel(e, horizontal=True))
        c.bind("<Control-MouseWheel>", lambda e: self.on_wheel(e, zoom=True))
        c.bind("<Command-MouseWheel>" if self.root.tk.call("tk", "windowingsystem") == "aqua"
               else "<Alt-MouseWheel>", lambda e: self.on_wheel(e, zoom=True))
        c.bind("<Button-4>", lambda e: self.scroll(0, 60))  # Linux
        c.bind("<Button-5>", lambda e: self.scroll(0, -60))
        self.root.bind("<Control-plus>", lambda e: self.zoom_at(1.2))
        self.root.bind("<Control-minus>", lambda e: self.zoom_at(1 / 1.2))
        self.root.bind("<Control-0>", lambda e: self.zoom_reset())
        self.root.bind("<Delete>", lambda e: self.delete())
        self.refresh_open_list()
        self.background(lambda: [t["name"] for t in self.ros.tools()], self._set_skills)
        self.draw()
        self.show_props()

    # --- Daten aus ROS ---
    def _set_skills(self, names):
        self.skill_names = names
        self.show_props()

    def on_arms(self, arms):
        keys = [a["arm"] for a in arms]
        if keys != self.arm_keys:
            self.arm_keys = keys
            self.show_props()
        if not self.skill_names and self.ros_ok:
            self.background(lambda: [t["name"] for t in self.ros.tools()], self._set_skills)

    # --- Zeichnen ---
    def port(self, nid, out):
        n = self.p["nodes"][nid]
        return (n["x"] + W, n["y"] + H / 2) if out == "next" else (n["x"] + W / 2, n["y"] + H)

    # --- Ansicht (zoomen, schieben wie auf einem Whiteboard) ---
    def tw(self, x, y):
        """Welt -> Bildschirm."""
        return x * self.zoom + self.off[0], y * self.zoom + self.off[1]

    def to_world(self, x, y):
        return (x - self.off[0]) / self.zoom, (y - self.off[1]) / self.zoom

    def fs(self, size):
        return max(4, int(round(size * self.zoom)))

    def scroll(self, dx, dy):
        self.off[0] += dx
        self.off[1] += dy
        self.draw()
        self.layout_spaeter()

    def layout_spaeter(self):
        """Ansicht nach kurzer Ruhe speichern (nicht bei jedem Mausrad-Schritt)."""
        job = getattr(self, "_layout_job", None)
        if job:
            self.root.after_cancel(job)
        self._layout_job = self.root.after(800, self.save_layout)

    def zoom_at(self, factor, x=None, y=None):
        if x is None:
            x, y = self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2
        z = max(0.25, min(3.0, self.zoom * factor))
        wx, wy = self.to_world(x, y)
        self.zoom = z
        self.off = [x - wx * z, y - wy * z]           # Punkt unter dem Mauszeiger bleibt stehen
        self.zoom_text.set(f"{round(z * 100)} %")
        self.draw()
        self.layout_spaeter()

    def zoom_reset(self):
        self.zoom_at(1.0 / self.zoom)

    def fit(self):
        nodes = self.p["nodes"].values()
        if not nodes:
            return
        x0, y0 = min(n["x"] for n in nodes) - 40, min(n["y"] for n in nodes) - 40
        x1, y1 = max(n["x"] for n in nodes) + W + 40, max(n["y"] for n in nodes) + H + 40
        cw, ch = max(200, self.canvas.winfo_width()), max(200, self.canvas.winfo_height())
        self.zoom = max(0.25, min(1.5, cw / (x1 - x0), ch / (y1 - y0)))
        self.off = [(cw - (x1 - x0) * self.zoom) / 2 - x0 * self.zoom, (ch - (y1 - y0) * self.zoom) / 2 - y0 * self.zoom]
        self.zoom_text.set(f"{round(self.zoom * 100)} %")
        self.draw()

    def on_wheel(self, e, horizontal=False, zoom=False):
        d = e.delta
        if abs(d) >= 120:                                 # Windows: 120 je Raste; Mac: kleine Werte
            d = d / 120 * 3
        if zoom:
            self.zoom_at(1.1 ** (1 if d > 0 else -1), e.x, e.y)
        elif horizontal:
            self.scroll(d * 10, 0)
        else:
            self.scroll(0, d * 10)

    def pan_start(self, e):
        self.pan = (e.x, e.y)

    def pan_move(self, e):
        if self.pan:
            px, py = self.pan
            self.pan = (e.x, e.y)
            self.moved = True
            self.scroll(e.x - px, e.y - py)

    def draw(self):
        c = self.canvas
        c.delete("all")
        nodes = self.p["nodes"]
        tw, fs, z = self.tw, self.fs, self.zoom
        c.create_text(8, max(20, c.winfo_height()) - 8, anchor="sw", fill="#999", font=("Segoe UI", 8),
                      text="Mausrad / 2 Finger = schieben · Strg (Mac: Cmd) + Mausrad = zoomen · "
                           "leere Flaeche oder mittlere Taste ziehen = schieben")
        for nid, n in nodes.items():                      # erst die Pfeile
            for out in ("next", "sonst"):
                tgt = n.get(out)
                if tgt in nodes:
                    x1, y1 = self.port(nid, out)
                    t = nodes[tgt]
                    x2, y2 = t["x"], t["y"] + H / 2
                    if out == "next":
                        pts = (x1, y1, x1 + 30, y1, x2 - 30, y2, x2, y2)
                    else:
                        pts = (x1, y1, x1, y1 + 30, x2 - 30, y2, x2, y2)
                    pts = [v for i in range(0, 8, 2) for v in tw(pts[i], pts[i + 1])]
                    c.create_line(*pts, smooth=True, arrow="last", width=max(1, 2 * z),
                                  fill="#333" if out == "next" else "#b3261e", dash=() if out == "next" else (5, 3))
                    if n["type"] in OUT_LABELS:
                        lx, ly = tw(*((x1 + 14, y1 - 9) if out == "next" else (x1 + 22, y1 + 14)))
                        c.create_text(lx, ly, text=OUT_LABELS[n["type"]][0 if out == "next" else 1],
                                      font=("Segoe UI", fs(8), "bold"), fill="#555")
        for nid, n in nodes.items():
            t = E.TYPES[n["type"]]
            x, y = tw(n["x"], n["y"])
            w, h = W * z, H * z
            state = self.states.get(nid)
            outline = STATE_COLORS.get(state, "#1d1d1d" if nid == self.sel else "#bbb")
            width = 4 if state or nid == self.sel else 1
            c.create_rectangle(x, y, x + w, y + h, fill="white", outline=outline, width=width, tags=("node", nid))
            c.create_rectangle(x, y, x + w, y + 20 * z, fill=t["color"], outline="", tags=("node", nid))
            if z >= 0.4:                                  # ganz klein: nur Kaesten, keine Schrift
                c.create_text(x + 6 * z, y + 10 * z, text=f"{t['label']} · {nid}", anchor="w", fill="white",
                              font=("Segoe UI", fs(8), "bold"), tags=("node", nid))
                c.create_text(x + 6 * z, y + 32 * z, text=n["title"], anchor="w", font=("Segoe UI", fs(10), "bold"),
                              tags=("node", nid))
                c.create_text(x + 6 * z, y + 50 * z, text=summary(n), anchor="w", font=("Segoe UI", fs(8)),
                              fill="#555", tags=("node", nid))
            if nid == self.p["start"]:
                c.create_text(x - 6, y + h / 2, text="▶", anchor="e", font=("Segoe UI", fs(12)), fill="#1f7a3a")
            if n["type"] != "ende":
                r = max(4, 6 * z)
                for out in ("next", "sonst") if n["type"] in E.BRANCHING else ("next",):
                    px, py = tw(*self.port(nid, out))
                    c.create_oval(px - r, py - r, px + r, py + r, fill="#333" if out == "next" else "#b3261e",
                                  outline="white", tags=("port", nid, out))

    # --- Maus ---
    def hit(self, x, y):
        for item in reversed(self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1)):
            tags = self.canvas.gettags(item)
            if "port" in tags:
                return "port", tags[1], tags[2]
            if "node" in tags:
                return "node", tags[1], None
        return None, None, None

    def on_press(self, e):
        kind, nid, out = self.hit(e.x, e.y)
        if kind == "port":
            self.link = (nid, out)
            return
        if kind == "node":
            self.sel = nid
            n = self.p["nodes"][nid]
            wx, wy = self.to_world(e.x, e.y)
            self.drag = (nid, wx - n["x"], wy - n["y"])
        else:
            self.pan, self.moved = (e.x, e.y), False       # leere Flaeche ziehen = Ansicht schieben
            return
        self.draw()
        self.show_props()

    def on_drag(self, e):
        if self.link:
            self.draw()
            x1, y1 = self.tw(*self.port(*self.link))
            self.canvas.create_line(x1, y1, e.x, e.y, arrow="last", width=2, dash=(3, 2), fill="#1f6f8b")
        elif self.drag:
            nid, dx, dy = self.drag
            n = self.p["nodes"][nid]
            wx, wy = self.to_world(e.x, e.y)
            n["x"], n["y"] = round(wx - dx), round(wy - dy)
            self.draw()
        elif self.pan:
            self.pan_move(e)

    def on_release(self, e):
        if self.link:
            kind, nid, _ = self.hit(e.x, e.y)
            src, out = self.link
            self.link = None
            if kind in ("node", "port") and nid != src:
                self.p["nodes"][src][out] = nid
            elif kind is None:
                self.p["nodes"][src][out] = None          # ins Leere ziehen = Verbindung loesen
            self.draw()
            self.show_props()
        elif self.pan and not self.moved and self.sel is not None:     # Klick ins Leere: Auswahl aufheben
            self.sel = None
            self.draw()
            self.show_props()
        if self.drag or (self.pan and self.moved):
            self.save_layout()
        self.drag = None
        self.pan = None

    # --- Knoten ---
    def add(self, kind):
        nid = E.next_id(self.p)
        cx, cy = self.to_world(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 3)
        k = len(self.p["nodes"]) % 5
        n = E.new_node(kind, nid, x=round(cx - W / 2 + 20 * k), y=round(cy + 20 * k))
        if kind in ("faehigkeit", "sitzung", "agent", "ende", "skill", "entscheidung") and self.arm_keys:
            n["params"]["arm"] = self.arm_keys[0]
        self.p["nodes"][nid] = n
        if self.sel and not self.p["nodes"][self.sel].get("next") and self.p["nodes"][self.sel]["type"] != "ende":
            self.p["nodes"][self.sel]["next"] = nid        # an den gewaehlten Knoten anhaengen
        self.sel = nid
        self.draw()
        self.show_props()

    def delete(self):
        if not self.sel or self.sel == self.p["start"] or self.focus_in_props():
            return
        del self.p["nodes"][self.sel]
        for n in self.p["nodes"].values():
            for out in ("next", "sonst"):
                if n.get(out) == self.sel:
                    n[out] = None
        self.sel = None
        self.draw()
        self.show_props()

    def focus_in_props(self):
        w = self.root.focus_get()
        return w is not None and str(w).startswith(str(self.props))

    # --- Einstellungen rechts ---
    def show_props(self):
        for w in self.props.winfo_children():
            w.destroy()
        if not self.sel or self.sel not in self.p["nodes"]:
            ttk.Label(self.props, text="Knoten anklicken, um ihn einzustellen.\n\nVerbinden: vom runden Ausgang "
                      "auf einen Knoten ziehen.\nVerbindung loesen: Ausgang ins Leere ziehen.\n\n"
                      "Werte aus frueheren Knoten: {{k3.ergebnis.feld}}", wraplength=300, justify="left").pack(anchor="w")
            return
        nid, n = self.sel, self.p["nodes"][self.sel]
        t = E.TYPES[n["type"]]
        ttk.Label(self.props, text=f"{t['label']} · {nid}", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self._field("Titel", n, "title", None)
        for key, default in t["params"].items():
            self._field(key, n["params"], key, default)
        if n["type"] not in ("ende",):
            names = [""] + [k for k in self.p["nodes"] if k != nid]
            for out in ("next", "sonst") if n["type"] in E.BRANCHING else ("next",):
                label = {"next": "weiter →", "sonst": "sonst →"}[out]
                if n["type"] in OUT_LABELS:
                    label = OUT_LABELS[n["type"]][0 if out == "next" else 1] + " →"
                self._choice(label, n, out, names)
        if n["type"] == "faehigkeit":
            ttk.Label(self.props, text="Der Arm fuehrt die gelernte Faehigkeit so viele Sekunden aus und haelt dann.",
                      wraplength=300, font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))
        if n["type"] == "sitzung":
            ttk.Label(self.props, text="Fragt im Harness die Freigabe vor Ort an und wartet, bis der Arm oben steht.",
                      wraplength=300, font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))
        if nid != self.p["start"]:
            ttk.Button(self.props, text="Als Start setzen", command=lambda: self._set_start(nid)).pack(anchor="w", pady=(10, 0))
            ttk.Button(self.props, text="Knoten loeschen", command=self.delete).pack(anchor="w", pady=(4, 0))

    def _set_start(self, nid):
        self.p["start"] = nid
        self.draw()

    def _choice(self, label, target, key, values):
        ttk.Label(self.props, text=label).pack(anchor="w", pady=(6, 0))
        var = tk.StringVar(value=target.get(key) or "")
        box = ttk.Combobox(self.props, textvariable=var, values=values, state="readonly", width=30)
        box.pack(anchor="w")
        def apply(*_):
            target[key] = var.get() or None
            self.draw()
        var.trace_add("write", apply)

    def _field(self, label, target, key, default):
        ttk.Label(self.props, text=label).pack(anchor="w", pady=(6, 0))
        value = target.get(key)
        if isinstance(default, bool):
            var = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(self.props, variable=var, text="ja").pack(anchor="w")
            var.trace_add("write", lambda *_: (target.__setitem__(key, var.get()), self.draw()))
            return
        var = tk.StringVar(value="" if value is None else str(value))
        options = None
        if key == "arm":
            options = self.arm_keys
        elif key == "modell":
            options = [m["name"] for m in jobs.models()]
        elif key == "vergleich":
            options = E.VERGLEICHE
        elif key == "name" and self.p["nodes"][self.sel]["type"] == "skill":
            from skilllib import store as skill_store
            options = [s["name"] for s in skill_store.all_skills()]
        elif key == "name" and self.skill_names:
            options = self.skill_names
        if options is not None:
            w = ttk.Combobox(self.props, textvariable=var, values=options, width=30)
        elif key in ("aufgabe", "args", "frage", "parameter"):
            w = tk.Text(self.props, height=4, width=34, font=("Segoe UI", 9), wrap="word")
            w.insert("1.0", var.get())
            w.bind("<KeyRelease>", lambda e: var.set(w.get("1.0", "end").strip()))
        else:
            w = ttk.Entry(self.props, textvariable=var, width=32)
        w.pack(anchor="w")

        def apply(*_):
            text = var.get()
            if isinstance(default, (int, float)) and not isinstance(default, bool) and "{{" not in text:
                try:
                    text = type(default)(float(text)) if isinstance(default, int) else float(text)
                except ValueError:
                    return
            target[key] = text
            self.draw()
        var.trace_add("write", apply)

    # --- Dateien ---
    def refresh_open_list(self):
        self.saved = store.names()
        self.open_box["values"] = [n for n, _ in self.saved]

    def new(self):
        self.p = E.new_pipeline()
        self.name.set(self.p["name"])
        self.sel, self.states = None, {}
        self.draw()
        self.show_props()

    def save(self):
        self.p["name"] = self.name.get().strip() or "Ablauf"
        self.p["ansicht"] = {"zoom": round(self.zoom, 3), "off": [round(v, 1) for v in self.off]}
        path = store.save(self.p)
        self.refresh_open_list()
        self.status.set(f"gespeichert: {path.split(chr(92))[-1]}")

    def save_layout(self):
        """Anordnung (Knotenpositionen) und Ansicht sofort in die gespeicherte Datei schreiben - nur diese Werte,
        andere ungespeicherte Aenderungen bleiben ungespeichert. Neue, nie gespeicherte Ablaeufe: erst Speichern."""
        import os
        self.p["ansicht"] = {"zoom": round(self.zoom, 3), "off": [round(v, 1) for v in self.off]}
        path = store.path_for(self.p["name"])
        if not os.path.exists(path):
            return
        try:
            disk = store.load(path)
            for nid, n in self.p["nodes"].items():
                if nid in disk.get("nodes", {}):
                    disk["nodes"][nid]["x"], disk["nodes"][nid]["y"] = n["x"], n["y"]
            disk["ansicht"] = self.p["ansicht"]
            store.save(disk)
        except Exception as exc:                          # Anordnung ist nicht wichtig genug fuer einen Absturz
            self.status.set(f"Anordnung nicht gespeichert: {exc}")

    def open(self):
        path = dict(self.saved).get(self.open_choice.get())
        if path:
            self.p = store.load(path)
            self.name.set(self.p["name"])
            self.sel, self.states = None, {}
            a = self.p.get("ansicht")
            if a:
                self.zoom, self.off = float(a.get("zoom", 1.0)), list(a.get("off", [0.0, 0.0]))
                self.zoom_text.set(f"{round(self.zoom * 100)} %")
                self.draw()
            else:
                self.fit()
            self.show_props()

    # --- Ausfuehren ---
    def log(self, text):
        def put():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.ui(put)

    def on_node(self, nid, state):
        def put():
            self.states[nid] = state
            self.draw()
        self.ui(put)

    def start(self):
        self.p["name"] = self.name.get().strip() or "Ablauf"
        problems = E.validate(self.p)
        if problems:
            messagebox.showerror("Ablauf", "Bitte zuerst beheben:\n\n" + "\n".join(problems), parent=self.root)
            return
        if not self.ros_ok:
            messagebox.showerror("Ablauf", "Der Harness ist nicht erreichbar.", parent=self.root)
            return
        def agent_factory(task, log):
            from agent.loop import AgentRun
            return AgentRun(self.ros, task, log)
        self.states = {}
        self.runner = E.Runner(copy.deepcopy(self.p), self.ros, log=self.log, on_node=self.on_node,
                               agent_factory=agent_factory, confirm=self.confirm_here)
        self.run_button.configure(state="disabled")
        self.halt_button.configure(state="normal")
        self.status.set("laeuft ...")
        def run():
            try:
                outcome = self.runner.run()
            except Exception as exc:
                outcome = f"Fehler: {exc}"
            self.ui(lambda: self._finished(outcome))
        threading.Thread(target=run, daemon=True, name="ablauf").start()

    def confirm_here(self, titel, text):
        """Aus dem Ablauf-Thread: Freigabe-Hinweis hier im Orchestrator zeigen und auf die Antwort warten."""
        antwort, fertig = {}, threading.Event()
        def frag():
            self.root.lift()
            antwort["ok"] = messagebox.askokcancel(titel, text, parent=self.root, icon="warning")
            fertig.set()
        self.ui(frag)
        while not fertig.wait(0.2):
            if self.runner is not None and self.runner.stop.is_set():
                return False
        return bool(antwort.get("ok"))

    def _finished(self, outcome):
        self.run_button.configure(state="normal")
        self.halt_button.configure(state="disabled")
        self.status.set(str(outcome)[:120])

    def halt(self):
        if self.runner:
            self.runner.halt()
            self.status.set("halte an nach dem laufenden Knoten ... (Arm sofort stoppen: Stop im Harness)")


if __name__ == "__main__":
    WorkflowModul().run()
