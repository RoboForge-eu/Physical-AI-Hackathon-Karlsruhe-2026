"""Visuelles Ausrichten: Kamera misst Versatz -> kleine Korrektur -> wieder messen, bis < Toleranz."""


def run(robot, ziel="oeffnung", toleranz_mm=0.5, max_versuche=8, kamera="arm"):
    t0 = robot.zeit()
    saetze = []
    letzte = None
    for i in range(int(max_versuche)):
        m = robot.messen(ziel=ziel, kamera=kamera)
        letzte = m
        if not m.get("gefunden"):
            saetze.append(f"Messung {i + 1}: {ziel} nicht im Bild.")
            return {"erfolg": False, "grund": f"{ziel} nicht gefunden", "bericht": " ".join(saetze),
                    "messbild": m.get("messbild")}
        if m.get("korrektur_mm") is None:
            return {"erfolg": False, "grund": "Handgelenk-Kamera nicht kalibriert (robot.kalibrieren())",
                    "bericht": " ".join(saetze), "messbild": m.get("messbild")}
        dx, dy = m["korrektur_mm"]
        rest = (dx * dx + dy * dy) ** 0.5
        if rest <= toleranz_mm:
            saetze.append(f"Nach {i} Korrekturen ausgerichtet, Restversatz {rest:.2f} mm "
                          f"({robot.zeit() - t0:.1f} s).")
            return {"erfolg": True, "grund": "ausgerichtet", "restversatz_mm": round(rest, 2), "korrekturen": i,
                    "bericht": " ".join(saetze), "messbild": m.get("messbild")}
        dx = max(-5, min(5, dx))
        dy = max(-5, min(5, dy))
        saetze.append(f"Versuch {i + 1}: Versatz {rest:.2f} mm, korrigiere um {dx:+.2f}/{dy:+.2f} mm.")
        robot.korrektur(dx=dx, dy=dy)
    return {"erfolg": False, "grund": f"nach {max_versuche} Versuchen nicht unter {toleranz_mm} mm",
            "bericht": " ".join(saetze), "messbild": letzte.get("messbild") if letzte else None}
