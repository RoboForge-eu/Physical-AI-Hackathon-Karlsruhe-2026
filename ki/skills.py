"""Benannte Befehle ("Skills"/Werkzeuge) mit Beschreibung und Parametern.

Dieselben Befehle benutzen: die Oberflaeche, der Fernzugriff (LiveKit) und spaeter ein Agent.
Ein Agent bekommt dafuer tool_schemas() als Werkzeugliste. Sicherheit steckt NICHT hier,
sondern im Worker; trotzdem markiert jeder Befehl, ob er den Arm bewegt (moves=True), damit
eine Freigabe vor Ort verlangt werden kann.
"""
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str                       # "arm.ablegen"
    description: str
    params: dict = field(default_factory=dict)      # JSON-Schema-Properties
    required: list = field(default_factory=list)
    handler: object = None          # callable(**kwargs) -> dict
    moves: bool = False             # bewegt einen echten Arm
    remote_ok: bool = True          # darf ueber das Internet aufgerufen werden
    agent_ok: bool = True           # darf ein Sprachmodell-Agent aufrufen (Zustimmungen: nur Menschen)


class SkillError(Exception):
    pass


class Registry:
    def __init__(self):
        self.skills = {}
        self.move_allowed = lambda skill, args, source: True   # Freigabe-Regel, setzt ROS

    def add(self, skill):
        self.skills[skill.name] = skill
        return skill

    def skill(self, name, description, params=None, required=None, moves=False, remote_ok=True, agent_ok=True):
        """Decorator: @reg.skill("kamera.foto", "...")"""
        def wrap(fn):
            self.add(Skill(name, description, params or {}, required or [], fn, moves, remote_ok, agent_ok))
            return fn
        return wrap

    def call(self, name, args=None, source="lokal"):
        """source: 'lokal' (Oberflaeche), 'remote' (Internet), 'agent'."""
        args = dict(args or {})
        skill = self.skills.get(name)
        if skill is None:
            raise SkillError(f"Unbekannter Befehl {name!r}")
        if source == "remote" and not skill.remote_ok:
            raise SkillError(f"{name} ist ueber das Internet nicht erlaubt")
        if source == "agent" and not skill.agent_ok:
            raise SkillError(f"{name} darf nur ein Mensch ausloesen")
        missing = [p for p in skill.required if p not in args]
        if missing:
            raise SkillError(f"{name}: fehlende Angaben {missing}")
        unknown = [p for p in args if p not in skill.params]
        if unknown:
            raise SkillError(f"{name}: unbekannte Angaben {unknown}")
        if skill.moves and not self.move_allowed(skill, args, source):
            raise SkillError(f"{name} bewegt den Arm und ist gerade nicht freigegeben (Freigabe vor Ort noetig)")
        return skill.handler(**args)

    def tool_schemas(self, source="agent"):
        """Werkzeugliste im ueblichen Format (name, description, input_schema) fuer einen Agenten."""
        out = []
        for s in self.skills.values():
            if (source == "remote" and not s.remote_ok) or (source == "agent" and not s.agent_ok):
                continue
            desc = s.description + (" (Bewegt den Arm.)" if s.moves else "")
            out.append({"name": s.name, "description": desc,
                        "input_schema": {"type": "object", "properties": s.params, "required": s.required}})
        return out
