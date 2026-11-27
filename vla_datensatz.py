"""Datensatz vorbereiten (eigenes Fenster aus dem VLA-Studio).

Mehrere Datensaetze waehlen -> alle Episoden in einer Tabelle (Quelle, Runde, Bauteil, Befehl, Licht ...),
filtern, an-/abwaehlen -> neuer Datensatz. Quellen bleiben unveraendert; Videos/Messdaten werden nur verlinkt.
Spaeter hier auch: Episoden im Datensatz anpassen (Aufgabentext, Split ...).
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox
from ki import DATASETS, episodes

ALLE = "(alle)"
COLS = (("quelle", "Quelle", 110), ("ep", "Episode", 70), ("runde", "Runde", 50), ("teil", "Bauteil", 95),
        ("befehl", "Befehl", 80), ("split", "Split", 55), ("licht", "Licht", 150), ("dauer", "Dauer", 55),
        ("zeit", "aufgenommen", 130), ("task", "Aufgabe", 300))
FILTERS = (("quelle", "Quelle"), ("teil", "Bauteil"), ("befehl", "Befehl"), ("split", "Split"), ("licht", "Licht"))


def rows_for(datasets):
    """Episodenzeilen aller gewaehlten Datensaetze (ohne Oberflaeche, testbar)."""
    out = []
    for ds in datasets:
        for ep in ds.episodes():
            i = ds.episode_info(ep) or {}
            test = i.get("split") == "test" or str(i.get("platzierung_id") or "").startswith("T")
            out.append({"key": (ds.name, ep), "quelle": ds.name, "ep": ep, "runde": i.get("runde", ""),
                        "teil": i.get("zielbauteil") or "-", "befehl": i.get("befehlsart") or "-",
                        "split": "test" if test else "train", "licht": i.get("licht") or "-",
                        "dauer": f"{i.get('seconds', 0):.1f} s", "zeit": i.get("recorded", ""),
                        "task": i.get("task") or ds.meta.get("task", "")})
    return out


def check(datasets):
    """-> (fehler, hinweise) fuer die gewaehlten Quellen."""
    if not datasets:
        return None, []
    first, notes = datasets[0].meta, []
    for d in datasets[1:]:
        if d.meta.get("arm") != first.get("arm"):
            return f"'{d.name}' gehoert zu einem anderen Arm als '{datasets[0].name}'.", notes
        if d.meta.get("cameras") != first.get("cameras"):
            return f"'{d.name}' hat andere Kameras ({d.meta.get('cameras')}) als '{datasets[0].name}'.", notes
    if len({str(d.meta.get("calibration")) for d in datasets}) > 1:
        notes.append("Kalibrier-Angaben unterscheiden sich (" + ", ".join(
            f"{d.name}: {d.meta.get('calibration')}" for d in datasets) + "). Nur zusammenfuehren, wenn der Arm "
            "dazwischen nicht neu kalibriert wurde.")
    return None, notes


class DatasetPrep:
    ON, OFF = "☑", "☐"

    def __init__(self, studio, preselected_sets=()):
        self.studio = studio
        self.win = tk.Toplevel(studio.root)
        self.win.title("Datensatz vorbereiten")
        self.win.geometry("1250x760")
        self.all_sets = {d.name: d for d in episodes.datasets()}
        self.rows, self.checked = [], set()

        top = ttk.Frame(self.win, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="1 · Datensaetze waehlen (mehrere = zusammenfuehren)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.set_vars = {}
        grid = ttk.Frame(top)
        grid.pack(anchor="w", pady=4)
        for k, (name, d) in enumerate(self.all_sets.items()):
            v = tk.BooleanVar(value=name in preselected_sets)
            self.set_vars[name] = v
            ttk.Checkbutton(grid, variable=v, command=self.load,
                            text=f"{name}  ({len(d.episodes())} Ep. · {d.meta.get('task', '')[:40]})").grid(
                row=k // 3, column=k % 3, sticky="w", padx=(0, 18))
        self.problem = tk.StringVar()
        ttk.Label(top, textvariable=self.problem, foreground="#b45309", wraplength=1180).pack(anchor="w")

        mid = ttk.Frame(self.win, padding=(12, 4))
        mid.pack(fill="both", expand=True)
        ttk.Label(mid, text="2 · Episoden filtern und auswaehlen (Klick = an/aus)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        frow = ttk.Frame(mid)
        frow.pack(fill="x", pady=4)
        self.filters = {}
        for key, label in FILTERS:
            ttk.Label(frow, text=label + ":").pack(side="left")
            cb = ttk.Combobox(frow, state="readonly", width=14, values=[ALLE])
            cb.set(ALLE)
            cb.bind("<<ComboboxSelected>>", lambda e: self.redraw())
            cb.pack(side="left", padx=(2, 10))
            self.filters[key] = cb
        ttk.Button(frow, text="Gefilterte an", command=lambda: self.set_shown(True)).pack(side="left")
        ttk.Button(frow, text="Gefilterte aus", command=lambda: self.set_shown(False)).pack(side="left", padx=4)
        tf = ttk.Frame(mid)
        tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in COLS], show="headings", selectmode="none")
        for key, title, w in COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, stretch=key == "task")
        bar = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.click)

        form = ttk.Frame(self.win, padding=12)
        form.pack(fill="x")
        ttk.Label(form, text="3 · Neuer Datensatz", font=("Segoe UI", 10, "bold")).grid(row=0, column=0,
                                                                                       columnspan=2, sticky="w")
        ttk.Label(form, text="Name:").grid(row=1, column=0, sticky="w")
        self.name = tk.StringVar()
        ttk.Entry(form, textvariable=self.name, width=40).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(form, text="Beschreibung:").grid(row=2, column=0, sticky="w")
        self.task = tk.StringVar()
        ttk.Entry(form, textvariable=self.task, width=70).grid(row=2, column=1, sticky="w", pady=2)
        self.eigene = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, variable=self.eigene, text="Aufgabentext je Episode behalten (noetig fuer "
                        "Aufnahmeplaene / SmolVLA mit mehreren Aufgaben)").grid(row=3, column=1, sticky="w")
        self.count = tk.StringVar()
        ttk.Label(form, textvariable=self.count, font=("Segoe UI", 9, "bold")).grid(row=4, column=1, sticky="w", pady=4)
        buttons = ttk.Frame(form)
        buttons.grid(row=5, column=1, sticky="w")
        self.ok = ttk.Button(buttons, text="Datensatz anlegen", command=self.create)
        self.ok.pack(side="left")
        ttk.Button(buttons, text="Schliessen", command=self.win.destroy).pack(side="left", padx=6)
        self.load()

    # --- Daten ---
    def chosen(self):
        return [self.all_sets[n] for n, v in self.set_vars.items() if v.get()]

    def load(self):
        sets = self.chosen()
        err, notes = check(sets)
        self.problem.set("\n".join(([f"Geht nicht: {err}"] if err else []) + notes))
        self.ok.configure(state="disabled" if err else "normal")
        old = {r["key"] for r in self.rows}
        self.rows = rows_for(sets)
        keys = {r["key"] for r in self.rows}
        self.checked = {k for k in self.checked if k in keys} | (keys - old)   # neu hinzugekommene: an
        for key, _ in FILTERS:
            vals = sorted({str(r[key]) for r in self.rows})
            cb = self.filters[key]
            cb.configure(values=[ALLE] + vals)
            if cb.get() not in vals:
                cb.set(ALLE)
        # Vorschlaege folgen der Auswahl, solange man sie nicht selbst geaendert hat
        auto = getattr(self, "_auto", ("", ""))
        if sets and self.name.get() in ("", auto[0]):
            self.name.set("_".join(d.name for d in sets) if len(sets) > 1 else sets[0].name + "_auswahl")
        if sets and self.task.get() in ("", auto[1]):
            self.task.set(" + ".join(d.meta.get("task", d.name) for d in sets))
        self._auto = (self.name.get(), self.task.get())
        self.redraw()

    def shown(self):
        f = {k: cb.get() for k, cb in self.filters.items()}
        return [r for r in self.rows if all(v == ALLE or str(r[k]) == v for k, v in f.items())]

    def redraw(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.shown():
            mark = self.ON if r["key"] in self.checked else self.OFF
            self.tree.insert("", "end", iid="/".join(r["key"]),
                             values=[f"{mark} {r['quelle']}"] + [r[c[0]] for c in COLS[1:]])
        picks = self.picks()
        per = {}
        for ds, _ in picks:
            per[ds] = per.get(ds, 0) + 1
        self.count.set(f"{len(picks)} Episoden gewaehlt" + (" (" + ", ".join(f"{k}: {v}" for k, v in per.items()) + ")"
                                                             if per else "") + f" · angezeigt {len(self.shown())}")

    def picks(self):
        return [r["key"] for r in self.rows if r["key"] in self.checked]

    def click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        key = tuple(iid.split("/", 1))
        self.checked ^= {key}
        self.redraw()
        self.tree.see(iid)

    def set_shown(self, on):
        keys = {r["key"] for r in self.shown()}
        self.checked = (self.checked | keys) if on else (self.checked - keys)
        self.redraw()

    def create(self):
        picks, name, task = self.picks(), self.name.get().strip(), self.task.get().strip()
        if not picks or not name or not task:
            messagebox.showinfo("Datensatz vorbereiten", "Bitte Episoden waehlen, Name und Beschreibung eintragen.",
                                parent=self.win)
            return
        if os.path.exists(os.path.join(DATASETS, episodes.slug(name))):
            messagebox.showerror("Datensatz vorbereiten", f"Datensatz '{episodes.slug(name)}' gibt es schon.",
                                 parent=self.win)
            return
        self.ok.configure(state="disabled")
        self.count.set(f"Lege {len(picks)} Episoden an ...")
        eigene = bool(self.eigene.get())

        def done(ds):
            self.studio.refresh_lists()
            if self.studio.ds_list.exists(ds.name):
                self.studio.ds_list.selection_set(ds.name)
            self.studio.ds_choice.set(ds.name)
            messagebox.showinfo("Datensatz vorbereiten", f"'{ds.name}' mit {len(ds.episodes())} Episoden angelegt.\n"
                                "Er steht jetzt beim Training zur Auswahl.", parent=self.studio.root)
            self.win.destroy()

        def failed(e):
            self.ok.configure(state="normal")
            self.redraw()
            messagebox.showerror("Datensatz vorbereiten", e, parent=self.win)

        self.studio.background(lambda: episodes.compose(name, task, picks, eigene_aufgaben=eigene), done, failed)
