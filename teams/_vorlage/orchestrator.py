"""Beispiel-Orchestrator: Elektrodose greifen und pruefen.

Ablauf: Arbeitssitzung anfragen (Mensch bestaetigt vor Ort) -> VLA-Modell greift -> Greifer pruefen ->
bei Misserfolg einmal wiederholen, sonst begruendet stoppen -> Sitzung beenden (Arm legt sich ab).

Starten: Plattform, Abschnitt "Orchestrator & Skills" -> "orchestrator.py starten".
Ausgaben (print) erscheinen dort im Protokoll.
"""
import time
from ros_client import RosClient, RosError

ARM = "follower"                 # Arm-Schluessel (siehe arme.liste)
MODELL = None                    # Name eines fertigen Modells; None = neuestes nehmen
AUFGABE = "Pick up the orange junction box"
VERSUCHE = 2

ros = RosClient("team-orchestrator")


def warte_auf_sitzung(arm, sekunden=120):
    """Bittet vor Ort um Freigabe und wartet, bis der Arm bereit ist."""
    ros.call("sitzung.anfragen", arm=arm, modul="Team-Orchestrator")
    print("Bitte im Harness-Fenster die Bewegung freigeben (Mensch vor Ort) ...", flush=True)
    ende = time.time() + sekunden
    while time.time() < ende:
        st = ros.call("sitzung.status", arm=arm)
        if st.get("bereit"):
            return True
        time.sleep(1)
    return False


def main():
    arme = ros.call("arme.liste")
    print("Arme:", ", ".join(f"{a['arm']} ({a['label']})" for a in arme))
    modelle = ros.call("modelle.liste")
    if not modelle:
        print("Noch kein trainiertes Modell. Erst im Abschnitt 'VLA trainieren' ein Modell trainieren.")
        return
    modell = MODELL or modelle[-1]["name"]
    print("Modell:", modell)
    ros.call("modell.vorladen", arm=ARM, modell=modell, aufgabe=AUFGABE)

    if not warte_auf_sitzung(ARM):
        print("Keine Freigabe erhalten - Ende.")
        return
    try:
        for versuch in range(1, VERSUCHE + 1):
            print(f"Versuch {versuch}: Modell greift ...", flush=True)
            ros.call("modell.ausfuehren", arm=ARM, modell=modell, sekunden=20, aufgabe=AUFGABE, timeout=60)
            ros.call("greifer.setzen", arm=ARM, prozent=0)          # sicher zu, dann messen
            halt = ros.call("greifer.pruefen", arm=ARM)
            print("Greifer:", halt)
            if halt.get("haelt_etwas"):
                print("Erfolg: Dose gegriffen.")
                break
            print("Nichts gegriffen.")
        else:
            print("Abbruch nach", VERSUCHE, "Versuchen (begruendeter Stopp).")
    except RosError as exc:
        print("Fehler vom Harness:", exc)
    finally:
        ros.call("sitzung.beenden", arm=ARM)
        print("Sitzung beendet, Arm legt sich ab.")


if __name__ == "__main__":
    main()
