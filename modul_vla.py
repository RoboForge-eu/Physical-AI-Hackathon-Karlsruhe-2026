"""VLA-Studio: Faehigkeiten durch Vorfuehren lernen (Imitation Learning, VLA).

Eigenes Programm. Liest Datensaetze und Modelle direkt von der Platte; Training und Zuweisung laufen
ueber die lokale Harness-Schnittstelle, damit ein Training weiterlaeuft, auch wenn dieses Fenster zu ist.
Aufgenommen wird im Steuermodus von RoboForge Harness (braucht Arm und Kameras).

  python modul_vla.py
"""
import os, subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from modul_basis import Modul
from ki import DATASETS, MODELS, KI_PYTHON, episodes, jobs, methods, auswahl

ACTIVE_STATES = jobs.ACTIVE + ("wartet (pausiert)",)


def fmt_time(seconds):
    if seconds is None:
        return "-"
    seconds = int(seconds)
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min" if seconds >= 3600 else f"{seconds // 60} min {seconds % 60:02d} s"


class VlaModul(Modul):
    def __init__(self):
        super().__init__("VLA-Studio", "Vision-Language-Action: Faehigkeiten durch Vorfuehren lernen (Imitation Learning)")
        ok = os.path.exists(KI_PYTHON)
        ttk.Label(self.root, text=("KI-Umgebung bereit (LeRobot, Grafikkarte)" if ok else
                                   "KI-Umgebung fehlt: Ordner ki-env nicht gefunden"),
                  foreground="#1f7a3a" if ok else "#b3261e", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16)
        body = ttk.Frame(self.root, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)

        ttk.Label(body, text="1 · Datensaetze (aufnehmen in ROS: Steuermodus eines Arms)",
                  font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.ds_list = self._tree(body, ("name", "aufgabe", "arm", "episoden", "dauer"),
                                  ("Datensatz", "Aufgabe", "Arm", "Episoden", "Dauer"), (150, 230, 70, 70, 70))
        left = ttk.Frame(body)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(4, 12))
        self.ds_list.master.pack(in_=left, fill="x")
        self.ds_list.master.lift(left)          # sonst verdeckt der (spaeter erzeugte) Rahmen die Liste
        self.ds_list.configure(height=2)
        self.ds_list.bind("<<TreeviewSelect>>", lambda e: self.show_episodes())
        ttk.Label(left, text="Episoden des gewaehlten Datensatzes:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        self.ep_list = self._tree(left, ("teil", "befehl", "dauer", "zeit"), ("Bauteil", "Befehl", "Dauer", "aufgenommen"),
                                  (110, 90, 60, 130))
        self.ep_list.configure(height=5, selectmode="extended", show="tree headings")
        self.ep_list.heading("#0", text="Session / Runde / Episode")
        self.ep_list.column("#0", width=260)
        self.ep_list.master.pack(fill="both", expand=True)
        self.ep_list.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        # Detail zur markierten Episode: letztes Bild, Kartonposition, Angaben aus dem Aufnahmeplan
        det = ttk.Frame(left)
        det.pack(fill="x", pady=(4, 0))
        self.det_img = tk.Label(det, text="", background="#222", foreground="#aaa", width=32, height=8)
        self.det_img.pack(side="left")
        self.det_map = tk.Canvas(det, width=180, height=100, background="#1b1b1b", highlightthickness=0)
        self.det_map.pack(side="left", padx=6)
        self.det_text = tk.StringVar()
        ttk.Label(det, textvariable=self.det_text, font=("Segoe UI", 8), justify="left", wraplength=320).pack(
            side="left", anchor="n")
        import tkinter.font as tkfont
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self.root).configure("Treeview", rowheight=int(line * 1.35))   # Zeilen nicht abschneiden
        self._det_photo = None
        erow = ttk.Frame(left)
        erow.pack(fill="x", pady=4)
        ttk.Button(erow, text="Markierte Episoden loeschen", command=self.delete_episodes).pack(side="left")
        ttk.Button(erow, text="Letzte Episode loeschen", command=self.delete_last).pack(side="left", padx=6)
        ttk.Label(erow, text="(landen im Papierkorb-Ordner)", font=("Segoe UI", 8)).pack(side="left")
        crow = ttk.Frame(left)
        crow.pack(fill="x")
        ttk.Button(crow, text="＋ Neuer Datensatz aus Episoden ...", command=self.compose).pack(side="left")
        ttk.Label(crow, text="(markierte Episoden sind schon vorausgewaehlt)", font=("Segoe UI", 8)).pack(side="left", padx=6)
        ttk.Button(crow, text="Datensatz vorbereiten ...", command=self.prepare).pack(side="left", padx=(12, 0))

        train = ttk.LabelFrame(body, text=" 2 · Training ", padding=10)
        train.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=(0, 12))
        ttk.Label(train, text="Datensatz:").grid(row=0, column=0, sticky="w")
        self.ds_choice = tk.StringVar()
        self.ds_box = ttk.Combobox(train, textvariable=self.ds_choice, state="readonly", width=34)
        self.ds_box.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(train, text="Methode:").grid(row=1, column=0, sticky="w")
        self.method_choice = tk.StringVar(value=methods.all_methods()[0].label)
        box = ttk.Combobox(train, textvariable=self.method_choice, state="readonly", width=34,
                           values=[m.label for m in methods.all_methods()])
        box.grid(row=1, column=1, sticky="w", pady=2)
        box.bind("<<ComboboxSelected>>", lambda e: self.show_method())
        self.method_text = tk.StringVar()
        ttk.Label(train, textvariable=self.method_text, wraplength=430, justify="left",
                  font=("Segoe UI", 9)).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 6))
        ttk.Label(train, text="Schritte:").grid(row=3, column=0, sticky="w")
        self.steps = tk.StringVar()
        ttk.Entry(train, textvariable=self.steps, width=10).grid(row=3, column=1, sticky="w")
        ttk.Label(train, text="1 Schritt = das Modell lernt aus einer Handvoll Schnappschuesse",
                  font=("Segoe UI", 8)).grid(row=3, column=1, sticky="w", padx=(90, 0))
        self.quiet = tk.BooleanVar(value=False)
        ttk.Checkbutton(train, text="Leise (Grafikkarte gedrosselt, dauert etwa doppelt so lange)",
                        variable=self.quiet).grid(row=5, column=1, sticky="w", pady=(6, 0))
        self.augment = tk.BooleanVar(value=True)
        ttk.Checkbutton(train, text="Bild-Variation (Helligkeit/Kontrast/Farbe zufaellig: robuster gegen Licht und Schatten)",
                        variable=self.augment).grid(row=4, column=0, columnspan=2, sticky="w", pady=(16, 0))
        ttk.Button(train, text="▶ Training starten / in Warteschlange", command=self.start_training).grid(
            row=6, column=1, sticky="w", pady=6)
        ttk.Label(train, text="Laeuft schon eines, startet das neue direkt danach (z. B. mehrere ueber Nacht).",
                  font=("Segoe UI", 8)).grid(row=7, column=0, columnspan=2, sticky="w")
        self.job_text = tk.StringVar(value="")
        ttk.Label(train, textvariable=self.job_text, font=("Consolas", 9), justify="left").grid(
            row=8, column=0, columnspan=2, sticky="nw", pady=(4, 0))
        self.job_bar = ttk.Progressbar(train, length=430, maximum=1.0)
        self.job_bar.grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(train, text="Warteschlange:", font=("Segoe UI", 9, "bold")).grid(row=10, column=0, sticky="w", pady=(6, 0))
        self.queue_list = self._tree(train, ("name", "zustand", "fortschritt", "optionen"),
                                     ("Training", "Zustand", "Fortschritt", "Optionen"), (220, 80, 75, 80))
        self.queue_list.configure(height=4)
        self.queue_list.master.grid(row=11, column=0, columnspan=2, sticky="ew")
        self.cancel_button = ttk.Button(train, text="Markiertes (sonst laufendes) Training abbrechen",
                                        command=self.cancel, state="disabled")
        self.cancel_button.grid(row=12, column=0, sticky="w", pady=6)
        self.pause_button = ttk.Button(train, text="Pausieren", command=self.toggle_pause, state="disabled")
        self.pause_button.grid(row=12, column=1, sticky="w", pady=6, padx=(8, 0))
        self.resume_button = ttk.Button(train, text="Weitertrainieren", command=self.resume, state="disabled")
        self.resume_button.grid(row=12, column=1, sticky="w", pady=6, padx=(100, 0))

        # Kamerawahl und Filter je Trainingslauf (wirkt auf den Start oben)
        sel = ttk.LabelFrame(train, text=" Kameras und Episoden fuer dieses Training ", padding=6)
        sel.grid(row=13, column=0, columnspan=2, sticky="ew")
        self.cam_frame = ttk.Frame(sel)
        self.cam_frame.pack(anchor="w")
        self.cam_vars = {}
        frow = ttk.Frame(sel)
        frow.pack(anchor="w", pady=(4, 0))
        ttk.Label(frow, text="Episoden:").pack(side="left")
        self.split = tk.StringVar(value="train")
        ttk.Combobox(frow, textvariable=self.split, state="readonly", width=7,
                     values=["train", "test", "alle"]).pack(side="left", padx=4)
        ttk.Label(frow, text="Befehle:").pack(side="left", padx=(8, 0))
        self.export = tk.StringVar(value="griff_alle")
        ttk.Combobox(frow, textvariable=self.export, state="readonly", width=16,
                     values=["griff_alle", "griff_allgemein", "nur spezifisch"]).pack(side="left", padx=4)
        for v in (self.split, self.export):
            v.trace_add("write", lambda *a: self.preview())
        self.preview_text = tk.StringVar()
        ttk.Label(sel, textvariable=self.preview_text, font=("Consolas", 8), justify="left",
                  wraplength=520).pack(anchor="w", pady=(4, 0))
        self.ds_choice.trace_add("write", lambda *a: self.build_cams())

        ttk.Label(body, text="3 · Fertige Modelle (= gelernte Faehigkeiten)", font=("Segoe UI", 12, "bold")).grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.model_list = self._tree(body, ("name", "methode", "aufgabe", "arm", "datum"),
                                     ("Modell", "Methode", "Aufgabe", "aufgenommen an", "fertig"), (260, 80, 300, 110, 140))
        self.model_list.master.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 6))
        self.assign_row = ttk.Frame(body)
        self.assign_row.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(self.assign_row, text="Ausgewaehltes Modell im Arm (Quelle 'KI') verwenden:").pack(side="left")
        self.arm_buttons = ttk.Frame(self.assign_row)
        self.arm_buttons.pack(side="left")
        ttk.Label(self.assign_row, text="  Aufgabe (Text fuer SmolVLA):").pack(side="left")
        self.task = tk.StringVar()
        ttk.Entry(self.assign_row, textvariable=self.task, width=34).pack(side="left", padx=4)
        ttk.Button(self.assign_row, text="Ordner oeffnen", command=self.open_folder).pack(side="left", padx=(12, 0))
        self.info = tk.StringVar()
        ttk.Label(body, textvariable=self.info, font=("Segoe UI", 9)).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.jobs = []
        self.arm_keys = None
        self.show_method()
        self.refresh()
        self.poll_jobs()

    # --- Hilfen ---
    def _tree(self, parent, cols, heads, widths):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=8, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="w")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        return tree

    def _fill(self, tree, rows):
        current = [tuple(tree.item(i, "values")) for i in tree.get_children()]
        if [tuple(str(v) for v in r[1]) for r in rows] == current:
            return
        sel = tree.selection()
        tree.delete(*tree.get_children())
        for iid, values in rows:
            tree.insert("", "end", iid=iid, values=values)
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])

    # --- Episoden ---
    def current_dataset(self):
        sel = self.ds_list.selection()
        return episodes.Dataset(os.path.join(DATASETS, sel[0])) if sel else None

    def show_episodes(self):
        """Episoden anzeigen; bei Aufnahmeplaenen gruppiert nach Session und Runde."""
        ds = self.current_dataset()
        tree = self.ep_list
        sig = (ds.name, tuple(ds.episodes())) if ds is not None else None
        if sig == getattr(self, "_ep_sig", object()):
            return                                       # unveraendert: nicht neu aufbauen (kein Flackern)
        self._ep_sig = sig
        sel = [i for i in tree.selection()]
        tree.delete(*tree.get_children())
        if ds is None:
            return
        infos = {ep: ds.episode_info(ep) or {} for ep in ds.episodes()}
        plan = self._plan_rounds(ds)
        names = self._part_names(ds)
        for ep, info in infos.items():
            parent = ""
            if info.get("runde") is not None:
                s, r = info.get("session"), info.get("runde")
                sid, rid = f"s{s}", f"r{r}"
                if not tree.exists(sid):
                    tree.insert("", "end", iid=sid, text=f"Session {s}", open=True)
                if not tree.exists(rid):
                    pr = plan.get(r, {})
                    soll = len(pr.get("auftraege", [])) or "?"
                    have = sum(1 for i in infos.values() if i.get("runde") == r)
                    pl = info.get("platzierung_id", "")
                    tree.insert(sid, "end", iid=rid, open=True,
                                text=f"Runde {r} · {pl} {info.get('ausrichtung', '')} · {have}/{soll}")
                parent = rid
            teil = names.get(info.get("zielbauteil"), info.get("zielbauteil", ""))
            befehl = info.get("befehlsart", "") + (f" ({info['lage']})" if info.get("lage") else "")
            tree.insert(parent, "end", iid=ep, text=ep,
                        values=(teil, befehl, f"{info.get('seconds', 0):.1f} s", info.get("recorded", "")))
        sel = [i for i in sel if tree.exists(i)]
        if sel:
            tree.selection_set(sel)

    def _plan_rounds(self, ds):
        """Runden des Aufnahmeplans (Fortschritt) dieses Datensatzes: {runde: runde-dict}."""
        pid = ds.meta.get("plan")
        if not pid:
            return {}
        try:
            from aufnahme import plan as P
            path = os.path.join(P.runs_root(), pid, "plan.json")
            with open(path, encoding="utf-8") as f:
                import json
                return {r["runde"]: r for r in json.load(f)["runden"]}
        except Exception:
            return {}

    def _part_names(self, ds):
        try:
            from aufnahme import plan as P
            d = P.load_definition(ds.meta.get("plan"))
            self._anord = {k: v["name"] for k, v in d["anordnungen"].items()}
            return {k: v["kurz"] for k, v in d["bauteile"].items()}
        except Exception:
            self._anord = {}
            return {}

    def selected_episodes(self):
        return [i for i in self.ep_list.selection() if i.startswith("ep_")]

    def show_detail(self):
        ds = self.current_dataset()
        eps = self.selected_episodes()
        c = self.det_map
        c.delete("all")
        if ds is None or not eps:
            self.det_text.set("")
            self.det_img.configure(image="", text="")
            return
        ep = eps[0]
        info = ds.episode_info(ep) or {}
        # letztes Bild (Haupt-Kamera)
        cams = info.get("kameras") or ds.meta.get("cameras") or []
        cam = "wrist" if "wrist" in cams else (cams[0] if cams else None)
        frame = None
        try:
            import cv2
            frame = ds.last_frame(ep, cam, cv2) if cam else None
            if frame is not None:
                h, w = frame.shape[:2]
                sc = min(200 / w, 112 / h)
                small = cv2.resize(frame, (int(w * sc), int(h * sc)))
                ok, ppm = cv2.imencode(".ppm", small)
                self._det_photo = tk.PhotoImage(data=ppm.tobytes(), format="PPM") if ok else None
        except Exception:
            frame = None
        if frame is not None and self._det_photo is not None:
            self.det_img.configure(image=self._det_photo, text="", width=200, height=112)
        else:
            self.det_img.configure(image="", text="kein Bild", width=32, height=8)
        lines = [f"{ep} · {info.get('task', '')}"]
        if info.get("runde") is not None:
            lines.append(f"Session {info.get('session')} · Runde {info.get('runde')} · {info.get('platzierung_id', '')} "
                         f"{info.get('ausrichtung', '')}")
            an = getattr(self, "_anord", {}).get(info.get("anordnung"), info.get("anordnung", ""))
            lines.append(f"Ladung {info.get('ladung', '')} · Anordnung {an} · "
                         f"Füllstand {info.get('fuellstand', '')}"
                         + (f" · Licht {info['licht']}" if info.get("licht") else ""))
            lines.append(f"Befehl {info.get('befehlsart', '')}" + (f" · Lage {info['lage']}" if info.get("lage") else "")
                         + f" · Maske {info.get('maske', '')}")
        lines.append(f"{info.get('seconds', 0):.1f} s · {info.get('frames', 0)} Bilder · {info.get('recorded', '')}")
        self.det_text.set("\n".join(lines))
        p = info.get("platzierung_soll")
        if p:
            self._draw_box(c, p, info)

    def _draw_box(self, c, p, info):
        """Halbring (Arbeitsbereich) und Karton von oben, wie auf der Karte im Steuermodus."""
        try:
            from aufnahme import plan as P, geometrie as G
            geo = P.load_definition(info.get("plan"))["geometrie"]
        except Exception:
            geo = {"r_innen": 16, "r_aussen": 42, "laenge": 25, "breite": 15.5}
        W, H = 180, 100
        ra, ri = geo["r_aussen"], geo["r_innen"]
        sc = min((W - 10) / (2 * ra), (H - 12) / ra)
        ox, oy = W / 2, H - 6
        to = lambda x, y: (ox + x * sc, oy - y * sc)
        c.create_line(0, oy, W, oy, fill="#bbb", width=2)
        c.create_arc(ox - ra * sc, oy - ra * sc, ox + ra * sc, oy + ra * sc, start=0, extent=180,
                     fill="#203a2a", outline="#3a6a4a")
        c.create_arc(ox - ri * sc, oy - ri * sc, ox + ri * sc, oy + ri * sc, start=0, extent=180,
                     fill="#1b1b1b", outline="#3a6a4a")
        pts = G.corners(p["x"], p["y"], p["winkel"], geo["laenge"], geo["breite"])
        flat = [v for q in pts for v in to(*q)]
        c.create_polygon(*flat, fill="#8a6a3a", outline="#f2c14e", width=2)
        c.create_text(ox, oy - 2, text="Roboter", fill="#ddd", anchor="s", font=("Segoe UI", 7))

    def _trash(self, eps):
        ds = self.current_dataset()
        if ds is None or not eps:
            return
        if not messagebox.askyesno("Episoden loeschen", f"{len(eps)} Episode(n) aus '{ds.name}' loeschen?\n\n"
                                   + ", ".join(eps) + "\n\nSie werden in den Papierkorb-Ordner verschoben "
                                   "(ki_daten/papierkorb) und sind fuer das Training weg.", parent=self.root):
            return
        for ep in eps:
            ds.trash_episode(ep)
        self.show_episodes()
        self.refresh_lists()

    def delete_episodes(self):
        self._trash(self.selected_episodes())

    def delete_last(self):
        ds = self.current_dataset()
        if ds is not None and ds.episodes():
            self._trash([ds.episodes()[-1]])

    def method(self):
        return next(m for m in methods.all_methods() if m.label == self.method_choice.get())

    def show_method(self):
        m = self.method()
        self.method_text.set(f"{m.description}\n{m.notes}".strip())
        self.steps.set(str(m.default_steps))

    def arm_label(self, key):
        return next((a["label"] for a in self.arms if a["arm"] == key), key or "")

    # --- Arme aus ROS ---
    def on_arms(self, arms):
        keys = [(a["arm"], a["label"]) for a in arms]
        if keys != self.arm_keys:
            self.arm_keys = keys
            for w in self.arm_buttons.winfo_children():
                w.destroy()
            for key, label in keys:
                ttk.Button(self.arm_buttons, text=label, command=lambda k=key: self.assign(k)).pack(side="left", padx=3)
            if not keys:
                ttk.Label(self.arm_buttons, text="(ROS nicht verbunden)").pack(side="left", padx=3)
        assigned = [f"{a['label']}: {a['ki_model']}" for a in arms if a.get("ki_model")]
        self.info.set("Zugewiesen · " + (" · ".join(assigned) if assigned else "noch keinem Arm"))

    # --- Listen ---
    def refresh(self):
        self.refresh_lists()
        rows = self.ds_list.get_children()
        if rows and not self.ds_list.selection():
            # ohne Auswahl bliebe die Episodenliste leer: zuletzt benutzten (oder neuesten) Datensatz waehlen
            from ki import history
            last = next((r for r in history.load()["datensatz"] if r in rows), rows[-1])
            self.ds_list.selection_set(last)
        self.show_episodes()
        self.root.after(2000, self.refresh)

    def refresh_lists(self):
        sets = episodes.datasets()
        names = [d.name for d in sets]
        if list(self.ds_box["values"]) != names:
            self.ds_box["values"] = names
            if not self.ds_choice.get() and names:
                self.ds_choice.set(names[-1])
        self._fill(self.ds_list, [(d.name, (d.name, d.meta.get("task", ""), self.arm_label(d.meta.get("arm")),
                                            len(d.episodes()), f"{d.frames() / episodes.FPS / 60:.1f} min")) for d in sets])
        known = {x.key: x.label for x in methods.all_methods()}
        self._fill(self.model_list, [(m["name"], (m["name"], known.get(m["method"], m["method"]), m.get("task", ""),
                                                  self.arm_label(m.get("arm")), m.get("created", "")))
                                     for m in jobs.models()])

    def training_queue(self):
        if getattr(self, "_queue", None) is None:
            self._queue = jobs.DetachedQueue()
        return self._queue

    def poll_jobs(self):
        def got(snapshot):
            self.jobs = snapshot or []
            active = [j for j in self.jobs if j["state"] in ACTIVE_STATES]
            j = active[0] if active else (self.jobs[-1] if self.jobs else None)
            if j:
                frac = j["step"] / max(1, j["steps"])
                self.job_bar["value"] = frac
                loss = f"{j['loss']:.3f}" if j["loss"] is not None else "-"
                self.job_text.set(f"{j['name']}\nZustand: {j['state']} · Schritt {j['step']}/{j['steps']} ({frac:.0%})"
                                  f" · Fehler (loss) {loss}\nRestzeit: {fmt_time(j['eta_s'])}"
                                  + (f" · weitere in Warteschlange: {len(active) - 1}" if len(active) > 1 else "")
                                  + f"\n{(j['message'] or '')[:70]}")
            self.cancel_button.configure(state="normal" if active else "disabled")
            self.resume_button.configure(state="normal" if self.resume_target() else "disabled")
            target = self.pause_target()
            self.pause_button.configure(state="normal" if target else "disabled",
                                        text="Fortsetzen" if target and "pausiert" in target["state"] else "Pausieren")
            self._fill(self.queue_list, [(x["name"], (x["name"], x["state"], f"{x['step'] / max(1, x['steps']):.0%}",
                                                      ", ".join(o for o, on in (("leise", x.get("quiet")),
                                                                                 ("Bild", x.get("augment"))) if on)))
                                         for x in self.jobs])
            self.root.after(1500, self.poll_jobs)
        self.background(lambda: self.training_queue().snapshot(), got,
                        lambda e: self.root.after(3000, self.poll_jobs))

    # --- Kamerawahl / Vorschau ---
    def build_cams(self):
        for w in self.cam_frame.winfo_children():
            w.destroy()
        self.cam_vars = {}
        name = self.ds_choice.get()
        if not name:
            return
        ds = episodes.Dataset(os.path.join(DATASETS, name))
        cams = ds.meta.get("cameras") or []
        self.is_plan = bool(ds.meta.get("plan"))
        ttk.Label(self.cam_frame, text="Kameras:").pack(side="left")
        for c in cams:
            v = tk.BooleanVar(value=(c == "wrist") if "wrist" in cams else True)   # Standard: nur wrist
            v.trace_add("write", lambda *a: self.preview())
            ttk.Checkbutton(self.cam_frame, text=c, variable=v).pack(side="left", padx=4)
            self.cam_vars[c] = v
        self.preview()

    def selection(self):
        """-> (kameras, filter, export) fuer training.start; Filter nur bei Plan-Datensaetzen sinnvoll."""
        cams = [c for c, v in self.cam_vars.items() if v.get()]
        exp = self.export.get()
        filters = {"split": self.split.get(), "befehle": "spezifisch" if exp == "nur spezifisch" else
                   auswahl.EXPORTE.get(exp, {}).get("befehle", "alle")}
        return cams, filters, (exp if exp in auswahl.EXPORTE and getattr(self, "is_plan", False) else None)

    def preview(self):
        name = self.ds_choice.get()
        if not name or not self.cam_vars:
            self.preview_text.set("")
            return
        ds = episodes.Dataset(os.path.join(DATASETS, name))
        cams, filters, _ = self.selection()
        eps, why = auswahl.select(ds, cams, filters)
        st = auswahl.stats(ds, eps)
        fmt = lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "-"
        lines = [f"{st['episoden']} von {len(ds.episodes())} Episoden, {st['bilder']} Bilder",
                 f"Bauteil: {fmt(st['bauteil'])}", f"Befehl: {fmt(st['befehlsart'])} · Ausrichtung: {fmt(st['ausrichtung'])}",
                 f"Platzierungen: {len(st['platzierungen'])}"]
        lines += ["⚠ " + w for w in auswahl.warnings(ds, cams, eps, why)]
        self.preview_text.set("\n".join(lines))

    # --- Aktionen ---
    def start_training(self):
        name = self.ds_choice.get()
        if not name:
            messagebox.showinfo("Training", "Erst im Steuermodus des Harness Episoden aufnehmen.", parent=self.root)
            return
        try:
            steps = int(self.steps.get())
        except ValueError:
            messagebox.showerror("Training", "Schritte muss eine Zahl sein.", parent=self.root)
            return
        m = self.method()
        quiet, augment = self.quiet.get(), self.augment.get()
        ds = episodes.Dataset(os.path.join(DATASETS, name))
        cams, filters, export = self.selection()
        eps, _ = auswahl.select(ds, cams, filters)
        if not eps:
            messagebox.showerror("Training", "Mit dieser Kamerawahl und diesen Filtern bleibt keine Episode uebrig.",
                                 parent=self.root)
            return
        active = [j for j in self.jobs if j["state"] in ACTIVE_STATES]
        when = (f"Es laufen/warten schon {len(active)} Training(s): dieses startet direkt danach."
                if active else "Startet sofort.")
        if not messagebox.askokcancel("Training starten",
                f"{m.label} mit '{ds.meta.get('name', name)}' ({len(eps)} von {len(ds.episodes())} Episoden, "
                f"Kameras {', '.join(cams)}), {steps} Schritte"
                + (", leise" if quiet else "") + (", mit Bild-Variation" if augment else "") + f".\n\n{when}\n\n"
                "Das Training laeuft im eigenen Trainings-Dienst auf der Grafikkarte - auch ohne Harness und wenn dieses Fenster zu ist.",
                parent=self.root):
            return
        # direkt an den Trainings-Dienst (ki/trainer.py): geht auch ohne laufenden Harness
        self.background(lambda: self.training_queue().add(name, m.key, steps, quiet=bool(quiet), augment=bool(augment),
                                                          cameras=cams, filters=filters, export=export).info(),
                        error=lambda e: messagebox.showerror("Training", e, parent=self.root))

    def pause_target(self):
        """Markiertes aktives Training, sonst das laufende/pausierte."""
        active = [j for j in self.jobs if j["state"] in ACTIVE_STATES]
        sel = [j for j in active if j["name"] in self.queue_list.selection()]
        running = [j for j in active if j["state"] != "wartet"]
        return (sel or running or [None])[0]

    def resume_target(self):
        """Markiertes (sonst juengstes) abgebrochenes Training mit Zwischenstand."""
        ok = [j for j in self.jobs if j.get("weiter_ab")]
        sel = [j for j in ok if j["name"] in self.queue_list.selection()]
        return (sel or ok[-1:] or [None])[0]

    def resume(self):
        j = self.resume_target()
        if j and messagebox.askokcancel("Weitertrainieren",
                f"{j['name']}" + chr(10) * 2 + f"Weiter ab Schritt {j['weiter_ab']} von {j['steps']} (letzter Zwischenstand; "
                "was danach kam, wird noch einmal gelernt).", parent=self.root):
            self.background(lambda: self.training_queue().resume(j["name"]),
                            error=lambda e: messagebox.showerror("Weitertrainieren", e, parent=self.root))

    def toggle_pause(self):
        j = self.pause_target()
        if j:
            on = "pausiert" not in j["state"]
            self.background(lambda: self.training_queue().pause(j["name"], on))

    def cancel(self):
        active = [j["name"] for j in self.jobs if j["state"] in ACTIVE_STATES]
        sel = [n for n in self.queue_list.selection() if n in active]
        name = sel[0] if sel else (active[0] if active else None)
        if name and messagebox.askyesno("Abbrechen", f"Training {name} abbrechen?", parent=self.root):
            self.background(lambda: self.training_queue().cancel(name))

    def prepare(self):
        """Eigenes Fenster: Datensaetze zusammenfuehren, filtern (vla_datensatz.py)."""
        import vla_datensatz
        ds = self.current_dataset()
        vla_datensatz.DatasetPrep(self, [ds.name] if ds else [])

    def compose(self):
        ds = self.current_dataset()
        pre = {(ds.name, ep) for ep in self.selected_episodes()} if ds else set()
        ComposeDialog(self, pre)

    def assign(self, key):
        sel = self.model_list.selection()
        if not sel:
            messagebox.showinfo("Modell", "Bitte oben ein Modell anklicken.", parent=self.root)
            return
        args = {"arm": key, "modell": sel[0]}
        if self.task.get().strip():
            args["aufgabe"] = self.task.get().strip()
        self.background(lambda: self.ros.call("ki.modell_waehlen", **args),
                        error=lambda e: messagebox.showerror("Modell", e, parent=self.root))

    def open_folder(self):
        path = os.path.dirname(DATASETS)
        os.makedirs(path, exist_ok=True)
        subprocess.Popen(["explorer", os.path.normpath(path)])


