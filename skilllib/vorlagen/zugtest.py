"""Zugtest: leicht nach oben ziehen. Folgt die Spitze nicht (Soll/Ist-Abweichung), sitzt das Teil fest."""


def run(robot, zug_mm=2.0):
    k = robot.kontakt()
    rest = k.get("fehler_z_mm") or 0
    hoch = max(-5, min(5, rest + zug_mm))          # Soll erst auf das Ist, dann zug_mm darueber
    robot.korrektur(dz=hoch)
    robot.warte(0.3)
    k = robot.kontakt()
    zurueck = k.get("fehler_z_mm") or 0             # < 0: Spitze blieb unter dem Soll
    robot.korrektur(dz=-hoch)
    if -zurueck > zug_mm * 0.5:
        return {"erfolg": True, "grund": "haelt", "bericht": f"Zugtest mit {zug_mm} mm: Teil haelt "
                f"(Spitze blieb {-zurueck:.1f} mm hinter dem Soll)."}
    return {"erfolg": False, "grund": "lose", "bericht": f"Zugtest mit {zug_mm} mm: Spitze folgte "
            f"(nur {-zurueck:.1f} mm Abweichung), Teil sitzt nicht fest."}
