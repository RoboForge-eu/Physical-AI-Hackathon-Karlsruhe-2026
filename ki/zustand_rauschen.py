"""Gelenkstellung beim Lernen verrauschen (laeuft in der KI-Umgebung, im Training).

Problem: Beim Aufnehmen faehrt man den Arm von Hand ueber das Teil. Die Startstellung verraet dann schon, wo das
Teil liegt, und das Modell lernt die Abkuerzung "von dieser Stellung aus fahre ich dorthin" - es schaut kaum
aufs Bild und macht immer dieselbe Bewegung.

Abhilfe: Jedes Lernbeispiel bekommt eine zufaellig verschobene Stellung (Grad, Normalverteilung) fuer Basis,
Schulter, Ellbogen, Handgelenk und Drehung. Der Greifer bleibt (offen/zu ist eine echte Information). Die Ziele
(Aktionen) bleiben unveraendert. So ist die Stellung nur noch ungefaehr, und das Bild muss den Rest liefern.
"""
import numpy as np

GELENKE = 5                    # Index 0..4 verrauschen, 5 (Greifer) nicht
_KLASSEN = {}


def verrauschen(zustand, sigma, rng=np.random):
    """zustand: Tensor oder Array (..., 6) in Grad -> gleicher Typ mit Rauschen auf den ersten 5 Werten.
    Bei Tensoren Zufall von torch: der wird in jedem Lade-Prozess neu gesetzt (numpy dort nicht immer)."""
    if sigma <= 0:
        return zustand
    if hasattr(zustand, "clone"):                       # torch.Tensor
        import torch
        out = zustand.clone()
        out[..., :GELENKE] += torch.randn(tuple(out.shape[:-1]) + (GELENKE,), dtype=out.dtype) * float(sigma)
        return out
    n = rng.normal(0.0, sigma, size=tuple(zustand.shape[:-1]) + (GELENKE,)).astype(np.float32)
    out = np.array(zustand, dtype=np.float32, copy=True)
    out[..., :GELENKE] += n
    return out


def klasse(base):
    """Unterklasse von `base`, deren Beispiele eine verrauschte Stellung haben. Liegt als Modul-Attribut
    'Verrauscht<Base>' bereit, damit die Lade-Prozesse (Windows startet sie neu) sie beim Entpacken finden."""
    name = f"Verrauscht{base.__name__}"
    if name not in _KLASSEN:
        def rauschen(self, item):
            if isinstance(item, dict) and "observation.state" in item:
                item["observation.state"] = verrauschen(item["observation.state"], getattr(self, "_rausch_sigma", 0))
            return item

        def __getitem__(self, idx):
            item = base.__getitem__(self, idx)
            return [rauschen(self, i) for i in item] if isinstance(item, list) else rauschen(self, item)

        attrs = {"__getitem__": __getitem__, "__module__": __name__}
        if hasattr(base, "__getitems__"):        # DataLoader holt ganze Stapel darueber, an __getitem__ vorbei
            def __getitems__(self, idxs):
                return [rauschen(self, i) for i in base.__getitems__(self, idxs)]
            attrs["__getitems__"] = __getitems__
        _KLASSEN[name] = type(name, (base,), attrs)
    return _KLASSEN[name]


def mit_rauschen(dataset, sigma):
    dataset.__class__ = klasse(type(dataset))
    dataset._rausch_sigma = float(sigma)
    return dataset


def __getattr__(name):
    """Beim Entpacken im Lade-Prozess: Klasse neu erzeugen."""
    if name == "VerrauschtLeRobotDataset":
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        return klasse(LeRobotDataset)
    raise AttributeError(name)
