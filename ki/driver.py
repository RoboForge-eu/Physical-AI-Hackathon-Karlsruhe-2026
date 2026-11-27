"""KI-Fahrer: laeuft in der KI-Umgebung als eigener Prozess, gestartet von ROS.

  python -m ki.driver <modell-ordner>

Protokoll ueber stdin/stdout (binaer, eine Anfrage -> eine Antwort):
  ROS -> Fahrer : JSON-Zeile + Bilddaten
      {"cmd": "obs", "state": [6 Servo-Schritte], "task": "...", "images": {"arm": [h, w], ...}}
      danach die Bilder (BGR, uint8, h*w*3 Bytes) in der Reihenfolge von "images"
      {"cmd": "reset"}       neue Episode
  Fahrer -> ROS : JSON-Zeile
      {"ready": true, ...} einmal nach dem Laden, dann je Anfrage {"action": [6 Servo-Schritte], "ms": ...}
      oder {"error": "..."}
Alles andere (Logs von LeRobot/PyTorch) geht nach stderr, damit das Protokoll sauber bleibt.
"""
import importlib, json, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ki import methods  # noqa: E402
from ki.units import to_deg, to_steps  # noqa: E402


def load_runner(model_dir):
    with open(os.path.join(model_dir, "modell.json"), encoding="utf-8") as f:
        meta = json.load(f)
    module, cls = methods.get(meta["method"]).runner.split(":")
    runner = getattr(importlib.import_module(module), cls)(meta["checkpoint"])
    return runner, meta


def read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf.extend(chunk)
    return bytes(buf)


def serve(model_dir, stdin=None, stdout=None, loader=load_runner):
    stdin = stdin or sys.stdin.buffer
    out = stdout or os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr                    # alle fremden Ausgaben weg vom Protokoll
    import cv2
    def send(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()
    try:
        runner, meta = loader(model_dir)
    except Exception as exc:
        send({"error": f"Modell laden fehlgeschlagen: {exc}"})
        return 1
    send({"ready": True, "method": meta["method"], "cameras": meta.get("cameras"), "task": meta.get("task")})
    while True:
        line = stdin.readline()
        if not line:
            return 0
        try:
            msg = json.loads(line)
            if msg.get("cmd") == "reset":
                runner.reset()
                send({"ok": True})
                continue
            images = {}
            for cam, (h, w) in msg["images"].items():
                bgr = np.frombuffer(read_exact(stdin, h * w * 3), dtype=np.uint8).reshape(h, w, 3)
                images[cam] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            cmap = meta.get("camera_map") or {}
            if meta.get("dataset_cameras") is not None:      # Modell nutzt nur einen Teil der Kameras
                images = {k: v for k, v in images.items() if k in (meta.get("cameras") or [])}
            images = {cmap.get(k, k): v for k, v in images.items()}   # z. B. arm -> camera1 (SmolVLA)
            t = time.perf_counter()
            action = runner.act(to_deg(msg["state"]), images, msg.get("task") or meta.get("task") or "")
            send({"action": [int(v) for v in to_steps(action)], "ms": round((time.perf_counter() - t) * 1000, 1)})
        except EOFError:
            return 0
        except Exception as exc:
            send({"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(serve(sys.argv[1]))
