"""Kontakt ohne Kraftsensor: aus Servo-Soll/Ist (OBS-Zeilen: Ist | Ziel) und Servolast (LAST-Zeilen).

Idee: Die Spitzenhoehe wird zweimal ueber die Kinematik gerechnet - aus dem Soll und aus dem Ist.
  fehler_z = z(Ist) - z(Soll) - Nulllinie   > 0: Spitze steht hoeher als befohlen -> etwas haelt sie auf
  Nulllinie: gleitender Mittelwert des Fehlers, solange kein Kontakt ist. Noetig, weil der echte Arm ohne
  Kontakt im Mittel ~10 mm unter dem Soll haengt (Schwerkraft/Regelrest, aus 26 000 Proben, regel/schwellen.py).
Ereignisse (je einmal, in Saetzen auswertbar):
  'angestossen'  fehler_z > ANSTOSS_MM fuer ANSTOSS_N Proben in Folge, oder Lastanstieg > LAST_ANSTIEG
  'abgesackt'    Ist-Hoehe faellt innerhalb SACK_FENSTER_S um > SACK_MM mehr als befohlen
                 (Stift rutscht in die Oeffnung)
  'frei'         nach Kontakt wieder fehler_z < FREI_MM
Schwellen: offline aus aufgenommenen Episoden (regel/schwellen.py) und der Simulation bestimmt, siehe
AGENTIC.md. Am echten Arm prueft sie der Nutzer vor Ort; sie sind Konstanten, kein Skill/Agent aendert sie.
"""
from collections import deque
from .kartesisch import spitze

ANSTOSS_MM = 1.5
ANSTOSS_N = 3
FREI_MM = 0.6
SACK_MM = 1.0
SACK_FENSTER_S = 0.4
LAST_ANSTIEG = 120          # Promille Summe Gelenke 2-4 ueber der Grundlast im freien Zustand


class KontaktMelder:
    def __init__(self):
        self.reset()

    def reset(self):
        self.kontakt = False
        self.n_ueber = 0
        self.verlauf = deque()          # (t, z_ist, z_soll)
        self.grundlast = None
        self.ereignisse = []            # alle (t, art, text)
        self.neu = []                   # seit dem letzten abholen()
        self.letzte = {}
        self.t_kontakt = None
        self.nulllinie = None

    def _melde(self, t, art, text):
        e = {"t": round(t, 3), "art": art, "text": text}
        self.ereignisse.append(e)
        self.neu.append(e)

    def probe(self, t, soll, ist, last=None):
        z_s = spitze(soll)[2] * 1000
        z_i = spitze(ist)[2] * 1000
        roh = z_i - z_s
        if self.nulllinie is None:
            self.nulllinie = roh
        fehler = roh - self.nulllinie
        if not self.kontakt and abs(fehler) < FREI_MM:   # nur frei und nahe der Nulllinie nachfuehren, sonst lernt er den Kontakt
            self.nulllinie = 0.98 * self.nulllinie + 0.02 * roh
        lastsum = sum(last[1:4]) if last else None
        if lastsum is not None and not self.kontakt:
            self.grundlast = lastsum if self.grundlast is None else 0.9 * self.grundlast + 0.1 * lastsum
        self.n_ueber = self.n_ueber + 1 if fehler > ANSTOSS_MM else 0
        last_hoch = (lastsum is not None and self.grundlast is not None and self.kontakt is False
                     and lastsum - self.grundlast > LAST_ANSTIEG and fehler > FREI_MM)
        if not self.kontakt and (self.n_ueber >= ANSTOSS_N or last_hoch):
            self.kontakt, self.t_kontakt = True, t
            self._melde(t, "angestossen", f"angestossen bei Hoehe {z_i:.1f} mm (Soll {fehler:.1f} mm tiefer)")
        self.verlauf.append((t, z_i, z_s))
        while self.verlauf and t - self.verlauf[0][0] > SACK_FENSTER_S:
            self.verlauf.popleft()
        t0, zi0, zs0 = self.verlauf[0]
        sack = (zi0 - z_i) - max(0.0, zs0 - z_s)
        if sack > SACK_MM and self.kontakt:
            dauer = t - (self.t_kontakt or t)
            self._melde(t, "abgesackt", f"um {zi0 - z_i:.1f} mm abgesackt (nach {dauer:.1f} s Kontakt), "
                                        f"jetzt Hoehe {z_i:.1f} mm")
            self.verlauf.clear()
            self.verlauf.append((t, z_i, z_s))
        if self.kontakt and fehler < FREI_MM:
            self.kontakt = False
            self.n_ueber = 0
            self._melde(t, "frei", f"frei bei Hoehe {z_i:.1f} mm")
        self.letzte = {"t": round(t, 3), "z_ist_mm": round(z_i, 2), "z_soll_mm": round(z_s, 2),
                       "fehler_z_mm": round(fehler, 2), "nulllinie_mm": round(self.nulllinie, 2), "last": list(last) if last else None, "kontakt": self.kontakt}
        return self.letzte

    def abholen(self):
        """Aktueller Zustand + neue Ereignisse seit dem letzten Abholen (fuer robot.kontakt())."""
        neu, self.neu = self.neu, []
        return {**self.letzte, "zustand": "beruehrt" if self.kontakt else "frei", "ereignisse": neu}
