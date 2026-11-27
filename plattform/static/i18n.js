// Physical AI Harness by RoboForge · Sprache (Deutsch / English).
//
// === KERN-DATEI · fuer Hackathon-Teams NICHT zum Umbauen gedacht ===
// Die Oberflaeche ist auf Deutsch geschrieben. Ist Englisch gewaehlt (<html data-sprache="en">, Einstellung im Profil,
// Standard je Installation in config.json "sprache"), uebersetzt dieser Baustein ALLE angezeigten Texte beim Erscheinen:
//   1. exakte Treffer (EN),  2. Muster mit Platzhaltern (MUSTER),  3. bekannte Satzteile (TEILE).
// So bleiben Harness und Seite unveraendert; neue Texte einfach unten ergaenzen. Eingaben, Code und Protokolle bleiben,
// wie sie sind. In JS-Code fuer alert/confirm/prompt: t("deutscher Text").
"use strict";
const SPRACHE = document.documentElement.dataset.sprache === "en" ? "en" : "de";
document.documentElement.lang = SPRACHE;

const EN = {
  // ---------------- Kopf, Navigation, allgemein
  "Hackathon": "Hackathon", "Datum": "Date", "Anmelden": "Sign in", "Abmelden": "Sign out", "Team": "Team",
  "Hackathon-Plan": "Hackathon schedule", "Hackathon-Plan und Erinnerungen": "Hackathon schedule and reminders",
  "Team-Profil": "Team profile", "Alle Arme sofort stoppen und ablegen": "Stop all arms now and put them down",
  "Alle Arme sofort stoppen und ablegen (F12)": "Stop all arms now and put them down (F12)",
  "GitHub: Hackathon-Repository": "GitHub: hackathon repository", "Hugging Face: RoboForge": "Hugging Face: RoboForge",
  "Start": "Start", "Roboter": "Robot", "Daten": "Data", "Training": "Training", "Orchestr.": "Orchestr.",
  "Interface": "Interface", "Teilen": "Share", "Demo": "Demo", "Roboter einrichten": "Set up the robot",
  "Daten aufnehmen": "Record data", "VLA trainieren": "Train a VLA", "Orchestrator & Skills": "Orchestrator & skills",
  "Orchestrator & Agentic Skills": "Orchestrator & agentic skills", "Euer Interface": "Your interface",
  "Vorstellen": "Present", "Zeiten in": "Times in", "Ordner": "Folder", "Station": "Station", "Mitglieder": "Members",
  "Modelle": "Models", "Datensätze": "Datasets", "GitHub": "GitHub", "Angemeldet": "Signed in",
  "Nicht angemeldet": "Not signed in", "Mit dem Team-Code anmelden (Abschnitt 0 · Start).": "Sign in with your team code (section 0 · Start).",
  "Zum Anmelden": "Go to sign in", "Sprache": "Language", "Abgemeldet.": "Signed out.", "OK": "OK",
  "Abbrechen": "Cancel", "Ja": "Yes", "Nein": "No", "Schließen": "Close", "Speichern": "Save", "Gespeichert.": "Saved.",
  "Läuft ...": "Running ...", "kein Bild": "no image", "leer": "empty", "Rückfrage": "Question", "Fehler": "Error",
  "Harness": "Harness", "fertig.": "done.", "FEHLER": "ERROR",

  // ---------------- 0 Start
  "Ablauf": "How it works", "Dieser Rechner": "This computer", "wird ermittelt ...": "detecting ...",
  "Team-Code vom Zettel an eurer Station eingeben. Damit kommen eure Kalibrierung, der Team-Ordner und die Zugänge zum Teilen automatisch.":
    "Enter the team code from the note at your station. It brings your calibration, your team folder and the access for sharing automatically.",
  "z. B. BLAU-4821": "e.g. BLAU-4821", "Noch kein Team-Paket auf diesem Rechner (Ordner stationspakete).":
    "No team package on this computer yet (folder stationspakete).",
  "Weiter zu 1 · Roboter": "Continue to 1 · Robot", "Rechenwerk": "Compute", "System": "System",
  "KI-Umgebung": "AI environment", "Empfehlung": "Recommendation", "fehlt (siehe README)": "missing (see README)", "ok": "ok",
  "NVIDIA-Grafikkarte: ACT und SmolVLA gehen gut.": "NVIDIA graphics card: ACT and SmolVLA both work well.",
  "Apple-Chip (MPS): ACT empfohlen, SmolVLA geht, ist aber langsam.": "Apple chip (MPS): ACT recommended; SmolVLA works but is slow.",
  "Nur Prozessor: ACT mit wenigen Schritten, besser auf einem Rechner mit Grafikkarte trainieren.":
    "CPU only: ACT with few steps; better train on a computer with a graphics card.",

  // ---------------- 1 Roboter / Station
  "Harness starten": "Start harness", "Harness läuft nicht.": "Harness is not running.",
  "Er steuert Arme und Kameras im Hintergrund. Findet er keine Arme: unten „Arme finden“.":
    "It controls arms and cameras in the background. If it finds no arms: see “Find arms” below.",
  "Anderer Harness aktiv": "Another harness is running",
  "Diese App nutzt nur ihren eigenen Harness mit eigenen Daten. Den anderen schließen (X im Harness-Fenster), dann":
    "This app only uses its own harness with its own data. Close the other one (X in its harness window), then",
  "Harness startet ... (ca. 10 s)": "Harness is starting ... (about 10 s)",
  "Alle ablegen · F12": "Put all down · F12", "Alle laufenden Arme: Greifer auf, ablegen (F12)": "All running arms: open gripper, put down (F12)",
  "Simulation": "Simulation", "Wer steuert den Arm?": "Who controls the arm?", "Leader": "Leader", "KI-Modell": "AI model",
  "Remote": "Remote", "Leader übernehmen": "Take over with leader", "Leader uebernehmen": "Take over with leader",
  "Remote uebernehmen (langsam)": "Take over remotely (slow)", "KI uebernehmen (langsam)": "Let the AI take over (slow)",
  "Stop · ablegen": "Stop · put down", "Steuermodus": "Control mode", "Steuermodus in neuem Fenster": "Control mode in new window",
  "Modell": "Model", "Aufgabe (leer = aus dem Modell)": "Task (empty = from the model)", "Zuweisen": "Assign",
  "Noch kein Modell zugewiesen.": "No model assigned yet.", "(noch kein Modell)": "(no model yet)",
  "Fernzugriff verwalten": "Manage remote access", "Protokoll": "Log", "Neu zuordnen": "Reassign",
  "Nur diesen Platz neu zuordnen": "Reassign only this slot", "Weitere Kameras": "More cameras",
  "gehören zu keinem Arm · zum Experimentieren (Skills kamera.platz_bild, kamera.tiefe)":
    "not attached to an arm · for experiments (skills kamera.platz_bild, kamera.tiefe)",
  "Einrichten": "Setup", "Kameras zuordnen": "Assign cameras", "Arme kalibrieren": "Calibrate arms",
  "Spannung messen": "Measure voltage", "Arbeitsbereich": "Workspace",
  "Kalibrieren und Spannung messen gehen nur, wenn alle Arme abgelegt sind.": "Calibration and voltage measurement only work when all arms are put down.",
  "Netz": "Network", "Fernsteuerung · Übertragung": "Remote control · streaming", "Video-Streaming starten": "Start video streaming",
  "Video-Streaming stoppen": "Stop video streaming", "Fernzugang erstellen": "Create remote access", "Harness neu starten": "Restart harness",
  "Simulation starten": "Start simulation", "Zurück zu echten Armen": "Back to real arms",
  "Neu starten geht nur, wenn alle Arme abgelegt sind. Trainings laufen weiter.": "Restarting only works when all arms are put down. Trainings keep running.",
  "Neu starten": "Restart", "Harness jetzt neu starten? Die Seite verbindet sich danach von selbst wieder.":
    "Restart the harness now? The page reconnects automatically.",
  "Simulation beenden und mit den echten Armen neu starten?": "Leave the simulation and restart with the real arms?",
  "Harness im Simulationsmodus neu starten?": "Restart the harness in simulation mode?",
  "Kein echter Arm bewegt sich, kein COM-Port wird geöffnet.": "No real arm moves, no COM port is opened.",
  "Harness startet neu ...": "Harness is restarting ...", "Video-Streaming startet.": "Video streaming is starting.",
  "Video-Streaming gestoppt.": "Video streaming stopped.", "Im Harness-Fenster": "In harness window",
  "Dieses Fenster stattdessen im Harness-Fenster öffnen": "Open this window in the harness window instead",
  "Im Harness-Fenster geöffnet.": "Opened in the harness window.", "Ich bin vor Ort · Bewegung starten": "I am on site · start moving",
  "Freigegeben · Arm fährt hoch.": "Approved · arm is powering up.", "Arm legt sich ab.": "Arm is putting itself down.",
  "Alle Arme legen sich ab.": "All arms are putting themselves down.", "Noch kein fertiges Modell.": "No finished model yet.",
  // Arme finden
  "Arme finden": "Find arms", "welches Board ist Follower, welches Leader · mit KI-Hilfe": "which board is follower, which is leader · with AI help",
  "Der Harness erkennt die Arme an der": "The harness recognises the arms by the", "USB-Seriennummer": "USB serial number",
  "ihrer Servo-Boards (in": "of their servo boards (in",
  "). Neue Station oder „Board fehlt“? Gib diesen Auftrag an Claude Code oder einen anderen Coding-Agent. Er muss Zugriff auf den Ordner der Software haben; der Pfad dieses Rechners steht schon drin.":
    "). New station or “board missing”? Give this task to Claude Code or another coding agent. It needs access to the software folder; the path on this computer is already included.",
  "Software-Ordner": "Software folder", "Ordner öffnen": "Open folder", "Auftrag für den Coding-Agent": "Task for the coding agent",
  "Kopieren": "Copy", "Angeschlossene Boards": "Connected boards", "Neu suchen": "Search again", "Port": "Port",
  "Seriennummer": "Serial number", "Beschreibung": "Description",
  "Kein Board gefunden. USB-Kabel und Netzteil (5–7,4 V, nie 12 V) prüfen.": "No board found. Check USB cable and power supply (5–7.4 V, never 12 V).",
  "Selbst machen:": "Do it yourself:", ", dann": ", then", "im Software-Ordner. Danach den Harness neu starten.": "in the software folder. Then restart the harness.",
  "Auftrag kopiert. In Claude Code (o. ä.) einfügen.": "Task copied. Paste it into Claude Code (or similar).",
  "Kopieren ging nicht. Bitte den Text markieren und kopieren.": "Copying failed. Please select the text and copy it.",

  // ---------------- 2 Daten / Steuermodus
  "alle Kameras · Aufnahme · Aufnahmeplan · Tasten F3–F8": "all cameras · recording · recording plan · keys F3–F8",
  "Wartet auf den Harness ...": "Waiting for the harness ...", "Verbinde mit dem Harness ...": "Connecting to the harness ...",
  "Harness nicht erreichbar.": "Harness not reachable.", "In neuem Fenster öffnen": "Open in new window",
  "Als Übersicht über den Roboter in einem eigenen Fenster": "As an overview of the robot in its own window",
  "Aufnahme": "Recording", "Datensatz": "Dataset", "Aufgabe": "Task", "● Start": "● Start", "■ Stop": "■ Stop",
  "Behalten": "Keep", "Verwerfen": "Discard", "Startpose": "Start pose", "Aktuelle Stellung als Startpose": "Use current position as start pose",
  "Aufnahmeplan": "Recording plan", "(ohne Plan)": "(no plan)", "noch keine festgelegt": "none set yet",
  "Abstand erst sichtbar, wenn der Arm dem Leader folgt": "Distance shows once the arm follows the leader",
  "✔ in Startpose": "✔ in start pose", "✖ nicht in Startpose": "✖ not in start pose",
  "· Aufnahme nur, während der Arm dem Leader folgt": "· recording only while the arm follows the leader",
  "(F5 = Start)": "(F5 = start)", "Aufnahme steuert der Plan (unten)": "The plan controls recording (below)",
  "Aktuelle Stellung als Startpose speichern?": "Save the current position as start pose?",
  "Neue Episoden sollten danach von hier beginnen. Ältere Episoden mit anderer Startpose am besten löschen.":
    "New episodes should start from here. Best delete older episodes with a different start pose.",
  "Startpose gespeichert.": "Start pose saved.",
  "F5 Start · F6 Stop · F7 Behalten · F8 Verwerfen · F3/F4 Plan · F12 alle ablegen": "F5 start · F6 stop · F7 keep · F8 discard · F3/F4 plan · F12 put all down",
  "Physical AI Harness": "Physical AI Harness", "Plan": "Plan", "So nimmst du auf": "How to record",
  "Noch keine Aufnahmen.": "No recordings yet.", "Name": "Name", "Episoden": "Episodes",
  "(Vorschau, noch nicht begonnen)": "(preview, not started yet)", "nächste:": "next:",
  "empfohlene Methode:": "recommended method:", "Datensatz:": "Dataset:",

  // ---------------- 3 Training
  "Neues Training": "New training", "Methode": "Method", "Schritte": "Steps", "Training starten": "Start training",
  "Trainings": "Trainings", "Fertige Modelle": "Finished models", "Noch kein Training.": "No training yet.",
  "Noch kein fertiges Modell.": "No finished model yet.", "Zustand": "State", "Fortschritt": "Progress", "Rest": "Remaining",
  "Pausieren": "Pause", "Fortsetzen": "Resume", "Am Arm testen": "Test on the arm", "Datensätze": "Datasets",
  "Achtung: ohne NVIDIA-Grafikkarte sehr langsam.": "Note: very slow without an NVIDIA graphics card.",
  "training": "training", "fertig": "done", "fehler": "error", "wartet": "waiting", "pausiert": "paused",
  "wartet (pausiert)": "waiting (paused)", "umwandeln": "converting", "abgebrochen": "cancelled",

  // ---------------- 4 Orchestrator
  "Neue Datei": "New file", "Aktualisieren": "Refresh", "Datei links wählen": "Pick a file on the left",
  "Ausführen": "Run", "aus": "off", "läuft": "running", "orchestrator.py starten": "Start orchestrator.py",
  "Beenden": "Stop", "Noch keine Ausgabe.": "No output yet.", "Orchestrator gestartet.": "Orchestrator started.",
  "Orchestrator beendet.": "Orchestrator stopped.", "Skill": "Skill",
  "Alle Skills des Harness (das kann euer Orchestrator aufrufen)": "All harness skills (your orchestrator can call these)",
  "Harness nicht verbunden.": "Harness not connected.", "Ungespeicherte Änderungen verwerfen?": "Discard unsaved changes?",
  "Neue Datei im Team-Ordner, z. B. skills/fach_pruefen.py": "New file in the team folder, e.g. skills/check_slot.py",
  "Nach dem Anmelden erscheint hier euer Team-Ordner.": "Your team folder appears here after signing in.",
  "Bitte zuerst anmelden (Abschnitt 0), dann erscheint hier euer Team-Ordner.": "Please sign in first (section 0); then your team folder appears here.",
  "· Dateien hier bearbeiten oder den Ordner im Editor öffnen.": "· edit files here or open the folder in your editor.",
  "Euer Team-Ordner:": "Your team folder:",

  // ---------------- 5 Interface, 6 Teilen, 7 Vorstellen
  "Neu laden": "Reload", "Eigenes Fenster": "Own window", "Code": "Code", "Modell": "Model",
  "Was habt ihr geändert?": "What did you change?", "Team-Ordner hochladen": "Upload team folder",
  "Änderungen der Kollegen holen": "Get your teammates’ changes", "Datensatz mit hochladen": "Upload dataset too",
  "Modell veröffentlichen": "Publish model", "Noch kein Modell zum Teilen.": "No model to share yet.",
  "Bitte zuerst anmelden.": "Please sign in first.", "nicht möglich": "not possible", "Zweig:": "Branch:",
  "Präsentationsmodus": "Presentation mode", "Präsentation beenden (Esc)": "Leave presentation (Esc)",
  "Physical AI Hackathon Karlsruhe": "Physical AI Hackathon Karlsruhe", "Euer Team": "Your team",
  "Episoden aufgenommen": "episodes recorded", "Modelle trainiert": "models trained", "Modelle verfügbar": "models available",
  "Text bearbeiten (vorstellung.md im Team-Ordner)": "Edit text (vorstellung.md in the team folder)",
  "Schreibt hier, was euer System kann: Aufgabe, Ablauf, Skills, was gut lief, was nicht.":
    "Write what your system can do: task, flow, skills, what went well, what didn’t.",

  // ---------------- Hackathon-Plan (hackathon_plan.json)
  "Ein SO-101-Arm legt drei Bauteile in die richtigen Fächer und prüft das Ergebnis per Kamera. Liegt die Montageplatte schräg oder ist ein Fach belegt, erkennt der Ablauf den Fehler, korrigiert ihn oder stoppt begründet.":
    "An SO-101 arm places three parts into the right slots and checks the result with a camera. If the mounting plate is tilted or a slot is occupied, the flow detects the error, fixes it or stops with a reason.",
  "Einführung und Demo": "Introduction and demo",
  "Vorstellung der Plattform, Beispiel Elektrodose: so nimmt man Daten auf und trainiert ein VLA.":
    "Platform tour, example junction box: how to record data and train a VLA.",
  "Station einrichten": "Set up the station",
  "Anmelden, Arm prüfen, Kameras scharf stellen, Leader steuert Follower testen.": "Sign in, check the arm, focus the cameras, test leader controlling follower.",
  "Mit dem Aufnahmeplan vormachen (Beispiel Elektrodose oder eigene Aufgabe). Ziel: 40-50 gute Episoden.":
    "Demonstrate with the recording plan (junction box example or your own task). Goal: 40–50 good episodes.",
  "Training 1 starten": "Start training 1",
  "Spätestens jetzt das erste Training starten (ACT, 1-3 Stunden). Währenddessen weiterbauen.":
    "Start the first training now at the latest (ACT, 1–3 hours). Keep building meanwhile.",
  "Orchestrator und Skills bauen": "Build orchestrator and skills",
  "Ablauf planen, Code-Skills mit dem Coding-Agent schreiben, Kameraprüfung bauen. Ab ca. 13:30 Modell 1 testen.":
    "Plan the flow, write code skills with your coding agent, build the camera check. Test model 1 from about 13:30.",
  "Training 2 starten": "Start training 2",
  "Letzter sinnvoller Start für ein besseres Modell (mehr/bessere Daten). Danach reicht die Zeit nicht mehr.":
    "Last sensible start for a better model (more/better data). After that there is not enough time.",
  "Interface bauen und alles verbinden": "Build the interface and connect everything",
  "Eigene Oberfläche in der App, Fehlerfälle (schräge Platte, belegtes Fach) abfangen, Ablauf am echten Arm testen.":
    "Your own UI in the app, handle error cases (tilted plate, occupied slot), test the flow on the real arm.",
  "Teilen und Demo vorbereiten": "Share and prepare the demo",
  "Code, Modell und Datensatz teilen. Vorstellungsseite ausfüllen, Demo einmal durchspielen.":
    "Share code, model and dataset. Fill in the presentation page, rehearse the demo once.",
  "Demos": "Demos", "Jedes Team zeigt seine Lösung am echten Arm (ca. 8 Minuten).": "Each team shows its solution on the real arm (about 8 minutes).",
  "In 15 Minuten das erste Training starten. Sind genug Episoden aufgenommen?": "Start the first training in 15 minutes. Have you recorded enough episodes?",
  "Jetzt das erste Training starten (ACT).": "Start the first training now (ACT).",
  "In 15 Minuten: letzte Chance für Training 2.": "In 15 minutes: last chance for training 2.",
  "Training 2 jetzt starten, später reicht die Zeit nicht mehr.": "Start training 2 now; later there is not enough time.",
  "Zeit zum Teilen: Code, Modell und Datensatz hochladen.": "Time to share: upload code, model and dataset.",
  "In 15 Minuten beginnen die Demos.": "The demos start in 15 minutes.",

  // ---------------- Beispielplan Elektrodose
  "Beispiel: Elektrodose anheben": "Example: lift the junction box",
  "Einfacher Einstieg: eine orange Elektrodose (Hohlwanddose) steht an wechselnden Stellen im Halbring vor dem Arm. Der Arm faehrt hin, greift sie und hebt sie an. 50 Runden = 50 Episoden, genug fuer ein erstes ACT-Modell.":
    "Easy start: an orange junction box stands at changing spots in the half ring in front of the arm. The arm moves there, grabs it and lifts it. 50 rounds = 50 episodes, enough for a first ACT model.",
  "Elektrodose": "Junction box", "Dose steht bereit": "Box is ready", "Dose wie auf der Karte hinstellen.": "Place the box as shown on the map.",
  "Orange Elektrodose": "Orange junction box", "Dose": "Box", "Dosen": "Boxes", "auf dem Tisch": "on the table",
  "Dose aufrecht direkt auf den Tisch stellen, Oeffnung nach oben.": "Stand the box upright on the table, opening facing up.",

  // ---------------- Harness: Status und Kopf
  "Bereit": "Ready", "Board nicht angeschlossen": "Board not connected", "Board: suche ...": "Board: searching ...",
  "Leader: suche ...": "Leader: searching ...", "Leader ausgefallen": "Leader lost", "Leader: frei": "Leader: free",
  "Folgt dem Leader": "Following the leader", "Lauf beendet": "Run finished", "Start abgebrochen": "Start cancelled",
  "Stop angefordert · Ablage abwarten": "Stop requested · wait until put down",
  "NOT-ABLAGE · Greifer oeffnen, ablegen": "EMERGENCY PUT-DOWN · opening gripper, putting down",
  "Vorpruefung → Hochfahren": "Pre-check → powering up", "Nicht sicher beendet": "Not finished safely",
  "Fehler · Zustand vor Ort pruefen, Protokoll beachten": "Error · check the situation on site, see the log",
  "Worker beendet · Zustand vor Ort pruefen, Protokoll beachten": "Worker stopped · check the situation on site, see the log",
  "KI STEUERT (langsam) · Stop zum Ablegen": "AI IN CONTROL (slow) · Stop to put down",
  "Folgt der FERNSTEUERUNG (langsam) · Stop zum Ablegen": "Following REMOTE CONTROL (slow) · Stop to put down",
  "Remote-Probelauf · Arm bewegt sich nicht": "Remote dry run · arm does not move",
  "KI: im VLA-Studio ein Modell fuer diesen Arm waehlen": "AI: pick a model for this arm",
  "● LEADER AKTIV": "● LEADER ACTIVE", "● KI STEUERT": "● AI IN CONTROL", "● REMOTE STEUERT": "● REMOTE IN CONTROL",
  "◌ KI · bereit": "◌ AI · ready", "◌ KI · kein Modell gewaehlt": "◌ AI · no model selected",
  "◌ REMOTE · PROBELAUF": "◌ REMOTE · DRY RUN", "ohne Leader": "no leader",
  "Kamera fehlt · Anschluss pruefen": "Camera missing · check connection", "nicht zugeordnet": "not assigned",
  "verbinde ...": "connecting ...", "kein Signal · Kabel pruefen": "no signal · check cable", "live": "live",
  "Neue Programmversion gespeichert → neu starten": "New program version saved → restart",
  "kein Modul verbunden": "no module connected",
  "Remote-Server: aus (startet, sobald ein Arm auf Remote steht)": "Remote server: off (starts as soon as an arm is set to remote)",
  "Download (Steuerdaten → Roboter): –": "Download (control data → robot): –", "Upload (Roboter → Bediener): –": "Upload (robot → operator): –",
  "Video ins Internet (LiveKit): aus": "Video to the internet (LiveKit): off",
  "Erst alle Arme ablegen (Stop), dann neu starten.": "Put all arms down first (Stop), then restart.",
  "Aufnahme geht nur, waehrend der Arm dem Leader folgt.": "Recording only works while the arm follows the leader.",
  "Bitte Datensatz-Name und Aufgabe eintragen.": "Please enter a dataset name and a task.",
  "Kein Modell gewaehlt.": "No model selected.", "Bewegung freigeben": "Approve movement",
  "KI-Steuerung freigeben": "Approve AI control", "Remote uebernehmen": "Take over remotely",
  "Arbeitssitzung freigeben": "Approve work session", "Fernsteuerung freigeben": "Approve remote control",
  "Jetzt Bewegung starten?": "Start moving now?",
  "Bist du vor Ort, hast den Arbeitsbereich im Blick und stimmst zu?": "Are you on site, watching the workspace, and do you agree?",
  "Follower liegt sicher in seiner Ablage (Hand nach oben geklappt); Arbeitsbereich frei. Leader ungefaehr in Mittelstellung halten.":
    "Follower rests safely in its cradle (hand folded up); workspace clear. Hold the leader roughly in its middle position.",
  "Der Follower faehrt einzeln hoch und gleicht sich in 0,75 Sekunden an den Leader an.": "The follower powers up on its own and matches the leader within 0.75 seconds.",
  "Stop und normales Fensterschliessen fordern das Ablegen an.": "Stop and closing the window request putting the arm down.",
  "Bei Strom-/Verbindungsverlust ist automatisches Ablegen nicht garantiert.": "On power or connection loss, automatic put-down is not guaranteed.",
  "Der Arm faehrt zuerst einzeln hoch und haelt dann seine Stellung, bis das Modell Ziele liefert. Kommen 1 s keine Ziele, legt er sich ab. Ein KI-Modell kann sich unerwartet bewegen.":
    "The arm first powers up on its own and holds its position until the model sends targets. If no targets arrive for 1 s, it puts itself down. An AI model can move unexpectedly.",
  "Bist du vor Ort und stimmst der Bewegung beider Arme zu?": "Are you on site and do you agree to both arms moving?",
  "KI-Fahrer startet (Modell wird geladen) ...": "AI driver starting (loading model) ...",
  "KI: Aufgabe erledigt (Modell haelt still). Arm wird abgelegt.": "AI: task done (model holds still). Putting the arm down.",
  "KI: Zeitgrenze erreicht. Arm wird abgelegt.": "AI: time limit reached. Putting the arm down.",
  "KI: fahre langsam in die Startpose der Aufnahmen ...": "AI: moving slowly to the recordings’ start pose ...",
  "KI: Startpose erreicht, Modell uebernimmt.": "AI: start pose reached, model takes over.",
  "KI: Startpose erreicht, warte auf das Modell (wird noch geladen) ...": "AI: start pose reached, waiting for the model (still loading) ...",
  "KI: Modell nicht rechtzeitig geladen. Arm wird abgelegt.": "AI: model did not load in time. Putting the arm down.",
  "Mindestens ein Arm meldet einen Fehler. Zustand vor Ort pruefen, Protokoll beachten.": "At least one arm reports an error. Check the situation on site, see the log.",
  "Erst alle Arme ablegen. Kalibrieren und Spannung messen brauchen die Ports der Boards.":
    "Put all arms down first. Calibration and voltage measurement need the boards’ ports.",
  "Erst alle Arme ablegen. Die Messung braucht die Ports der Boards, die gerade der Steuerung gehoeren.":
    "Put all arms down first. The measurement needs the boards’ ports, which the controller is using.",
  "Erst alle Arme ablegen und die Spannungsmessung schliessen.": "Put all arms down first and close the voltage measurement.",
  "Kalibrierung oder Spannungsmessung ist schon im Harness-Fenster offen.": "Calibration or voltage measurement is already open in the harness window.",
  "Der Remote-Server laeuft nicht (startet, sobald ein Arm auf Remote steht).": "The remote server is not running (starts as soon as an arm is set to remote).",
  "Erst ablegen, dann die Steuerung wechseln.": "Put the arm down first, then switch control.",
  "Ohne Zustimmung vor Ort bewegt sich nichts.": "Nothing moves without consent on site.",
  "Dieses Fenster ist schon geschlossen.": "This window is already closed.", "Diese Frage ist nicht mehr offen.": "This question is no longer open.",
  "Noch kein Bild": "No image yet", "Der Harness antwortet gerade nicht (beschaeftigt). Bitte gleich nochmal.": "The harness is not responding right now (busy). Please try again.",
  "Keine aktuelle Stellung: der Arm muss dem Leader folgen.": "No current position: the arm must follow the leader.",
  "Bitte bestaetigen.": "Please confirm.",
  // ---------------- Server-Meldungen
  "Bitte den Team-Code eingeben.": "Please enter the team code.", "Bitte zuerst mit dem Team-Code anmelden.": "Please sign in with your team code first.",
  "Der Orchestrator laeuft schon.": "The orchestrator is already running.", "Im Team-Paket fehlt der Hugging-Face-Token.": "The team package has no Hugging Face token.",
  "Jetzt der Datensatz ...": "Now the dataset ...", "Kein fertiger Modellstand gefunden.": "No finished model checkpoint found.",
  "Keine neuen Aenderungen im Team-Ordner.": "No new changes in the team folder.", "Laeuft schon.": "Already running.",
  "Nur Dateien im eigenen Team-Ordner.": "Only files in your own team folder.", "Ordner nicht gefunden (angemeldet?)": "Folder not found (signed in?)",
  "Unbekannter Team-Code. Liegt das Stationspaket im Ordner 'stationspakete'?": "Unknown team code. Is the station package in the folder 'stationspakete'?",
  "unbekannte Aktion": "unknown action", "nur lokal": "local only", "nur aus der Plattform-Seite": "only from the app page",
  "Plattform-Server nicht erreichbar.": "App server not reachable.",

  // ---------------- Harness: Kalibrieren
  "Arme kalibrieren · Anschlaege": "Calibrate arms · end stops", "Welcher Arm:": "Which arm:", "Messung starten": "Start measurement",
  "Arm waehlen und 'Messung starten'. Der Arm liegt in der Ablage, ohne Kraft.": "Pick an arm and press ‘Start measurement’. The arm rests in its cradle, without torque.",
  "Jedes Gelenk wird von Hand bis zum Anschlag gedrueckt, zweimal hin und her. Kein Motor bewegt sich, es wird nur gelesen. Die Messung startet von selbst, sobald du am Anschlag ruhig haeltst.":
    "Push each joint by hand to its end stop, twice back and forth. No motor moves, values are only read. The measurement starts by itself once you hold still at the stop.",
  "Gelenk Anschlag 1 Anschlag 2 Spanne Wiederholung": "Joint Stop 1 Stop 2 Range Repeat",
  "⟳ Alle": "⟳ All", "◀ Zurueck": "◀ Back", "Gelenk wiederholen": "Repeat joint", "Weiter ▶": "Next ▶", "Fertig ▶": "Finish ▶",
  "Senkrecht uebernehmen": "Use vertical", "Nullpunkt setzen": "Set zero point", "Zuordnung aktivieren": "Activate mapping",
  "Zuordnung Leader → Follower": "Mapping leader → follower", "✔ Nullpunkt gesetzt": "✔ Zero point set", "✔ Senkrecht gemerkt": "✔ Vertical saved",
  "✖ Nullpunkt NICHT gesetzt": "✖ Zero point NOT set", "✖ Zuruecklesen stimmt nicht": "✖ Read-back does not match",
  "Nicht alle Servos antworten. Strom und Kabel pruefen, dann erneut starten.": "Not all servos respond. Check power and cables, then start again.",
  "Die Motoren dieses Arms haben Kraft. Erst im Harness 'Stop · ablegen', dann erneut starten.": "This arm’s motors have torque. First ‘Stop · put down’, then start again.",
  "Alle Gelenke sind schon gemessen. Oben das Gelenk anklicken, das du neu messen willst; danach 'Speichern'. Die anderen Gelenke bleiben, wie sie sind.":
    "All joints are measured already. Click the joint above you want to measure again; then ‘Save’. The other joints stay as they are.",
  "Anschlaege sind schon gemessen. Greifer senkrecht stellen (feste Backe nach oben, 90 Grad zum Tisch), ruhig halten und 'Senkrecht uebernehmen' druecken. Oder neu messen.":
    "End stops are measured already. Set the gripper vertical (fixed jaw up, 90° to the table), hold still and press ‘Use vertical’. Or measure again.",
  "Bitte ruhig halten und nochmal druecken": "Please hold still and press again",
  "✖ Stellung liegt nicht zwischen den Anschlaegen": "✖ Position is not between the end stops", "Weiter geht es von selbst.": "It continues by itself.",
  "Nichts gespeichert": "Nothing saved", "Kein Gelenk wurde gueltig gemessen.": "No joint was measured validly.",
  "Naechsten Arm waehlen oder unten die Zuordnung aktivieren.": "Pick the next arm or activate the mapping below.", "nicht aktiv": "not active",
  "Erst die laufende Messung speichern oder schliessen.": "Save or close the running measurement first.",
  "Gilt ab dem naechsten Start des Arms.": "Applies from the arm’s next start.",
  "(Schon gemessen - eine neue Messung ersetzt die alte.)": "(Measured already — a new measurement replaces the old one.)",
  "Alle Gelenke": "All joints",
  "Alle Gelenke neu messen? Die bisherigen Messungen in diesem Fenster werden verworfen (gespeichert wird erst mit 'Speichern').":
    "Measure all joints again? The measurements in this window are discarded (saved only with ‘Save’).",
  "① An einen Anschlag druecken und ruhig halten": "① Push to one end stop and hold still",
  "② Jetzt zum ANDEREN Anschlag und halten": "② Now to the OTHER end stop and hold",
  "③ Zurueck zum ersten Anschlag und halten": "③ Back to the first end stop and hold",
  "④ Noch einmal zum anderen Anschlag und halten": "④ Once more to the other end stop and hold",
  "· erst vom Anschlag wegbewegen": "· move away from the stop first", "· bitte wiederholen": "· please repeat",
  "✔ Anschlaege gemessen · jetzt Greifer senkrecht stellen": "✔ End stops measured · now set the gripper vertical",
  "Greifer so drehen, dass die feste Backe genau senkrecht nach oben zeigt (90 Grad zum Tisch). Ruhig halten und 'Senkrecht uebernehmen' druecken. Kein Motor bewegt sich. Diese Stellung ist dann bei Leader und Follower dieselbe.":
    "Rotate the gripper so the fixed jaw points straight up (90° to the table). Hold still and press ‘Use vertical’. No motor moves. This position is then the same on leader and follower.",
  "✖ Bereich laeuft ueber den Nullpunkt (0/4095) · bitte 'Weiter'": "✖ Range crosses the zero point (0/4095) · please press ‘Next’",
  "Sicherung unvollstaendig (Servo antwortet nicht) · nichts geschrieben": "Backup incomplete (servo not responding) · nothing written",
  "Motoren haben Kraft · nichts geschrieben": "Motors have torque · nothing written",
  "Motoren haben Kraft · erst im Harness 'Stop · ablegen'": "Motors have torque · first ‘Stop · put down’",
  "Ablage-/Startstellung umgerechnet.": "Rest/start position converted.", "Bitte eine Zahl in Grad eintragen, z. B. 2.5": "Please enter a number in degrees, e.g. 2.5",
  "Greifer antwortet nicht": "Gripper does not respond", "(von vorher)": "(from before)", "noch nicht gemessen": "not measured yet",
  "Gelenk zurueck in die Ablage legen.": "Put the joint back into its rest position.",
  "Die alte Messung bleibt, bis eine neue gelingt.": "The old measurement stays until a new one succeeds.",
  "keine Antwort": "no response", "Greifer zu/auf": "Gripper closed/open", "Gleiche Stellung": "Same position",
  "Bitte beide Arme ruhig halten und nochmal.": "Please hold both arms still and try again.",
  "beide Greifer gleich drehen, z. B. die feste Backe genau senkrecht nach oben": "rotate both grippers the same way, e.g. fixed jaw straight up",
  "beide Gelenke in dieselbe, gut erkennbare Stellung bringen (z. B. genau 90 Grad)": "bring both joints into the same clearly visible position (e.g. exactly 90°)",
  "Gilt, sobald die Zuordnung aktiviert ist.": "Applies once the mapping is activated.",
  "Aktive Zuordnung aktualisiert (gilt ab dem naechsten Start).": "Active mapping updated (applies from the next start).",

  // ---------------- Harness: Kameras zuordnen
  "Kameras zuordnen": "Assign cameras", "Ergebnis beim Speichern:": "Result when saving:",
  "Ueberspringen (alte Zuordnung behalten)": "Skip (keep old assignment)", "Jetzt speichern und Harness neu starten": "Save now and restart harness",
  "neu zugeordnet": "newly assigned", "getauscht/ergaenzt": "swapped/added", "bleibt": "unchanged", "Fertig": "Done",
  "Zuordnung pruefen und speichern. ROS startet danach neu und zeigt die Kameras am richtigen Platz.":
    "Check the assignment and save. The harness then restarts and shows the cameras in the right place.",
  "Eine Kamera wurde zwei Plaetzen zugeordnet. Bitte neu zuordnen.": "One camera was assigned to two slots. Please assign again.",
  "Setup 1 · Arm": "Setup 1 · Arm", "Setup 1 · Turm": "Setup 1 · Tower", "Übersicht 2 · OAK-D Lite": "Overview 2 · OAK-D Lite",
  "frei 3": "free 3", "frei 4": "free 4",

  // ---------------- Harness: Spannung, Arbeitsbereich, Fernzugang
  "Spannungsmessung · nur Lesen": "Voltage measurement · read only", "Zaehler zuruecksetzen": "Reset counters",
  "Nur Lesen: kein Motor wird angesteuert, die Arme bleiben kraftlos. Arme in der Ablage lassen.": "Read only: no motor is driven, the arms stay without torque. Leave the arms in their cradles.",
  "Am Kabel zwischen Handgelenk-Drehung (5) und Greifer (6) wackeln und die Drehung von Hand bewegen. Gezaehlt werden Einbrueche unter 4,0 V und Aussetzer (Servo antwortet nicht).":
    "Wiggle the cable between wrist roll (5) and gripper (6) and turn the roll by hand. Drops below 4.0 V and dropouts (servo not responding) are counted.",
  "Hinweis: ohne Last fliesst kaum Strom. Ein schlechter Kontakt zeigt sich dann eher als Aussetzer als als Spannungseinbruch.":
    "Note: without load hardly any current flows. A bad contact then shows up as a dropout rather than a voltage drop.",
  "Arbeitsbereich 3D · Waende je Arm": "Workspace 3D · walls per arm", "Plan laden": "Load plan", "SVG / DXF laden ...": "Load SVG / DXF ...",
  "Von oben": "From above", "Von der Seite": "From the side", "beide Arme zeigen": "show both arms",
  "Basis buendig an Tischkante (y = 0)": "Base flush with table edge (y = 0)", "Waende aktiv (speichert sofort)": "Walls active (saves immediately)",
  "Uebernehmen und speichern": "Apply and save", "Bitte Zahlen eintragen.": "Please enter numbers.",
  "Ablage-Stellung (Arm laeuft nicht)": "Rest position (arm not running)", "steht im Bereich": "is inside the area",
  "Basis x [m] (entlang der Kante)": "Base x [m] (along the edge)", "Basis y [m] (Mitte der Basis)": "Base y [m] (centre of base)",
  "Basis zeigt nach [Grad]": "Base points to [deg]", "Arm-Mitte zeigt nach [Grad]": "Arm centre points to [deg]",
  "Drehsinn (+1 / -1)": "Rotation sense (+1 / -1)", "Abstand zur Wand [cm]": "Distance to wall [cm]",
  "Keine geschlossenen Flaechen gefunden.": "No closed areas found.", "Ohne erlaubte Flaeche kann nichts aktiv sein.": "Without an allowed area nothing can be active.",
  "Gruen: erlaubter Bereich mit Waenden, rot: Hindernis, roter Punkt: engste Stelle. Der Arm ist das echte SO-101-Modell, live wenn er laeuft (sonst Ablage-Stellung). In SVG/DXF ist die groesste Flaeche der erlaubte Bereich, alle anderen sind Hindernisse.":
    "Green: allowed area with walls, red: obstacle, red dot: tightest spot. The arm is the real SO-101 model, live when running (otherwise rest position). In SVG/DXF the largest area is the allowed area, all others are obstacles.",
  "Hoechstdauer pro Bediener (Minuten):": "Maximum time per operator (minutes):", "Uebernehmen": "Apply",
  "✖ Entfernen (kicken)": "✖ Remove (kick)", "Verlaengern um": "Extend by", "Merken mit Limit": "Remember with limit",
  "Niemand steuert": "Nobody is in control", "Remote-Server laeuft nicht.": "Remote server is not running.", "Limit (min)": "Limit (min)",
  "Zugangscode fuer die App „RoboForge Fernsteuerung“": "Access code for the “RoboForge Remote Control” app",
  "In die Zwischenablage kopieren": "Copy to clipboard", "kopiert ✔": "copied ✔",
  "Hinweis: Video-Streaming laeuft noch nicht. Die App kann es auch selbst starten.": "Note: video streaming is not running yet. The app can also start it itself.",

  // ---------------- Harness: Aufnahmeplan (Steuermodus)
  "Wrist-Cam · Startpose": "Wrist cam · start pose", "Wrist-Cam wird gesucht ...": "Looking for wrist cam ...",
  "Maske manuell": "Mask manual", "Maske irrt (Bild merken)": "Mask is wrong (save image)", "Schärfe messen + speichern": "Measure + save sharpness",
  "Nicht erreichbar": "Unreachable", "● Start (F5)": "● Start (F5)", "✔ Behalten (F7)": "✔ Keep (F7)", "✖ Verwerfen (F8)": "✖ Discard (F8)",
  "Nicht greifbar (F4)": "Not graspable (F4)", "Automatischer Start/Stopp": "Automatic start/stop", "Start nach": "Start after", "s": "s",
  "Runden (anklicken)": "Rounds (click)", "grün fertig · gelb aktuell · blau begonnen": "green done · yellow current · blue started",
  "◀ Aktuelle Runde": "◀ Current round", "Runde neu": "Redo round", "Letztes Bild": "Last image", "Bild fehlt": "Image missing",
  "Bild ansehen": "View image", "Schärfe: keine Kamera": "Sharpness: no camera", "Schärfe: keine Kamera liefert Bilder": "Sharpness: no camera delivers images",
  "Schärfe wird gemessen ... Kamera ruhig halten": "Measuring sharpness ... hold the camera still", "Kein Wrist-Cam-Bild": "No wrist cam image",
  "Maske: OK": "Mask: OK", "Maske: manuell bestaetigt": "Mask: confirmed manually", "Maske: Kanten an die Fuehrungen bringen": "Mask: align the edges with the guides",
  "Arm folgt nicht dem Leader": "Arm does not follow the leader", "Fertig: alle Runden aufgenommen.": "Done: all rounds recorded.", "Runde fertig.": "Round done.",
  "Runde fertig": "Round done", "Griff gut? F7 = behalten · F8 = verwerfen": "Good grasp? F7 = keep · F8 = discard",
  "Alle Runden aufgenommen. Testplatzierungen getrennt aufnehmen (VLA-Studio).": "All rounds recorded. Record test placements separately.",
  "Karton wie auf der Karte hinlegen.": "Place the box as shown on the map.", "Karton liegt bereit": "Box is ready",
  "Greifer nicht geschlossen": "Gripper not closed", "Greifer schliessen": "close the gripper", "Greifer geschlossen": "Gripper closed", "Greifer offen": "Gripper open",
  "die freieste": "the most accessible one", "aktuelle Aufnahme": "current recording", "Das Kameravideo ist nicht verfügbar.": "The camera video is not available.",
  "Griff wiederholen": "Repeat grasp", "Runde wiederholen": "Repeat round", "Griff wirklich neu aufnehmen?": "Really re-record this grasp?",
  "Runde wirklich loeschen?": "Really delete this round?", "Nicht greifbar": "Not graspable", "Platzierung": "Placement", "Lage": "Position",
  "Wrist-Cam liefert kein Bild – Aufnahme nicht gestartet": "Wrist cam delivers no image – recording not started",
  "Bitte im Startbild antippen, wo das gegriffene Exemplar lag.": "Please tap in the start image where the grasped item was.",
  "Kein anderes Bauteil mehr offen: die Runde ist beendet. Die fehlenden Griffe werden in den Ist-Zahlen ausgewiesen.":
    "No other part left: the round is finished. The missing grasps are shown in the actual counts.",
  "Leg das Teil wieder so in den Karton, wie es vor dem Griff lag.": "Put the part back into the box the way it was before the grasp.",
  "Diese Runde liegt nicht mehr auf dem Tisch: Karton wieder an ihre Position legen und so befüllen, wie es dann angezeigt wird. Danach geht es mit der aktuellen Runde weiter.":
    "This round is no longer on the table: put the box back at its position and fill it as shown. Then the current round continues.",
  "Diese Platzierung ist nicht erreichbar (Maske nicht erfuellbar oder Greifer kommt nicht an alle vier Ecken)?": "Is this placement unreachable (mask cannot be met or the gripper cannot reach all four corners)?",
  "Es wird eine Ersatzplatzierung derselben Ausrichtung erzeugt.": "A replacement placement with the same orientation is created.",
  "Die noch offene Aufnahme wird verworfen.": "The open recording is discarded.", "[Lage: nach dem Griff antippen]": "[position: tap after the grasp]",
  "Andere Runde im Blick.": "Looking at another round.", "↺ Griff neu · ◀ zurück": "↺ redo grasp · ◀ back", "Runde nicht bestaetigt": "Round not confirmed",
  "Maske nicht gruen": "Mask not green", "alles bereit": "all set", "haelt ein Teil": "holding a part", "noch zu": "still closed",
  "Nach dem Griff: Lage im Startbild antippen oder Taste 1-9 (wie Ziffernblock: 7 8 9 = hinten, 1 2 3 = vorne).":
    "After the grasp: tap the position in the start image or press 1–9 (like a numpad: 7 8 9 = back, 1 2 3 = front).",
  "Wo lag das Teil? Im Bild antippen oder Taste 1–9": "Where was the part? Tap in the image or press 1–9",
  "(7 8 9 = hinten · 4 5 6 = Mitte · 1 2 3 = vorne)": "(7 8 9 = back · 4 5 6 = middle · 1 2 3 = front)",
  "STARTBILD: Lage des gegriffenen Teils antippen": "START IMAGE: tap the position of the grasped part",
  "→ Greifer kommt von hier (blau)": "→ gripper comes from here (blue)", "Hinterkante oben im Bild": "Back edge at top of image",
  "Vorderkante nahe Greiferspitze": "Front edge near gripper tip", "Ganzer Karton von oben": "Whole box from above",
  "Fertig: alle Runden aufgenommen": "Done: all rounds recorded",
};

