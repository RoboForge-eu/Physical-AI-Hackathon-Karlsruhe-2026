"""Isaac-Sim-Server fuer den SO-101 (laeuft in %USERPROFILE%\\isaac-env, Isaac Sim 6.2 / Isaac Lab 3.0).

  %USERPROFILE%\\isaac-env\\Scripts\\python.exe sim/isaac/server.py [--seed N] [--visualizer kit]

Protokoll (stdin JSON-Zeilen -> stdout JSON-Zeilen; Bilder als Rohbytes direkt nach der Antwortzeile):
  {"cmd":"szene", palette, schachtel, halter, loch, marker, licht, ...}  Szene wie sim.welt.Szene bauen
  {"cmd":"schritt","soll":[6 Ticks],"n":k} -> {"t","ist":[6 Ticks],"last":[6 Promille]}
  {"cmd":"zustand"} / {"cmd":"bild","kamera":"arm"|"turm"} -> {"h","w","bytes"} + BGR-Bytes
  {"cmd":"werkzeugpunkt"} / {"cmd":"ende"}
Antriebe: positionsgeregelt (ImplicitActuator, PD aus der SysID-USD) wie die STS3215.
Last = |angewandtes Moment| / EFFORT_MAX * 1000 (Promille, wie das STS-Register).
Alle Ausgaben von Kit/Omniverse gehen nach stderr; stdout gehoert nur dem Protokoll.
Setzt NIE OMNI_KIT_ACCEPT_EULA - die Lizenz bestaetigt der Nutzer beim ersten Start selbst.
UNGETESTET bis zum ersten Start (EULA): API nach Isaac-Lab-3.0-Quellen (run_articulation.py, so101.py).
"""
import argparse, json, os, sys

PROTO = os.fdopen(os.dup(1), "wb", buffering=0)
os.dup2(2, 1)                                  # alles andere (Kit-Logs) nach stderr
sys.stdout = sys.stderr
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import umrechnung as U  # noqa: E402
from isaaclab.app import add_launcher_args, launch_simulation  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--zufall", action="store_true")
add_launcher_args(ap)
args = ap.parse_args()
args.enable_cameras = True   # Kameras entstehen erst nach dem Start -> Rendering selbst einschalten
W, H = 640, 360
PHYS_HZ = 100
SPITZE_AB_GREIFER = 0.05  # m, Greifer-Koerper -> Fingerspitze (grob, mit pruefen.py nachmessen)
EFFORT_MAX = 2.9          # Nm, STS3215 ~ 30 kg*cm


def send(obj, raw=None):
    PROTO.write((json.dumps(obj) + "\n").encode())
    if raw is not None:
        PROTO.write(raw)


