"""Eigenes Aufnahmeformat. Einfach und stabil; die Umwandlung ins LeRobot-Format macht
convert.py in der KI-Umgebung direkt vor dem Training.

datensaetze/<name>/meta.json                      Aufgabe, fps, Kameras, Arm, Kalibrierung
datensaetze/<name>/ep_0007/daten.npz              t (N), state (N,6), action (N,6)
datensaetze/<name>/ep_0007/<kamera>.mp4           N Bilder, gleiche Reihenfolge
datensaetze/<name>/ep_0007/info.json              Aufgabe, Bilderzahl, Dauer, Zeitpunkt
"""
import json, os, re, shutil, threading, time
import numpy as np
from . import DATASETS, DATA

TRASH = os.path.join(DATA, "papierkorb")

FPS = 30
SIZE = (640, 360)          # Breite x Hoehe der gespeicherten Bilder (16:9 wie die Kameras)


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().replace("ä", "ae").replace("ö", "oe")
               .replace("ü", "ue").replace("ß", "ss")).strip("_")
    return s[:48] or "datensatz"


class Dataset:
    def __init__(self, path):
        self.path = path
        self.meta = load_json(os.path.join(path, "meta.json")) or {}

    @property
    def name(self):
        return os.path.basename(self.path)

    def episodes(self):
        if not os.path.isdir(self.path):
            return []
        return sorted(d for d in os.listdir(self.path)
                      if d.startswith("ep_") and os.path.exists(os.path.join(self.path, d, "info.json")))

    def frames(self):
        return sum((load_json(os.path.join(self.path, e, "info.json")) or {}).get("frames", 0) for e in self.episodes())

    def next_episode_dir(self):
        nums = [int(e[3:]) for e in self.episodes() if e[3:].isdigit()]
        return os.path.join(self.path, f"ep_{(max(nums) + 1) if nums else 0:04d}")

    def delete_episode(self, ep):
        shutil.rmtree(os.path.join(self.path, ep), ignore_errors=True)

    def episode_info(self, ep):
        return load_json(os.path.join(self.path, ep, "info.json")) or {}

    def last_frame(self, ep, camera, cv2):
        """Letztes Bild aus dem gespeicherten Kameravideo lesen, auch bei alten Episoden."""
        if not re.fullmatch(r"ep_\d+(?:_\d{8}-\d{6})?", ep) or not re.fullmatch(r"[\w-]+", camera):
            return None
        path = os.path.join(self.path, ep, f"{camera}.mp4")
        if not os.path.isfile(path):
            return None
        cap = cv2.VideoCapture(path)
        try:
            if not cap.isOpened():
                return None
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if count > 0 and cap.set(cv2.CAP_PROP_POS_FRAMES, count - 1):
                ok, frame = cap.read()
                if ok:
                    return frame
            cap.release()
            cap = cv2.VideoCapture(path)
            last = None
            while True:
                ok, frame = cap.read()
                if not ok:
                    return last
                last = frame
        finally:
            cap.release()

    def trash_episode(self, ep, trash=None):
        """Episode in den Papierkorb verschieben (ki_daten/papierkorb/<datensatz>/), nicht endgueltig loeschen."""
        if ep not in self.episodes():
            raise ValueError(f"Episode {ep} gibt es nicht")
        target_dir = os.path.join(trash or TRASH, self.name)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{ep}_{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.move(os.path.join(self.path, ep), target)
        return target


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def datasets(root=None):
    root = root or DATASETS
    if not os.path.isdir(root):
        return []
    return [Dataset(os.path.join(root, d)) for d in sorted(os.listdir(root))
            if os.path.exists(os.path.join(root, d, "meta.json"))]


def open_dataset(name, task, arm, cameras, calibration=None, root=None, variabel=False, extra_meta=None):
    """Datensatz anlegen oder oeffnen. Ein Datensatz = eine Aufgabe, ein Arm, feste Kameras.
    variabel=True (Aufnahmeplaene): Kameras duerfen je Episode wechseln (z. B. Overview-Cam kommt spaeter dazu);
    meta['cameras'] ist dann die Vereinigung, info.json jeder Episode nennt ihre Kameras."""
    path = os.path.join(root or DATASETS, slug(name))
    meta_path = os.path.join(path, "meta.json")
    meta = load_json(meta_path)
    if meta is None:
        os.makedirs(path, exist_ok=True)
        meta = {"name": name, "task": task, "arm": arm, "fps": FPS, "size": list(SIZE),
                "cameras": list(cameras), "joints": ["basis", "schulter", "ellbogen", "handgelenk_beugung",
                                                    "handgelenk_drehung", "greifer"],
                "calibration": calibration, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        if variabel:
            meta["kameras_variabel"] = True
        meta.update(extra_meta or {})
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)
    elif variabel and meta.get("kameras_variabel") and meta.get("arm") == arm:
        union = list(meta["cameras"]) + [c for c in cameras if c not in meta["cameras"]]
        if union != meta["cameras"]:
            meta["cameras"] = union
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=1, ensure_ascii=False)
    elif meta.get("cameras") != list(cameras) or meta.get("arm") != arm:
        raise ValueError(f"Datensatz '{name}' gehoert zu Arm {meta.get('arm')} mit Kameras {meta.get('cameras')}")
    return Dataset(path)


