"""Laeuft in der KI-Umgebung: startet das LeRobot-Training mit zwei Windows-Anpassungen.

1. LeRobot legt nach jedem Speichern eine symbolische Verknuepfung 'checkpoints/last' an. Unter Windows
   braucht das Admin- oder Entwicklerrechte; stattdessen schreiben wir 'checkpoints/last.txt'.
2. Der Fortschrittsbalken (tqdm) schreibt ohne Zeilenende; er wird abgeschaltet, ROS liest die
   regelmaessigen 'step:'-Logzeilen.

  python -m ki.train <alle lerobot-train Argumente>
"""
import os, sys

os.environ.setdefault("TQDM_DISABLE", "1")


KEEP_EVERY = 5000      # diese Zwischenstaende bleiben (Vergleich), die 1000er dazwischen nur als neuester


def _write_last(checkpoint_dir):
    import shutil
    from pathlib import Path
    checkpoint_dir = Path(checkpoint_dir)
    (checkpoint_dir.parent / "last.txt").write_text(checkpoint_dir.name, encoding="utf-8")
    # Ein SmolVLA-Zwischenstand hat ~1,3 GB. Aeltere ausser jedem 5000er loeschen - erst NACH last.txt,
    # damit immer ein vollstaendiger Stand zum Weitertrainieren da ist.
    for d in checkpoint_dir.parent.iterdir():
        if d.is_dir() and d.name.isdigit() and d != checkpoint_dir and int(d.name) % KEEP_EVERY:
            shutil.rmtree(d, ignore_errors=True)


def local_hub_paths(args):
    """'--policy.path=lerobot/smolvla_base' -> lokaler Ordner. LeRobot macht unter Windows aus dem
    Hub-Namen einen Pfad mit Backslash, den Hugging Face dann ablehnt. Also vorher herunterladen
    (einmalig, danach aus dem Cache) und den lokalen Ordner uebergeben."""
    out = []
    for arg in args:
        if arg.startswith("--policy.path="):
            value = arg.split("=", 1)[1]
            if "/" in value and not os.path.exists(value) and value.count("/") == 1:
                from huggingface_hub import snapshot_download
                print(f"Lade Basismodell {value} (einmalig, danach aus dem Zwischenspeicher) ...", flush=True)
                arg = "--policy.path=" + snapshot_download(repo_id=value)
        out.append(arg)
    return out


def quiet(update, pause, sleep=None, clock=None):
    """Leise-Modus: nach jedem Lernschritt pause * (Dauer des Schritts) warten. Die Grafikkarte arbeitet nur einen
    Teil der Zeit, wird weniger warm, die Luefter drehen langsamer. Dauer etwa (1 + pause)-fach.
    (Ein Stromlimit per nvidia-smi braeuchte Admin-Rechte und gaelte fuer das ganze System.)"""
    import time
    sleep, clock = sleep or time.sleep, clock or time.perf_counter

    def wrapped(*a, **kw):
        t0 = clock()
        out = update(*a, **kw)          # endet mit loss.item(): die Grafikkarte ist dann wirklich fertig
        sleep(min(2.0, (clock() - t0) * pause))
        return out
    return wrapped


def rauschend(make, sigma):
    """Nur der Trainings-Datensatz bekommt verrauschte Stellungen, der Pruef-Datensatz nicht."""
    def wrapped(*a, **kw):
        from ki.zustand_rauschen import mit_rauschen
        train, evaluate = make(*a, **kw)
        return mit_rauschen(train, sigma), evaluate
    return wrapped


def main():
    import lerobot.common.train_utils as tu
    import lerobot.scripts.lerobot_train as lt
    tu.update_last_checkpoint = _write_last
    lt.update_last_checkpoint = _write_last
    pause = float(os.environ.get("ROBOFORGE_LEISE") or 0)
    if pause > 0:
        print(f"Leise-Modus: Grafikkarte gedrosselt (Pause {pause:.1f}x je Lernschritt)", flush=True)
        lt.update_policy = quiet(lt.update_policy, pause)
    sigma = float(os.environ.get("ROBOFORGE_ZUSTAND_RAUSCHEN") or 0)
    if sigma > 0:
        print(f"Gelenkstellung verrauscht: +-{sigma:.0f} Grad je Lernbeispiel (Modell muss aufs Bild schauen)",
              flush=True)
        lt.make_train_eval_datasets = rauschend(lt.make_train_eval_datasets, sigma)
    from ki.geraet import fix_args
    sys.argv = ["lerobot-train"] + fix_args(local_hub_paths(sys.argv[1:]))
    lt.main()


if __name__ == "__main__":
    main()
