"""Verlauf der Eingaben fuer die Aufnahme (Datensatz-Namen, Aufgaben): zuletzt benutzte zuerst.
Gespeichert in ki_daten/aufnahme_verlauf.json, bleibt ueber Neustarts erhalten."""
import json, os
from . import DATA

PATH = os.path.join(DATA, "aufnahme_verlauf.json")
MAX = 20


def load(path=None):
    try:
        with open(path or PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}
    return {"datensatz": list(data.get("datensatz", [])), "aufgabe": list(data.get("aufgabe", []))}


def remember(name, task, path=None):
    data = load(path)
    for key, value in (("datensatz", name), ("aufgabe", task)):
        value = (value or "").strip()
        if value:
            data[key] = [value] + [v for v in data[key] if v != value][:MAX - 1]
    os.makedirs(os.path.dirname(path or PATH), exist_ok=True)
    with open(path or PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    return data


def options(key, extra=(), path=None):
    """Verlauf zuerst, danach weitere bekannte Werte (z. B. vorhandene Datensaetze), ohne Doppelte."""
    seen, out = set(), []
    for v in list(load(path)[key]) + [e for e in extra if e]:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
