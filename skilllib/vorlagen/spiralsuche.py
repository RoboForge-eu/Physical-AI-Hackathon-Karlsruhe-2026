"""Spiralsuche: absenken bis Kontakt, leicht andruecken, in kleiner (eckiger) Spirale suchen.
Erfolg = Ereignis 'abgesackt' (Stift rutscht in die Oeffnung)."""


def spirale(schritt, max_radius):
    wege = []
    n = 1
    richtungen = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    k = 0
    while n * schritt <= 2 * max_radius:
        for wdh in range(2):
            rx, ry = richtungen[k % 4]
            wege.append((rx * n * schritt, ry * n * schritt))
            k += 1
        n += 1
    return wege


def einfuehren(robot, saetze, max_mm=20, oberflaeche_mm=None, min_tiefe_mm=6):
    """Nach dem Absacken weiter absenken, bis der Stift unten aufsitzt (Kontakt) - der Arm faehrt nur bis zum Soll."""
    robot.kontakt()
    for i in range(int(max_mm)):
        robot.korrektur(dz=-1)
        k = robot.kontakt()
        if any(e["art"] == "angestossen" for e in k["ereignisse"]):
            z = k.get("z_ist_mm")
            tiefe = (oberflaeche_mm - z) if (oberflaeche_mm is not None and z is not None) else None
            if tiefe is not None and tiefe < min_tiefe_mm:
                saetze.append(f"Nach {i + 1} mm Einfuehren Anschlag schon {tiefe:.1f} mm unter der Oberflaeche: "
                              "verkantet.")
                return False
            saetze.append(f"Weitere {i + 1} mm eingefuehrt, sitzt unten auf (Hoehe {z} mm"
                          + (f", {tiefe:.1f} mm tief)." if tiefe is not None else ")."))
            return True
    saetze.append(f"{max_mm} mm eingefuehrt ohne Anschlag.")
    return False


def run(robot, andruck_mm=2.0, schritt_mm=0.5, max_radius_mm=3.0, spalt_mm=12.0):
    """spalt_mm: Abstand Spitze -> Oberflaeche zu Beginn (Schwebehoehe der Pose). Kontakt erst deutlich tiefer
    heisst: der Stift ist ohne Widerstand in die Oeffnung eingetaucht."""
    max_absenken_mm = spalt_mm + 25
    t0 = robot.zeit()
    robot.kontakt()
    saetze = []
    kontakt_bei = None
    abgesenkt = 0
    while abgesenkt < max_absenken_mm and kontakt_bei is None:
        robot.korrektur(dz=-1)
        abgesenkt += 1
        k = robot.kontakt()
        for e in k["ereignisse"]:
            if e["art"] == "angestossen":
                kontakt_bei = k.get("z_ist_mm")
                saetze.append(f"Kontakt bei {kontakt_bei} mm Hoehe nach {abgesenkt} mm Absenken und {robot.zeit() - t0:.1f} s.")
                if abgesenkt > spalt_mm + 3:
                    saetze.append(f"Das sind {abgesenkt - spalt_mm:.0f} mm tiefer als die Oberflaeche: Stift ohne "
                                  "Widerstand in die Oeffnung eingetaucht.")
                    return {"erfolg": True, "grund": "eingetaucht", "bericht": " ".join(saetze)}
            if e["art"] == "abgesackt":
                saetze.append("Beim Absenken direkt in die Oeffnung gerutscht.")
                return {"erfolg": True, "grund": "abgesackt", "bericht": " ".join(saetze)}
    if kontakt_bei is None:
        return {"erfolg": False, "grund": f"kein Kontakt nach {abgesenkt} mm", "bericht": " ".join(saetze)}
    robot.korrektur(dz=-andruck_mm)
    k = robot.kontakt()
    if any(e["art"] == "abgesackt" for e in k["ereignisse"]):
        saetze.append("Beim Andruecken abgesackt.")
        if not einfuehren(robot, saetze, oberflaeche_mm=kontakt_bei):
            return {"erfolg": False, "grund": "verkantet", "bericht": " ".join(saetze)}
        return {"erfolg": True, "grund": "abgesackt", "bericht": " ".join(saetze)}
    saetze.append(f"Druecke {andruck_mm} mm an und suche in einer Spirale bis {max_radius_mm} mm.")
    gesamt = 0
    for dx, dy in spirale(schritt_mm, max_radius_mm):
        robot.korrektur(dx=dx, dy=dy)
        gesamt += 1
        k = robot.kontakt()
        for e in k["ereignisse"]:
            if e["art"] == "abgesackt":
                saetze.append(f"Nach {gesamt} Spiralschritten und {robot.zeit() - t0:.1f} s {e['text']}.")
                robot.korrektur(dx=-dx / 2, dy=-dy / 2)     # halber Schritt zurueck: Soll wieder ueber den Stift
                if not einfuehren(robot, saetze, oberflaeche_mm=kontakt_bei):
                    return {"erfolg": False, "grund": "verkantet", "bericht": " ".join(saetze)}
                return {"erfolg": True, "grund": "abgesackt", "spiralschritte": gesamt, "bericht": " ".join(saetze)}
    robot.korrektur(dz=andruck_mm + 2)
    saetze.append(f"Spirale ({gesamt} Schritte) ohne Absacken beendet, Spitze wieder angehoben.")
    return {"erfolg": False, "grund": "nicht abgesackt", "bericht": " ".join(saetze)}
