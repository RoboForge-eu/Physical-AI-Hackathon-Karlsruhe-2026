"""Kabel-Schachtel greifen und auf die Palette legen (Posen aus der Bibliothek, Erfolg per Greifer-Pruefung)."""


def run(robot, versuche=2):
    for v in range(int(versuche)):
        robot.greifer(100)
        robot.pose("ueber_schachtel")
        robot.pose("an_schachtel", grad_pro_s=15)
        robot.greifer(0)
        robot.warte(0.3)
        if robot.greifer_haelt():
            break
        robot.log(f"Versuch {v + 1}: Schachtel nicht gegriffen")
        robot.pose("ueber_schachtel")
    else:
        return {"erfolg": False, "grund": "Schachtel nicht gegriffen"}
    robot.pose("ueber_schachtel")
    robot.pose("ueber_palette")
    robot.pose("auf_palette", grad_pro_s=15)
    robot.greifer(100)
    robot.pose("ueber_palette")
    return {"erfolg": True, "grund": "Schachtel liegt auf der Palette"}
