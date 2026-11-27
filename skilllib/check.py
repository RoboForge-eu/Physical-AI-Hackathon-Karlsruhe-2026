"""Pruefung eines Code-Skills, bevor er laeuft.

Der Code darf nur rechnen, entscheiden und 'robot' benutzen. Verboten: import, Dateien, eval/exec,
Zugriff auf __interne__ Attribute, globale Variablen. Das ist keine perfekte Sandbox (Python laesst sich
nie ganz einsperren), aber es verhindert versehentlich gefaehrlichen Code; zusaetzlich laeuft jeder Skill
als eigener Prozess mit Zeitgrenze, und jede Bewegung geht durch die Sicherheitsschicht des Harness.
"""
import ast

FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr",
                   "setattr", "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "type", "object"}
ALLOWED_BUILTINS = {"abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "isinstance", "len", "list",
                    "max", "min", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
                    "print", "True", "False", "None", "Exception", "ValueError", "RuntimeError"}
FORBIDDEN_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await,
                   ast.ClassDef, ast.Lambda)


def check(code):
    """Liste der Probleme (leer = erlaubt)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Syntaxfehler Zeile {exc.lineno}: {exc.msg}"]
    problems = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, FORBIDDEN_NODES):
            problems.append(f"Zeile {line}: {type(node).__name__} ist nicht erlaubt")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            problems.append(f"Zeile {line}: Zugriff auf '{node.attr}' ist nicht erlaubt")
        elif isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            problems.append(f"Zeile {line}: '{node.id}' ist nicht erlaubt")
    top = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
    funcs = [n for n in top if isinstance(n, ast.FunctionDef)]
    if not any(f.name == "run" for f in funcs):
        problems.append("Es fehlt die Funktion run(robot, ...)")
    for n in top:
        if not isinstance(n, (ast.FunctionDef, ast.Assign)):
            problems.append(f"Zeile {n.lineno}: auf oberster Ebene nur Funktionen und Konstanten")
    run = next((f for f in funcs if f.name == "run"), None)
    if run is not None and (not run.args.args or run.args.args[0].arg != "robot"):
        problems.append("run muss als erstes Argument 'robot' haben")
    return problems


def safe_builtins():
    import builtins
    return {k: getattr(builtins, k) for k in ALLOWED_BUILTINS if hasattr(builtins, k)}
