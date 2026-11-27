"""Example orchestrator: grasp the junction box and check the result.

Flow: request a work session (a person on site approves in the app) -> the VLA model grasps -> check the gripper ->
retry once on failure, otherwise stop with a reason -> end the session (the arm puts itself down).

Run: app, section "4 · Orchestrator" -> "Start orchestrator.py". Output (print) appears there in the log.
Skill names and result keys are German (e.g. "haelt_etwas" = "is holding something"); see skills.liste.
"""
import time
from ros_client import RosClient, RosError

ARM = "follower"                 # arm key (see arme.liste)
MODEL = None                     # name of a finished model; None = take the newest
TASK = "Pick up the orange junction box"
ATTEMPTS = 2

ros = RosClient("team-orchestrator")


def wait_for_session(arm, seconds=120):
    """Asks for approval on site and waits until the arm is ready."""
    ros.call("sitzung.anfragen", arm=arm, modul="Team orchestrator")
    print("Please approve the movement in the app (person on site) ...", flush=True)
    end = time.time() + seconds
    while time.time() < end:
        st = ros.call("sitzung.status", arm=arm)
        if st.get("bereit"):                      # bereit = ready
            return True
        time.sleep(1)
    return False


def main():
    arms = ros.call("arme.liste")
    print("Arms:", ", ".join(f"{a['arm']} ({a['label']})" for a in arms))
    models = ros.call("modelle.liste")
    if not models:
        print("No trained model yet. Train one first in section '3 · Training'.")
        return
    model = MODEL or models[-1]["name"]
    print("Model:", model)
    ros.call("modell.vorladen", arm=ARM, modell=model, aufgabe=TASK)      # preload the model

    if not wait_for_session(ARM):
        print("No approval received - stopping.")
        return
    try:
        for attempt in range(1, ATTEMPTS + 1):
            print(f"Attempt {attempt}: model grasps ...", flush=True)
            ros.call("modell.ausfuehren", arm=ARM, modell=model, sekunden=20, aufgabe=TASK, timeout=60)
            ros.call("greifer.setzen", arm=ARM, prozent=0)          # close safely, then measure
            hold = ros.call("greifer.pruefen", arm=ARM)
            print("Gripper:", hold)
            if hold.get("haelt_etwas"):
                print("Success: box grasped.")
                break
            print("Nothing grasped.")
        else:
            print("Stopped after", ATTEMPTS, "attempts (stop with a reason).")
    except RosError as exc:
        print("Error from the harness:", exc)
    finally:
        ros.call("sitzung.beenden", arm=ARM)                         # end session, arm puts itself down
        print("Session ended, arm is putting itself down.")


if __name__ == "__main__":
    main()
