"""Kontakt-Schwellen offline aus aufgenommenen Episoden bestimmen (nur lesen, keine Hardware).

  python -m regel.schwellen [datensatz ...]

Fuer jede Probe: Spitzenhoehe aus Ist und aus Soll (Aktion) ueber die Kinematik, Fehler = z(Ist) - z(Soll).
Ausgewertet nur, wo sich der Arm langsam bewegt (|dSoll| klein): so sieht der Fehler bei langsamen Korrekturen
ohne Kontakt aus. Die Schwelle 'angestossen' muss deutlich darueber liegen (regel/kontakt.py: ANSTOSS_MM).
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ki import DATASETS  # noqa: E402
from regel.kartesisch import spitze  # noqa: E402

LANGSAM_TICKS = 3        # Soll aendert sich je Probe um hoechstens so viel (30 Hz -> ~8 Grad/s)


def fehler(state, action):
    out = []
    for i in range(1, len(state)):
        if np.abs(action[i] - action[i - 1])[:4].max() > LANGSAM_TICKS:
            continue
        out.append((spitze(state[i])[2] - spitze(action[i])[2]) * 1000)
    return out


def auswerten(namen=None, root=None):
    root = root or DATASETS
    namen = namen or sorted(d for d in os.listdir(root) if not d.startswith("sim_"))
    werte = []
    for n in namen:
        for dirpath, _, files in os.walk(os.path.join(root, n)):
            if "daten.npz" in files:
                d = np.load(os.path.join(dirpath, "daten.npz"))
                werte += fehler(d["state"], d["action"])
    if not werte:
        return None
    w = np.array(werte)
    sprung = np.abs(w[10:] - w[:-10])          # Aenderung in ~0,3 s: darauf reagiert der Melder (Nulllinie gleitet)
    return {"sprung_0_3s_p95_mm": round(float(np.percentile(sprung, 95)), 2),
            "sprung_0_3s_p99_mm": round(float(np.percentile(sprung, 99)), 2),"proben": len(w), "median_mm": round(float(np.median(w)), 2),
            "p95_abs_mm": round(float(np.percentile(np.abs(w), 95)), 2),
            "p99_abs_mm": round(float(np.percentile(np.abs(w), 99)), 2), "max_mm": round(float(w.max()), 2)}


if __name__ == "__main__":
    print(auswerten(sys.argv[1:] or None))
