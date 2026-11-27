r"""Isaac-Sim-Backend (Isaac Sim 6.2 / Isaac Lab 3.0, Umgebung %USERPROFILE%\isaac-env).

server.py laeuft IN der Isaac-Umgebung (Python 3.12, eigener Prozess), backend.py im Harness-Python und
spricht mit ihm ueber JSON-Zeilen. So bleiben Harness und Isaac sauber getrennt.
Der Roboter ist die offizielle Isaac-Lab-Vorlage isaaclab_assets.robots.so101.SO101_CFG (TheRobotStudio-USD).
"""
