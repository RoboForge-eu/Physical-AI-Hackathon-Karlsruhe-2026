"""Grund-Skills: benannte Posen (Arbeitsplatz-Karte) und sichere Fahrten dorthin.

Posen werden vor Ort gemerkt (Arm von Hand/Leader an die Stelle bringen -> pose.merken) und in
ki_daten/posen.json je Arm gespeichert. Eine Fahrt geht gleichzeitig in allen Gelenken, langsam, und
wird vorher mit dem Hoehenmodell geprueft: Unterwegs darf kein Gelenkpunkt tiefer kommen als an Start
oder Ziel (minus 1 cm) - so faehrt eine Bewegung von oben nach oben nicht durch den Tisch.
"""
import json, math, os
from . import DATA

PATH = os.path.join(DATA, "posen.json")
MARGIN_M = 0.01
SAMPLES = 60


def load(path=None):
    try:
        with open(path or PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_pose(arm, name, values, path=None):
    data = load(path)
    data.setdefault(arm, {})[name] = [int(v) for v in values]
    os.makedirs(os.path.dirname(path or PATH), exist_ok=True)
    with open(path or PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    return data[arm][name]


def get_pose(arm, name, path=None):
    pose = load(path).get(arm, {}).get(name)
    if pose is None:
        raise KeyError(f"Pose {name!r} fuer {arm} unbekannt. Vorhanden: {sorted(load(path).get(arm, {}))}")
    return pose


def lowest(values):
    """Tiefster Gelenkpunkt (Meter ueber Tisch) einer Stellung [j1..j6]."""
    import so101
    return min(so101.heights({2: values[1], 3: values[2], 4: values[3]}))


def check_path(start, target):
    """(ok, text). Linear in allen Gelenken von start nach target."""
    floor = min(lowest(start), lowest(target)) - MARGIN_M
    worst = min(lowest([a + (b - a) * i / SAMPLES for a, b in zip(start, target)]) for i in range(SAMPLES + 1))
    if worst < floor:
        return False, (f"Weg geht {100 * (floor + MARGIN_M - worst):.1f} cm tiefer als Start/Ziel "
                       f"(tiefster Punkt {100 * worst:.1f} cm) - erst ueber eine hoehere Pose fahren")
    return True, f"tiefster Punkt unterwegs {100 * worst:.1f} cm"


def steps_per_tick(deg_per_s, fps=30):
    return max(1, int(deg_per_s * 4096 / 360 / fps))
