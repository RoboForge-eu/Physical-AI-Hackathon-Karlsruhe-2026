"""Anflug: den Arm in die Startstellung ueber dem Karton bringen, von der aus das VLA gelernt hat.

Zwei Stufen (Coarse-to-Fine, wie Johns 2021 / DOME 2022):
  1. grobziel(): Kartonposition (Plan-Koordinaten, cm) -> Gelenkstellung. Eine einfache lineare Formel je Gelenk:
        gelenk = a * (Peilwinkel - 90) + b * (Abstand - 28) + c * (Kartondrehung gegen Peilung) + d
     Die Zahlen a..d werden aus den Aufnahmen bestimmt (lerne): jede Episode hat die Soll-Platzierung und die
     Startstellung. Kein neuronales Netz, keine Uebersichtskamera-Aufnahmen noetig - nur Ausgleichsrechnung.
  2. Feinausrichten mit der Handkamera-Maske (Servo): Fehler = Maskenwerte - Mittelwerte aus dem Training.
     Drei Stellgroessen: Basis drehen (seitlich), vor/zurueck (radial, wie in den Aufnahmen), Handgelenk rollen.
     Die Wirkung jeder Stellgroesse aufs Bild wird mit drei kleinen Testbewegungen gemessen (Bild-Jacobi-Matrix),
     dann wird in kleinen Schritten nachgeregelt, bis die Maske gruen ist und nahe am Trainingsmittel liegt.

Datei: calibration/anflug_<arm>.json (von lerne geschrieben).
"""
import glob, json, math, os
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALDIR = os.path.join(HERE, "calibration")
TICKS_PRO_GRAD = 4096 / 360
ROLL_PERIODE = 2048                 # Greifer ist um 180 Grad symmetrisch
ROLL_BEVORZUGT = 1300               # von zwei gleichwertigen Rollstellungen die naehere nehmen
MASKE_FEHLER = ("vorne_dx", "vorne_y", "vorne_winkel")


def pfad(arm):
    return os.path.join(CALDIR, f"anflug_{arm}.json")


def merkmale(platz):
    """Platzierung {x, y, winkel} (cm, Grad; Ursprung = Basisachse, y vom Roboter weg) -> Merkmalsvektor."""
    peil = math.degrees(math.atan2(platz["y"], platz["x"]))
    r = math.hypot(platz["x"], platz["y"])
    rel = (platz["winkel"] - peil) % 180 - 90          # 0 = quer (lange Seite zur Basis), +-90 = laengs
    return np.array([peil - 90, r - 28, rel, 1.0])


def _roll_nah(wert, ziel):
    """Gleichwertige Rollstellung (+-2048) waehlen, die am naechsten an ziel liegt."""
    k = round((ziel - wert) / ROLL_PERIODE)
    return wert + k * ROLL_PERIODE


def lerne(ordner, arm="follower", speichern=True):
    """Formel aus Episoden bestimmen. ordner: Datensatz-Ordner (Liste). Gibt das Modell (dict) zurueck."""
    X, Y, M, G = [], [], [], []
    for d in ordner:
        for f in sorted(glob.glob(os.path.join(d, "ep_*", "info.json"))):
            with open(f, encoding="utf-8") as fh:
                i = json.load(fh)
            if not i.get("startpose") or not i.get("platzierung_soll") or i.get("split", "train") != "train":
                continue
            X.append(merkmale(i["platzierung_soll"]))
            Y.append([float(v) for v in i["startpose"][:5]])
            G.append(float(i["startpose"][5]))
            if i.get("maske_werte"):
                M.append(i["maske_werte"])
    if len(X) < 10:
        raise ValueError(f"Zu wenige Episoden mit Platzierung und Startstellung ({len(X)})")
    X, Y = np.array(X), np.array(Y)
    # Rolle: Periode 180 Grad -> erst grob (Steigung = Drehung der Kartonkante) entfalten, dann ausgleichen
    roll = Y[:, 4]
    c0 = float(np.median([_roll_nah(r - TICKS_PRO_GRAD * x[2], ROLL_BEVORZUGT) for r, x in zip(roll, X)]))
    Y[:, 4] = [_roll_nah(r, c0 + TICKS_PRO_GRAD * x[2]) for r, x in zip(roll, X)]
    koef, rest = [], []
    for k in range(5):
        c, *_ = np.linalg.lstsq(X, Y[:, k], rcond=None)
        koef.append([round(float(v), 3) for v in c])
        rest.append(round(float(np.std(Y[:, k] - X @ c)), 1))
    ziel = {k: round(float(np.mean([m[k] for m in M if k in m])), 3) for k in ("vorne_y", "vorne_dx", "vorne_winkel",
                                                                              "hinten_y") if any(k in m for m in M)}
    streu = {k: round(float(np.std([m[k] for m in M if k in m])), 3) for k in ziel}
    model = {"merkmale": ["peilung-90 (Grad)", "abstand-28 (cm)", "drehung gegen peilung (Grad)", "1"],
             "gelenke": ["basis", "schulter", "ellbogen", "beugung", "drehung"],
             "koef": koef, "rest_ticks": rest, "greifer": round(float(np.median(G))),
             "maske_ziel": ziel, "maske_streuung": streu, "episoden": len(X),
             "quellen": [os.path.basename(os.path.normpath(d)) for d in ordner]}
    if speichern:
        os.makedirs(CALDIR, exist_ok=True)
        with open(pfad(arm), "w", encoding="utf-8") as f:
            json.dump(model, f, indent=1, ensure_ascii=False)
    return model


