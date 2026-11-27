"""Zugangscode fuer die Fernsteuerungs-App.

Ein Code ist base64-kodiertes JSON: {"v":1, "url": LiveKit-Adresse, "token": Bediener-Token, "raum", "bis"}.
Er enthaelt NIE den LiveKit-Schluessel oder das Geheimnis, nur ein Token mit Ablaufzeit
(Rechte: Video ansehen, Steuerdaten senden, kein eigenes Video).
"""
import base64, json, time

PREFIX = "RF1."


def make_code(cfg, hours=12, identity=None):
    import stream_livekit
    url, token = stream_livekit.operator_access(cfg, identity=identity, hours=hours)
    data = {"v": 1, "url": url, "token": token, "raum": cfg.get("room", "roboforge"),
            "bis": int(time.time() + hours * 3600)}
    return PREFIX + base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def read_code(code):
    """-> dict mit url, token, raum, bis. Wirft ValueError bei ungueltigem oder abgelaufenem Code."""
    code = "".join((code or "").split())
    if not code.startswith(PREFIX):
        raise ValueError("Das ist kein RoboForge-Zugangscode (beginnt mit RF1.)")
    try:
        data = json.loads(base64.urlsafe_b64decode(code[len(PREFIX):].encode()))
    except (ValueError, json.JSONDecodeError):
        raise ValueError("Zugangscode ist beschaedigt (unvollstaendig kopiert?)") from None
    if not all(k in data for k in ("url", "token")):
        raise ValueError("Zugangscode ist unvollstaendig")
    if data.get("bis") and data["bis"] < time.time():
        raise ValueError("Zugangscode ist abgelaufen - im Harness einen neuen erstellen")
    return data
