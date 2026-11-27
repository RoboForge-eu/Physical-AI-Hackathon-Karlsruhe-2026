"""Physical AI Harness by RoboForge: Weboberflaeche fuer den Hackathon (eine Seite zum Durchscrollen).

Laeuft neben dem bisherigen Harness (ros.py), ersetzt ihn nicht. Arm, Kameras und Sicherheit bleiben im Harness;
die Plattform spricht mit ihm ueber die lokale Schnittstelle (kern_api, 127.0.0.1:8770).

  python physical_ai_harness.py      -> startet die Oberflaeche im Browser (http://127.0.0.1:8780)
"""
import os

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIER = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HIER, "static")
DATEN = os.path.join(KIT, "plattform_daten")          # nur lokal (gitignore): Zustand, aktives Team, Logs
PAKETE = os.path.join(KIT, "stationspakete")          # Team-/Stationspakete mit Zugangsdaten (gitignore)
TEAMS = os.path.join(KIT, "teams")                    # Team-Ordner (werden geteilt)
PORT = 8780
