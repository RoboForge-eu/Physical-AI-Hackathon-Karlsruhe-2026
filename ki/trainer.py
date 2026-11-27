"""Trainings-Dienst: arbeitet die Trainingsauftraege ab, unabhaengig vom Harness.

  python -m ki.trainer [auftragsordner]

Startet automatisch, wenn im Harness/VLA-Studio ein Training angelegt wird. Laeuft ohne Fenster, haelt eine
Sperrdatei (nur ein Dienst gleichzeitig) und beendet sich nach 60 s ohne Auftraege. Zustand und Fortschritt
stehen in ki_daten/training_auftraege/<name>.json, das Protokoll des Dienstes in dienst.log daneben.
Der Harness kann waehrenddessen beliebig neu starten.
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ki import jobs  # noqa: E402

IDLE_EXIT_S = 60


def lock(store):
    """Exklusive Sperre halten, solange der Dienst lebt. None: es laeuft schon einer."""
    f = open(os.path.join(store, jobs.LOCK_NAME), "a")
    f.seek(0)
    try:
        try:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main(store=jobs.STORE, idle_exit=IDLE_EXIT_S, poll=5.0):
    os.makedirs(store, exist_ok=True)
    held = lock(store)
    if held is None:
        return 0                                  # anderer Dienst arbeitet schon
    logf = open(os.path.join(store, "dienst.log"), "a", encoding="utf-8", buffering=1)

    def log(text):
        logf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")

    log(f"Dienst gestartet (PID {os.getpid()})")
    q = jobs.Queue(store=store, log=log)
    idle = 0.0
    while True:
        time.sleep(poll)
        if q.active():
            idle = 0.0
            continue
        idle += poll
        if idle >= idle_exit:
            q._adopt()                            # zuletzt noch angelegte Auftraege nicht verlieren
            if not q.active():
                break
            idle = 0.0
    log("Dienst beendet (keine Auftraege)")
    logf.close()
    held.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else jobs.STORE))
