"""Werkzeug fuer Veranstalter: Station einrichten und Team-Pakete anlegen.

  python -m plattform.station boards
        zeigt angeschlossene Servo-Boards (USB-Seriennummern)
  python -m plattform.station arme --follower 5B79080244 --leader 5B79080431 [--name "Station 3"]
        schreibt config.json fuer EIN Setup (Follower + Leader, Kameras 1 und 2)
  python -m plattform.station paket --team "Team Blau" [--station "Station 3"] [--mit-kalibrierung]
        legt stationspakete/<team>.json an: Team-Code, Ordner, Hugging-Face-/GitHub-Ziele und (optional) die
        Kalibrierung und Arm-Zuordnung DIESES Rechners. Tokens: aus den Umgebungsvariablen TEAM_HF_TOKEN und
        TEAM_GH_TOKEN, sonst bleiben sie leer und werden spaeter in die Datei eingetragen.
  python -m plattform.station zettel
        druckbare Liste aller Team-Codes (plattform_daten/team_codes.html)

Pakete enthalten Zugangsdaten: nie ins Repo, nur per USB-Stick/sicher an die Station geben.
"""
import argparse, html as H, json, os, re, secrets, sys

from . import KIT, PAKETE, DATEN
from .kern import slug, _write, _read

ORG = "RoboForge"
REPO = "https://github.com/RoboForge-eu/Physical-AI-Hackathon-28.11.26-Karlsruhe-"
DATIERT = re.compile(r"_\d{4}-\d{2}-\d{2}_\d+\.json$")


def boards():
    from serial.tools import list_ports
    return [(p.device, (p.serial_number or "").upper(), p.description) for p in list_ports.comports()
            if p.serial_number]


def config_schreiben(follower, leader, name="Setup 1", kit=KIT):
    path = os.path.join(kit, "config.json")
    cfg = _read(path, {}) or {}
    old = cfg.get("follower", {})
    cfg.update({
        "follower": {"usb_serial": follower.upper(), "port": None, "label": name, "cameras": old.get("cameras", [1, 2]),
                     **({"rest_pose": old["rest_pose"]} if old.get("rest_pose") else {})},
        "leader": {"usb_serial": leader.upper(), "port": None},
        "baud": cfg.get("baud", 1000000),
    })
    for k in [k for k in cfg if k.startswith("follower") and k != "follower"]:
        del cfg[k]                                         # ein Setup pro Team
    cfg.setdefault("cameras", [{"name": f"{name} · Arm", "device": ""}, {"name": f"{name} · Turm", "device": ""},
                               {"name": "frei 3", "device": ""}, {"name": "frei 4", "device": ""}])
    _write(path, cfg)
    return path


def kalibrierung(kit=KIT):
    """Aktuelle Kalibrierdateien (ohne datierte Sicherungen und Unterordner)."""
    d = os.path.join(kit, "calibration")
    out = {}
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if f.endswith(".json") and os.path.isfile(p) and not DATIERT.search(f):
                data = _read(p)
                if data is not None:
                    out[f] = data
    return out


def neuer_code(team):
    wort = re.sub(r"[^A-Z]", "", slug(team).replace("team-", "").upper())[:5] or "TEAM"
    return f"{wort}-{secrets.randbelow(9000) + 1000}"


def paket(team, station=None, mit_kalibrierung=False, pakete=PAKETE, kit=KIT, env=os.environ):
    ordner = slug(team)
    p = {"code": neuer_code(team), "team": team, "ordner": ordner, "mitglieder": [],
         "station": {"name": station or ""},
         "huggingface": {"org": ORG, "modell_repo": f"{ORG}/{ordner}-modelle",
                         "datensatz_repo": f"{ORG}/{ordner}-daten", "token": env.get("TEAM_HF_TOKEN", "")},
         "github": {"repo": REPO, "zweig": f"team/{ordner}", "token": env.get("TEAM_GH_TOKEN", "")}}
    if mit_kalibrierung:
        p["station"]["kalibrierung"] = kalibrierung(kit)
        cfg = _read(os.path.join(kit, "config.json"))
        if cfg:
            p["station"]["config"] = cfg
    path = os.path.join(pakete, ordner + ".json")
    if os.path.exists(path):
        alt = _read(path, {})
        p["code"] = alt.get("code", p["code"])              # Code bleibt gleich (Zettel ist schon gedruckt)
        for k in ("huggingface", "github"):
            if alt.get(k, {}).get("token") and not p[k]["token"]:
                p[k]["token"] = alt[k]["token"]
    _write(path, p)
    return path, p


def zettel(pakete=PAKETE, daten=DATEN):
    rows = []
    for f in sorted(os.listdir(pakete)) if os.path.isdir(pakete) else []:
        p = _read(os.path.join(pakete, f))
        if isinstance(p, dict) and p.get("code"):
            rows.append(f"<div class=z><b>{H.escape(p['team'])}</b><span>{H.escape(p['station'].get('name', ''))}</span>"
                        f"<code>{H.escape(p['code'])}</code><small>Physical AI Harness · http://127.0.0.1:8780</small></div>")
    html = ("<!doctype html><meta charset=utf-8><title>Team-Codes</title><style>body{font:14px system-ui;margin:20px}"
            ".z{border:1px dashed #999;padding:18px;margin:10px 0;display:grid;gap:4px;width:360px}"
            "code{font-size:26px;letter-spacing:.1em}small{color:#666}</style>" + "".join(rows))
    os.makedirs(daten, exist_ok=True)
    path = os.path.join(daten, "team_codes.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m plattform.station")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("boards")
    a = sub.add_parser("arme")
    a.add_argument("--follower", required=True)
    a.add_argument("--leader", required=True)
    a.add_argument("--name", default="Setup 1")
    b = sub.add_parser("paket")
    b.add_argument("--team", required=True)
    b.add_argument("--station")
    b.add_argument("--mit-kalibrierung", action="store_true")
    sub.add_parser("zettel")
    args = ap.parse_args(argv)
    if args.cmd == "boards":
        for dev, sn, desc in boards():
            print(f"{dev:12} {sn:14} {desc}")
    elif args.cmd == "arme":
        print("geschrieben:", config_schreiben(args.follower, args.leader, args.name))
    elif args.cmd == "paket":
        path, p = paket(args.team, args.station, args.mit_kalibrierung)
        fehlt = [k for k in ("huggingface", "github") if not p[k]["token"]]
        print(f"{path}\n  Code: {p['code']}" + (f"\n  Tokens fehlen noch: {', '.join(fehlt)} (in der Datei eintragen)"
                                                if fehlt else ""))
    elif args.cmd == "zettel":
        print(zettel())
    return 0


if __name__ == "__main__":
    sys.exit(main())
