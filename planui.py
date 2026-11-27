"""Plan-Ansicht im Steuermodus: fuehrt den Bediener anhand eines Aufnahmeplans durch Runden und Griffe.

Links:        Wrist-Cam live mit Masken-Fuehrung (bzw. nach einem spezifischen Griff das Startbild mit 3x3-Raster)
Mitte oben:   Rundenanweisung mit statischer Karte (Tischkante, Basis, Halbring, Karton mit Anflugseite)
Mitte unten:  Griffanweisung (Bauteil, Befehl, Kartoninhalt), Nicht greifbar / Maske manuell / Behalten / Verwerfen
Rechts:       Auftragsliste der Runde, alle Runden kompakt, Soll/Ist je Bauteil

Bewegt wird nichts von hier aus: der Bediener steuert per Leader (Teleoperation). Diese Ansicht startet und
stoppt nur die Aufnahme (automatisch oder per Taste) und schreibt Plan-Fortschritt und Metadaten.
"""
import json, math, os, re, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from aufnahme import plan as P, maske as M, automatik as AU, geometrie as G

BG, FG, DIM = "#111", "#eee", "#888"


class PlanPanel(tk.Frame):
    def __init__(self, parent, view, plan_id):
        super().__init__(parent, background=BG)
        self.view, self.lab, self.key = view, view.lab, view.key
        self.run = P.PlanRun.open(plan_id)
        self.defn = self.run.defn
        self.obj = dict(self.defn.get("objekt") or {})      # Gegenstand statt Karton (z. B. Elektrodose)
        self.cv2 = self.lab.cams.cameras.cv2
        self.mask_cfg = dict(self.defn.get("maske", {}))
        auto_cfg = dict(self.defn.get("automatik", {}))
        self.auto = AU.Automatik(auto_cfg, greifer_zu=self._gripper_closed())
        self.auto_on = tk.BooleanVar(value=auto_cfg.get("an", True))
        self.mask_manual = False
        self.mask_res = {"ok": False, "ok_a": False, "ok_b": False, "werte": {}}
        self.pending = None              # Episode wartet auf Behalten/Verwerfen: {"start", "stopp", ...}
        self.lage = None                 # (zeile, spalte) beim spezifischen Griff
        self.dataset = None
        self.photo = None
        self.cam_locked = False
        self.sharp_next = 0.0            # naechste Live-Schaerfemessung (monotonic)
        self.sharp_busy = False
        self.review_round = None
        self.review_open = False
        self.thumbnails = {}
        self._build()
        self.refresh_all()
        self.after(150, self._tick)

    # ------------------------------------------------------------------ Aufbau
    def _build(self):
        for i, wgt in enumerate((5, 4, 4)):
            self.columnconfigure(i, weight=wgt, uniform="plan")
        self.rowconfigure(0, weight=1)
        lbl = lambda p, **kw: tk.Label(p, background=BG, foreground=FG, justify="left", **kw)

        # links: Wrist-Cam
        left = tk.Frame(self, background=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        lbl(left, text="Wrist-Cam · Startpose", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.cam = tk.Label(left, background="#000", foreground=DIM, text="Wrist-Cam wird gesucht ...",
                            font=("Segoe UI", 12))
        self.cam.pack(fill="both", expand=True)
        self.cam.bind("<Button-1>", self._click_grid)
        row = tk.Frame(left, background=BG)
        row.pack(fill="x", pady=4)
        self.mask_text = tk.StringVar()
        lbl(row, textvariable=self.mask_text, font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(row, text="Maske manuell", command=self.manual_mask).pack(side="right")
        tk.Button(row, text="Maske irrt (Bild merken)", command=self.mask_wrong).pack(side="right", padx=4)
        self.auto_text = tk.StringVar()
        lbl(left, textvariable=self.auto_text, font=("Segoe UI", 10)).pack(anchor="w")
        srow = tk.Frame(left, background=BG)
        srow.pack(fill="x", pady=(2, 0))
        self.sharp_text = tk.StringVar()
        self.sharp_lbl = lbl(srow, textvariable=self.sharp_text, font=("Segoe UI", 9))
        self.sharp_lbl.pack(side="left")
        tk.Button(srow, text="Schärfe messen + speichern", command=self.measure_sharpness).pack(side="right")

        # Mitte
        mid = tk.Frame(self, background=BG)
        mid.grid(row=0, column=1, sticky="nsew", padx=4)
        self.round_title = tk.StringVar()
        first = lbl(mid, textvariable=self.round_title, font=("Segoe UI", 14, "bold"))
        first.pack(anchor="w")
        self.now_text = tk.StringVar()
        self.now_box = tk.Label(mid, textvariable=self.now_text, background="#f2c14e", foreground="#111",
                                font=("Segoe UI", 15, "bold"), justify="left", anchor="w", padx=10, pady=8)
        self.now_box.pack(fill="x", pady=(2, 4))
        self.round_banner = tk.Label(mid, text="", background="#f2c14e", foreground="#111",
                                     font=("Segoe UI", 12, "bold"), wraplength=520, justify="left", padx=8, pady=4)
        self.map = tk.Canvas(mid, background="#1b1b1b", highlightthickness=0, height=210)
        self.map.pack(fill="x", pady=4)
        self.map.bind("<Configure>", lambda e: self.draw_map())
        self.round_text = tk.StringVar()
        self.round_lbl = lbl(mid, textvariable=self.round_text, font=("Segoe UI", 9), wraplength=520)
        self.round_lbl.pack(anchor="w")
        rb = self.round_row = tk.Frame(mid, background=BG)
        rb.pack(fill="x", pady=4)
        self.ready_btn = tk.Button(rb, text="✔ " + self.obj.get("bereit", "Karton liegt bereit") + " (F3)", background="#1f7a3a", foreground="white",
                                   font=("Segoe UI", 10, "bold"), command=self.confirm_round)
        self.ready_btn.pack(side="left")
        self.unreachable_btn = tk.Button(rb, text="Nicht erreichbar", command=self.unreachable)
        self.unreachable_btn.pack(side="left", padx=6)
        ttk.Separator(mid).pack(fill="x", pady=3)
        self.grip_title = tk.StringVar()
        lbl(mid, textvariable=self.grip_title, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.grip_text = tk.StringVar()
        tk.Label(mid, textvariable=self.grip_text, background=BG, foreground=DIM, font=("Segoe UI", 9),
                 wraplength=520, justify="left").pack(anchor="w")
        self.cmd_text = tk.StringVar()
        tk.Label(mid, textvariable=self.cmd_text, background="#1d2b3a", foreground="#cfe3ff",
                 font=("Consolas", 11, "bold"), padx=6, pady=2, justify="left").pack(anchor="w", pady=2)
        self.hint_text = tk.StringVar()
        tk.Label(mid, textvariable=self.hint_text, background=BG, foreground="#f2c14e",
                 font=("Segoe UI", 9, "bold"), wraplength=520, justify="left").pack(anchor="w")
        gb = tk.Frame(mid, background=BG)
        gb.pack(side="bottom", fill="x", pady=3, before=first)   # Knoepfe immer sichtbar
        btn = {"font": ("Segoe UI", 10, "bold"), "padx": 6}
        self.start_btn = tk.Button(gb, text="● Start (F5)", background="#b3261e", foreground="white",
                                   command=self.manual_start, **btn)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        self.keep_btn = tk.Button(gb, text="✔ Behalten (F7)", background="#1f7a3a", foreground="white",
                                  command=lambda: self.decide(True), **btn)
        self.keep_btn.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        self.drop_btn = tk.Button(gb, text="✖ Verwerfen (F8)", command=lambda: self.decide(False), **btn)
        self.drop_btn.grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        tk.Button(gb, text="Nicht greifbar (F4)", command=self.not_graspable, **btn).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        gb.columnconfigure((0, 1), weight=1)
        # Texte in der Mitte an die Spaltenbreite anpassen (sonst abgeschnitten)
        mid.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 16))
                                           for w in mid.winfo_children() if isinstance(w, tk.Label)])
        arow = tk.Frame(mid, background=BG)
        arow.pack(side="bottom", anchor="w", before=gb)
        tk.Checkbutton(arow, text="Automatischer Start/Stopp", variable=self.auto_on, background=BG, foreground=FG,
                       selectcolor="#333", activebackground=BG).pack(side="left")
        tk.Label(arow, text="   Start nach", background=BG, foreground=FG).pack(side="left")
        self.countdown = tk.StringVar(value=str(self.auto.c.get("countdown_s", 2.0)))
        tk.Spinbox(arow, from_=0.0, to=10.0, increment=0.1, format="%.1f", width=5,
                   textvariable=self.countdown).pack(side="left", padx=4)
        tk.Label(arow, text="s", background=BG, foreground=FG).pack(side="left")

        # rechts: Plan (oben Runden-Kacheln zum Wechseln, darunter die Griffe der gewaehlten Runde)
        right = tk.Frame(self, background=BG)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        lbl(right, text="Runden (anklicken)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.round_grid = tk.Frame(right, background=BG)
        self.round_grid.pack(anchor="w", fill="x", pady=(2, 0))
        tk.Label(right, text="grün fertig · gelb aktuell · blau begonnen", font=("Segoe UI", 8),
                 background=BG, foreground=DIM).pack(anchor="w", pady=(0, 6))
        self.orders_title = lbl(right, font=("Segoe UI", 11, "bold"), wraplength=380)
        self.orders_title.pack(anchor="w")
        self.arr_text = tk.Label(right, background=BG, foreground="#f2c14e", font=("Segoe UI", 9), justify="left",
                                 wraplength=380)
        self.arr_text.pack(anchor="w", pady=(0, 4))
        self.orders = tk.Frame(right, background="#1b1b1b")
        self.orders.pack(fill="x")
        self.orders.columnconfigure(0, weight=1)
        brow = tk.Frame(right, background=BG)
        brow.pack(anchor="w", fill="x", pady=4)
        self.current_round_btn = tk.Button(brow, text="◀ Aktuelle Runde", command=self._show_current_round)
        self.repeat_btn = tk.Button(brow, command=self._repeat_round)
        self.repeat_btn.pack(side="right")
        self.soll_ist = tk.StringVar()
        lbl(right, textvariable=self.soll_ist, font=("Consolas", 9)).pack(anchor="w", pady=(6, 4))

    # ------------------------------------------------------------------ Hilfen
    def _gripper_closed(self):
        from ki import poses
        p = poses.load().get(self.key, {}).get("_greifer_zu")
        if p:
            return int(p[5])
        try:
            import so101
            return int(so101.CFG[self.key]["rest_pose"]["6"])
        except Exception:
            return 1420

    def _wrist_short(self):
        return self.defn["kameras"][self.defn.get("haupt_kamera", "wrist")]

    def _frames(self):
        return self.lab.arm_frames(self.key)

    def _available_cams(self):
        """Plan-Kameras (feste Namen), die gerade Bilder liefern."""
        frames = self._frames()
        return [name for name, short in self.defn["kameras"].items() if frames.get(short) is not None]

    # ------------------------------------------------------------------ Takt
    def _tick(self):
        if not self.winfo_exists():
            return
        try:
            self._tick_inner()
        except tk.TclError:
            return
        self.after(120, self._tick)

    # ------------------------------------------------------------------ Kameraschaerfe
    def _sharp_now(self, frames=None):
        """{kamera (Planname): schaerfewert} fuer alle Plan-Kameras mit Bild."""
        from cameras import sharpness
        frames = frames if frames is not None else self._frames()
        return {name: sharpness(frames[short]) for name, short in self.defn["kameras"].items()
                if frames.get(short) is not None}

    def _show_sharpness(self, frames):
        """Etwa jede Sekunde: aktuelle Schaerfe gegen den im Plan gespeicherten Wert."""
        if self.sharp_busy or time.monotonic() < self.sharp_next:
            return
        self.sharp_next = time.monotonic() + 1.0
        cmp = self.run.schaerfe_vergleich(self._sharp_now(frames))
        if not cmp:
            self.sharp_text.set("Schärfe: keine Kamera")
            return
        parts = [f"{c} {v:.0f}" + (f" / Plan {b:.0f}" if b is not None else " (nicht gespeichert)")
                 + ("" if ok else " ⚠ unscharf?") for c, (v, b, ok) in cmp.items()]
        bad = any(not ok for _, _, ok in cmp.values())
        self.sharp_text.set("Schärfe: " + " · ".join(parts))
        self.sharp_lbl.configure(foreground="#f2c14e" if bad else FG)

    def measure_sharpness(self, then=None):
        """Schaerfe aller Plan-Kameras ueber ~1,5 s messen (Median) und im Plan speichern."""
        if self.sharp_busy:
            return
        self.sharp_busy = True
        self.sharp_text.set("Schärfe wird gemessen ... Kamera ruhig halten")
        samples = {}

        def step(n):
            for cam, v in self._sharp_now().items():
                samples.setdefault(cam, []).append(v)
            if n > 1:
                self.after(150, step, n - 1)
                return
            self.sharp_busy = False
            werte = {c: sorted(vs)[len(vs) // 2] for c, vs in samples.items() if vs}
            if werte:
                self.run.schaerfe_speichern(werte)
                self.sharp_text.set("Schärfe gespeichert: " + " · ".join(f"{c} {v:.0f}" for c, v in werte.items()))
            else:
                self.sharp_text.set("Schärfe: keine Kamera liefert Bilder")
            self.sharp_next = time.monotonic() + 3.0
            if then:
                then()
        step(10)

    def _tick_inner(self):
        frames = self._frames()
        self._show_sharpness(frames)
        wrist = frames.get(self._wrist_short())
        r, o, _ = self.run.current()
        if self.pending and self.pending.get("startbild") is not None and o and o["art"] == "spezifisch":
            self._show(self._grid_image(self.pending["startbild"]))
        elif wrist is not None:
            self.mask_res = M.detect(wrist, self.mask_cfg, self.cv2)
            st = self.lab.arm_state(self.key)
            zu = (st[5] <= self.auto.zu + self.auto.c.get("greifer_zu_toleranz", 40)) if st is not None else None
            self._show(M.draw(wrist, self.mask_res, self.mask_cfg, self.cv2, greifer_zu=zu,
                              countdown=self.auto.rest if not self.auto.recording else None))
        else:
            self.mask_res = {"ok": False, "ok_a": False, "ok_b": False, "werte": {}}
        mask_ok = wrist is not None and (self.mask_res["ok"] or self.mask_manual)
        self.mask_text.set("Kein Wrist-Cam-Bild" if wrist is None else
                           "Maske: OK" if self.mask_res["ok"] else
                           "Maske: manuell bestaetigt" if self.mask_manual else
                           "Maske: Kanten an die Fuehrungen bringen")
        rec = self.lab.recorders.get(self.key)
        rec_state = rec.state if rec else "bereit"
        state = self.lab.arm_state(self.key)
        bereit = bool(r and r.get("status") == "bereit" and o is not None
                      and self.review_round is None and not self.review_open)
        if state is not None and (self.pending is None or rec_state == "nimmt_auf"):
            self.auto.c["an"] = self.auto_on.get()
            try:
                self.auto.c["countdown_s"] = max(0.0, float(self.countdown.get().replace(",", ".")))
            except ValueError:
                pass
            ev = self.auto.update(time.monotonic(), state, bereit and rec_state == "bereit" or self.auto.recording,
                                  mask_ok)
            if ev == "start" and rec_state == "bereit":
                self.start_episode(state)
            elif ev in ("stop", "zeitlimit") and rec_state == "nimmt_auf":
                self.stop_episode(ev)
        self.auto_text.set(self.auto.status_text() if state is not None else "Arm folgt nicht dem Leader")
        now = self._now(rec_state)
        if self.now_text.get() != now:
            self.now_text.set(now)
            rec = rec_state == "nimmt_auf"
            light = getattr(self, "_light_alert", False) and now.startswith("💡")
            self.now_box.configure(background="#e0453a" if rec else "#3a7bd5" if light else "#f2c14e",
                                   foreground="white" if (rec or light) else "#111",
                                   font=("Segoe UI", 15 if len(now) < 110 else 12, "bold"))
        zu = state is not None and state[5] <= self.auto.zu + self.auto.c.get("greifer_zu_toleranz", 40)
        self.start_btn.configure(state="normal" if bereit and zu and rec_state == "bereit" and not self.pending
                                 else "disabled")      # Start nur mit geschlossenem Greifer
        self.keep_btn.configure(state="normal" if self.pending and rec_state == "wartet_entscheidung" else "disabled")
        self.drop_btn.configure(state="normal" if self.pending and rec_state == "wartet_entscheidung" else "disabled")
        self._update_repeat_button()

    def _show(self, img):
        import base64
        w = max(200, self.cam.winfo_width())
        h = int(w * img.shape[0] / img.shape[1])
        maxh = max(150, self.cam.winfo_height())
        if h > maxh:
            h, w = maxh, int(maxh * img.shape[1] / img.shape[0])
        small = self.cv2.resize(img, (w, h))
        ok, ppm = self.cv2.imencode(".ppm", small)
        if ok:
            self.photo = tk.PhotoImage(data=ppm.tobytes(), format="PPM")
            self.cam.configure(image=self.photo, text="")
            self._shown = (w, h)

    # ------------------------------------------------------------------ 3x3-Raster
    def _grid_image(self, img):
        out = img.copy()
        h, w = out.shape[:2]
        cv2 = self.cv2
        for k in (1, 2):
            cv2.line(out, (k * w // 3, 0), (k * w // 3, h), (240, 240, 240), 2)
            cv2.line(out, (0, k * h // 3), (w, k * h // 3), (240, 240, 240), 2)
        for zi in range(3):
            for sp in range(3):
                txt = self.run.lage_text(zi, sp)
                col = (60, 190, 80) if self.lage == (zi, sp) else (255, 255, 255)
                if self.lage == (zi, sp):
                    cv2.rectangle(out, (sp * w // 3, zi * h // 3), ((sp + 1) * w // 3, (zi + 1) * h // 3), col, 6)
                cv2.putText(out, txt, (sp * w // 3 + 12, zi * h // 3 + 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2,
                            cv2.LINE_AA)
        cv2.putText(out, "STARTBILD: Lage des gegriffenen Teils antippen", (12, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 220, 240), 2, cv2.LINE_AA)
        return out

    def _click_grid(self, event):
        r, o, _ = self.run.current()
        if not (self.pending and o and o["art"] == "spezifisch" and getattr(self, "_shown", None)):
            return
        w, h = self._shown
        lw, lh = self.cam.winfo_width(), self.cam.winfo_height()
        x0, y0 = (lw - w) / 2, (lh - h) / 2                      # Bild ist im Label zentriert
        x, y = event.x - x0, event.y - y0
        if 0 <= x < w and 0 <= y < h:
            self.lage = (int(3 * y / h), int(3 * x / w))
            self.refresh_all()

    # ------------------------------------------------------------------ Karte
    def draw_map(self):
        c = self.map
        c.delete("all")
        W, H = max(300, c.winfo_width()), max(120, c.winfo_height())
        geo = self.defn["geometrie"]
        ra, ri = geo["r_aussen"], geo["r_innen"]
        scale = min((W - 20) / (2 * ra + 6), (H - 20) / (ra + 6))
        ox, oy = W / 2, H - 12                                   # Roboterbasis an der Tischkante
        to = lambda x, y: (ox + x * scale, oy - y * scale)
        c.create_line(0, oy, W, oy, fill="#bbb", width=3)                       # Tischkante
        c.create_text(8, oy - 8, text="Tischkante", anchor="w", fill=DIM, font=("Segoe UI", 8))
        c.create_arc(ox - ra * scale, oy - ra * scale, ox + ra * scale, oy + ra * scale, start=0, extent=180,
                     style="pieslice", fill="#24352a", outline="#4a7a55")
        c.create_arc(ox - ri * scale, oy - ri * scale, ox + ri * scale, oy + ri * scale, start=0, extent=180,
                     style="pieslice", fill="#1b1b1b", outline="#4a7a55")
        c.create_rectangle(ox - 12, oy - 10, ox + 12, oy, fill="#ddd", outline="")
        c.create_text(ox, oy - 18, text="Roboter", fill="#ddd", font=("Segoe UI", 8))
        L, B = geo["laenge"], geo["breite"]
        cur = self.run.data["aktuelle_runde"]
        review = getattr(self, "review_round", None)
        if review is not None:                    # angeklickte Runde zeigen, nicht die aktuelle
            cur = review
        done = [r["platzierung"] for r in self.run.rounds[:cur]]
        for k, p in enumerate(done):
            recent = k >= len(done) - 6
            pts = [v for xy in G.corners(p["x"], p["y"], p["winkel"], L, B) for v in to(*xy)]
            c.create_polygon(pts, fill="", outline="#6a6a6a" if recent else "#3a3a3a", width=1)
        r = self.run.round(review) if review is not None else self.run.round()
        if r is None:
            return
        p = r["platzierung"]
        pts = [v for xy in G.corners(p["x"], p["y"], p["winkel"], L, B) for v in to(*xy)]
        c.create_polygon(pts, fill="#8a6a45", outline="#5fb0ff" if review is not None else "#f2c14e", width=3)
        if review is not None:
            c.create_text(W - 8, 8, text=f"Ansicht Runde {r['runde']} · x {p['x']:g} y {p['y']:g} cm · {p['winkel']:g}°",
                          fill="#5fb0ff", font=("Segoe UI", 9, "bold"), anchor="ne")
        (ax, ay), (bx, by) = G.side_points(p, L, B)
        c.create_line(*to(ax, ay), *to(bx, by), fill="#2fd0ff", width=6)
        mx, my = (ax + bx) / 2, (ay + by) / 2
        # Pfeil von aussen auf die Anflugseite (Richtung von der Kartonmitte weg)
        vx, vy = mx - p["x"], my - p["y"]
        n = math.hypot(vx, vy) or 1
        sx, sy = mx + vx / n * 9, my + vy / n * 9
        c.create_line(*to(sx, sy), *to(mx, my), fill="#2fd0ff", width=4, arrow="last", arrowshape=(14, 16, 6))
        tx, ty = to(sx, sy)
        c.create_text(8, 8, text="→ Greifer kommt von hier (blau)", fill="#2fd0ff",
                      font=("Segoe UI", 9, "bold"), anchor="nw")

    # ------------------------------------------------------------------ Anzeige
    def refresh_all(self):
        run, defn = self.run, self.defn
        nr = len(run.rounds)
        if run.finished():
            self.round_title.set(f"Plan fertig · {nr} Runden")
            self.round_text.set("Alle Runden aufgenommen. Testplatzierungen getrennt aufnehmen (VLA-Studio).")
            self.grip_title.set("")
            self.grip_text.set("")
            self.cmd_text.set("")
            self.hint_text.set("")
            self.ready_btn.configure(state="disabled")
            self._fill_lists()
            self.draw_map()
            return
        r, o, i = run.current()
        ld = run.content(r)
        an = defn["anordnungen"][r["anordnung"]]
        self.round_title.set(f"Runde {r['runde']} von {nr} · Session {r['session']}")
        alt = r["platzierung"].get("ersatz_fuer")
        besch = f" – {an['beschreibung']}" if r["status"] == "offen" else ""   # nach Bereit kurz halten
        self.round_text.set(f"Befuellung: {run.content_text(ld)} · Anordnung: {an['name']}{besch}"
                            + (f"\n(geplant {alt}, ersetzt durch {r['platzierung']['ausrichtung']})" if alt else ""))
        self.ready_btn.configure(state="normal" if r["status"] == "offen" else "disabled")
        self.unreachable_btn.configure(state="disabled" if r.get("wiederholung") or r["behalten"] else "normal")
        if r["status"] == "offen":          # Rundenteil nur zeigen, solange der Karton vorbereitet wird
            if not self.round_row.winfo_ismapped():
                self.round_lbl.pack(anchor="w", after=self.map)
                self.round_row.pack(fill="x", pady=4, after=self.round_lbl)
        else:
            self.round_lbl.pack_forget()
            self.round_row.pack_forget()
        if o is None:
            self.grip_title.set("Runde fertig")
            return
        b = defn["bauteile"][o["teil"]]
        content = run.content()
        self.grip_title.set(f"Griff {i + 1} von {len(r['auftraege'])}: {b['kurz']}")
        self.grip_text.set(f"Befehlsart: {o['art']}" + ("" if self.obj else f" · Im Karton: {run.content_text(content)}"))
        lage = run.lage_text(*self.lage) if self.lage else "[Lage: nach dem Griff antippen]"
        self.cmd_text.set(run.task_text(o, lage) if o["art"] == "spezifisch" else run.task_text(o))
        if o["art"] == "spezifisch":
            self.hint_text.set("Nach dem Griff: Lage im Startbild antippen oder Taste 1-9 "
                               "(wie Ziffernblock: 7 8 9 = hinten, 1 2 3 = vorne).")
        else:
            self.hint_text.set("")
        self._fill_lists()
        self.draw_map()

    def _light_text(self, r):
        """Lichtphase des Plans: beim Wechsel (und in der ersten Runde) gross ankuendigen."""
        from aufnahme import plan as P
        ph = P.light_phase(self.defn, r["runde"])
        self._light_alert = False
        if not ph:
            return ""
        prev = P.light_phase(self.defn, r["runde"] - 1) if r["runde"] > 1 else None
        if prev is None or prev["id"] != ph["id"]:
            self._light_alert = True
            return f"💡 LICHT: {ph['anweisung']}\n"
        return f"(Licht: {ph['name']})\n"

    def _now(self, rec_state):
        """Die eine Anweisung, die gerade zaehlt (gross oben in der Mitte)."""
        run = self.run
        if self.review_round is not None and rec_state == "bereit":
            return "Andere Runde im Blick.\n↺ Griff neu · ◀ zurück"
        if run.finished():
            return "Fertig: alle Runden aufgenommen."
        r, o, _ = run.current()
        if r["status"] == "offen":
            ld = run.content(r)
            an = self.defn["anordnungen"][r["anordnung"]]
            p = r["platzierung"]
            place = (f"{self.obj.get('name', 'Karton')} wie zuvor platzieren (x {p['x']:g} cm, y {p['y']:g} cm, {p['winkel']:g}°)."
                     if r.get("wiederholung") else self.obj.get("hinlegen", "Karton wie auf der Karte hinlegen."))
            licht = self._light_text(r)
            return (licht + f"1. {place}\n"
                    f"2. Befuellen: {run.content_text(ld)} – {an['name']} (Details rechts)\n"
                    "3. Dann F3 druecken.")
        if o is None:
            return "Runde fertig."
        b = self.defn["bauteile"][o["teil"]]
        if self.pending and rec_state == "wartet_entscheidung":
            if o["art"] == "spezifisch" and not self.lage:
                return "Wo lag das Teil? Im Bild antippen oder Taste 1–9\n(7 8 9 = hinten · 4 5 6 = Mitte · 1 2 3 = vorne)"
            return "Griff gut?   F7 = behalten   ·   F8 = verwerfen"
        if rec_state == "nimmt_auf":
            return f"● AUFNAHME: {b['kurz']} greifen, anheben,\nzurueck zur Startpose und still halten (oder F6)."
        welche = ("irgendeine – aber NICHT die freieste!\n(Geht das nicht sicher, z. B. gestapelt: "
                  "die freieste nehmen und Lage antippen.)" if o["art"] == "spezifisch" else "die freieste")
        wait = ""
        if self.auto.ok_since is None and self.auto.grund:
            wait = "\nWarte auf: " + self.auto.grund.replace("Greifer nicht geschlossen", "Greifer schliessen")
        return f"Greif: {b['kurz'].upper()} – {welche}{wait}"

    def _fill_lists(self):
        run = self.run
        self._fill_orders()
        self._fill_round_grid()
        soll, ist = run.stats()
        done = sum(len(rr["behalten"]) for rr in run.rounds)
        total = sum(len(rr["auftraege"]) for rr in run.rounds)
        self.soll_ist.set(f"Gesamt {done}/{total} · " + " · ".join(
            f"{p} {ist.get(p, 0)}/{soll[p]}" for p in soll))

    def _fill_round_grid(self):
        """Kacheln je Session: R1..R9, Farbe = Stand, Rahmen = gerade angezeigte Runde."""
        for w in self.round_grid.winfo_children():
            w.destroy()
        run = self.run
        cur = run.data["aktuelle_runde"]
        shown = self.review_round if self.review_round is not None else cur
        sessions = sorted({r["session"] for r in run.rounds})
        for row, s in enumerate(sessions):
            tk.Label(self.round_grid, text=f"S{s}", background=BG, foreground=DIM,
                     font=("Segoe UI", 9, "bold")).grid(row=row, column=0, padx=(0, 4))
            col = 1
            for k, r in enumerate(run.rounds):
                if r["session"] != s:
                    continue
                if r["status"] == "fertig":
                    bg, fg = "#2d6a3a", "white"
                elif k == cur:
                    bg, fg = "#d6a529", "#111"
                elif r["behalten"]:
                    bg, fg = "#2a6f8a", "white"
                else:
                    bg, fg = "#333", "#bbb"
                b = tk.Button(self.round_grid, text=str(r["runde"]), width=2, background=bg, foreground=fg,
                              activebackground=bg, font=("Segoe UI", 8, "bold"), padx=0, pady=0,
                              relief="sunken" if k == shown else "raised", bd=3 if k == shown else 1,
                              command=lambda i=k: self._pick_round(i))
                b.grid(row=row, column=col, padx=1, pady=1)
                col += 1

    def _pick_round(self, index):
        self.review_round = None if index == self.run.data["aktuelle_runde"] else index
        self._fill_round_grid()
        self._fill_orders()
        self.draw_map()

    def _shown_round(self):
        if self.review_round is not None:
            return self.run.round(self.review_round)
        return self.run.round() or self.run.round(len(self.run.rounds) - 1)

    def _show_current_round(self):
        self.review_round = None
        self._fill_round_grid()
        self._fill_orders()
        self.draw_map()

    def _review_dataset(self):
        from ki import DATASETS, episodes
        return episodes.Dataset(os.path.join(DATASETS, episodes.slug(self.defn["datensatz"])))

    def _last_frame(self, r, order, dataset):
        from ki import episodes

        ep = order.get("episode")
        if not ep or not re.fullmatch(r"ep_\d+", ep):
            return None
        camera = self.defn.get("haupt_kamera", "wrist")
        if self.run.episode_belongs(r, order, dataset.episode_info(ep)):
            frame = dataset.last_frame(ep, camera, self.cv2)
            if frame is not None:
                return frame
        # Auch bereits im VLA-Studio aussortierte Episoden lassen sich noch pruefen.
        trash = Path(episodes.TRASH) / dataset.name
        archive = episodes.Dataset(str(trash))
        for folder in sorted(trash.glob(f"{ep}_*"), reverse=True):
            if self.run.episode_belongs(r, order, archive.episode_info(folder.name)):
                frame = archive.last_frame(folder.name, camera, self.cv2)
                if frame is not None:
                    return frame
        return None

    def _review_photo(self, frame, max_w, max_h):
        h, w = frame.shape[:2]
        scale = min(max_w / w, max_h / h)
        img = self.cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))))
        ok, ppm = self.cv2.imencode(".ppm", img)
        return tk.PhotoImage(master=self, data=ppm.tobytes(), format="PPM") if ok else None

    def _fill_orders(self):
        for row in self.orders.winfo_children():
            row.destroy()
        r = self._shown_round()
        self._update_repeat_button()
        if r is None:
            return
        an = self.defn["anordnungen"][r["anordnung"]]["name"]
        self.orders_title.configure(text=f"Runde {r['runde']} · Session {r['session']} · "
                                         f"{r['platzierung']['ausrichtung']} · {an}")
        arr = self.defn["anordnungen"][r["anordnung"]]
        self.arr_text.configure(text=f"Anordnung „{arr['name']}“: {arr['beschreibung']}")
        self.current_round_btn.pack_forget()
        if self.review_round is not None:
            self.current_round_btn.pack(side="left")
        tk.Label(self.orders, text="Letztes Bild", background="#1b1b1b", foreground=DIM).grid(row=0, column=1)
        cur = self.run.current_order_index() if self.review_round is None else None
        dataset = self._review_dataset()
        for k, order in enumerate(r["auftraege"], start=1):
            bg = "#3a3a1a" if k - 1 == cur else "#1b1b1b"
            mark = {"erledigt": "✓", "ausgelassen": "–"}.get(order["status"], "▸" if k - 1 == cur else " ")
            part = self.defn["bauteile"][order["teil"]]["kurz"]
            art = " · spez." if order["art"] == "spezifisch" else ""
            tk.Label(self.orders, text=f"{mark} {k} {part}{art}", background=bg, foreground=FG,
                     anchor="w", padx=4, pady=1, font=("Segoe UI", 9)).grid(row=k, column=0, sticky="nsew")
            pending_frame = self.pending.get("endbild") if k - 1 == cur and self.pending else None
            photo = None
            if pending_frame is not None:
                photo = self._review_photo(pending_frame, 64, 36)
            elif order.get("episode"):
                key = (r["runde"], k, order["episode"])
                if key not in self.thumbnails:
                    frame = self._last_frame(r, order, dataset)
                    self.thumbnails[key] = self._review_photo(frame, 64, 36) if frame is not None else None
                photo = self.thumbnails[key]
            if photo:
                button = tk.Button(self.orders, image=photo, background=bg, padx=2, pady=0,
                                   command=lambda a=order, f=pending_frame: self._enlarge_frame(r, a, f))
                button.image = photo
                button.grid(row=k, column=1, sticky="e", padx=4, pady=2)
            elif order.get("episode"):
                tk.Label(self.orders, text="Bild fehlt", background=bg, foreground=DIM).grid(row=k, column=1)
            if order["status"] == "erledigt":
                tk.Button(self.orders, text="↺", width=2, font=("Segoe UI", 9, "bold"), pady=0,
                          state="normal" if self._can_redo_one() else "disabled",
                          command=lambda i=k - 1: self._repeat_order(r, i)).grid(row=k, column=2, padx=(0, 4))

    def _enlarge_frame(self, r, order, frame=None):
        if frame is None:
            frame = self._last_frame(r, order, self._review_dataset())
        self.review_open = True
        self.auto.ok_since = None
        try:
            if frame is None:
                messagebox.showinfo("Letztes Bild", "Das Kameravideo ist nicht verfügbar.", parent=self)
                return
            win = tk.Toplevel(self)
            win.title(f"Letztes Bild · Runde {r['runde']} · {order.get('episode', 'aktuelle Aufnahme')}")
            win.transient(self.winfo_toplevel())
            photo = self._review_photo(frame, 900, 550)
            tk.Label(win, image=photo, background=BG).pack()
            tk.Button(win, text="Schließen", command=win.destroy).pack(pady=4)
            win.bind("<Escape>", lambda _event: win.destroy())
            win.grab_set()
            self.wait_window(win)
        finally:
            self.review_open = False

    def _can_redo_one(self):
        rec = self.lab.recorders.get(self.key)
        return (rec is None or rec.state == "bereit") and self.pending is None and not self.review_open

    def _repeat_order(self, r, index):
        """Einen einzelnen Griff verwerfen und neu aufnehmen (mit Warnung)."""
        if not self._can_redo_one():
            return
        order = r["auftraege"][index]
        part = self.defn["bauteile"][order["teil"]]["kurz"]
        other = r is not self.run.round()
        self.review_open = True
        self.auto.ok_since = None
        try:
            ok = messagebox.askyesno(
                "Griff wirklich neu aufnehmen?",
                f"Runde {r['runde']}, Griff {index + 1} ({part}) wirklich löschen und neu aufnehmen?\n\n"
                "Die Aufnahme kommt in den Papierkorb (ki_daten/papierkorb).\n"
                + ("Diese Runde liegt nicht mehr auf dem Tisch: Karton wieder an ihre Position legen und so "
                   "befüllen, wie es dann angezeigt wird. Danach geht es mit der aktuellen Runde weiter."
                   if other else "Leg das Teil wieder so in den Karton, wie es vor dem Griff lag."),
                icon="warning", default="no", parent=self)
            if not ok:
                return
            self.run.repeat_order(r["runde"], index, self._review_dataset())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Griff wiederholen", str(exc), parent=self)
            return
        finally:
            self.review_open = False
        self.review_round = None
        self.thumbnails.clear()
        self._after_episode()

    def _can_repeat(self, r):
        rec = self.lab.recorders.get(self.key)
        state = rec.state if rec else "bereit"
        if r is None or self.review_open:
            return False
        if self.pending is not None:
            return state == "wartet_entscheidung" and r is self.run.round()
        return state == "bereit" and bool(r["behalten"] or r["status"] == "fertig")

    def _update_repeat_button(self):
        r = self._shown_round()
        label = f"Runde {r['runde']} ganz neu" if r else "Runde neu"
        self.repeat_btn.configure(text=label, state="normal" if self._can_repeat(r) else "disabled")

    def _repeat_round(self):
        r = self._shown_round()
        if not self._can_repeat(r):
            return
        runde = r["runde"]
        pending = "Die noch offene Aufnahme wird verworfen. " if self.pending else ""
        self.review_open = True
        self.auto.ok_since = None
        try:
            n = len(r["behalten"])
            ok = messagebox.askyesno(
                "Runde wirklich loeschen?",
                f"Runde {runde} wirklich loeschen und neu aufnehmen?\n\n"
                f"{pending}Die {n} gespeicherten Aufnahmen dieser Runde kommen in den Papierkorb "
                f"(ki_daten/papierkorb). Die Runde startet erneut an derselben Kartonposition.",
                icon="warning", default="no", parent=self)
            if not ok:
                return
            self.run.repeat_round(runde, self._review_dataset())
            if self.pending:
                self.lab.record_decide(self.key, False)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Runde wiederholen", str(exc), parent=self)
            return
        finally:
            self.review_open = False
        self.review_round = None
        self.thumbnails.clear()
        self._after_episode()

    # ------------------------------------------------------------------ Aktionen
    def confirm_round(self):
        if self.review_round is not None or self.review_open:
            return
        if not self.cam_locked:
            self.cam_locked = True
            res = self.lab.cams.lock_settings(self.view.panel.slots) if hasattr(self.lab.cams, "lock_settings") else {}
            self.cam_settings = res
            if not self.run.schaerfe():          # erster Start des Plans: Schaerfe automatisch als Bezug merken
                self.measure_sharpness()
        self.run.confirm_round()
        self.refresh_all()

    def unreachable(self):
        r = self.run.round()
        if not r or r.get("wiederholung") or r["behalten"] or self.pending or self.review_round is not None:
            return
        if messagebox.askyesno("Platzierung", "Diese Platzierung ist nicht erreichbar (Maske nicht erfuellbar "
                               "oder Greifer kommt nicht an alle vier Ecken)?\n\nEs wird eine Ersatzplatzierung "
                               "derselben Ausrichtung erzeugt.", parent=self):
            self.run.unreachable()
            self.refresh_all()

    def mask_wrong(self):
        """Maske liegt daneben: Rohbild mit Urteil speichern (falsch_gruen / falsch_rot) zum Nachjustieren."""
        art = "falsch_gruen" if self.mask_res.get("ok") else "falsch_rot"
        self._save_mask_example(art)
        self.mask_text.set(f"Bild gemerkt ({art.replace('_', ' ')}) – danke")

    def _save_mask_example(self, art):
        try:
            import cv2 as _cv2
            from ki import DATA
            img = self._frames().get(self._wrist_short())
            if img is not None:
                d = os.path.join(DATA, "maske_beispiele")
                os.makedirs(d, exist_ok=True)
                _cv2.imwrite(os.path.join(d, time.strftime(f"{art}_%Y%m%d-%H%M%S.jpg")), img)
        except Exception:
            pass

    def manual_mask(self):
        self.mask_manual = True
        # Rohbild merken: Beispiele, bei denen die Maske versagt, zum Nachjustieren (ki_daten/maske_beispiele)
        try:
            import cv2 as _cv2
            from ki import DATA
            img = self._frames().get(self._wrist_short())
            if img is not None:
                d = os.path.join(DATA, "maske_beispiele")
                os.makedirs(d, exist_ok=True)
                _cv2.imwrite(os.path.join(d, time.strftime("manuell_%Y%m%d-%H%M%S.jpg")), img)
        except Exception:
            pass

    def manual_start(self):
        state = self.lab.arm_state(self.key)
        if (state is None or self.review_open or self.review_round is not None
                or str(self.start_btn["state"]) == "disabled"):
            return
        self.auto.recording, self.auto.start_pose, self.auto.t_start = True, list(state), time.monotonic()
        self.auto.opened = self.auto.closed_on_part = False
        self.start_episode(state, manuell=True)

    def _dataset(self):
        if self.dataset is None:
            from ki import episodes
            import stopcal
            m = stopcal.load(stopcal.map_path(self.key))
            self.dataset = episodes.open_dataset(self.defn["datensatz"], self.defn["name"], self.key,
                                                 list(self.defn["kameras"]), calibration=m.get("time") if m else None,
                                                 variabel=True, extra_meta={"plan": self.defn["id"], "kamera_slots": self.defn["kameras"],
                                                                            "aufgaben_je_episode": True})
        return self.dataset

    def start_episode(self, state, manuell=False):
        r, o, i = self.run.current()
        if o is None:
            return
        cams = self._available_cams()
        main = self.defn.get("haupt_kamera", "wrist")
        if main not in cams:
            self.auto.reset()
            self.auto_text.set("Wrist-Cam liefert kein Bild – Aufnahme nicht gestartet")
            return
        rename = {short: name for name, short in self.defn["kameras"].items()}
        try:
            self.lab.record_start_plan(self.key, self._dataset(), self.run.task_text(o), cams, [main], rename)
        except (RuntimeError, ValueError) as exc:
            self.auto.reset()
            self.auto_text.set(str(exc))
            return
        self.pending = {"start_stellung": list(state), "maske": "manuell" if (self.mask_manual and not self.mask_res["ok"])
                        else "automatisch", "maske_werte": dict(self.mask_res.get("werte", {})),
                        "inhalt_vor": self.run.content(), "start_manuell": manuell, "t0": time.time(),
                        "kameras": cams}
        self.lage = None

    def stop_episode(self, grund):
        self.lab.record_stop(self.key)
        rec = self.lab.recorders.get(self.key)
        if self.pending is not None:
            self.pending["stopp"] = grund
            self.pending["stopp_frame"] = rec.frames if rec else None
            first = (rec.first_frames or {}) if rec else {}
            main = self.defn.get("haupt_kamera", "wrist")
            self.pending["startbild"] = first.get(main)
            self.pending["endbild"] = rec.writer.last.get(main) if rec and rec.writer else None
        self.refresh_all()

    def decide(self, keep):
        if self.review_open:
            return
        rec = self.lab.recorders.get(self.key)
        if rec is not None and rec.state == "nimmt_auf":
            self.stop_episode("taste")
        if not self.pending or rec is None or rec.state != "wartet_entscheidung":
            return
        r, o, i = self.run.current()
        if keep and o["art"] == "spezifisch" and self.lage is None:
            messagebox.showinfo("Lage", "Bitte im Startbild antippen, wo das gegriffene Exemplar lag.", parent=self)
            return
        if not keep:
            self.lab.record_decide(self.key, False)
            self._after_episode()
            return
        lage = self.run.lage_text(*self.lage) if self.lage else None
        n = sum(self.pending["inhalt_vor"].values())
        meta = self._episode_meta(r, o, lage, n)
        path = self.lab.record_decide(self.key, True, extra=meta)
        if path:
            self.run.keep(os.path.basename(path), lage=lage, extra={"fuellstand": meta["fuellstand"]})
        self._after_episode()

    def _episode_meta(self, r, o, lage, n):
        import stopcal
        m = stopcal.load(stopcal.map_path(self.key))
        cams = self.pending["kameras"]
        rates = {}
        for name in cams:
            short = self.defn["kameras"][name]
            slot = next((s for s in self.view.panel.slots if self.lab.cam_key(s) == short), None)
            cam = self.lab.cams.manager.cams[slot] if slot is not None else None
            rates[name] = round(getattr(cam, "rate", 0.0), 1) if cam is not None else None
        return {
            "task": self.run.task_text(o, lage), "plan": self.defn["id"], "plan_version": self.defn.get("version"),
            "session": r["session"], "runde": r["runde"], "split": "train", "licht": r.get("licht"),
            "platzierung_id": r["platzierung_id"], "ausrichtung": r["platzierung"]["ausrichtung"],
            "ausrichtung_soll": r["ausrichtung_soll"],
            "platzierung_soll": {k: r["platzierung"][k] for k in ("x", "y", "winkel")},
            "anflugseite": r["platzierung"]["seite"], "ladung": r["ladung"], "anordnung": r["anordnung"],
            "zielbauteil": o["teil"], "befehlsart": o["art"], "lage": lage,
            "lage_raster": list(self.lage) if self.lage else None,
            "inhalt_vor": self.pending["inhalt_vor"], "fuellstand": P.fuellstand(n),
            "startpose": self.pending["start_stellung"], "maske": self.pending["maske"],
            "maske_werte": self.pending["maske_werte"], "start_manuell": self.pending["start_manuell"],
            "stopp": self.pending.get("stopp"), "stopp_frame": self.pending.get("stopp_frame"),
            "bildrate": rates, "kamera_einstellungen": getattr(self, "cam_settings", {}),
            "kalibrierung": m.get("time") if m else None, "overview_montage": self.defn.get("overview_montage"),
        }

    def _after_episode(self):
        self.pending = None
        self.lage = None
        self.mask_manual = False
        self.auto.reset()
        self.refresh_all()

    def not_graspable(self):
        r, o, i = self.run.current()
        if o is None or self.pending or self.review_round is not None or self.review_open:
            return
        frames = self._frames()
        img = frames.get(self._wrist_short())
        d = os.path.join(self.run.dir, "nicht_greifbar")
        os.makedirs(d, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bild = None
        if img is not None:
            bild = os.path.join(d, f"{stamp}_R{r['runde']}_{o['teil']}.jpg")
            self.cv2.imwrite(bild, img)
        ex = {"zeit": stamp, "runde": r["runde"], "zielbauteil": o["teil"], "inhalt": self.run.content(),
              "bild": os.path.basename(bild) if bild else None}
        with open(os.path.join(d, f"{stamp}_R{r['runde']}_{o['teil']}.json"), "w", encoding="utf-8") as f:
            json.dump(ex, f, indent=1, ensure_ascii=False)
        res = self.run.not_graspable(ex)
        if res == "runde_beendet":
            messagebox.showinfo("Nicht greifbar", "Kein anderes Bauteil mehr offen: die Runde ist beendet. "
                                "Die fehlenden Griffe werden in den Ist-Zahlen ausgewiesen.", parent=self)
        self.refresh_all()

    # Tasten aus dem Steuermodus
    def key_ready(self):
        r = self.run.round()
        if r is not None and r.get("status") == "offen":
            self.confirm_round()

    def key_lage(self, n):
        """Ziffer 1-9 wie Ziffernblock: 7 8 9 = hinten, 4 5 6 = Mitte, 1 2 3 = vorne."""
        r, o, _ = self.run.current()
        if self.pending and o and o["art"] == "spezifisch":
            self.lage = ((9 - n) // 3, (n - 1) % 3)
            self.refresh_all()

    def key_start(self):
        self.manual_start()

    def key_stop(self):
        rec = self.lab.recorders.get(self.key)
        if rec is not None and rec.state == "nimmt_auf":
            self.auto.recording = False
            self.stop_episode("taste")