// Muster: Platzhalter-Gruppen werden selbst wieder uebersetzt (z. B. Phasennamen).
const MUSTER = [
  [/^Harness verbunden · (\d+) Arm\(e\)$/, "Harness connected · $1 arm(s)"],
  [/^Phase bis (.+)$/, "Phase until $1"], [/^· danach (.+) \((.+)\)$/, (m, a, b) => `· then ${tr(a)} (${b})`],
  [/^Weiter bei „(.+)“ \((.+)\)$/, (m, a, b) => `Continuing at “${tr(a)}” (${tr(b)})`],
  [/^zuletzt angesehen$/, "last viewed"], [/^zuletzt gearbeitet$/, "last worked on"],
  [/^Zuletzt: (.+) \((.+)\)$/, (m, a, b) => `Last: ${tr(a)} (${b})`], [/^Willkommen, (.+)!$/, "Welcome, $1!"],
  [/^Training (.+) gestartet\.$/, "Training $1 started."], [/^Training (.+) wirklich abbrechen\?$/, "Really cancel training $1?"],
  [/^Training (.+): (.+)$/, "Training $1: $2"], [/^beendet \((.+)\)$/, "finished ($1)"],
  [/^GitHub: euer Team-Ordner \((.+)\)$/, "GitHub: your team folder ($1)"], [/^Ziel: (.+)$/, "Target: $1"],
  [/^Repo: (.+)$/, "Repo: $1"], [/^\(wird beim Hochladen (.+)\)$/, "(becomes $1 when uploading)"],
  [/^(\d+) h (\d+) min$/, "$1 h $2 min"], [/^(\d+) Episoden$/, "$1 episodes"], [/^(.+) Team-Paket\(e\) auf diesem Rechner\.$/, "$1 team package(s) on this computer."],
  [/^Modell (.+) zugewiesen\.$/, "Model $1 assigned."], [/^Zugewiesen: (.+)$/, "Assigned: $1"], [/^Steuermodus · (.+)$/, "Control mode · $1"],
  [/^● AUFNAHME ([\d.]+) s · (.*) \(F6 = Stop\)$/, (m, a, b) => `● RECORDING ${a} s · ${tr(b)} (F6 = stop)`],
  [/^([\d.]+) s aufgenommen · F7 behalten \/ F8 verwerfen$/, "$1 s recorded · F7 keep / F8 discard"],
  [/^(\d+) Episoden (.+)$/, (m, a, b) => `${a} episodes ${tr(b)}`],
  [/^✔ in Startpose (.+)$/, (m, a) => `✔ in start pose ${a.replace(/Bas/g, "Bas").replace(/Sch/g, "Sho").replace(/Ell/g, "Elb").replace(/HdB/g, "WrF").replace(/HdD/g, "WrR").replace(/Gr /g, "Gr ")}`],
  [/^✖ nicht in Startpose (.+)$/, "✖ not in start pose $1"],
  [/^· (\d+) von (\d+) Runden fertig(.*)$/, (m, a, b, c) => `· ${a} of ${b} rounds done${c ? " " + tr(c.trim()) : ""}`],
  [/^Runde (\d+)$/, "Round $1"], [/^Tischkante unten · Kreise (.+) cm um die Armbasis$/, "Table edge at bottom · circles $1 cm around the arm base"],
  [/^bei x (.+) cm, y (.+) cm$/, "at x $1 cm, y $2 cm"],
  // Harness
  [/^Leader: (.+) verbunden$/, "Leader: $1 connected"], [/^Leader nicht angeschlossen \(USB (.*)\) · Anschluss pruefen$/, "Leader not connected (USB $1) · check connection"],
  [/^Board fehlt \(USB (.*)\) · Anschluss pruefen$/, "Board missing (USB $1) · check connection"], [/^Board (COM\d+|\/dev\/.+)$/, "Board $1"],
  [/^Modell: (.+) · Aufgabe: (.+)$/, "Model: $1 · Task: $2"], [/^ARBEITSSITZUNG \((.+)\) · Stop zum Ablegen$/, "WORK SESSION ($1) · Stop to put down"],
  [/^Leader ausgefallen: (.+)$/, "Leader lost: $1"], [/^(.+): Bist du vor Ort und stimmst der schnellen Bewegung zu\?$/, "$1: Are you on site and do you agree to the fast movement?"],
  [/^Leader von (.+) zu (.+) wechseln\?$/, "Switch the leader from $1 to $2?"],
  [/^(.+) legt sich kontrolliert ab, GLEICHZEITIG faehrt (.+) hoch und folgt dem Leader\.$/, "$1 puts itself down in a controlled way, AT THE SAME TIME $2 powers up and follows the leader."],
  [/^(.+) wird vom KI-Modell (.+) \((.+)\) bewegt, hoechstens (.+) Grad\/s je Gelenk\. Haelt das Modell nach der Aufgabe still oder ist eine Minute um, legt sich der Arm ab\.$/,
    "$1 is moved by the AI model $2 ($3), at most $4 deg/s per joint. When the model holds still after the task or a minute has passed, the arm puts itself down."],
  [/^Aufgabe: (.+)$/, "Task: $1"], [/^ACHTUNG: Das Modell wurde an (.+) aufgenommen, nicht an (.+)\.$/, "CAUTION: the model was recorded on $1, not on $2."],
  [/^Das Modell braucht die Kameras (.+), (.+) hat (.+) \(fehlt: (.+)\)\.$/, "The model needs the cameras $1, $2 has $3 (missing: $4)."],
  [/^Das Modul '(.+)' moechte (.+) bewegen\.$/, "The module '$1' wants to move $2."],
  [/^(.+) faehrt hoch und haelt dann seine Stellung\. Das Modul bewegt den Arm danach selbst: .*$/,
    "$1 powers up and then holds its position. After that the module moves the arm itself: fixed programmed moves (slow, checked against the height model beforehand) and learned skills (at most 45 deg/s per joint). Stop puts the arm down at any time and ends the session."],
  [/^(.+) faehrt hoch und haelt dann seine Stellung\. Bewegungen gibt es nur, wenn .*$/,
    "$1 powers up and then holds its position. It only moves when the module runs a skill (trained model), slowly (at most 45 deg/s per joint). Stop puts the arm down at any time and ends the session."],
  [/^ARBEITSSITZUNG fuer Modul '(.+)' freigegeben.*$/, "WORK SESSION approved for module '$1'"],
  [/^Uebernehmen geht gerade nicht: (.+)$/, (m, a) => `Taking over is not possible right now: ${a.split(" · ").map(tr).join(" · ")}`],
  [/^Remote-Server: Start fehlgeschlagen \((.+)\)$/, "Remote server: start failed ($1)"], [/^LiveKit ist nicht eingerichtet: (.+)$/, "LiveKit is not set up: $1"],
  [/^Download \(Steuerdaten → Roboter\): (.+)$/, "Download (control data → robot): $1"], [/^Upload \(Roboter → Bediener\): (.+)$/, "Upload (robot → operator): $1"],
  [/^Video ins Internet \(LiveKit\): (.+)$/, (m, a) => `Video to the internet (LiveKit): ${tr(a)}`],
  [/^🎮 Bediener: (.+) · noch (.+) min$/, "🎮 Operator: $1 · $2 min left"], [/^Limit (\d+) min · Zuschauer\/Warteschlange: (.+)$/, "Limit $1 min · viewers/queue: $2"],
  [/^Es läuft ein anderer Harness \(aus (.+)\)\. Bitte diesen schließen, dann hier „Harness starten“\.$/, "Another harness is running (from $1). Please close it, then press “Start harness” here."],
  [/^(\d+) · (.+)$/, (m, a, b) => `${a} · ${tr(b)}`],
  [/^Modell '(.+)' nicht gefunden \(noch nicht fertig trainiert\?\)$/, "Model '$1' not found (not finished training yet?)"],
  [/^Team-Ordner teams\/(.+) aus der Vorlage angelegt\.$/, "Team folder teams/$1 created from the template."],
  [/^(.+) fehlt im Team-Ordner\.$/, "$1 is missing in the team folder."], [/^(.+) endete mit Fehler (.+)$/, "$1 ended with error $2"],
  [/^Hochgeladen in (.+)\. Der Waechter uebernimmt den Ordner in wenigen Minuten nach main\.$/, "Uploaded to $1. The guard copies the folder to main within a few minutes."],
  [/^Wechsle auf den Team-Zweig (.+) \.\.\.$/, "Switching to the team branch $1 ..."], [/^Fertig: (.+)$/, "Done: $1"], [/^FEHLER: (.+)$/, "ERROR: $1"],
  [/^ROS nicht erreichbar \((.+)\): (.+)$/, "Harness not reachable ($1): $2"], [/^Unbekannter Befehl (.+)$/, "Unknown command $1"],
  // Kalibrieren, Kameras
  [/^Hand weg von allen Kameras \.\.\. gleich: die Kamera fuer »(.+)« mit der Hand ganz abdecken\.$/, (m, a) => `Hands off all cameras ... next: cover the camera for »${tr(a)}« completely with your hand.`],
  [/^Jetzt die Kamera fuer »(.+)« mit der Hand ganz abdecken und halten\.$/, (m, a) => `Now cover the camera for »${tr(a)}« completely with your hand and hold.`],
  [/^Erkannt: (.+) ist »(.+)«\. Hand wieder weg\.$/, (m, a, b) => `Detected: ${a} is »${tr(b)}«. Hand away again.`],
  [/^Helligkeit jetzt: (.*)$/, "Brightness now: $1"], [/^(\d+)\/(\d+) · (.+)$/, (m, a, b, c) => `${a}/${b} · ${tr(c)}`],
  [/^Position (.+) gemessen: (.+)$/, "Position $1 measured: $2"], [/^Gespeichert in calibration\/stops_(.+)$/, "Saved in calibration/stops_$1"],
  [/^✔ (.+): Versatz (.+) Grad gespeichert\.$/, "✔ $1: offset $2 deg saved."], [/^Gleiche Stellung · Leader → (.+)$/, "Same position · leader → $1"],
  [/^Leader (.+) Follower (.+) Unterschied (.+) Grad$/, "Leader $1 Follower $2 Difference $3 deg"],
  [/^Noch etwas weiter druecken \(ca\. (.+) Grad\): eben warst du an dieser Seite schon weiter$/, "Push a bit further (about $1 deg): you were further on this side before"],
  [/^Board nicht gefunden: (.+)$/, "Board not found: $1"], [/^Port nicht frei oder Fehler: (.+)$/, "Port busy or error: $1"],
  [/^Nicht gespeichert: (.+)$/, "Not saved: $1"], [/^AKTIV seit (.+)$/, "ACTIVE since $1"], [/^Leader: (.+)$/, "Leader: $1"],
  [/^Arm \((.+)\): engste Stelle (.+) cm$/, "Arm ($1): tightest spot $2 cm"], [/^ragt (.+) cm ueber eine Wand$/, "sticks out $1 cm over a wall"],
  [/^Fernzugriff · (.+)$/, "Remote access · $1"], [/^Bediener: (.+) · noch (.+) min$/, "Operator: $1 · $2 min left"],
  [/^Spannungsmessung · nur Lesen · (.+) Durchlaeufe\/s$/, "Voltage measurement · read only · $1 cycles/s"],
  // Aufnahmeplan
  [/^Runde (\d+) von (\d+) · Session (\d+)$/, "Round $1 of $2 · session $3"], [/^Griff (\d+) von (\d+): (.+)$/, (m, a, b, c) => `Grasp ${a} of ${b}: ${tr(c)}`],
  [/^Greif: (.+) – (.+)$/, (m, a, b) => `Grasp: ${tr(a.toLowerCase().replace(/^./, (x) => x.toUpperCase())).toUpperCase()} – ${tr(b)}`],
  [/^Warte auf: (.+)$/, (m, a) => `Waiting for: ${a.split(", ").map(tr).join(", ")}`],
  [/^● AUFNAHME: (.+) greifen, anheben,$/, (m, a) => `● RECORDING: grasp ${tr(a)}, lift,`],
  [/^zurueck zur Startpose und still halten \(oder F6\)\.$/, "back to the start pose and hold still (or F6)."],
  [/^Runde (\d+) ganz neu$/, "Redo round $1 completely"], [/^Plan fertig · (\d+) Runden$/, "Plan done · $1 rounds"],
  [/^Befuellung: (.+) · Anordnung: (.+)$/, (m, a, b) => `Filling: ${a} · arrangement: ${tr(b)}`], [/^Befehlsart: (.+)$/, "Command type: $1"],
  [/^1\. (.+)$/, (m, a) => `1. ${tr(a)}`], [/^2\. Befuellen: (.+) – (.+) \(Details rechts\)$/, (m, a, b) => `2. Fill: ${a} – ${tr(b)} (details on the right)`],
  [/^3\. Dann F3 druecken\.$/, "3. Then press F3."], [/^Gesamt (\d+)\/(\d+) · (.*)$/, "Total $1/$2 · $3"],
  [/^Runde (\d+) · Session (\d+) · (.+) · (.+)$/, (m, a, b, c, d) => `Round ${a} · session ${b} · ${c} · ${tr(d)}`],
  [/^Anordnung „(.+)“: (.+)$/, (m, a, b) => `Arrangement “${tr(a)}”: ${tr(b)}`], [/^Letztes Bild · Runde (\d+) · (.+)$/, (m, a, b) => `Last image · round ${a} · ${tr(b)}`],
  [/^Ansicht Runde (\d+) · x (.+) y (.+) cm · (.+)$/, "View round $1 · x $2 y $3 cm · $4"], [/^✔ (.+) \(F3\)$/, (m, a) => `✔ ${tr(a)} (F3)`],
  [/^Alles bereit · Start in (.+) s$/, "All set · start in $1 s"], [/^Start in (.+) s$/, "Start in $1 s"], [/^Start, sobald: (.+)$/, (m, a) => `Start once: ${a.split(", ").map(tr).join(", ")}`],
  [/^● Aufnahme · (.+)$/, (m, a) => `● Recording · ${tr(a)}`], [/^Schärfe: (.+)$/, (m, a) => `Sharpness: ${a.replace(/ \/ Plan /g, " / plan ").replace(/\(nicht gespeichert\)/g, "(not saved)").replace(/⚠ unscharf\?/g, "⚠ blurry?")}`],
  [/^Schärfe gespeichert: (.+)$/, "Sharpness saved: $1"], [/^Bild gemerkt \((.+)\) – danke$/, "Image saved ($1) – thanks"],
  [/^(.+) wie zuvor platzieren \(x (.+) cm, y (.+) cm, (.+)°\)\.$/, (m, a, b, c, d) => `Place the ${tr(a).toLowerCase()} as before (x ${b} cm, y ${c} cm, ${d}°).`],
  [/^💡 LICHT: (.+)$/, "💡 LIGHT: $1"], [/^\(Licht: (.+)\)$/, "(light: $1)"],
  [/^irgendeine – aber NICHT die freieste!$/, "any one – but NOT the most accessible!"],
  [/^\(Geht das nicht sicher, z\. B\. gestapelt: die freieste nehmen und Lage antippen\.\)$/, "(If that is not safe, e.g. stacked: take the most accessible one and tap its position.)"],
];

