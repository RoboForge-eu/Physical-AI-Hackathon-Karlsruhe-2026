"""Example code skill: mean brightness of a camera image (basis for "is the slot empty/occupied?").

A code skill is a plain Python function that calls harness skills and returns a clear result.
In the orchestrator: from skills.beispiel_skill import helligkeit
"""
import base64


def helligkeit(ros, arm="follower", kamera="arm"):
    """Mean brightness 0..255 of the current camera image (helligkeit = brightness)."""
    import cv2
    import numpy as np
    jpg = base64.b64decode(ros.call("kamera.bild", arm=arm, kamera=kamera)["jpeg_base64"])
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    return float(img.mean())
