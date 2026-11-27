"""Werkzeugliste fuer den Agenten.

- Befehle aus ROS (skills.liste). Claude erlaubt in Werkzeugnamen keine Punkte: 'modelle.liste'
  heisst fuer den Agenten 'modelle__liste'.
- Jedes trainierte Modell wird automatisch eine eigene Faehigkeit 'faehigkeit_<modell>'
  (ruft intern modell.ausfuehren auf). So sieht der Agent direkt, was der Arm gelernt hat.
- Manche Befehle sind fuer den Agenten gesperrt (Training starten/abbrechen, Modell zuweisen):
  er soll den Arm benutzen, nicht die Werkstatt umbauen.
"""
import re

HIDDEN = {"training.start", "training.abbrechen", "ki.modell_waehlen", "ki.starten", "modell.ausfuehren",
          "pose.merken", "greifer.merken", "vision.werkzeugpunkt_merken",
          "sitzung.freigeben", "karton.einmessen", "kamera.kalibrieren"}   # Zustimmen und Einrichten macht der Mensch vor Ort


def tool_name(skill):
    return skill.replace(".", "__")


def skill_name(tool):
    return tool.replace("__", ".")


def model_tool_name(model):
    return ("faehigkeit_" + re.sub(r"[^a-zA-Z0-9_-]", "_", model))[:64]


def build(ros_tools, models, arms):
    """ros_tools: skills.liste; models: modelle.liste; arms: Arm-Schluessel.
    -> (werkzeuge fuer Claude, zuordnung werkzeugname -> ("skill", name) | ("modell", name))"""
    tools, route = [], {}
    for t in ros_tools:
        if t["name"] in HIDDEN:
            continue
        name = tool_name(t["name"])
        tools.append({"name": name, "description": t["description"], "input_schema": t["input_schema"]})
        route[name] = ("skill", t["name"])
    for m in models:
        name = model_tool_name(m["name"])
        desc = (f"Gelernte Faehigkeit (Modell {m['name']}, Methode {m.get('method')}): "
                f"\"{m.get('task') or 'ohne Beschreibung'}\". Laesst den Arm diese Faehigkeit fuer 'sekunden' "
                "ausfuehren; danach haelt der Arm seine Stellung. Braucht eine freigegebene Arbeitssitzung "
                "(sitzung__anfragen / sitzung__status). Bewegt den Arm.")
        if m.get("arm"):
            desc += f" Aufgenommen an Arm {m['arm']}."
        tools.append({"name": name, "description": desc, "input_schema": {
            "type": "object",
            "properties": {"arm": {"type": "string", "enum": list(arms)},
                           "sekunden": {"type": "number", "minimum": 1, "maximum": 120,
                                        "description": "wie lange die Faehigkeit laufen soll"},
                           "aufgabe": {"type": "string", "description": "optional: Aufgabentext (nur SmolVLA)"}},
            "required": ["arm", "sekunden"]}})
        route[name] = ("modell", m["name"])
    try:
        from skilllib import store
        code_skills = [m for m in store.all_skills() if m.get("aktiv")]
    except Exception:
        code_skills = []
    for m in code_skills:
        name = ("skill_" + m["name"])[:64]
        props = {"arm": {"type": "string", "enum": list(arms)}}
        for k, desc in (m.get("params") or {}).items():
            props[k] = {"description": str(desc)}
        tools.append({"name": name, "description": f"Code-Skill (Version {m['aktiv']}): {m.get('ziel')}. "
                      f"Erfolg, wenn: {m.get('kriterium')}. Meldet selbst erfolg true/false. Bewegt den Arm; "
                      "braucht eine freigegebene Arbeitssitzung.",
                      "input_schema": {"type": "object", "properties": props, "required": ["arm"]}})
        route[name] = ("code", m["name"])
    return tools, route


def call(ros, route, name, args):
    """Fuehrt ein Werkzeug ueber ROS aus. Gibt das Ergebnis (JSON-faehig) zurueck."""
    kind, target = route[name]
    if kind == "code":
        from skilllib.runner import run_skill
        args = dict(args)
        return run_skill(target, args, arm=args.pop("arm"), modus="echt", log=lambda t: None)
    if kind == "modell":
        return ros.call("modell.ausfuehren", timeout=300, modell=target, **args)
    return ros.call(target, timeout=60, **args)
