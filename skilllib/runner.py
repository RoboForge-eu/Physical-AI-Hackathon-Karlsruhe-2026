"""Fuehrt einen Code-Skill aus - als eigener Prozess (Absturz oder Endlosschleife trifft nur diesen Prozess).

Aufruf durch run_skill(); intern:  python -m skilllib.runner   (Auftrag als JSON auf stdin)
Ausgabe: Zeilen 'LOG <text>' waehrend des Laufs, am Ende 'ERGEBNIS <json>'.
"""
import json, os, subprocess, sys, threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_DEPTH = 3


def execute(code, params, robot):
    """Code pruefen und run(robot, **params) aufrufen. Gibt ein Ergebnis-Dict zurueck."""
    from .check import check, safe_builtins
    problems = check(code)
    if problems:
        return {"erfolg": False, "fehler": "Code nicht erlaubt: " + "; ".join(problems)}
    ns = {"__builtins__": safe_builtins()}
    try:
        exec(compile(code, "<skill>", "exec"), ns)
        result = ns["run"](robot, **(params or {}))
    except Exception as exc:
        import traceback
        tb = traceback.extract_tb(exc.__traceback__)
        line = next((f.lineno for f in reversed(tb) if f.filename == "<skill>"), None)
        return {"erfolg": False, "fehler": f"{type(exc).__name__}: {exc}" + (f" (Zeile {line})" if line else "")}
    if not isinstance(result, dict) or "erfolg" not in result:
        return {"erfolg": False, "fehler": "run() muss ein Dict mit 'erfolg' zurueckgeben", "rueckgabe": repr(result)[:200]}
    return result


def make_decider(cfg):
    """Entscheidungspunkt im Skill: ein Sprachmodell waehlt eine Option (mit Kamerabild, wenn gegeben)."""
    def decide(frage, optionen, bild):
        import anthropic
        key = cfg.get("api_key")
        client = anthropic.Anthropic(api_key=key) if key and "<" not in key else anthropic.Anthropic()
        content = []
        if bild:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": bild}})
        content.append({"type": "text", "text": f"{frage}\n\nAntworte nur mit genau einer dieser Optionen: "
                                                f"{', '.join(optionen)}"})
        r = client.messages.create(model=cfg.get("entscheider_model", cfg["model"]), max_tokens=2000,
                                   output_config={"effort": "low"}, messages=[{"role": "user", "content": content}])
        text = " ".join(b.text for b in r.content if b.type == "text").strip()
        return next((o for o in optionen if o.lower() == text.lower()), next((o for o in optionen if o.lower() in text.lower()), optionen[0]))
    return decide


def main():
    job = json.loads(sys.stdin.read())
    sys.path.insert(0, HERE)
    from ros_client import RosClient
    from . import store
    from .api import RobotAPI, DryRunAPI
    from agent import config
    out = sys.stdout

    def log(text):
        out.write("LOG " + str(text).replace("\n", " ") + "\n")
        out.flush()

    if job.get("modus") == "sim":                  # SIMULATION: kein Harness, kein echter Arm
        from sim.ros_sim import szenario
        sj = job.get("sim") or {}
        ros = szenario(sj.get("szenario", "standard"), int(sj.get("seed", 0)), bool(sj.get("zufall", True)),
                       float(sj.get("spiel_mm", 0.5)))
        job["arm"] = ros.arm
    else:
        ros = RosClient(f"Skill {job['name']}")
    depth = {"n": 0}

    def make_robot():
        kw = {"run_skill": run_nested}
        if job.get("modus") == "sim":
            return RobotAPI(ros, job["arm"], log, decide=lambda f, o, b: o[0], **kw)
        if job.get("modus") == "trocken":
            d = job.get("drehbuch") or {}
            return DryRunAPI(ros, job["arm"], log, posen=job.get("posen"), modelle=job.get("modelle"),
                             haelt=d.get("haelt", [True]), antworten=d.get("antworten"), **kw)
        return RobotAPI(ros, job["arm"], log, decide=make_decider(config.load()), **kw)

    def run_nested(name, params):
        if depth["n"] >= MAX_DEPTH:
            raise RuntimeError("Skills rufen sich zu tief gegenseitig auf")
        depth["n"] += 1
        try:
            code, _ = store.code(name)
            log(f"→ Skill {name}")
            return execute(code, params, make_robot())
        finally:
            depth["n"] -= 1

    result = execute(job["code"], job.get("params"), make_robot())
    out.write("ERGEBNIS " + json.dumps(result, ensure_ascii=False, default=str) + "\n")
    out.flush()


def run_skill(name, params=None, arm="follower", modus="echt", version=None, code=None, log=print, timeout=600,
              drehbuch=None, posen=None, modelle=None, python=None, record=True, sim=None):
    """modus: 'echt' (Harness, Freigabe noetig), 'trocken' (Drehbuch) oder 'sim' (Simulation, sim={szenario, seed,
    zufall, spiel_mm})."""
    """Startet den Runner-Prozess und wartet auf das Ergebnis. Zeichnet den Lauf in der Statistik auf."""
    from . import store
    if code is None:
        code, version = store.code(name, version)
    job = {"name": name, "code": code, "params": params or {}, "arm": arm, "modus": modus, "drehbuch": drehbuch,
           "posen": posen, "modelle": modelle, "sim": sim}
    proc = subprocess.Popen([python or sys.executable, "-m", "skilllib.runner"], cwd=HERE, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    proc.stdin.write(json.dumps(job))
    proc.stdin.close()
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    result, other = None, []
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("LOG "):
                log(line[4:])
            elif line.startswith("ERGEBNIS "):
                result = json.loads(line[9:])
            elif line.strip():
                other.append(line)
        proc.wait()
    finally:
        timer.cancel()
    if result is None:
        result = {"erfolg": False, "fehler": "Skill-Prozess ohne Ergebnis beendet" +
                  (" (Zeitgrenze)" if proc.returncode not in (0, None) else ""), "ausgabe": "\n".join(other[-15:])}
    if record and version is not None:
        store.record(name, version, "echt" if modus == "echt" else "trocken", result)
    return result


if __name__ == "__main__":
    main()