class EpisodeWriter:
    """Nimmt eine Episode auf. add() wird mit 30 Hz vom Aufnahme-Takt gerufen.
    Videos werden sofort geschrieben (wenig Speicher), Gelenkdaten am Ende."""
    def __init__(self, dataset, task, cv2, cameras=None, required=None):
        """cameras: Kameras dieser Episode (Standard: alle des Datensatzes). required: ohne Bild dieser Kameras
        wird der Schnappschuss verworfen (Standard: alle). Fehlt eine andere Kamera, wird ihr letztes Bild
        wiederholt und als verloren gezaehlt."""
        self.dataset, self.task, self.cv2 = dataset, task, cv2
        self.dir = dataset.next_episode_dir()
        self.tmp = self.dir + ".tmp"
        os.makedirs(self.tmp, exist_ok=True)
        self.cameras = list(cameras) if cameras else list(dataset.meta["cameras"])
        self.required = set(required) if required else set(self.cameras)
        self.lost = {c: 0 for c in self.cameras}
        self.last = {}
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writers = {c: cv2.VideoWriter(os.path.join(self.tmp, f"{c}.mp4"), fourcc, FPS, SIZE) for c in self.cameras}
        self.t, self.state, self.action = [], [], []
        self.lock = threading.Lock()
        self.closed = False
        self.started = time.time()

    def add(self, t, state, action, frames):
        """frames: {kamera: BGR-Bild}. Fehlt ein Bild, wird der Schnappschuss verworfen
        (lieber eine Luecke als ein falsches Bild)."""
        if state is None or action is None:
            return False
        missing = [c for c in self.cameras if frames.get(c) is None]
        for c in missing:
            self.lost[c] += 1
        if any(c in self.required for c in missing) or any(c not in self.last and frames.get(c) is None
                                                             for c in self.cameras):
            return False
        with self.lock:
            if self.closed:
                return False
            for c in self.cameras:
                img = frames.get(c)
                if img is None:
                    img = self.last[c]                 # nur optionale Kamera: letztes Bild wiederholen
                self.last[c] = img
                if (img.shape[1], img.shape[0]) != SIZE:
                    img = self.cv2.resize(img, SIZE, interpolation=self.cv2.INTER_AREA)
                self.writers[c].write(img)
            self.t.append(t)
            self.state.append(list(state))
            self.action.append(list(action))
        return True

    @property
    def frames(self):
        return len(self.t)

    def finish(self, keep, extra=None):
        """keep=True: als Episode speichern; False: verwerfen. Gibt den Ordner oder None zurueck.
        extra: zusaetzliche Metadaten fuer info.json (Plan, Runde, Maske ...)."""
        with self.lock:
            self.closed = True
            for w in self.writers.values():
                w.release()
        if not keep or self.frames < 2:
            shutil.rmtree(self.tmp, ignore_errors=True)
            return None
        np.savez(os.path.join(self.tmp, "daten.npz"), t=np.array(self.t, dtype=np.float64),
                 state=np.array(self.state, dtype=np.float32), action=np.array(self.action, dtype=np.float32))
        info = {"task": self.task, "frames": self.frames, "seconds": round(self.t[-1] - self.t[0], 2),
                "recorded": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started)),
                "kameras": list(self.cameras), "verlorene_bilder": dict(self.lost)}
        info.update(extra or {})
        with open(os.path.join(self.tmp, "info.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, ensure_ascii=False)
        os.replace(self.tmp, self.dir)
        return self.dir


def _link_or_copy(src, dst):
    """Videos und Messdaten nur verlinken (Hardlink: kein zusaetzlicher Platz, Quellen bleiben unveraendert,
    weil diese Dateien nie ueberschrieben werden). info.json wird geaendert, daher immer echt kopieren."""
    if os.path.basename(src) != "info.json":
        try:
            os.link(src, dst)
            return dst
        except OSError:
            pass
    return shutil.copy2(src, dst)


def compose(name, task, picks, root=None, eigene_aufgaben=False):
    """Neuen Datensatz aus ausgewaehlten Episoden anderer Datensaetze bauen (Kopien, Quellen bleiben).
    picks: [(datensatz, episode), ...] in gewuenschter Reihenfolge. Alle Quellen muessen zum selben Arm
    mit denselben Kameras gehoeren.
    eigene_aufgaben=True: jede Episode behaelt ihren Aufgabentext (mehrere Aufgaben in einem Datensatz, fuer
    SmolVLA); 'task' ist dann nur die Beschreibung des Datensatzes."""
    root = root or DATASETS
    if not picks:
        raise ValueError("Keine Episoden ausgewaehlt")
    path = os.path.join(root, slug(name))
    if os.path.exists(path):
        raise FileExistsError(f"Datensatz '{slug(name)}' gibt es schon")
    sources = {}
    for ds_name, ep in picks:
        if ds_name not in sources:
            sources[ds_name] = Dataset(os.path.join(root, ds_name))
        if ep not in sources[ds_name].episodes():
            raise ValueError(f"Episode {ds_name}/{ep} gibt es nicht")
    first_name = next(iter(sources))
    first = sources[first_name].meta
    for ds in sources.values():
        if ds.meta.get("arm") != first.get("arm") or ds.meta.get("cameras") != first.get("cameras"):
            raise ValueError(f"'{ds.name}' passt nicht: anderer Arm oder andere Kameras als '{first_name}'")
    meta = dict(first, name=name, task=task, created=time.strftime("%Y-%m-%d %H:%M:%S"),
                zusammengestellt_aus=sorted(sources))
    meta.pop("umgedreht_aus", None)
    def aufgabe_von(ds_name, ep):
        info = load_json(os.path.join(root, ds_name, ep, "info.json")) or {}
        return info.get("task") or sources[ds_name].meta.get("task") or task
    if eigene_aufgaben:
        meta["aufgaben"] = sorted({aufgabe_von(d, e) for d, e in picks})
    tmp = path + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        for i, (ds_name, ep) in enumerate(picks):
            dst = os.path.join(tmp, f"ep_{i:04d}")
            shutil.copytree(os.path.join(root, ds_name, ep), dst, copy_function=_link_or_copy)
            info = load_json(os.path.join(dst, "info.json")) or {}
            info.update(task=aufgabe_von(ds_name, ep) if eigene_aufgaben else task, herkunft=f"{ds_name}/{ep}")
            with open(os.path.join(dst, "info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, indent=1, ensure_ascii=False)
        with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return Dataset(path)
