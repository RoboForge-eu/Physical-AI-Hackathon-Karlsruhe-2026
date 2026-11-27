"""Kleine kartesische Korrektur der Werkzeugspitze ueber die Kinematik aus remote_kin.

Grenzen (fest, nicht vom Skill/Agent aenderbar):
  - hoechstens MAX_SCHRITT_MM je Achse und Aufruf (laengere Wege: mehrere Aufrufe, dazwischen messen),
  - Neigung der Hand, Handgelenk-Rolle und Greifer bleiben, wie sie sind,
  - Ziel muss loesbar sein und alle Gelenke JOINT_MARGIN vor den Anschlaegen (remote_kin.joints_ok),
  - Gelenkspruenge > MAX_TICKS je Aufruf werden abgelehnt (Schutz gegen Ellbogen-Umschlag).
Bewusst NICHT remote_kin.in_box: Einstecken passiert knapp ueber der Halterung (z < 3 cm).
Langsam faehrt erst der Aufrufer (Harness-Sitzung bzw. Simulation), hier wird nur gerechnet.
"""
import math
import remote_kin as K

MAX_SCHRITT_MM = 5.0
MAX_TICKS = 120
MIN_Z_M = 0.0


class KorrekturFehler(ValueError):
    pass


def spitze(soll):
    return K.fk({1: soll[0], 2: soll[1], 3: soll[2], 4: soll[3]})


def korrektur(soll, dx_mm=0.0, dy_mm=0.0, dz_mm=0.0):
    """soll: [6 Ticks] (aktuelles Soll). -> (neues Soll [6], neue Spitze (x, y, z, phi) in m)."""
    for name, v in (("dx", dx_mm), ("dy", dy_mm), ("dz", dz_mm)):
        if not math.isfinite(float(v)) or abs(float(v)) > MAX_SCHRITT_MM + 1e-9:
            raise KorrekturFehler(f"{name}={v} mm: hoechstens {MAX_SCHRITT_MM} mm je Schritt")
    x, y, z, phi = spitze(soll)
    ziel = (x + dx_mm / 1000, y + dy_mm / 1000, z + dz_mm / 1000, phi)
    if ziel[2] < MIN_Z_M:
        raise KorrekturFehler("Ziel unter der Tischplatte")
    j = K.ik(ziel)
    if j is None:
        raise KorrekturFehler("Ziel nicht erreichbar")
    j = {s: int(round(v)) for s, v in j.items()}
    if not K.joints_ok(j):
        raise KorrekturFehler("Ziel zu nah an einem Gelenkanschlag oder Arm zu tief")
    sprung = max(abs(j[s] - soll[s - 1]) for s in range(1, 5))
    if sprung > MAX_TICKS:
        raise KorrekturFehler(f"Gelenksprung {sprung} Ticks - Korrektur abgelehnt")
    neu = [j[1], j[2], j[3], j[4], int(soll[4]), int(soll[5])]
    return neu, spitze(neu)