def bauen(sz):
    """Tisch, Palette, Schachtel, Halterung mit Loch (Bloecke um die Oeffnung), Licht, zwei Kameras."""
    import isaaclab.sim as sim_utils
    from isaaclab.assets import Articulation, RigidObject, RigidObjectCfg
    from isaaclab.sensors import Camera, CameraCfg
    from isaaclab.utils import clone
    from isaaclab_assets.robots.so101 import SO101_CFG

    g = sim_utils.GroundPlaneCfg()
    g.func("/World/Boden", g)
    licht = sz.get("licht", {})
    lc = sim_utils.DomeLightCfg(intensity=800.0 * licht.get("gain", 1.0),
                                color=tuple(0.75 * v for v in licht.get("tint", [1, 1, 1])))
    lc.func("/World/Licht", lc)

    def block(pfad, x, y, z, b, t, h, rgb):
        cfg = sim_utils.CuboidCfg(size=(b, t, h), visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=tuple(rgb)),
                                  collision_props=sim_utils.CollisionPropertiesCfg(),
                                  rigid_props=sim_utils.RigidBodyPropertiesCfg(kinematic_enabled=True),
                                  mass_props=sim_utils.MassPropertiesCfg(mass=0.05))
        cfg.func(pfad, cfg, translation=(x, y, z + h / 2))

    p = sz["palette"]
    block("/World/Palette", p["x"], p["y"], 0, p["b"], p["t"], p["h"], (0.55, 0.35, 0.15))
    s = sz["schachtel"]
    schachtel = RigidObject(RigidObjectCfg(prim_path="/World/Schachtel", spawn=sim_utils.CuboidCfg(
        size=(s["b"], s["t"], s["h"]), visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=tuple(sz["farbe"][::-1])),
        collision_props=sim_utils.CollisionPropertiesCfg(), rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        mass_props=sim_utils.MassPropertiesCfg(mass=0.05)),
        init_state=RigidObjectCfg.InitialStateCfg(pos=(s["x"], s["y"], s["h"] / 2))))
    h, L = sz["halter"], sz["loch"]
    r, grau, lx, ly = L["r"], (0.85, 0.85, 0.83), L["x"], L["y"]
    x0, x1, y0, y1 = h["x"] - h["b"] / 2, h["x"] + h["b"] / 2, h["y"] - h["t"] / 2, h["y"] + h["t"] / 2
    block("/World/Halter/vorn", (lx + r + x1) / 2, h["y"], 0, x1 - lx - r, h["t"], h["h"], grau)
    block("/World/Halter/hinten", (x0 + lx - r) / 2, h["y"], 0, lx - r - x0, h["t"], h["h"], grau)
    block("/World/Halter/links", lx, (ly + r + y1) / 2, 0, 2 * r, y1 - ly - r, h["h"], grau)
    block("/World/Halter/rechts", lx, (y0 + ly - r) / 2, 0, 2 * r, ly - r - y0, h["h"], grau)
    block("/World/Halter/boden", lx, ly, 0, 2 * r, 2 * r, h["h"] - L["tiefe"], grau)
    robot_cfg = clone(SO101_CFG)
    robot_cfg.prim_path = "/World/Robot"
    # Die USD zeigt nach -y, remote_kin/kinsim nach +x -> Basis +90 Grad um z drehen (Isaac Lab 3.0: Quaternion x,y,z,w)
    robot_cfg.init_state.rot = (0.0, 0.0, 0.70710678, 0.70710678)
    robot = Articulation(cfg=robot_cfg)
    pin = sim_utils.PinholeCameraCfg(focal_length=1.93, horizontal_aperture=3.75, clipping_range=(0.01, 5.0))
    arm = Camera(CameraCfg(prim_path="/World/Robot/gripper/hand_cam", height=H, width=W, data_types=["rgb"], spawn=pin,
                           offset=CameraCfg.OffsetCfg(pos=(0.0, -0.03, -0.09), rot=(1.0, 0.0, 0.0, 0.0), convention="ros")))
    tv = sz.get("turm_versatz", [0, 0, 0])
    turm = Camera(CameraCfg(prim_path="/World/TurmKamera", height=H, width=W, data_types=["rgb"], spawn=pin,
                            offset=CameraCfg.OffsetCfg(pos=(0.18 + tv[0], -0.38 + tv[1], 0.42 + tv[2]),
                                                       rot=(0.82, -0.40, 0.18, 0.37), convention="world")))
    return robot, schachtel, {"arm": arm, "turm": turm}


