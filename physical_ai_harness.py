"""Startet den Physical AI Harness by RoboForge (Weboberflaeche im Browser).

  python physical_ai_harness.py            -> Oberflaeche starten und Browser oeffnen
  python physical_ai_harness.py --harness  -> zusaetzlich den Harness (Arme, Kameras) starten, falls er nicht laeuft

Laeuft die Oberflaeche schon, wird nur der Browser geoeffnet.
"""
import socket, sys, webbrowser

from plattform import PORT


def laeuft_schon(port=PORT):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def config_anlegen():
    """Frische Kopie (Hackathon-Repo): config.json aus der Vorlage, bis das Team-Paket die echte bringt."""
    import os, shutil
    hier = os.path.dirname(os.path.abspath(__file__))
    cfg, bsp = os.path.join(hier, "config.json"), os.path.join(hier, "config.example.json")
    if not os.path.exists(cfg) and os.path.exists(bsp):
        shutil.copy(bsp, cfg)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    config_anlegen()
    if laeuft_schon():
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return 0
    from plattform import server
    if "--harness" in argv:
        import threading, time
        def starte():
            time.sleep(3)
            try:
                server.APP.harness.starten()
            except Exception as exc:
                print("Harness konnte nicht gestartet werden:", exc)
        threading.Thread(target=starte, daemon=True).start()
    server.serve(open_browser="--ohne-browser" not in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
