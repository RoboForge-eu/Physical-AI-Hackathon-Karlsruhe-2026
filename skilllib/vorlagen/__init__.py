"""Vorlagen fuer Code-Skills mit Regelschleife (Agentic Robotics). Jede Vorlage ist normaler Skill-Code
(run(robot, ...)), den der SkillAuthor lesen, kopieren und verbessern kann.

  installieren(root=None)  legt alle Vorlagen als Skills in der Bibliothek an (Version 1, aktiv), falls noch nicht da.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VORLAGEN = {
    "visuelles_ausrichten": ("Werkzeugspitze per Handgelenk-Kamera ueber ein Merkmal (Oeffnung/Marker) ausrichten",
                             "Restabstand unter der Toleranz", {"ziel": "oeffnung|marker|kreis", "toleranz_mm": "Standard 0.5",
                                                                "max_versuche": "Standard 8"}),
    "spiralsuche": ("Leicht andruecken und in kleiner Spirale suchen, bis der Stift in die Oeffnung absackt",
                    "Ereignis 'abgesackt'", {"andruck_mm": "Standard 2", "schritt_mm": "Standard 0.5",
                                              "max_radius_mm": "Standard 3"}),
    "zugtest": ("Leicht ziehen und pruefen, ob das Teil festsitzt", "Spitze folgt dem Zug nicht (Teil haelt)",
                {"zug_mm": "Standard 2"}),
    "stift_einstecken": ("Stift ueber der Oeffnung ausrichten, absenken, per Spiralsuche einstecken, Zugtest",
                         "abgesackt und Zugtest haelt", {}),
    "schachtel_auf_palette": ("Kabel-Schachtel greifen und auf die Palette legen", "Greifer hielt die Schachtel und "
                              "hat sie ueber der Palette abgelegt", {}),
}


def code(name):
    with open(os.path.join(HERE, name + ".py"), encoding="utf-8") as f:
        return f.read()


def installieren(root=None):
    from skilllib import store
    neu = []
    for name, (ziel, kriterium, params) in VORLAGEN.items():
        meta = store.create(name, ziel, kriterium, params, root=root)
        if not meta.get("versionen"):
            v = store.add_version(name, code(name), "Vorlage (Agentic Robotics)", root=root)
            store.set_active(name, v, root=root)
            neu.append(name)
    return neu