def laden(arm="follower"):
    try:
        with open(pfad(arm), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def grobziel(model, platz):
    """Platzierung -> Gelenkstellung [j1..j6] (Ticks), Greifer geschlossen wie im Training."""
    x = merkmale(platz)
    j = [float(np.dot(c, x)) for c in model["koef"]]
    j[4] = _roll_nah(j[4], ROLL_BEVORZUGT)
    return [int(round(v)) for v in j] + [int(model["greifer"])]


def richtungen(model):
    """Gelenk-Aenderung (j1..j5) je Stellgroesse: 1 Grad seitlich, 1 cm vor, 1 Tick rollen."""
    K = np.array(model["koef"])                          # 5 x 4
    seitlich = K[:, 0].copy()
    seitlich[1:] = 0                                     # nur die Basis dreht
    vor = K[:, 1].copy()
    vor[0] = vor[4] = 0                                  # Schulter/Ellbogen/Beugung wie beim Weiterweg-Stellen
    roll = np.array([0, 0, 0, 0, 1.0])
    return np.stack([seitlich, vor, roll], axis=1)       # 5 x 3


def fehler(werte, ziel):
    """Maskenwerte -> Fehlervektor (3) oder None, wenn die Vorderkante fehlt."""
    if not werte or any(k not in werte for k in MASKE_FEHLER):
        return None
    return np.array([werte[k] - ziel.get(k, 0.0) for k in MASKE_FEHLER])


TEST = np.array([2.0, 1.0, 60.0])              # Testbewegung je Stellgroesse: 2 Grad, 1 cm, 60 Ticks
GRENZE = np.array([4.0, 2.0, 120.0])           # groesster Regelschritt
SKALA = np.array([0.06, 0.035, 3.0])           # "nah genug" = etwa die Streuung der Trainings-Starts


def jacobi(messe, bewege, start_fehler):
    """Testbewegungen: Stellgroesse k um TEST[k] aendern, messen, zurueck. messe() -> Fehler oder None,
    bewege(u) faehrt um u (3 Stellgroessen) relativ. Gibt J (3x3, Fehler je Einheit) zurueck."""
    J = np.zeros((3, 3))
    for k in range(3):
        u = np.zeros(3)
        u[k] = TEST[k]
        bewege(u)
        e = messe()
        bewege(-u)
        if e is None:
            raise RuntimeError("Testbewegung: Kartonkante nicht mehr im Bild")
        J[:, k] = (e - start_fehler) / TEST[k]
    return J


def regelschritt(J, e, gain=0.7):
    """Naechste Stellgroessen (gedaempft, begrenzt). Gibt u (3) zurueck."""
    W = 1.0 / SKALA                                      # Fehlergroessen vergleichbar machen
    u, *_ = np.linalg.lstsq(J * W[:, None], -e * W, rcond=1e-3)
    u = gain * u
    f = max(1.0, float(np.max(np.abs(u) / GRENZE)))
    return u / f


def nah(e, faktor=1.0):
    return e is not None and bool(np.all(np.abs(e) <= SKALA * faktor))


def ausrichten(messe, bewege, max_schritte=12, log=print):
    """Feinausrichten. messe() -> (fehler oder None, maske_ok), bewege(u) relativ.
    Gibt dict mit ok, schritte, fehler zurueck. Ziel: Maske gruen und Fehler klein."""
    e, ok = messe()
    if e is None:
        return {"ok": False, "grund": "Vorderkante des Kartons nicht im Handkamera-Bild", "schritte": 0}
    if ok and nah(e):
        return {"ok": True, "schritte": 0, "fehler": e.round(3).tolist()}
    J = jacobi(lambda: messe()[0], bewege, e)
    log(f"Bildwirkung gemessen: {np.round(J, 4).tolist()}")
    e, ok = messe()
    for n in range(1, max_schritte + 1):
        if e is None:
            return {"ok": False, "grund": "Kartonkante verloren", "schritte": n - 1}
        u = regelschritt(J, e)
        log(f"Schritt {n}: Fehler {np.round(e, 3).tolist()} -> {np.round(u, 2).tolist()}")
        bewege(u)
        e, ok = messe()
        if ok and nah(e):
            return {"ok": True, "schritte": n, "fehler": e.round(3).tolist()}
    return {"ok": bool(ok), "schritte": max_schritte, "fehler": None if e is None else e.round(3).tolist(),
            "grund": None if ok else "Maske nach allen Schritten nicht gruen"}