class ComposeDialog:
    """Episoden aus allen Datensaetzen anhaken -> neuer Datensatz (Kopien). Klick = an/aus, Klick auf einen
    Datensatz = alle seine Episoden, Umschalt-Klick = Bereich bis zum letzten Klick."""
    ON, OFF = "☑", "☐"

    def __init__(self, studio, preselected=()):
        self.studio = studio
        self.win = tk.Toplevel(studio.root)
        self.win.title("Neuer Datensatz aus Episoden")
        self.win.geometry("760x620")
        self.win.transient(studio.root)
        ttk.Label(self.win, padding=(12, 10, 12, 4), wraplength=720, justify="left",
                  text="Episoden anhaken, die in den neuen Datensatz sollen. Klick = an/aus · Klick auf einen Datensatz "
                       "= alle seine Episoden · Umschalt-Klick = alles bis zum letzten Klick. Die Spalte 'aufgenommen' "
                       "hilft z. B. Tageslicht- und Abend-Aufnahmen zu trennen. Die Quellen bleiben unveraendert.").pack(anchor="w")
        frame = ttk.Frame(self.win, padding=(12, 0))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("dauer", "zeit"), selectmode="none")
        self.tree.heading("#0", text="Datensatz / Episode")
        self.tree.heading("dauer", text="Dauer")
        self.tree.heading("zeit", text="aufgenommen")
        self.tree.column("#0", width=330)
        self.tree.column("dauer", width=80)
        self.tree.column("zeit", width=170)
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.checked, self.labels, self.last = set(preselected), {}, None
        for d in episodes.datasets():
            node = "ds:" + d.name
            self.labels[node] = f"{d.name}  ({len(d.episodes())} Episoden · {d.meta.get('task', '')})"
            self.tree.insert("", "end", iid=node, text="", open=any(k[0] == d.name for k in self.checked))
            for ep in d.episodes():
                info = d.episode_info(ep)
                iid = f"ep:{d.name}/{ep}"
                self.labels[iid] = ep
                self.tree.insert(node, "end", iid=iid, text="",
                                 values=(f"{info.get('seconds', 0):.1f} s", info.get("recorded", "")))
        self.tree.bind("<Button-1>", self.click)
        form = ttk.Frame(self.win, padding=12)
        form.pack(fill="x")
        ttk.Label(form, text="Name:").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar()
        ttk.Entry(form, textvariable=self.name, width=40).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(form, text="Aufgabe:").grid(row=1, column=0, sticky="w")
        self.task = tk.StringVar()
        ttk.Entry(form, textvariable=self.task, width=60).grid(row=1, column=1, sticky="w", pady=2)
        self.eigene = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, variable=self.eigene, text="Aufgabentext je Episode behalten (mehrere Aufgaben, "
                        "fuer SmolVLA)").grid(row=4, column=1, sticky="w", pady=(4, 0))
        self.count = tk.StringVar()
        ttk.Label(form, textvariable=self.count, font=("Segoe UI", 9, "bold")).grid(row=2, column=1, sticky="w", pady=4)
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=1, sticky="w")
        self.ok = ttk.Button(buttons, text="Datensatz anlegen", command=self.create)
        self.ok.pack(side="left")
        ttk.Button(buttons, text="Abbrechen", command=self.win.destroy).pack(side="left", padx=6)
        self.redraw()

    def picks(self):
        """Angehakte Episoden in Listenreihenfolge."""
        out = []
        for node in self.tree.get_children():
            for iid in self.tree.get_children(node):
                key = tuple(iid[3:].split("/", 1))
                if key in self.checked:
                    out.append(key)
        return out

    def redraw(self):
        for node in self.tree.get_children():
            kids = [tuple(i[3:].split("/", 1)) for i in self.tree.get_children(node)]
            n = sum(k in self.checked for k in kids)
            mark = self.ON if kids and n == len(kids) else ("◪" if n else self.OFF)
            self.tree.item(node, text=f"{mark} {self.labels[node]}" + (f"  · {n} gewaehlt" if n else ""))
            for iid in self.tree.get_children(node):
                key = tuple(iid[3:].split("/", 1))
                self.tree.item(iid, text=f"{self.ON if key in self.checked else self.OFF} {self.labels[iid]}")
        picks = self.picks()
        self.count.set(f"{len(picks)} Episode(n) ausgewaehlt")
        if picks and not self.task.get():
            first = episodes.Dataset(os.path.join(DATASETS, picks[0][0]))
            self.task.set(first.meta.get("task", ""))

    def click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_element(event.x, event.y) in ("Treeitem.indicator", "indicator"):
            return
        if iid.startswith("ds:"):
            kids = [tuple(i[3:].split("/", 1)) for i in self.tree.get_children(iid)]
            if all(k in self.checked for k in kids):
                self.checked.difference_update(kids)
            else:
                self.checked.update(kids)
                self.tree.item(iid, open=True)
            self.last = None
        else:
            key = tuple(iid[3:].split("/", 1))
            parent = self.tree.parent(iid)
            if event.state & 0x0001 and self.last and self.tree.parent(self.last) == parent:
                kids = list(self.tree.get_children(parent))
                a, b = sorted((kids.index(self.last), kids.index(iid)))
                turn_on = tuple(self.last[3:].split("/", 1)) in self.checked
                for i in kids[a:b + 1]:
                    k = tuple(i[3:].split("/", 1))
                    (self.checked.add if turn_on else self.checked.discard)(k)
            elif key in self.checked:
                self.checked.discard(key)
            else:
                self.checked.add(key)
            self.last = iid
        self.redraw()
        return "break"

    def create(self):
        picks, name, task = self.picks(), self.name.get().strip(), self.task.get().strip()
        if not picks or not name or not task:
            messagebox.showinfo("Neuer Datensatz", "Bitte Episoden anhaken, Name und Aufgabe eintragen.", parent=self.win)
            return
        self.ok.configure(state="disabled")
        self.count.set(f"Kopiere {len(picks)} Episoden ...")

        def done(ds):
            from ki import history
            history.remember(ds.name, task)
            self.studio.refresh_lists()
            if self.studio.ds_list.exists(ds.name):
                self.studio.ds_list.selection_set(ds.name)
            self.studio.ds_choice.set(ds.name)
            messagebox.showinfo("Neuer Datensatz", f"'{ds.name}' mit {len(ds.episodes())} Episoden angelegt.\n"
                                "Er steht jetzt beim Training zur Auswahl.", parent=self.studio.root)
            self.win.destroy()

        def failed(e):
            self.ok.configure(state="normal")
            self.redraw()
            messagebox.showerror("Neuer Datensatz", e, parent=self.win)

        eigene = bool(self.eigene.get())
        self.studio.background(lambda: episodes.compose(name, task, picks, eigene_aufgaben=eigene), done, failed)


if __name__ == "__main__":
    VlaModul().run()
