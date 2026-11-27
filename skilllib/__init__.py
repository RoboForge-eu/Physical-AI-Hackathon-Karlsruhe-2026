"""Code-Skills: kleine Python-Programme, die ein Agent schreibt und verbessert und die der Harness danach
immer wieder ausfuehren kann (wie bei 'Agentic Robotics': der Agent lernt eine Aufgabe, indem er Code schreibt).

  store.py   Skills mit Versionen und Erfolgsstatistik (ki_daten/skills/<name>/)
  check.py   Pruefung des Codes vor jedem Lauf (nur erlaubte Sprachmittel, kein import, keine Dateien)
  api.py     'robot': das Einzige, womit ein Skill etwas tun kann - alles geht ueber den Harness
  runner.py  fuehrt einen Skill als eigenen Prozess aus (echt oder Trockenlauf)

Ein Skill sieht so aus:

    def run(robot, teile=1):
        robot.pose("ueber_bett")
        robot.faehigkeit("teil-greifen-act", sekunden=8)
        if not robot.greifer_haelt():
            return {"erfolg": False, "grund": "nichts gegriffen"}
        robot.pose("ueber_kiste")
        robot.greifer(100)
        return {"erfolg": True}
"""
