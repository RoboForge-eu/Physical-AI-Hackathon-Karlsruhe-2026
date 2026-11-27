"""Einstellungen des Agenten aus agent.json (neben ros.py). Alles optional.

  {"model": "claude-opus-5-5", "effort": "high", "max_turns": 30, "api_key": "sk-ant-..."}

Ohne "api_key" nimmt die Anthropic-Bibliothek ANTHROPIC_API_KEY aus der Umgebung (oder ein
'ant auth login'-Profil). Der Schluessel bleibt auf diesem PC und wird nie angezeigt.
"""
import json, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, "agent.json")
DEFAULTS = {"model": "claude-opus-5-5", "effort": "high", "max_turns": 30}


def load(path=PATH):
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except ValueError as exc:
        raise ValueError(f"agent.json ist kein gueltiges JSON: {exc}") from None
    return cfg


def key_source(cfg):
    if cfg.get("api_key") and "<" not in cfg["api_key"]:
        return "agent.json"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "Umgebungsvariable ANTHROPIC_API_KEY"
    return None
