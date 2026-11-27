"""Ablaeufe als JSON-Dateien in ki_daten/workflow/."""
import json, os, re
from ki import DATA

ROOT = os.path.join(DATA, "workflow")


def path_for(name, root=None):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                  .replace("ß", "ss")).strip("_") or "ablauf"
    return os.path.join(root or ROOT, slug + ".json")


def save(p, root=None):
    os.makedirs(root or ROOT, exist_ok=True)
    path = path_for(p["name"], root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=1, ensure_ascii=False)
    return path


def names(root=None):
    root = root or ROOT
    if not os.path.isdir(root):
        return []
    out = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".json"):
            try:
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    out.append((json.load(fh)["name"], os.path.join(root, f)))
            except (OSError, ValueError, KeyError):
                pass
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
