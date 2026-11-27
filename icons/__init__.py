"""App-Icon und eigene Taskleisten-Gruppe (Windows) fuer Harness und Fernsteuerung."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def apply(root, name):
    """name = 'harness' oder 'fernsteuerung'. Fehler werden ignoriert (Icon ist nur Schmuck)."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"RoboForge.{name}")
    except Exception:
        pass
    base = getattr(sys, "_MEIPASS", None)
    for folder in ([os.path.join(base, "icons")] if base else []) + [HERE]:
        try:
            if sys.platform == "win32" and os.path.exists(os.path.join(folder, name + ".ico")):
                root.iconbitmap(default=os.path.join(folder, name + ".ico"))
            else:
                import tkinter as tk
                img = tk.PhotoImage(file=os.path.join(folder, name + ".png"))
                root.iconphoto(True, img)
                root._rf_icon = img
            return
        except Exception:
            continue
