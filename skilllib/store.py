"""Code-Skills auf der Platte:

  ki_daten/skills/<name>/skill.json   Ziel, Erfolgskriterium, Parameter, aktive Version, Statistik je Version
  ki_daten/skills/<name>/v3.py        Code der Version 3 (Versionen werden nie ueberschrieben)
  ki_daten/skills/<name>/laeufe.jsonl ein Eintrag pro Lauf (Version, Art, Ergebnis, Zeit)
"""
import json, os, re, time
from ki import DATA

ROOT = os.path.join(DATA, "skills")


def slug(name):
    s = re.sub(r"[^a-z0-9_]+", "_", name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
               .replace("ß", "ss")).strip("_")
    return s[:40] or "skill"


def _dir(name, root=None):
    return os.path.join(root or ROOT, slug(name))


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def create(name, ziel, kriterium, params=None, root=None):
    d = _dir(name, root)
    os.makedirs(d, exist_ok=True)
    meta = _load(os.path.join(d, "skill.json")) or {"name": slug(name), "versionen": {}, "aktiv": None,
                                                    "erstellt": time.strftime("%Y-%m-%d %H:%M:%S")}
    meta.update(ziel=ziel, kriterium=kriterium, params=params or {})
    _write(d, meta)
    return meta


def _write(d, meta):
    with open(os.path.join(d, "skill.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)


def get(name, root=None):
    meta = _load(os.path.join(_dir(name, root), "skill.json"))
    if meta is None:
        raise KeyError(f"Skill {name!r} gibt es nicht")
    return meta


def all_skills(root=None):
    root = root or ROOT
    if not os.path.isdir(root):
        return []
    return [m for m in (_load(os.path.join(root, d, "skill.json")) for d in sorted(os.listdir(root))) if m]


def add_version(name, code, notiz="", root=None):
    d = _dir(name, root)
    meta = get(name, root)
    v = max([int(k) for k in meta["versionen"]] or [0]) + 1
    with open(os.path.join(d, f"v{v}.py"), "w", encoding="utf-8") as f:
        f.write(code)
    meta["versionen"][str(v)] = {"notiz": notiz, "zeit": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "echt": [0, 0], "trocken": [0, 0]}      # [Erfolge, Versuche]
    _write(d, meta)
    return v


def code(name, version=None, root=None):
    meta = get(name, root)
    v = version or meta.get("aktiv") or max(int(k) for k in meta["versionen"])
    with open(os.path.join(_dir(name, root), f"v{v}.py"), encoding="utf-8") as f:
        return f.read(), int(v)


def set_active(name, version, root=None):
    meta = get(name, root)
    if str(version) not in meta["versionen"]:
        raise KeyError(f"Version {version} gibt es nicht")
    meta["aktiv"] = int(version)
    _write(_dir(name, root), meta)


def record(name, version, art, result, root=None):
    """art: 'echt' oder 'trocken'. result: Rueckgabe des Laufs (mit 'erfolg')."""
    d = _dir(name, root)
    meta = get(name, root)
    stats = meta["versionen"].setdefault(str(version), {"echt": [0, 0], "trocken": [0, 0]})
    ok = bool(isinstance(result, dict) and result.get("erfolg"))
    stats[art][1] += 1
    stats[art][0] += int(ok)
    _write(d, meta)
    with open(os.path.join(d, "laeufe.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"zeit": time.strftime("%Y-%m-%d %H:%M:%S"), "version": int(version), "art": art,
                            "erfolg": ok, "ergebnis": result}, ensure_ascii=False, default=str) + "\n")
    return stats