def main():
    import numpy as np
    import torch
    import isaaclab.sim as sim_utils
    from isaaclab.sim import SimulationContext

    sim_cfg = sim_utils.SimulationCfg(dt=1.0 / PHYS_HZ, device=args.device)
    with launch_simulation(sim_cfg, args):
        sim = SimulationContext(sim_cfg)
        send({"bereit": True})
        szene = json.loads(sys.stdin.readline())
        if szene.get("cmd") != "szene":
            send({"fehler": "erst szene senden"})
            return
        robot, _, kameras = bauen(szene)
        sim.reset()
        tv = szene.get("turm_versatz", [0, 0, 0])
        kameras["turm"].set_world_poses_from_view(          # wie kinsim: von vorn-rechts oben auf die Arbeitsflaeche
            torch.tensor([[0.18 + tv[0], -0.38 + tv[1], 0.42 + tv[2]]], device=sim.device),
            torch.tensor([[0.18, 0.02, 0.02]], device=sim.device))
        print("KOERPER", robot.body_names, file=sys.stderr)
        send({"ok": True})
        ids = [robot.joint_names.index(n) for n in U.NAMES]
        t = [0.0]

        def zustand():
            q = robot.data.joint_pos.torch[0].cpu().numpy()
            eff = getattr(robot.data, "applied_torque", None)
            eff = eff.torch[0].cpu().numpy() if eff is not None else np.zeros(len(q))
            return {"t": round(t[0], 4), "ist": U.rad_zu_ticks([float(q[i]) for i in ids]),
                    "last": [int(min(1000, abs(float(eff[i])) / EFFORT_MAX * 1000)) for i in ids]}

        bi = {n: robot.body_names.index(n) for n in ("wrist", "gripper")}

        def hand_kamera_setzen():
            """Wie kinsim.kamera_handgelenk: 9 cm hinter der Spitze auf der Handachse, 3 cm zur Oberseite, blickt zur Spitze."""
            g = robot.data.body_pos_w.torch[0].cpu().numpy()[bi["gripper"]]
            x, y, z, w = robot.data.body_quat_w.torch[0].cpu().numpy()[bi["gripper"]]   # Isaac Lab 3.0: x,y,z,w
            R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            d = -R[:, 2]                        # Fingerachse = -z des Greifer-Koerpers (Ruhestellung: zeigt nach +x)
            oben = R[:, 0]                      # Oberseite der Hand (Ruhestellung: +z)
            spitze = g + SPITZE_AB_GREIFER * d
            auge = spitze - 0.02 * d - 0.05 * oben   # vor dem Handmotor, Gegenseite der Oberseite
            kameras["arm"].set_world_poses_from_view(torch.tensor([auge], dtype=torch.float32, device=sim.device),
                                                     torch.tensor([spitze + 0.08 * d], dtype=torch.float32, device=sim.device))

        for line in sys.stdin:
            m = json.loads(line)
            c = m.get("cmd")
            try:
                if c == "schritt":
                    ziel = torch.tensor([U.ticks_zu_rad(m["soll"])], device=sim.device)
                    robot.actuators.target_command.set_position_index(value=ziel, joint_ids=ids)
                    for _ in range(int(m.get("n", 1))):
                        robot.write_data_to_sim()
                        sim.step()
                        robot.update(1.0 / PHYS_HZ)
                        t[0] += 1.0 / PHYS_HZ
                    send(zustand())
                elif c == "koerper":
                    send({"pos": robot.data.body_pos_w.torch[0].cpu().numpy().round(4).tolist(),
                          "quat": robot.data.body_quat_w.torch[0].cpu().numpy().round(4).tolist()})
                elif c == "zustand":
                    send(zustand())
                elif c == "bild":
                    if m.get("kamera", "arm") == "arm":
                        hand_kamera_setzen()
                    cam = kameras[m.get("kamera", "arm")]
                    cam.update(0.0, force_recompute=True)
                    rgb = cam.data.output["rgb"].torch[0, ..., :3].cpu().numpy().astype(np.uint8)
                    bgr = np.ascontiguousarray(rgb[..., ::-1])
                    send({"h": bgr.shape[0], "w": bgr.shape[1], "bytes": bgr.nbytes}, bgr.tobytes())
                elif c == "werkzeugpunkt":
                    send({"px": [W / 2, H / 2 - 30]})          # beim ersten Start mit pruefen.py nachmessen
                elif c == "ende":
                    send({"ok": True})
                    return
                else:
                    send({"fehler": f"unbekannt {c}"})
            except Exception as exc:
                send({"fehler": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
