"""Rechenwerk automatisch waehlen: NVIDIA (cuda) -> Apple-Chip (mps) -> Prozessor (cpu).

Laeuft ueberall, auch ohne torch (dann 'cpu'). Wird beim Training (ki/train.py) und beim Fahren
(ki/lerobot_runner.py) benutzt, damit dieselbe Software auf Windows-PCs und MacBooks laeuft.
"""
import os, sys


def detect(torch=None):
    """'cuda', 'mps' oder 'cpu'. Mit RF_GERAET=cpu|cuda|mps erzwingbar."""
    forced = os.environ.get("RF_GERAET", "").strip().lower()
    if forced in ("cpu", "cuda", "mps"):
        return forced
    if torch is None:
        try:
            import torch
        except ImportError:
            return "cpu"
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    try:
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def resolve(device, torch=None):
    """'auto' (oder ein nicht vorhandenes Geraet) -> passendes Geraet."""
    if device in (None, "", "auto"):
        return detect(torch)
    if device == "cuda" and detect(torch) != "cuda":
        return detect(torch)
    return device


def fix_args(args, torch=None):
    """'--policy.device=auto' in den Trainingsargumenten ersetzen."""
    out = []
    for a in args:
        if a.startswith("--policy.device="):
            a = "--policy.device=" + resolve(a.split("=", 1)[1], torch)
        out.append(a)
    return out


def beschreibung(device):
    return {"cuda": "NVIDIA-Grafikkarte", "mps": "Apple-Chip (Metal)", "cpu": "Prozessor (langsam)"}.get(device, device)


def empfehlung(device):
    """Welche Methode auf diesem Rechner sinnvoll ist."""
    if device == "cuda":
        return "smolvla", "NVIDIA-Grafikkarte: ACT und SmolVLA gehen gut."
    if device == "mps":
        return "act", "Apple-Chip: ACT geht gut (1-3 h). SmolVLA ist hier sehr langsam."
    return "act", "Keine passende Grafikkarte: nur kleines ACT-Training sinnvoll, dauert lange."


def ki_python(here):
    """Python der KI-Umgebung (Windows: Scripts/python.exe, Mac/Linux: bin/python)."""
    win = os.path.join(here, "ki-env", "Scripts", "python.exe")
    nix = os.path.join(here, "ki-env", "bin", "python")
    if sys.platform == "win32":
        return win
    return nix if os.path.exists(nix) or not os.path.exists(win) else win


def popen_detached_kwargs():
    """Argumente fuer einen losgeloesten Hintergrundprozess, je nach System."""
    import subprocess
    if sys.platform == "win32":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"creationflags": flags}
    return {"start_new_session": True}
