"""Stift einstecken: ueber die Oeffnung fahren, visuell ausrichten, per Spiralsuche einstecken, Zugtest.
Gibt einen Ereignis-Bericht in Saetzen fuer das Sprachmodell zurueck."""


def run(robot, pose="ueber_oeffnung"):
    saetze = []
    robot.pose(pose, grad_pro_s=20)
    if not robot.messen(ziel="marker").get("kalibriert"):
        robot.kalibrieren()
        saetze.append("Handgelenk-Kamera am Marker kalibriert.")
    a = robot.skill("visuelles_ausrichten", ziel="oeffnung", toleranz_mm=0.5)
    saetze.append(a.get("bericht", ""))
    if not a.get("erfolg"):
        return {"erfolg": False, "grund": "Ausrichten: " + str(a.get("grund")), "bericht": " ".join(saetze),
                "messbild": a.get("messbild")}
    s = robot.skill("spiralsuche")
    saetze.append(s.get("bericht", ""))
    if not s.get("erfolg"):
        return {"erfolg": False, "grund": "Einstecken: " + str(s.get("grund")), "bericht": " ".join(saetze),
                "messbild": a.get("messbild")}
    z = robot.skill("zugtest")
    saetze.append(z.get("bericht", ""))
    return {"erfolg": bool(z.get("erfolg")), "grund": "eingesteckt" if z.get("erfolg") else "Zugtest: lose",
            "bericht": " ".join(saetze), "messbild": a.get("messbild")}