// Satzteile fuer alles, was weder exakt noch per Muster passt (laengste zuerst)
const TEILE = Object.entries({
  "Stop · ablegen": "Stop · put down", "Anschluss pruefen": "check connection", "nicht angeschlossen": "not connected",
  "Arbeitsbereich": "workspace", "Kalibrierung": "calibration", "abgelegt": "put down", "verbunden": "connected",
  "Aufnahme": "recording", "Runde": "round", "Griff": "grasp", "Greifer": "gripper", "Gelenk": "joint", "Anschlag": "end stop",
  "Sicherung": "backup", "gespeichert": "saved", "fehlt": "missing", "nicht gefunden": "not found", "Bitte": "Please",
  "Fehler": "error", "Kamera": "camera", "Kameras": "cameras", "Datensatz": "dataset", "Modell": "model", "Aufgabe": "task",
}).sort((a, b) => b[0].length - a[0].length).map(([de, en]) => [new RegExp(`(^|[^\\wäöüÄÖÜß])${de.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=$|[^\\wäöüÄÖÜß])`, "g"), en]);

const NORM = (s) => s.replace(/\s+/g, " ").trim();
const EN_NORM = Object.fromEntries(Object.entries(EN).map(([k, v]) => [NORM(k), v]));

function tr(text) {
  if (SPRACHE !== "en" || text == null) return text;
  const s = NORM(String(text));
  if (!s || !/[A-Za-zÄÖÜäöüß]/.test(s)) return text;
  if (s in EN_NORM) return EN_NORM[s];
  for (const [re, ziel] of MUSTER) {
    const m = s.match(re);
    if (m) return typeof ziel === "function" ? ziel(...m) : s.replace(re, ziel);
  }
  if (!/[äöüÄÖÜß]|\b(der|die|das|und|nicht|ist|mit|fuer|für|von|zum|zur|bitte|noch|jetzt|erst)\b/i.test(s)) return text;
  let out = s;
  for (const [re, en] of TEILE) out = out.replace(re, (m, a) => a + en);
  return out;
}
function t(text) { return tr(text); }

