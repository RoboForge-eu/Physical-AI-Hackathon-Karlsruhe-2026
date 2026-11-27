"""Agentic-Skill-Studio: ein Agent (Claude) entwickelt Code-Skills - schreiben, im Trockenlauf testen,
echte Versuche (vom Menschen freigegeben), Ergebnis ansehen, verbessern. Fertige Skills liegen in der
Bibliothek des Harness und laufen danach ohne Agent, z. B. im Orchestrator.

  python modul_agentic.py
"""
import json, threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from modul_basis import Modul
from agent import config
from agent.author import SkillAuthor
from skilllib import store
from skilllib.runner import run_skill

COLORS = {"text": "#1d1d1d", "werkzeug": "#1f6f8b", "ergebnis": "#555", "fehler": "#b3261e", "info": "#777",
          "ende": "#1f7a3a", "version": "#6a3fb5"}


def rate(pair):
    ok, n = pair
    return f"{ok}/{n}" + (f" ({100 * ok // n} %)" if n else "")


class AgenticModul(Modul):
    def __init__(self):
        super().__init__("Agentic-Skill-Studio", "Ein Agent entwickelt Code-Skills fuer die Bibliothek des Harness",
                         size="1350x880")
        self.cfg = config.load()
        src = config.key_source(self.cfg)
        ttk.Label(self.root, text=(f"Agent: {self.cfg['model']} · API-Schluessel aus {src}" if src else
                                   "Kein API-Schluessel: agent.json mit \"api_key\" anlegen oder ANTHROPIC_API_KEY setzen"),
                  foreground="#1f7a3a" if src else "#b3261e", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16)
        row = ttk.Frame(self.root, padding=(16, 6))
        row.pack(fill="x")
        ttk.Label(row, text="Arm:").pack(side="left")
        self.arm = tk.StringVar()
        self.arm_box = ttk.Combobox(row, textvariable=self.arm, state="readonly", width=14)
        self.arm_box.pack(side="left", padx=4)
        ttk.Button(row, text="Arbeitssitzung anfragen", command=self.request_session).pack(side="left", padx=6)
        ttk.Button(row, text="Arm ablegen", command=self.end_session).pack(side="left")
        self.session = tk.StringVar()
        ttk.Label(row, textvariable=self.session, font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        left = ttk.Frame(body)
        body.add(left, weight=1)
        right = ttk.Frame(body)
        body.add(right, weight=2)

        # --- Bibliothek ---
        ttk.Label(left, text="Skill-Bibliothek", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.skills = ttk.Treeview(left, columns=("aktiv", "echt", "versionen"), show="tree headings", height=9)
        for c, h, w in (("#0", "Skill", 170), ("aktiv", "aktiv", 50), ("echt", "echt erfolgreich", 110), ("versionen", "Vers.", 50)):
            self.skills.heading(c, text=h)
            self.skills.column(c, width=w)
        self.skills.pack(fill="x", pady=4)
        self.skills.bind("<<TreeviewSelect>>", lambda e: self.show_skill())
        self.info = tk.StringVar()
        ttk.Label(left, textvariable=self.info, wraplength=430, justify="left", font=("Segoe UI", 9)).pack(anchor="w")
        vrow = ttk.Frame(left)
        vrow.pack(fill="x", pady=4)
        ttk.Label(vrow, text="Version:").pack(side="left")
        self.version = tk.StringVar()
        self.version_box = ttk.Combobox(vrow, textvariable=self.version, state="readonly", width=6)
        self.version_box.pack(side="left", padx=4)
        self.version_box.bind("<<ComboboxSelected>>", lambda e: self.show_code())
        ttk.Button(vrow, text="aktiv setzen", command=self.activate).pack(side="left", padx=4)
        self.code = ScrolledText(left, height=14, font=("Consolas", 9), wrap="none")
        self.code.pack(fill="both", expand=True)
        prow = ttk.Frame(left)
        prow.pack(fill="x", pady=4)
        ttk.Label(prow, text="Parameter (JSON):").pack(side="left")
        self.params = tk.StringVar(value="{}")
        ttk.Entry(prow, textvariable=self.params, width=20).pack(side="left", padx=4)
        ttk.Button(prow, text="Trockenlauf", command=lambda: self.run_selected("trocken")).pack(side="left", padx=2)
        ttk.Button(prow, text="▶ Echt ausfuehren", command=lambda: self.run_selected("echt")).pack(side="left", padx=2)

        # --- Entwicklung ---
        ttk.Label(right, text="Skill entwickeln lassen", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        form = ttk.Frame(right)
        form.pack(fill="x")
        self.f_name, self.f_ziel, self.f_krit, self.f_params = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar(value="{}")
        for r, (label, var, hint) in enumerate((
                ("Name", self.f_name, "z. B. teil_in_kiste"),
                ("Ziel", self.f_ziel, "Was soll der Skill tun?"),
                ("Erfolg, wenn", self.f_krit, "Woran erkennt man, dass es geklappt hat?"),
                ("Parameter", self.f_params, 'z. B. {"versuche": "wie oft hoechstens greifen"}'))):
            ttk.Label(form, text=label + ":").grid(row=r, column=0, sticky="w")
            ttk.Entry(form, textvariable=var, width=70).grid(row=r, column=1, sticky="w", pady=1)
            ttk.Label(form, text=hint, font=("Segoe UI", 8), foreground="#777").grid(row=r, column=2, sticky="w", padx=6)
        ttk.Label(right, text="Hinweise fuer den Agenten (optional):").pack(anchor="w", pady=(4, 0))
        self.f_hint = tk.Text(right, height=3, font=("Segoe UI", 10), wrap="word")
        self.f_hint.pack(fill="x")
        brow = ttk.Frame(right)
        brow.pack(fill="x", pady=6)
        self.dev_button = ttk.Button(brow, text="▶ Neuen Skill entwickeln", command=self.develop_new)
        self.dev_button.pack(side="left")
        self.improve_button = ttk.Button(brow, text="▶ Gewaehlten Skill verbessern", command=self.develop_selected)
        self.improve_button.pack(side="left", padx=6)
        self.halt_button = ttk.Button(brow, text="■ Agent anhalten", command=self.halt, state="disabled")
        self.halt_button.pack(side="left")
        self.state = tk.StringVar()
        ttk.Label(brow, textvariable=self.state, font=("Segoe UI", 9)).pack(side="left", padx=8)

        self.trial = tk.Frame(right, background="#f2c14e")
        self.trial_text = tk.StringVar()
        tk.Label(self.trial, textvariable=self.trial_text, background="#f2c14e", font=("Segoe UI", 10, "bold"),
                 wraplength=640, justify="left").pack(side="left", padx=8, pady=6)
        tk.Button(self.trial, text="Versuch freigeben", background="#1f7a3a", foreground="white",
                  command=lambda: self.answer_trial(True)).pack(side="right", padx=4, pady=4)
        tk.Button(self.trial, text="Ablehnen", command=lambda: self.answer_trial(False)).pack(side="right", padx=4)
        self.trial_wait = None

        self.log_box = ScrolledText(right, font=("Segoe UI", 10), state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)
        for kind, color in COLORS.items():
            self.log_box.tag_configure(kind, foreground=color)
        self.log_box.tag_configure("werkzeug", font=("Consolas", 9, "bold"))
        self.author = None
        self.refresh_skills()

    # --- Bibliothek ---
    def refresh_skills(self):
        sel = self.skills.selection()
        self.skills.delete(*self.skills.get_children())
        for s in store.all_skills():
            vs = s["versionen"]
            act = s.get("aktiv")
            stats = vs.get(str(act), {}).get("echt", [0, 0]) if act else [0, 0]
            self.skills.insert("", "end", iid=s["name"], text=s["name"],
                               values=(f"v{act}" if act else "-", rate(stats), len(vs)))
        if sel and self.skills.exists(sel[0]):
            self.skills.selection_set(sel[0])

    def selected(self):
        sel = self.skills.selection()
        return sel[0] if sel else None

    def show_skill(self):
        name = self.selected()
        if not name:
            return
        meta = store.get(name)
        lines = [f"Ziel: {meta.get('ziel')}", f"Erfolg, wenn: {meta.get('kriterium')}"]
        for v, st in sorted(meta["versionen"].items(), key=lambda x: int(x[0])):
            lines.append(f"v{v}: echt {rate(st['echt'])}, trocken {rate(st['trocken'])} · {st.get('notiz', '')[:60]}")
        self.info.set("\n".join(lines))
        versions = sorted((int(v) for v in meta["versionen"]), reverse=True)
        self.version_box["values"] = versions
        if versions:
            self.version.set(str(meta.get("aktiv") or versions[0]))
        self.f_params.set(json.dumps(meta.get("params") or {}, ensure_ascii=False))
        self.show_code()

    def show_code(self):
        name = self.selected()
        self.code.delete("1.0", "end")
        if name and self.version.get():
            code, _ = store.code(name, int(self.version.get()))
            self.code.insert("1.0", code)

    def activate(self):
        name = self.selected()
        if name and self.version.get():
            store.set_active(name, int(self.version.get()))
            self.refresh_skills()
            self.show_skill()

    def run_selected(self, modus):
        name, arm = self.selected(), self.arm.get()
        if not name or not self.version.get():
            return
        try:
            params = json.loads(self.params.get() or "{}")
        except ValueError as exc:
            messagebox.showerror("Parameter", f"Kein JSON: {exc}", parent=self.root)
            return
        version = int(self.version.get())
        if modus == "echt" and not messagebox.askokcancel("Echt ausfuehren", f"'{name}' v{version} am Arm {arm} "
                                                          "ausfuehren? (Arbeitssitzung muss im Harness freigegeben sein)",
                                                          parent=self.root):
            return
        kw = {}
        if modus == "trocken":
            def lib():
                return ({"posen": sorted(self.ros.call("pose.liste", arm=arm)),
                         "modelle": [m["name"] for m in self.ros.call("modelle.liste")]})
        self.log("info", f"{'Trockenlauf' if modus == 'trocken' else 'Echter Lauf'}: {name} v{version} {params}")
        def go():
            extra = lib() if modus == "trocken" else {}
            return run_skill(name, params, arm=arm, modus=modus, version=version,
                             log=lambda t: self.log("info", "  " + t), timeout=30 if modus == "trocken" else 600, **extra)
        self.background(go, lambda r: (self.log("ergebnis", json.dumps(r, ensure_ascii=False)[:300]), self.refresh_skills(),
                                       self.show_skill()), lambda e: self.log("fehler", e))

    # --- Sitzung ---
    def on_arms(self, arms):
        keys = [a["arm"] for a in arms]
        if list(self.arm_box["values"]) != keys:
            self.arm_box["values"] = keys
            if keys and self.arm.get() not in keys:
                self.arm.set(keys[0])
        a = next((a for a in arms if a["arm"] == self.arm.get()), None)
        if a is None:
            self.session.set("")
        elif a.get("sitzung") and a["sitzung"].get("aktiv"):
            self.session.set(f"Sitzung aktiv ({a['sitzung']['von']}) · {a['status']}")
        else:
            self.session.set(f"keine Sitzung · {a['status']}")

    def request_session(self):
        arm = self.arm.get()
        if arm:
            self.background(lambda: self.ros.call("sitzung.anfragen", arm=arm, modul="Agentic-Skill-Studio"),
                            error=lambda e: messagebox.showerror("Sitzung", e, parent=self.root))

    def end_session(self):
        arm = self.arm.get()
        if arm:
            self.background(lambda: self.ros.call("sitzung.beenden", arm=arm))

    # --- Entwicklung ---
    def log(self, kind, text):
        def put():
            self.log_box.configure(state="normal")
            prefix = {"werkzeug": "⚙ ", "ergebnis": "   ← ", "fehler": "✖ ", "ende": "■ ", "version": "★ "}.get(kind, "")
            self.log_box.insert("end", prefix + text + "\n", kind)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.ui(put)

    def ask_trial(self, text):
        """Aus dem Agent-Thread: wartet, bis der Mensch klickt."""
        done, answer = threading.Event(), {}
        def show():
            self.trial_wait = (done, answer)
            self.trial_text.set(text + "\nArm und Arbeitsbereich im Blick?")
            self.trial.pack(fill="x", pady=4, before=self.log_box)
            self.root.bell()
        self.ui(show)
        while not done.wait(0.5):
            if self.author and self.author.stop.is_set():
                return False
        return answer.get("ok", False)

    def answer_trial(self, ok):
        if self.trial_wait:
            done, answer = self.trial_wait
            answer["ok"] = ok
            done.set()
            self.trial_wait = None
        self.trial.pack_forget()

    def develop_new(self):
        name = store.slug(self.f_name.get().strip())
        if not self.f_name.get().strip() or not self.f_ziel.get().strip():
            messagebox.showinfo("Skill", "Bitte Name und Ziel eintragen.", parent=self.root)
            return
        try:
            params = json.loads(self.f_params.get() or "{}")
        except ValueError as exc:
            messagebox.showerror("Parameter", f"Kein JSON: {exc}", parent=self.root)
            return
        store.create(name, self.f_ziel.get().strip(), self.f_krit.get().strip(), params)
        self.refresh_skills()
        self.skills.selection_set(name)
        self.start_author(name)

    def develop_selected(self):
        name = self.selected()
        if name:
            self.start_author(name)

    def start_author(self, name):
        if not config.key_source(self.cfg):
            messagebox.showerror("Agent", "Kein API-Schluessel eingerichtet.", parent=self.root)
            return
        arm = self.arm.get()
        hint = self.f_hint.get("1.0", "end").strip()
        self.author = SkillAuthor(self.ros, name, arm, self.log, self.ask_trial, cfg=self.cfg,
                                  on_version=lambda v: self.ui(lambda: (self.refresh_skills(), self.show_skill())))
        self.dev_button.configure(state="disabled")
        self.improve_button.configure(state="disabled")
        self.halt_button.configure(state="normal")
        self.state.set(f"Agent entwickelt '{name}' ...")
        self.log("info", f"— Entwicklung von '{name}' am Arm {arm} —")
        def run():
            try:
                outcome = self.author.run(hint or "Entwickle den Skill.")
            except Exception as exc:
                outcome = "fehler"
                self.log("fehler", f"{type(exc).__name__}: {exc}")
            self.ui(lambda: self._finished(outcome))
        threading.Thread(target=run, daemon=True, name="skill-autor").start()

    def _finished(self, outcome):
        self.dev_button.configure(state="normal")
        self.improve_button.configure(state="normal")
        self.halt_button.configure(state="disabled")
        self.state.set(f"Entwicklung beendet: {outcome}")
        self.answer_trial(False)
        self.refresh_skills()
        self.show_skill()

    def halt(self):
        if self.author:
            self.author.stop.set()
            self.state.set("halte an ... (Arm sofort stoppen: 'Arm ablegen' oder Stop im Harness)")


if __name__ == "__main__":
    AgenticModul().run()
