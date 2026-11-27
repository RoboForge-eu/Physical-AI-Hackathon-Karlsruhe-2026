"""Einmalig: SO-101-Modell (URDF + STL aus TheRobotStudio/SO-ARM100, Simulation/SO101) aufbereiten.

    python modell/build_so101.py

Liest modell/so101_roh/so101_new_calib.urdf und die STL-Dateien daneben und schreibt modell/so101.json:
  - Gelenkkette (Ursprung, Achse) wie im URDF
  - je Teil (Link): konvexe Huelle (zum Zeichnen) und Pruefpunkte auf der Huellen-Oberflaeche (~1,5 cm Abstand),
    beides im Koordinatensystem des Teils, in Metern.
Die Rohdateien werden danach nicht mehr gebraucht.
"""
import json, math, os, struct, sys
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import ConvexHull

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "so101_roh")
OUT = os.path.join(HERE, "so101.json")
SPACING = 0.015                  # Pruefpunkte (Kollision)
DRAW_SPACING = 0.03              # Darstellung
DETAIL = {"gripper_link": 10, "moving_jaw_so101_v1_link": 6}   # so viele Teil-Huellen (genauer Greifer)


def rpy_matrix(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def origin(el):
    o = el.find("origin") if el is not None else None
    xyz = [float(v) for v in (o.get("xyz") if o is not None else "0 0 0").split()]
    rpy = [float(v) for v in (o.get("rpy") if o is not None else "0 0 0").split()]
    return xyz, rpy


def read_stl(path):
    data = open(path, "rb").read()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        pts = [[float(v) for v in l.split()[1:4]] for l in data.decode(errors="ignore").splitlines()
               if l.strip().startswith("vertex")]
        return np.array(pts)
    n = struct.unpack("<I", data[80:84])[0]
    rec = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    return rec["v"].reshape(-1, 3).astype(float)


def surface_samples(pts, hull, spacing):
    out = [pts[hull.vertices]]
    for tri in hull.simplices:
        a, b, c = pts[tri]
        area = 0.5 * np.linalg.norm(np.cross(b - a, c - a))
        k = int(math.ceil(math.sqrt(area) / spacing))
        if k <= 1:
            continue
        for i in range(k + 1):
            for j in range(k + 1 - i):
                u, v = i / k, j / k
                out.append((a + u * (b - a) + v * (c - a))[None, :])
    s = np.vstack(out)
    # gleichmaessig ausduennen: hoechstens ein Punkt je Wuerfel mit Kante spacing/1.5
    key = np.round(s / (spacing / 1.5)).astype(int)
    _, idx = np.unique(key, axis=0, return_index=True)
    return s[np.sort(idx)]


def box(c, a, b, d):
    """Quader-Ecken (8) aus Mitte und drei Halbachsen-Vektoren, dicht abgetastet."""
    g = np.linspace(-1, 1, 5)
    return np.array([c + i * a + j * b + k * d for i in g for j in g for k in g])


def add_part(links, name, pts, draw_spacing=DRAW_SPACING / 3):
    hull = ConvexHull(pts)
    samples = surface_samples(pts, hull, SPACING)
    coarse = surface_samples(pts, hull, draw_spacing)
    small = ConvexHull(coarse)
    hv = coarse[small.vertices]
    index = {int(i): k for k, i in enumerate(small.vertices)}
    links[name] = {"huelle": np.round(hv, 5).tolist(), "flaechen": [[index[int(i)] for i in t] for t in small.simplices],
                   "punkte": np.round(samples, 5).tolist()}
    print(f"{name:28s} {len(pts):6d} Ecken -> Huelle {len(hv):4d}, Pruefpunkte {len(samples):4d}")


def main():
    urdf = "so101_new_calib_camera.urdf" if os.path.exists(os.path.join(RAW, "so101_new_calib_camera.urdf"))         else "so101_new_calib.urdf"
    root = ET.parse(os.path.join(RAW, urdf)).getroot()
    halter = None
    hp = os.path.join(HERE, "kamera", "halter.json")
    if os.path.exists(hp):                       # eigene Kamera-Halterung und Einbaulage (modell/kamera/halter.json)
        halter = json.load(open(hp, encoding="utf-8"))
    links = {}
    for link in root.findall("link"):
        verts = []
        if halter and link.get("name") == "wrist_camera_mount_link":
            verts.append(read_stl(os.path.join(HERE, "kamera", halter["stl"])) / 1000.0)
        for vis in ([] if halter and link.get("name") == "wrist_camera_mount_link" else link.findall("visual")):
            mesh = vis.find("geometry/mesh")
            if mesh is None:
                continue
            fn = os.path.join(RAW, os.path.basename(mesh.get("filename")))
            v = read_stl(fn)
            scale = [float(x) for x in (mesh.get("scale") or "1 1 1").split()]
            v = v * np.array(scale)
            if np.abs(v).max() > 5:          # STL in mm statt m
                v = v / 1000.0
            xyz, rpy = origin(vis)
            verts.append(v @ rpy_matrix(*rpy).T + np.array(xyz))
        if halter and halter.get("kamera") and link.get("name") == "wrist_camera_link":
            continue                                 # ersetzt durch Linse + Platine an der Halterung
        if not verts:
            continue
        pts = np.unique(np.round(np.vstack(verts), 5), axis=0)
        if halter and link.get("name") == "wrist_camera_mount_link":
            # V-foermiges Blech: je Abschnitt eine eigene Huelle (sonst ein dicker Klotz)
            bend_x = pts[np.argmin(pts[:, 1]), 0]
            for tag, sel in (("platte", pts[:, 0] > -0.004), ("mitte", (pts[:, 0] <= -0.002) & (pts[:, 0] >= bend_x - 0.002)),
                             ("kamera", pts[:, 0] <= bend_x + 0.002)):
                add_part(links, link.get("name") + "#" + tag, pts[sel])
            cam = halter.get("kamera")
            if cam:                                  # Linse vorn und Platine hinten an der Kameraplatte (Masse in mm)
                end, bend = pts[np.argmin(pts[:, 0])], pts[np.argmin(pts[:, 1])]
                u = (end - bend)[:2] / np.linalg.norm((end - bend)[:2])
                u = np.array([u[0], u[1], 0.0])
                n = np.array([-u[1], u[0], 0.0])                  # Plattennormale nach vorn (Kamera-Seite)
                if n[1] < 0:
                    n = -n
                w = np.array([0.0, 0.0, 1.0])
                pc = (end + bend) / 2 + w * (pts[:, 2].max() / 2 - (end + bend)[2] / 2)
                t = cam.get("platte_mm", 3.0) / 2000
                pb = cam["platine_mm"]
                add_part(links, link.get("name") + "#platine",
                         box(pc - n * (t + pb[2] / 2000), u * pb[0] / 2000, w * pb[1] / 2000, n * pb[2] / 2000))
                ln = cam["linse_mm"]
                add_part(links, link.get("name") + "#linse",
                         box(pc + n * (t + ln[1] / 2000), u * ln[0] / 2000, w * ln[0] / 2000, n * ln[1] / 2000))
            continue
        if link.get("name") in DETAIL:               # Greifer/Backe: in mehrere kleine Huellen zerlegen (schlanke Form)
            from scipy.cluster.vq import kmeans2
            np.random.seed(1)
            _, lab = kmeans2(pts, DETAIL[link.get("name")], minit="++", seed=1)
            for i in range(DETAIL[link.get("name")]):
                sub = pts[lab == i]
                if len(sub) >= 8:
                    add_part(links, f"{link.get('name')}#{i}", sub, draw_spacing=0.012)
            continue
        hull = ConvexHull(pts)
        samples = surface_samples(pts, hull, SPACING)
        coarse = surface_samples(pts, hull, DRAW_SPACING)
        small = ConvexHull(coarse)                   # Huelle zum Zeichnen: grob, wenige Flaechen (schnell)
        samples_draw = coarse
        hv = samples_draw[small.vertices]
        index = {int(i): k for k, i in enumerate(small.vertices)}
        faces = [[index[int(i)] for i in tri] for tri in small.simplices]
        links[link.get("name")] = {"huelle": np.round(hv, 5).tolist(), "flaechen": faces,
                                   "punkte": np.round(samples, 5).tolist()}
        print(f"{link.get('name'):28s} {len(pts):6d} Ecken -> Huelle {len(hv):4d}, Pruefpunkte {len(samples):4d}")
    joints = []
    for j in root.findall("joint"):
        xyz, rpy = origin(j)
        if halter and j.get("name") == "wrist_camera_mount_joint":
            xyz, rpy = halter["xyz"], halter["rpy"]
        ax = j.find("axis")
        joints.append({"name": j.get("name"), "type": j.get("type"), "parent": j.find("parent").get("link"),
                       "child": j.find("child").get("link"), "xyz": xyz, "rpy": rpy,
                       "axis": [float(v) for v in (ax.get("xyz") if ax is not None else "0 0 1").split()]})
    json.dump({"quelle": "TheRobotStudio/SO-ARM100 Simulation/SO101/" + urdf,
               "links": links, "joints": joints}, open(OUT, "w"), separators=(",", ":"))
    print("geschrieben:", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    sys.exit(main())