// ---- DOM automatisch uebersetzen (Texte, title, placeholder) ----
const AUSNAHMEN = "code, textarea, input, pre.log, .dateiliste, .vortrag, .prompt-box pre, [data-kein-i18n], script, style, kbd";
const ORIGINAL = new WeakMap();
function textKnoten(n) {
  const p = n.parentElement;
  if (!p || p.closest(AUSNAHMEN)) return;
  const roh = n.data;
  if (ORIGINAL.get(n) === roh) return;                  // schon uebersetzt (unsere eigene Aenderung)
  const neu = tr(roh);
  if (neu !== roh && NORM(neu) !== NORM(roh)) {
    const vorne = roh.match(/^\s*/)[0], hinten = roh.match(/\s*$/)[0];
    const ziel = vorne + neu + hinten;
    ORIGINAL.set(n, ziel);
    n.data = ziel;
  } else ORIGINAL.set(n, roh);
}
function attribute(el) {
  if (el.closest && el.closest(AUSNAHMEN)) return;
  for (const a of ["title", "placeholder", "aria-label"]) {
    const v = el.getAttribute && el.getAttribute(a);
    if (v && el.dataset["i18n" + a] !== v) { const n = tr(v); el.setAttribute(a, n); el.dataset["i18n" + a] = n; }
  }
}
function uebersetzeBaum(wurzel) {
  if (wurzel.nodeType === 3) return textKnoten(wurzel);
  if (wurzel.nodeType !== 1) return;
  attribute(wurzel);
  const w = document.createTreeWalker(wurzel, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  let n;
  while ((n = w.nextNode())) n.nodeType === 3 ? textKnoten(n) : attribute(n);
}
if (SPRACHE === "en") {
  const start = () => {
    uebersetzeBaum(document.body);
    new MutationObserver((liste) => {
      for (const m of liste) {
        if (m.type === "characterData") textKnoten(m.target);
        else if (m.type === "attributes") attribute(m.target);
        else for (const n of m.addedNodes) uebersetzeBaum(n);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["title", "placeholder", "aria-label"] });
    const titel = () => { const n = tr(document.title); if (n !== document.title) document.title = n; };
    titel(); new MutationObserver(titel).observe(document.querySelector("title"), { childList: true });
  };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
}
