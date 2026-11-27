"""Steckplaetze fuer Lernverfahren.

Jede Methode beschreibt nur:
  - wie sie heisst und was sie kann (fuer Oberflaeche, Fernzugriff, spaeter Agent)
  - wie sie trainiert wird   -> train_command(...)  (laeuft in der KI-Umgebung)
  - wie sie faehrt           -> runner_spec          (Klasse, die der KI-Fahrer laedt)

Eine eigene Methode = eine neue Method(...) mit register(). Alles andere (Aufnahme, Sicherheit,
Stop, Fernsteuerung, Auswahl in der KI-Werkstatt) funktioniert dann ohne Aenderung.
"""
from dataclasses import dataclass, field


@dataclass
class Method:
    key: str                         # kurz, fuer Befehle und Dateien: "act"
    label: str                       # fuer Menschen: "ACT"
    description: str
    uses_language: bool              # versteht einen Aufgabentext
    multi_task: bool                 # mehrere Aufgaben in einem Modell
    default_steps: int
    batch_size: int
    # Trainingsbefehl; Platzhalter {python} {dataset} {repo} {out} {steps} {batch} {job}
    train: list = field(default_factory=list)
    # Was der KI-Fahrer laedt: "modul:Klasse" in der KI-Umgebung, plus Hinweise
    runner: str = ""
    notes: str = ""
    # Kameranamen, die ein vortrainiertes Modell erwartet (unsere Kameras werden der Reihe nach darauf
    # abgebildet); None = unsere Namen behalten
    camera_names: list = None
    # Gelenkstellung beim Lernen verrauschen (Grad, 0 = aus): gegen die Abkuerzung "Startstellung -> Bewegung"
    state_noise_deg: float = 0.0

    def train_command(self, python, dataset_root, repo_id, out_dir, steps=None, batch=None, job="job"):
        values = {"python": python, "dataset": dataset_root, "repo": repo_id, "out": out_dir,
                  "steps": steps or self.default_steps, "batch": batch or self.batch_size, "job": job}
        return [str(part).format(**values) for part in self.train]

    def info(self):
        return {"key": self.key, "label": self.label, "description": self.description,
                "uses_language": self.uses_language, "multi_task": self.multi_task,
                "default_steps": self.default_steps}


_REGISTRY = {}


def register(method):
    _REGISTRY[method.key] = method
    return method


def get(key):
    if key not in _REGISTRY:
        raise KeyError(f"Unbekannte Methode {key!r}. Vorhanden: {', '.join(_REGISTRY)}")
    return _REGISTRY[key]


def all_methods():
    return list(_REGISTRY.values())


# --- Eingebaute Methoden (beide ueber LeRobot; Befehl in der KI-Umgebung gleich bis auf den Typ) ---
_LEROBOT_TRAIN = ["{python}", "-m", "ki.train",
                  "--dataset.repo_id={repo}", "--dataset.root={dataset}",
                  "--output_dir={out}", "--job_name={job}", "--steps={steps}", "--batch_size={batch}",
                  "--policy.device=auto", "--policy.push_to_hub=false",
                  "--save_freq=1000", "--log_freq=50"]   # Zwischenstand alle 1000: Weitertrainieren nach PC-Neustart

register(Method(
    key="act", label="ACT",
    description="Lernt genau eine Aufgabe aus Vorfuehrungen. Klein, schnell trainiert, zuverlaessig. Versteht keinen Text.",
    uses_language=False, multi_task=False, default_steps=40000, batch_size=8,
    train=_LEROBOT_TRAIN + ["--policy.type=act"],
    runner="ki.lerobot_runner:LeRobotRunner",
    notes="Gut als erster Versuch: zeigt schnell, ob Aufnahme und Kette funktionieren."))

register(Method(
    key="smolvla", label="SmolVLA",
    description="Vortrainiertes Vision-Language-Action-Modell. Versteht Aufgabentexte, kann mehrere Aufgaben, "
                "robuster bei Abweichungen. Groesser, Training dauert laenger.",
    uses_language=True, multi_task=True, default_steps=20000, batch_size=32,
    train=_LEROBOT_TRAIN + ["--policy.path=lerobot/smolvla_base"],
    runner="ki.lerobot_runner:LeRobotRunner",
    camera_names=["camera1", "camera2", "camera3"],
    notes="Startet vom vortrainierten Modell lerobot/smolvla_base (Download beim ersten Training)."))

register(Method(
    key="smolvla_robust", label="SmolVLA robust",
    description="Wie SmolVLA, aber die Gelenkstellung wird beim Lernen verrauscht (+-8 Grad). Das Modell kann sich "
                "nicht mehr auf die Startstellung verlassen und muss aufs Kamerabild schauen. Fuer Aufnahmen, bei "
                "denen der Arm von Hand ueber das Teil gefahren wurde.",
    uses_language=True, multi_task=True, default_steps=30000, batch_size=32,
    train=_LEROBOT_TRAIN + ["--policy.path=lerobot/smolvla_base"],
    runner="ki.lerobot_runner:LeRobotRunner",
    camera_names=["camera1", "camera2", "camera3"],
    state_noise_deg=8.0,
    notes="Gegen 'macht immer dieselbe Bewegung'. Gleiches Fahren wie SmolVLA, nur das Training unterscheidet sich."))
