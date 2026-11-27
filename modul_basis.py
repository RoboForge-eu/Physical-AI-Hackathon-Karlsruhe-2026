"""Gemeinsames fuer die Modul-Programme (VLA-Studio, Agentic-Skill-Studio, Orchestrator):
Verbindung zu ROS im Hintergrund pruefen, Befehle ohne Einfrieren der Oberflaeche ausfuehren."""
import queue, threading, tkinter as tk
from tkinter import ttk
from ros_client import RosClient, RosError


class Modul:
    """Grundgeruest: Fenster, Kopfzeile mit Verbindungsanzeige, Hintergrund-Abfragen."""
    def __init__(self, name, untertitel, size="1150x780"):
        self.name = name
        self.root = tk.Tk()
        self.root.title(f"{name} · RoboForge")
        self.root.geometry(size)
        self.ros = RosClient(name)
        self.ros_ok = False
        self.inbox = queue.Queue()     # Auftraege aus Hintergrund-Threads an den Fenster-Thread
        self.arms = []                 # letzte Antwort von arme.liste
        top = ttk.Frame(self.root, padding=(16, 12, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text=name, font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(top, text="  " + untertitel, font=("Segoe UI", 10)).pack(side="left", pady=(8, 0))
        self.conn = tk.Label(top, text="Harness: verbinde ...", font=("Segoe UI", 10, "bold"), foreground="#b36b00")
        self.conn.pack(side="right")
        threading.Thread(target=self._watch, daemon=True, name="ros-watch").start()
        self.root.after(50, self._drain)

    def ui(self, fn):
        """fn() im Fenster-Thread ausfuehren (aus jedem Thread erlaubt). Tk darf nur dort benutzt werden."""
        self.inbox.put(fn)

    def _drain(self):
        while True:
            try:
                fn = self.inbox.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:
                pass                                   # Fenster wird gerade geschlossen
            except Exception:
                import traceback
                traceback.print_exc()                  # ein Fehler darf die Abarbeitung nicht stoppen
        try:
            self.root.after(50, self._drain)
        except tk.TclError:
            pass

    def _watch(self):
        stop = threading.Event()
        while True:
            try:
                arms = self.ros.call("arme.liste", timeout=5)
                ok = True
            except RosError:
                arms, ok = [], False
            self.ui(lambda a=arms, o=ok: self._set_conn(a, o))
            stop.wait(1.5)

    def _set_conn(self, arms, ok):
        self.ros_ok, self.arms = ok, arms
        self.conn.configure(text="Harness: verbunden" if ok else "Harness: nicht erreichbar (laeuft RoboForge Harness?)",
                            foreground="#1f7a3a" if ok else "#b3261e")
        self.on_arms(arms)

    def on_arms(self, arms):
        """Wird nach jeder Abfrage aufgerufen; Module ueberschreiben das bei Bedarf."""

    def background(self, fn, done=None, error=None):
        """fn() im Hintergrund; done(result) / error(text) danach im Fenster-Thread."""
        def run():
            try:
                result = fn()
            except Exception as exc:
                if error:
                    self.ui(lambda e=str(exc): error(e))
                return
            if done:
                self.ui(lambda r=result: done(r))
        threading.Thread(target=run, daemon=True).start()

    def run(self):
        self.root.mainloop()
