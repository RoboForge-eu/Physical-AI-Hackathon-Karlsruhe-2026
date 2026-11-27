"""Beispiel fuer einen Code-Skill: mittlere Helligkeit eines Kamerabilds (Grundlage fuer "Fach leer/belegt?").

Ein Code-Skill ist eine normale Python-Funktion, die Harness-Skills aufruft und ein klares Ergebnis liefert.
Im Orchestrator: from skills.beispiel_skill import helligkeit
"""
import base64


def helligkeit(ros, arm="follower", kamera="arm"):
    """Mittlere Helligkeit 0..255 des aktuellen Kamerabilds."""
    import cv2
    import numpy as np
    jpg = base64.b64decode(ros.call("kamera.bild", arm=arm, kamera=kamera)["jpeg_base64"])
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    return float(img.mean())
