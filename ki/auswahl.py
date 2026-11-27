"""Auswahl fuer ein Training: welche Kameras, welche Episoden (Filter, Train/Test-Split).
Ohne LeRobot, testbar. Wird von jobs.py (Harness) und ki.convert (ki-env, ueber eine JSON-Datei) genutzt.

Filter:
  split      "train" (Standard: Testplatzierungen T* und split=test raus) | "test" | "alle"
  befehle    "alle" (Export griff_alle) | "allgemein" (Export griff_allgemein) | "spezifisch"
  teile      Liste von Bauteil-Schluesseln oder None (alle)
Eine Episode kommt nur mit, wenn sie alle gewaehlten Kameras hat.
"""
import json, os, subprocess

EXPORTE = {"griff_alle": {"befehle": "alle"}, "griff_allgemein": {"befehle": "allgemein"}}
DEFAULT_SLOTS = {"wrist": "arm", "overview": "turm"}       # Datensatz-Kamera -> Harness-Kamera (Aufnahmeplaene)


def episode_cameras(ds, ep, info=None):
    info = info if info is not None else (ds.episode_info(ep) or {})
    if info.get("kameras"):
        return list(info["kameras"])
    return [c for c in ds.meta.get("cameras") or [] if os.path.exists(os.path.join(ds.path, ep, f"{c}.mp4"))]


def is_test(info):
    return info.get("split") == "test" or str(info.get("platzierung_id") or "").startswith("T")


def select(ds, cameras, filters=None):
    """-> (episoden, gruende) ; gruende = {episode: warum raus}."""
    f = {"split": "train", "befehle": "alle", "teile": None, **(filters or {})}
    keep, why = [], {}
    for ep in ds.episodes():
        info = ds.episode_info(ep) or {}
        test = is_test(info)
        if f["split"] == "train" and test:
            why[ep] = "Testplatzierung"
        elif f["split"] == "test" and not test:
            why[ep] = "kein Test"
        elif f["befehle"] != "alle" and info.get("befehlsart", "allgemein") != f["befehle"]:
            why[ep] = f"Befehl {info.get('befehlsart')}"
        elif f["teile"] and info.get("zielbauteil") not in f["teile"]:
            why[ep] = "anderes Bauteil"
        elif any(c not in episode_cameras(ds, ep, info) for c in cameras):
            why[ep] = "Kamera fehlt"
        else:
            keep.append(ep)
    return keep, why


def stats(ds, eps):
    """Kurze Uebersicht fuer die Vorschau: Episoden, Bilder, je Bauteil/Befehlsart/Ausrichtung."""
    out = {"episoden": len(eps), "bilder": 0, "bauteil": {}, "befehlsart": {}, "ausrichtung": {}, "platzierungen": set()}
    for ep in eps:
        info = ds.episode_info(ep) or {}
        out["bilder"] += int(info.get("frames") or 0)
        for k in ("bauteil", "befehlsart", "ausrichtung"):
            v = info.get("zielbauteil" if k == "bauteil" else k) or "-"
            out[k][v] = out[k].get(v, 0) + 1
        if info.get("platzierung_id"):
            out["platzierungen"].add(info["platzierung_id"])
    out["platzierungen"] = sorted(out["platzierungen"])
    return out


def warnings(ds, cameras, eps, why):
    w = []
    if not cameras:
        w.append("Keine Kamera gewaehlt.")
    lost = sum(1 for r in why.values() if r == "Kamera fehlt")
    if lost:
        w.append(f"{lost} Episoden ohne alle gewaehlten Kameras bleiben draussen.")
    if len(eps) < 20:
        w.append(f"Nur {len(eps)} Episoden: eher zu wenig fuer ein gutes Modell.")
    return w


def slot_map(ds):
    """Datensatz-Kamera -> Harness-Kamera (arm/turm). Alte Datensaetze nutzen direkt die Harness-Namen."""
    m = ds.meta.get("kamera_slots")
    if m:
        return dict(m)
    return {c: DEFAULT_SLOTS.get(c, c) for c in ds.meta.get("cameras") or []} if ds.meta.get("plan") else {}


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=os.path.dirname(os.path.abspath(__file__)),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip() or None
    except Exception:
        return None


def write(path, cameras, eps):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cameras": list(cameras), "episodes": list(eps)}, f, indent=1)
