"""Tests fuer webstation.py: Fenster-Spiegel (Baum, Knoepfe, Eingaben, Zeichnung) und Rueckfragen ueber die Webseite."""
import threading, time, types, unittest
import tkinter as tk
from tkinter import ttk, messagebox

import webstation as W


class FakeLab:
    def __init__(self, root):
        self.root = root
        self.events = []

    def on_ui(self, fn):
        self.root.after(0, fn)


class WebstationTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.lab = FakeLab(self.root)
        W.SPIEGEL.clear()
        W.FRAGEN.clear()
        W.installieren(self.lab)
        W.besuch()
        self.ergebnis = {}

    def tearDown(self):
        for name, orig in W._ORIG.items():
            setattr(messagebox, name, orig)
        W._ORIG.clear()
        W.LAB = None
        self.root.destroy()

    def im_hintergrund(self, fn, sekunden=10):
        """fn in einem Thread (wie der Kern-Server), waehrend Tk im Hauptthread laeuft."""
        fehler = []

        def lauf():
            try:
                fn()
            except Exception as exc:          # noqa: BLE001
                fehler.append(exc)
            finally:
                self.root.after(0, self.root.quit)
        threading.Thread(target=lauf, daemon=True).start()
        self.root.after(int(sekunden * 1000), self.root.quit)
        self.root.mainloop()
        if fehler:
            raise fehler[0]

    def assistent(self):
        win = tk.Toplevel(self.root)
        win.title("Test-Assistent")
        self.text = tk.StringVar(value="Schritt 1")
        ttk.Label(win, textvariable=self.text, font=("Segoe UI", 16, "bold")).pack()
        row = ttk.Frame(win)
        row.pack(fill="x")
        self.name = tk.StringVar(value="alt")
        ttk.Entry(row, textvariable=self.name).pack(side="left")

        def weiter():
            if messagebox.askyesno("Sicher?", "Wirklich weiter?", parent=win):
                self.text.set("Schritt 2")
            else:
                self.text.set("abgebrochen")
        ttk.Button(row, text="Weiter", command=weiter).pack(side="left")
        ttk.Button(row, text="Gesperrt", state="disabled").pack(side="right")
        c = tk.Canvas(win, width=200, height=100, background="#111")
        c.pack()
        c.create_line(0, 0, 200, 100, fill="#e8b230", width=2)
        c.create_text(100, 50, text="Hallo", fill="white")
        return win

    def finde(self, n, typ, text=None):
        if n is None:
            return None
        if n.get("typ") == typ and (text is None or text in n.get("text", "")):
            return n
        for k in n.get("kinder", []):
            r = self.finde(k, typ, text)
            if r:
                return r
        return None

    def test_spiegel_baum_knopf_und_rueckfrage(self):
        def ablauf():
            ids = W.oeffnen(self.assistent)
            self.assertEqual(len(ids), 1)
            fid = ids[0]
            baum = W.zustand(fid)["baum"]
            self.assertEqual(self.finde(baum, "text", "Schritt")["text"], "Schritt 1")
            self.assertTrue(self.finde(baum, "text", "Schritt")["fett"])
            self.assertTrue(self.finde(baum, "knopf", "Gesperrt")["aus"])
            svg = self.finde(baum, "zeichnung")["svg"]
            self.assertIn("<polyline", svg)
            self.assertIn("Hallo", svg)
            # Eingabe setzen
            feld = self.finde(baum, "eingabe")
            W.aktion(fid, feld["pfad"], "setzen", "neu")
            self.assertEqual(W.ui_call(self.name.get), "neu")
            # Knopf -> Rueckfrage erscheint in der Webseite, Antwort "Ja"
            W.aktion(fid, self.finde(baum, "knopf", "Weiter")["pfad"], "klick")
            for _ in range(100):
                if W.FRAGEN:
                    break
                time.sleep(0.05)
            frage = list(W.fragen_und_meldungen()["fragen"])[0]
            self.assertEqual(frage["titel"], "Sicher?")
            # waehrend die Frage offen ist, antwortet der Harness weiter (Pumpe laeuft in der Dialog-Schleife)
            self.assertEqual(W.zustand(fid)["id"], fid)
            W.antworten(frage["id"], True)
            for _ in range(100):
                if W.ui_call(self.text.get) == "Schritt 2":
                    break
                time.sleep(0.05)
            self.assertEqual(W.ui_call(self.text.get), "Schritt 2")
            # Fenster bleibt versteckt (nicht auf dem Bildschirm) und laesst sich schliessen
            self.assertIn(fid, [f["id"] for f in W.liste()])
            W.schliessen(fid)
            time.sleep(0.3)
            self.assertNotIn(fid, [f["id"] for f in W.liste()])
        self.im_hintergrund(ablauf)

    def test_fragen_aus_normalem_fenster_bleiben_im_harness(self):
        self.assertFalse(W.gespiegelt(self.root))
        self.assertFalse(W.gespiegelt(None))

    def test_ohne_webseite_antwortet_frage_sicher_mit_nein(self):
        win = tk.Toplevel(self.root)
        W.aufnehmen(win)
        W.LETZTER_BESUCH[0] = time.monotonic() - 999      # Webseite seit langem weg
        # dann gilt die normale Tk-Frage; hier pruefen wir nur die Web-Frage direkt: sie bricht sofort mit Nein ab
        self.assertFalse(W.frage(win, "T", "Text"))


if __name__ == "__main__":
    unittest.main()
