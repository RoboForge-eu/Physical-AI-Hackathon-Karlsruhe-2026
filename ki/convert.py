"""Laeuft in der KI-Umgebung (ki-env): eigene Aufnahmen -> LeRobot-Datensatz (Version 0.7).

  python -m ki.convert <datensatz-ordner> <ziel-ordner> <repo_id> [kamera-zuordnung als JSON] [auswahl.json]

auswahl.json (ki/auswahl.py): {"cameras": [...], "episodes": [...]} - nur diese Kameras und Episoden.

Einheiten: Gelenke in Grad relativ zur Mitte (Servo 2047 = 0 Grad), so wie es LeRobot fuer den
SO-101 ueblich ist. Der KI-Fahrer rechnet mit units.py wieder zurueck.
"""
import json, os, shutil, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ki.units import to_deg  # noqa: E402

JOINT_NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos",
               "gripper.pos"]


def features(cameras, size):
    w, h = size
    f = {"observation.state": {"dtype": "float32", "shape": (6,), "names": JOINT_NAMES},
         "action": {"dtype": "float32", "shape": (6,), "names": JOINT_NAMES}}
    for c in cameras:
        f[f"observation.images.{c}"] = {"dtype": "video", "shape": (h, w, 3), "names": ["height", "width", "channels"]}
    return f


def read_video(path):
    import cv2
    cap = cv2.VideoCapture(path)
    frames = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    cap.release()
    return frames


def convert(src, out, repo_id, camera_map="{}", auswahl=None):
    cmap = json.loads(camera_map) if isinstance(camera_map, str) else dict(camera_map or {})
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    with open(os.path.join(src, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    episodes = sorted(d for d in os.listdir(src) if d.startswith("ep_") and os.path.exists(os.path.join(src, d, "info.json")))
    cams = list(meta["cameras"])
    if auswahl:
        with open(auswahl, encoding="utf-8") as f:
            sel = json.load(f)
        cams = list(sel["cameras"])
        episodes = [e for e in episodes if e in set(sel["episodes"])]
    if not episodes:
        raise SystemExit("Keine Episoden im Datensatz")
    if os.path.exists(out):
        shutil.rmtree(out)
    from lerobot.configs.video import RGBEncoderConfig
    # H.264 statt AV1: auf diesem PC rund zehnmal schneller umgewandelt, beim Training schnell zu lesen
    encoder = RGBEncoderConfig(vcodec="h264", crf=23, preset="veryfast")
    ds = LeRobotDataset.create(repo_id=repo_id, fps=meta["fps"], features=features([cmap.get(c, c) for c in cams], meta["size"]),
                               root=out, robot_type="so101_follower", use_videos=True, rgb_encoder=encoder)
    total = 0
    for n, ep in enumerate(episodes):
        d = os.path.join(src, ep)
        with open(os.path.join(d, "info.json"), encoding="utf-8") as f:
            info = json.load(f)
        with np.load(os.path.join(d, "daten.npz")) as z:
            state, action = to_deg(z["state"]), to_deg(z["action"])
        videos = {c: read_video(os.path.join(d, f"{c}.mp4")) for c in cams}
        count = min([len(state)] + [len(v) for v in videos.values()])
        if count < len(state):
            print(f"{ep}: {len(state) - count} Bilder ohne Video uebersprungen", flush=True)
        for i in range(count):
            frame = {"observation.state": state[i].astype(np.float32), "action": action[i].astype(np.float32),
                     "task": info.get("task") or meta["task"]}
            for c in cams:
                frame[f"observation.images.{cmap.get(c, c)}"] = videos[c][i]
            ds.add_frame(frame)
        ds.save_episode(parallel_encoding=False)   # Windows: kein Prozess-Pool je Episode (sehr langsamer Start)
        total += count
        print(f"Episode {n + 1}/{len(episodes)} umgewandelt ({count} Bilder)", flush=True)
    ds.finalize()
    print(f"FERTIG: {len(episodes)} Episoden, {total} Bilder -> {out}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5, 6):
        raise SystemExit(__doc__)
    convert(*sys.argv[1:])
