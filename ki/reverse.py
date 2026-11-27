"""Rueckwaerts-Datensatz: jede Episode rueckwaerts abspielen (Experiment).

Aus 'Schachtel auf die Palette legen' wird 'Schachtel von der Palette nehmen und ablegen': rueckwaerts wird
aus dem Loslassen ein Zugreifen und umgekehrt. Bilder und Ist-Stellungen werden umgedreht. Die Aktionen
(Leader-Ziele) laufen der Stellung voraus - rueckwaerts wuerden sie hinterherlaufen. Deshalb wird die
Aktion neu gebildet: die (umgedrehte) Stellung LEAD Takte spaeter, beim Greifer das umgedrehte Leader-Ziel
ebenso verschoben (es enthaelt das Zudruecken beim Halten).

  python -m ki.reverse <quell-datensatz> <neuer-name> "<neue Aufgabe>"
"""
import json, os, shutil, sys
import numpy as np
from . import DATASETS
from .episodes import Dataset, slug

LEAD = 3          # Takte (100 ms): so weit laeuft ein Leader-Ziel der Stellung typischerweise voraus


def reverse_episode(state, action, lead=LEAD):
    """Aktion = Stellung LEAD Takte spaeter + Halte-Ausgleich. Der Ausgleich (Leader-Ziel liegt auch im Stillstand
    etwas ueber der Stellung, gegen das Absacken unter Last) wird aus der Vorwaerts-Aufnahme ohne den
    Bewegungsanteil geschaetzt und mit umgedreht."""
    n = len(state)
    fwd = np.minimum(np.arange(n) + lead, n - 1)
    hold_offset = (action - state) - (state[fwd] - state)        # vorwaerts: Ausgleich ohne Vorlauf
    st = state[::-1].copy()
    act_src, off = action[::-1], hold_offset[::-1]
    new_action = st[fwd].copy()
    new_action[:, :5] += off[:, :5]
    new_action[:, 5] = act_src[fwd, 5]
    return st, new_action.astype(np.float32)


def reverse_video(src, dst, cv2):
    cap = cv2.VideoCapture(src)
    frames = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        frames.append(img)
    cap.release()
    if not frames:
        raise RuntimeError(f"Video leer: {src}")
    h, w = frames[0].shape[:2]
    out = cv2.VideoWriter(dst, cv2.VideoWriter_fourcc(*"mp4v"), 30, (w, h))
    for img in reversed(frames):
        out.write(img)
    out.release()
    return len(frames)


def build(src_name, new_name, new_task, root=None, cv2=None):
    if cv2 is None:
        import cv2 as _cv2
        cv2 = _cv2
    root = root or DATASETS
    src = Dataset(os.path.join(root, slug(src_name)))
    if not src.episodes():
        raise ValueError(f"Datensatz {src_name} hat keine Episoden")
    dst_path = os.path.join(root, slug(new_name))
    if os.path.exists(dst_path):
        raise FileExistsError(f"Datensatz {new_name} gibt es schon")
    os.makedirs(dst_path)
    meta = dict(src.meta, name=new_name, task=new_task, umgedreht_aus=src.name)
    with open(os.path.join(dst_path, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    done = 0
    for ep in src.episodes():
        s_dir, d_dir = os.path.join(src.path, ep), os.path.join(dst_path, ep)
        os.makedirs(d_dir)
        with np.load(os.path.join(s_dir, "daten.npz")) as z:
            t, state, action = z["t"], z["state"], z["action"]
        counts = [reverse_video(os.path.join(s_dir, f"{c}.mp4"), os.path.join(d_dir, f"{c}.mp4"), cv2)
                  for c in meta["cameras"]]
        n = min([len(state)] + counts)
        st, act = reverse_episode(state[:n], action[:n])
        np.savez(os.path.join(d_dir, "daten.npz"), t=t[:n], state=st.astype(np.float32), action=act)
        info = json.load(open(os.path.join(s_dir, "info.json"), encoding="utf-8"))
        info.update(task=new_task, umgedreht_aus=f"{src.name}/{ep}", frames=int(n))
        with open(os.path.join(d_dir, "info.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1, ensure_ascii=False)
        done += 1
    return Dataset(dst_path), done


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    ds, n = build(*sys.argv[1:])
    print(f"{n} Episoden umgedreht -> {ds.path}")
