"""Die Befehle von RoboForge Harness als Skills. Dieselbe Liste nutzen Fernzugriff und spaeter ein Agent.

Regeln:
  - Lesen, Training und Modellwahl duerfen auch von aussen (remote) kommen.
  - Alles, was einen Arm BEWEGT, braucht eine Freigabe vor Ort (Dialog im Harness). Von aussen und vom
    Agenten ist das vorerst gesperrt; 'arm.ablegen' (Stop) ist immer erlaubt, weil es sicherer macht.
  - Befehle, die die Oberflaeche aendern, laufen ueber lab.on_ui() im Fenster-Thread.
"""
import base64, os, sys
from . import MODELS, episodes, jobs, methods
from .skills import Registry


def build(lab):
    reg = Registry()
    def move_allowed(skill, args, source):
        if source == "lokal":
            return True                     # Oberflaeche: der Dialog dort ist die Freigabe
        if source in ("modul", "agent"):    # Module duerfen nur in einer vor Ort freigegebenen Sitzung bewegen
            ok = getattr(lab, "session_ok", None)
            return bool(ok and ok(args.get("arm")))
        return False                        # Internet: keine Bewegung
    reg.move_allowed = move_allowed
    arm_param = {"arm": {"type": "string", "description": "Arm-Schluessel, z. B. follower oder follower2",
                         "enum": list(lab.panels)}}

    def panel(arm):
        if arm not in lab.panels:
            raise ValueError(f"Unbekannter Arm {arm!r}")
        return lab.panels[arm]

    @reg.skill("methoden.liste", "Verfuegbare Lernverfahren (z. B. ACT, SmolVLA) mit Beschreibung.")
    def methoden():
        return [m.info() for m in methods.all_methods()]

    @reg.skill("datensaetze.liste", "Aufgenommene Datensaetze mit Aufgabe, Arm und Episodenzahl.")
    def datensaetze():
        return [{"name": d.name, "task": d.meta.get("task"), "arm": d.meta.get("arm"),
                 "episodes": len(d.episodes()), "frames": d.frames()} for d in episodes.datasets()]

    @reg.skill("modelle.liste", "Fertig trainierte Modelle.")
    def modelle():
        return [{k: m.get(k) for k in ("name", "method", "task", "arm", "dataset", "created")} for m in jobs.models()]

    @reg.skill("training.start", "Startet ein Training (laeuft im Hintergrund auf der Grafikkarte).",
               {"datensatz": {"type": "string"}, "methode": {"type": "string", "enum": [m.key for m in methods.all_methods()]},
                "schritte": {"type": "integer", "description": "optional, sonst Standard der Methode"},
                "leise": {"type": "boolean", "description": "Grafikkarte drosseln: leiser, dauert etwa doppelt so lange"},
                "bildvariation": {"type": "boolean", "description": "Bilder beim Lernen zufaellig heller/dunkler, "
                                  "kontrastaermer usw.: robuster gegen Licht und Schatten"},
                "kameras": {"type": "array", "items": {"type": "string"}, "description": "optional: nur diese Kameras (z. B. ['wrist'])"},
                "filter": {"type": "object", "description": "optional: split train|test|alle, befehle alle|allgemein|spezifisch"},
                "export": {"type": "string", "enum": ["griff_alle", "griff_allgemein"]}},
               ["datensatz", "methode"])
    def training_start(datensatz, methode, schritte=None, leise=False, bildvariation=False, kameras=None, filter=None,
                       export=None):
        # laeuft schon ein Training, wird dieses hinten angehaengt und startet direkt danach.
        # Das Training laeuft im eigenen Trainings-Dienst: Harness-Neustart bricht es nicht ab.
        return queue().add(datensatz, methode, schritte, quiet=bool(leise), augment=bool(bildvariation),
                           cameras=kameras, filters=filter, export=export).info()

    def queue():
        if lab.ki_queue is None:
            lab.ki_queue = jobs.DetachedQueue()
        return lab.ki_queue

    @reg.skill("datensatz.zusammenstellen", "Neuer Datensatz aus ausgewaehlten Episoden (Kopien; Quellen bleiben).",
               {"name": {"type": "string"}, "aufgabe": {"type": "string"},
                "episoden": {"type": "array", "items": {"type": "string"}, "description": "je 'datensatz/ep_0007'"},
                "eigene_aufgaben": {"type": "boolean", "description": "jede Episode behaelt ihren Aufgabentext "
                                    "(mehrere Aufgaben fuer SmolVLA)"}},
               ["name", "aufgabe", "episoden"])
    def datensatz_zusammenstellen(name, aufgabe, episoden, eigene_aufgaben=False):
        ds = episodes.compose(name, aufgabe, [tuple(e.split("/", 1)) for e in episoden],
                              eigene_aufgaben=bool(eigene_aufgaben))
        return {"name": ds.name, "episodes": len(ds.episodes())}

    @reg.skill("training.status", "Zustand aller Trainings (Schritt, Fehlerwert, Restzeit).")
    def training_status():
        return queue().snapshot()           # auch Trainings, die vor einem Harness-Neustart begonnen haben

    @reg.skill("training.abbrechen", "Bricht ein laufendes oder wartendes Training ab.", {"name": {"type": "string"}}, ["name"])
    def training_abbrechen(name):
        return {"abgebrochen": bool(queue().cancel(name))}

    @reg.skill("training.weiter", "Setzt ein abgebrochenes/unterbrochenes Training beim letzten Zwischenstand fort.",
               {"name": {"type": "string"}}, ["name"])
    def training_weiter(name):
        return queue().resume(name)

    @reg.skill("training.pausieren", "Haelt ein Training an (an=true) oder setzt es fort (an=false).",
               {"name": {"type": "string"}, "an": {"type": "boolean"}}, ["name"])
    def training_pausieren(name, an=True):
        return {"pausiert": bool(an), "ok": queue().pause(name, bool(an))}

    @reg.skill("arm.status", "Zustand eines Arms: laeuft er, Quelle, Statuszeile, zugewiesenes Modell.", arm_param, ["arm"])
    def arm_status(arm):
        p = panel(arm)
        return {"label": p.label, "running": p.running, "mode": p.mode if p.running else None,
                "source": p.source.get(), "status": p.status.get(),
                "ki_model": os.path.basename(p.ki_model) if p.ki_model else None, "ki_task": p.ki_task}

    @reg.skill("ki.modell_waehlen", "Weist einem Arm ein trainiertes Modell (und optional den Aufgabentext) zu. Bewegt nichts.",
               {**arm_param, "modell": {"type": "string"}, "aufgabe": {"type": "string"}}, ["arm", "modell"])
    def modell_waehlen(arm, modell, aufgabe=None):
        p = panel(arm)
        meta = next((m for m in jobs.models() if m["name"] == modell), None)
        if meta is None:
            raise ValueError(f"Modell {modell!r} nicht gefunden")
        def apply():
            p.ki_model = os.path.join(MODELS, modell)
            p.ki_task = aufgabe or meta.get("task") or ""
            lab.update_buttons()
        lab.on_ui(apply)
        return {"arm": arm, "modell": modell, "aufgabe": aufgabe or meta.get("task")}

    @reg.skill("ki.starten", "Laesst das zugewiesene Modell den Arm steuern (langsam).", arm_param, ["arm"], moves=True)
    def ki_starten(arm):
        lab.on_ui(lambda: lab.take_ki(arm))      # zeigt den Freigabe-Dialog vor Ort
        return {"angefragt": True}

    @reg.skill("notablage", "NOT-ABLAGE: alle laufenden Arme sofort stoppen, Greifer oeffnen, ablegen. Immer erlaubt.")
    def notablage():
        lab.on_ui(lab.emergency_all)
        return {"not_ablage_angefordert": True}

    @reg.skill("arm.ablegen", "Stop: Arm legt sich kontrolliert ab. Immer erlaubt.", arm_param, ["arm"])
    def ablegen(arm):
        panel(arm)
        lab.on_ui(lambda: lab.stop(arm))
        return {"stop_angefordert": True}

    @reg.skill("kamera.bild", "Aktuelles Kamerabild eines Arms als JPEG (Base64), klein (breite: 160-1280, Standard 480).",
               {**arm_param, "kamera": {"type": "string", "description": "z. B. arm oder turm"},
                "breite": {"type": "integer"}}, ["arm", "kamera"])
    def kamera_bild(arm, kamera, breite=480):
        frames = lab.arm_frames(arm)
        img = frames.get(kamera)
        if img is None:
            raise ValueError(f"Kein aktuelles Bild von {kamera!r} (vorhanden: {list(frames)})")
        cv2 = lab.cams.cameras.cv2
        b = max(160, min(1280, int(breite)))
        h = int(img.shape[0] * b / img.shape[1])
        ok, jpg = cv2.imencode(".jpg", cv2.resize(img, (b, h)), [cv2.IMWRITE_JPEG_QUALITY, 80])
        return {"jpeg_base64": base64.b64encode(jpg.tobytes()).decode()}

    def platz_kamera(platz):
        platz = int(platz)
        slots = lab.cams.manager.slots
        if not 0 <= platz < len(slots):
            raise ValueError(f"Kamera-Platz 0..{len(slots) - 1}")
        _, cam = lab.cams.manager.status(platz)
        return platz, cam

    @reg.skill("kamera.plaetze", "Alle Kamera-Plaetze mit Name, Zustand und welchem Arm sie gehoeren (auch freie, z. B. OAK-D Lite).")
    def kamera_plaetze():
        arm_von = {s: k for k, p in lab.panels.items() for s in p.slots}
        out = []
        for i, s in enumerate(lab.cams.manager.slots):
            text, cam = lab.cams.manager.status(i)
            out.append({"platz": i, "name": s["name"], "zustand": text, "arm": arm_von.get(i),
                        "oak": str(s.get("device", "")).upper().startswith("OAK"),
                        "tiefe": hasattr(cam, "latest_depth")})
        return out

    @reg.skill("kamera.platz_bild", "Aktuelles Bild eines Kamera-Platzes (0-3) als JPEG (Base64), auch fuer freie Kameras.",
               {"platz": {"type": "integer"}, "breite": {"type": "integer"}}, ["platz"])
    def kamera_platz_bild(platz, breite=640):
        import time as _t
        platz, cam = platz_kamera(platz)
        img, t = cam.latest() if cam is not None else (None, None)
        if img is None or t is None or _t.monotonic() - t > 1.0:
            raise ValueError(f"Kein aktuelles Bild von Platz {platz}")
        cv2 = lab.cams.cameras.cv2
        b = max(160, min(1280, int(breite)))
        ok, jpg = cv2.imencode(".jpg", cv2.resize(img, (b, int(img.shape[0] * b / img.shape[1]))),
                               [cv2.IMWRITE_JPEG_QUALITY, 80])
        return {"jpeg_base64": base64.b64encode(jpg.tobytes()).decode()}

    @reg.skill("kamera.tiefe", "OAK-D Lite: Entfernung in mm an einer Bildstelle (x, y als Anteil 0..1, Standard Mitte) "
               "und optional ein eingefaerbtes Tiefenbild (bild=true).",
               {"platz": {"type": "integer"}, "x": {"type": "number"}, "y": {"type": "number"},
                "bild": {"type": "boolean"}}, ["platz"])
    def kamera_tiefe(platz, x=0.5, y=0.5, bild=False):
        platz, cam = platz_kamera(platz)
        if not hasattr(cam, "latest_depth"):
            raise ValueError("Dieser Platz hat keine Tiefenkamera (OAK-D Lite)")
        d = cam.latest_depth()
        if d is None:
            raise ValueError("Noch kein Tiefenbild")
        h, w = d.shape[:2]
        px, py = min(w - 1, max(0, int(x * w))), min(h - 1, max(0, int(y * h)))
        feld = d[max(0, py - 3):py + 4, max(0, px - 3):px + 4]
        werte = feld[feld > 0]
        out = {"mm": int(sorted(werte.tolist())[len(werte) // 2]) if len(werte) else None, "x": px, "y": py}
        if bild:
            cv2 = lab.cams.cameras.cv2
            norm = cv2.convertScaleAbs(d, alpha=255.0 / 2000.0)        # 0-2 m auf 0-255
            farbe = cv2.applyColorMap(norm, cv2.COLORMAP_INFERNO)
            ok, jpg = cv2.imencode(".jpg", farbe, [cv2.IMWRITE_JPEG_QUALITY, 80])
            out["jpeg_base64"] = base64.b64encode(jpg.tobytes()).decode()
        return out

    @reg.skill("video.status", "Laeuft das Video-Streaming ins Internet? Mit Kamera-Namen und Datenrate.")
    def video_status():
        st = getattr(lab, "streamer", None)
        return st.summary() if st is not None else {"state": "aus"}

    @reg.skill("video.starten", "Startet das Video-Streaming der Kameras ins Internet (LiveKit). Bewegt nichts.")
    def video_starten():
        st = getattr(lab, "streamer", None)
        if st is None or not st.running:
            lab.on_ui(lab.toggle_stream)
        return {"angefragt": True}

    @reg.skill("video.stoppen", "Stoppt das Video-Streaming ins Internet.")
    def video_stoppen():
        st = getattr(lab, "streamer", None)
        if st is not None and st.running:
            lab.on_ui(lab.toggle_stream)
        return {"angefragt": True}

    @reg.skill("harness.info", "Aus welchem Ordner laeuft dieser Harness? (Damit eine Oberflaeche nur ihren eigenen Harness steuert.)")
    def harness_info():
        return {"ordner": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}

    @reg.skill("arme.liste", "Alle Arme mit Anzeigename, Kameras, Zustand und Arbeitssitzung.")
    def arme():
        out = []
        for key, p in lab.panels.items():
            cams = [lab.cam_key(s) for s in p.slots] if hasattr(lab, "cam_key") else []
            sess = getattr(lab, "sessions", {}).get(key)
            out.append({"arm": key, "label": p.label, "kameras": cams, "running": p.running,
                        "status": p.status.get(), "sitzung": sess.info() if sess else None,
                        "ki_model": os.path.basename(p.ki_model) if p.ki_model else None})
        return out

    @reg.skill("sitzung.anfragen", "Bittet vor Ort um Freigabe, dass ein Modul den Arm bewegen darf. Der Arm faehrt "
               "dann hoch und haelt. Ergebnis mit sitzung.status pruefen.",
               {**arm_param, "modul": {"type": "string"}}, ["arm"])
    def sitzung_anfragen(arm, modul="Modul"):
        panel(arm)
        lab.on_ui(lambda: lab.session_request(arm, modul))
        return {"angefragt": True}

    @reg.skill("sitzung.hinweis", "Text des Freigabe-Hinweises (fuer Module, die die Zustimmung selbst vor Ort "
               "abfragen, z. B. der Orchestrator). Bewegt nichts.", {**arm_param, "modul": {"type": "string"}}, ["arm"])
    def sitzung_hinweis(arm, modul="Modul"):
        panel(arm)
        return {"titel": "Arbeitssitzung freigeben", "text": lab.session_text(arm, modul)}

    @reg.skill("sitzung.freigeben", "Startet die Arbeitssitzung, nachdem der Mensch VOR ORT im lokalen Modul "
               "zugestimmt hat (zustimmung=true). Nur lokal, nie aus dem Internet.",
               {**arm_param, "modul": {"type": "string"}, "zustimmung": {"type": "boolean"}}, ["arm", "zustimmung"],
               remote_ok=False, agent_ok=False)
    def sitzung_freigeben(arm, zustimmung, modul="Modul"):
        panel(arm)
        if zustimmung is not True:
            raise PermissionError("Ohne Zustimmung vor Ort keine Arbeitssitzung")
        lab.on_ui(lambda: lab.session_open(arm, modul))
        return {"freigegeben": True}

    @reg.skill("sitzung.status","Ist eine Arbeitssitzung auf dem Arm freigegeben und bereit?", arm_param, ["arm"])
    def sitzung_status(arm):
        p = panel(arm)
        s = lab.sessions.get(arm)
        return {"freigegeben": bool(s and not s.halt.is_set()),
                "bereit": bool(s and not s.halt.is_set() and p.status.get().startswith("ARBEITSSITZUNG")),
                "status": p.status.get(), **(s.info() if s else {})}

    @reg.skill("sitzung.beenden", "Beendet die Arbeitssitzung: der Arm legt sich ab.", arm_param, ["arm"])
    def sitzung_beenden(arm):
        panel(arm)
        lab.on_ui(lambda: lab.stop(arm))
        return {"stop_angefordert": True}

    # --- Grund-Skills: Posen und Greifer (fest programmiert, langsam, mit Hoehenmodell geprueft) ---
    from . import poses as P

    def state_of(arm):
        st = lab.arm_state(arm)
        if st is None:
            raise RuntimeError("Keine aktuelle Stellung: der Arm muss laufen (z. B. in einer Arbeitssitzung)")
        return st

    @reg.skill("arm.stellung", "Aktuelle Gelenkstellung [j1..j6] in Servo-Schritten (Mitte 2047).", arm_param, ["arm"])
    def arm_stellung(arm):
        panel(arm)
        return {"stellung": state_of(arm)}

    @reg.skill("pose.liste", "Gemerkte Posen (benannte Orte) eines Arms.", arm_param, ["arm"])
    def pose_liste(arm):
        panel(arm)
        return {k: v for k, v in P.load().get(arm, {}).items() if not k.startswith("_")}

    @reg.skill("pose.merken", "Merkt die aktuelle Stellung des Arms unter einem Namen (z. B. 'ueber_kiste').",
               {**arm_param, "name": {"type": "string"}}, ["arm", "name"], remote_ok=False)
    def pose_merken(arm, name):
        panel(arm)
        if not name or name.startswith("_"):
            raise ValueError("Name darf nicht leer sein oder mit _ beginnen")
        return {"name": name, "stellung": P.save_pose(arm, name, state_of(arm))}

    @reg.skill("pose.anfahren", "Faehrt langsam zu einer gemerkten Pose (alle Gelenke gleichzeitig; der Greifer "
               "bleibt, wie er ist). Der Weg wird vorher mit dem Hoehenmodell geprueft.",
               {**arm_param, "name": {"type": "string"},
                "grad_pro_s": {"type": "number", "minimum": 5, "maximum": 60, "description": "Standard 30"}},
               ["arm", "name"], moves=True, remote_ok=False)
    def pose_anfahren(arm, name, grad_pro_s=30):
        panel(arm)
        s = lab.ready_session(arm)
        target = P.get_pose(arm, name)
        start = s.hold or state_of(arm)
        target = list(target[:5]) + [start[5]]
        ok, why = P.check_path(start, target)
        if not ok:
            raise RuntimeError(f"Fahrt zu {name!r} abgelehnt: {why}")
        reached, st = s.move_to(target, P.steps_per_tick(min(60.0, float(grad_pro_s))), joints=[0, 1, 2, 3, 4])
        return {"erreicht": reached, "pose": name, "ist": st, "weg": why}

    @reg.skill("greifer.merken", "Merkt die aktuelle Greiferstellung als 'auf' oder 'zu' (einmal pro Arm einrichten).",
               {**arm_param, "zustand": {"type": "string", "enum": ["auf", "zu"]}}, ["arm", "zustand"], remote_ok=False)
    def greifer_merken(arm, zustand):
        panel(arm)
        return {"zustand": zustand, "wert": P.save_pose(arm, "_greifer_" + zustand, state_of(arm))[5]}

    def gripper_range(arm):
        try:
            return P.get_pose(arm, "_greifer_zu")[5], P.get_pose(arm, "_greifer_auf")[5]
        except KeyError:
            raise RuntimeError("Greifer noch nicht eingerichtet: einmal greifer.merken mit 'auf' und 'zu'") from None

    @reg.skill("greifer.setzen", "Oeffnet oder schliesst den Greifer: 0 = zu, 100 = ganz auf.",
               {**arm_param, "prozent": {"type": "number", "minimum": 0, "maximum": 100}}, ["arm", "prozent"],
               moves=True, remote_ok=False)
    def greifer_setzen(arm, prozent):
        panel(arm)
        s = lab.ready_session(arm)
        zu, auf = gripper_range(arm)
        value = int(zu + (auf - zu) * float(prozent) / 100)
        target = list(s.hold or state_of(arm))
        target[5] = value
        reached, st = s.move_to(target, 40, joints=[5], tol=10 ** 6)
        return {"ziel": value, "ist": st[5], "prozent": prozent}

    @reg.skill("greifer.pruefen", "Haelt der Greifer etwas? Schliesst er auf 'zu' und bleibt trotzdem deutlich offen, "
               "steckt ein Teil darin. Zuverlaessig und ohne Kamera.", arm_param, ["arm"])
    def greifer_pruefen(arm):
        panel(arm)
        zu, auf = gripper_range(arm)
        st = state_of(arm)
        s = lab.sessions.get(arm)
        closing = s is not None and s.hold is not None and abs(s.hold[5] - zu) <= 30
        gap = abs(st[5] - zu)
        return {"haelt_etwas": bool(closing and gap > 40), "greifer_geschlossen_befohlen": closing,
                "abstand_zu_zu_grad": round(gap * 360 / 4096, 1),
                "hinweis": None if closing else "Greifer ist nicht auf 'zu' befohlen; erst greifer.setzen mit 0"}

    @reg.skill("modell.vorladen", "Laedt ein gelerntes Modell schon im Hintergrund (dauert 10-30 s), damit "
               "modell.ausfuehren danach sofort startet. Bewegt nichts.",
               {**arm_param, "modell": {"type": "string"}, "aufgabe": {"type": "string"}}, ["arm", "modell"],
               remote_ok=False)
    def modell_vorladen(arm, modell, aufgabe=None):
        panel(arm)
        return lab.preload_model(arm, modell, aufgabe or None)

    @reg.skill("modell.ausfuehren", "Laesst eine gelernte Faehigkeit (trainiertes Modell) eine Zeit lang den Arm "
               "steuern; danach haelt der Arm. Braucht eine freigegebene Arbeitssitzung.",
               {**arm_param, "modell": {"type": "string"}, "sekunden": {"type": "number", "minimum": 1, "maximum": 120},
                "aufgabe": {"type": "string", "description": "optional: Aufgabentext (SmolVLA)"}},
               ["arm", "modell", "sekunden"], moves=True, remote_ok=False)
    def modell_ausfuehren(arm, modell, sekunden, aufgabe=None):
        panel(arm)
        return lab.session_run_model(arm, modell, float(sekunden), aufgabe)

    # --- Agentic Robotics: Mess-Werkzeuge, kleine Korrekturen, Kontakt (siehe AGENTIC.md) ---
    from regel import kartesisch, werkzeuge
    from vision.kalib import Kalibrierung

    def frame(arm, kamera):
        img = lab.arm_frames(arm).get(kamera)
        if img is None:
            raise ValueError(f"Kein aktuelles Bild von {kamera!r}")
        return img

    @reg.skill("vision.messen", "Misst mit der Kamera (ohne Sprachmodell): runde Oeffnung, ArUco-Marker oder Kreis. "
               "Gibt Abstand in mm und - wenn die Handgelenk-Kamera kalibriert ist - die Korrektur dx/dy in mm, die "
               "das Merkmal unter die Werkzeugspitze bringt; dazu ein Messbild mit eingezeichneter Messung.",
               {**arm_param, "kamera": {"type": "string", "description": "Standard arm (Handgelenk)"},
                "ziel": {"type": "string", "enum": list(werkzeuge.ZIELE)},
                "groesse_mm": {"type": "number", "description": "Kantenlaenge des Markers, Standard 20"},
                "marker_id": {"type": "integer"}}, ["arm"])
    def vision_messen(arm, kamera="arm", ziel="oeffnung", groesse_mm=20.0, marker_id=None):
        panel(arm)
        r = werkzeuge.messen(frame(arm, kamera), ziel, Kalibrierung.laden(arm), groesse_mm, marker_id, name=f"{arm}-{ziel}")
        from vision.zeichnen import jpeg_base64
        r["messbild_jpeg_base64"] = jpeg_base64(r.pop("_bild"))
        return r

    @reg.skill("vision.werkzeugpunkt_merken", "Einmal vor Ort: Stiftspitze genau auf die Markermitte setzen, auf "
               "Schwebehoehe anheben, dann aufrufen - die Markermitte im Bild wird der Werkzeugpunkt.",
               {**arm_param, "groesse_mm": {"type": "number"}}, ["arm"], remote_ok=False)
    def werkzeugpunkt_merken(arm, groesse_mm=20.0):
        panel(arm)
        r = werkzeuge.messen(frame(arm, "arm"), "marker", None, groesse_mm, name=f"{arm}-werkzeugpunkt")
        if not r["gefunden"]:
            raise RuntimeError("Kein Marker im Bild der Handgelenk-Kamera")
        k = Kalibrierung.laden(arm) or Kalibrierung([[1, 0], [0, 1]], r["merkmal_px"])
        k.werkzeugpunkt, k.mm_pro_px = r["merkmal_px"], r["mm_pro_px"]
        return {"werkzeugpunkt": k.werkzeugpunkt, "datei": k.speichern(arm)}

    def korrigiere(arm, dx_mm=0.0, dy_mm=0.0, dz_mm=0.0):
        s = lab.ready_session(arm)
        start = s.hold or state_of(arm)
        neu, sp = kartesisch.korrektur([int(v) for v in start], dx_mm, dy_mm, dz_mm)
        reached, st = s.move_to(neu, 2, joints=[0, 1, 2, 3, 4], tol=10 ** 6, settle=0.3)
        ist = kartesisch.spitze(st)
        return {"spitze_soll_mm": [round(v * 1000, 1) for v in sp[:3]],
                "spitze_ist_mm": [round(v * 1000, 1) for v in ist[:3]]}

    @reg.skill("arm.korrektur", "Kleine kartesische Korrektur der Werkzeugspitze in mm (hoechstens 5 mm je Achse und "
               "Aufruf, langsam; Handneigung, Rolle und Greifer bleiben). Fuer Feinarbeit in einer Mess-Schleife.",
               {**arm_param, "dx_mm": {"type": "number", "minimum": -5, "maximum": 5},
                "dy_mm": {"type": "number", "minimum": -5, "maximum": 5},
                "dz_mm": {"type": "number", "minimum": -5, "maximum": 5}}, ["arm"], moves=True, remote_ok=False)
    def arm_korrektur(arm, dx_mm=0.0, dy_mm=0.0, dz_mm=0.0):
        panel(arm)
        lab.kontakt_melder(arm)
        return korrigiere(arm, float(dx_mm), float(dy_mm), float(dz_mm))

    @reg.skill("vision.kalibrieren", "Kalibriert die Handgelenk-Kamera am Marker mit zwei kleinen Testbewegungen "
               "(Pixel -> mm -> Bewegung). Braucht einen gemerkten Werkzeugpunkt (vision.werkzeugpunkt_merken).",
               {**arm_param, "schritt_mm": {"type": "number", "minimum": 1, "maximum": 5},
                "groesse_mm": {"type": "number"}}, ["arm"], moves=True, remote_ok=False)
    def vision_kalibrieren(arm, schritt_mm=3.0, groesse_mm=20.0):
        panel(arm)
        alt = Kalibrierung.laden(arm)
        if alt is None:
            raise RuntimeError("Erst vor Ort vision.werkzeugpunkt_merken ausfuehren")
        import time as _t
        def messe():
            _t.sleep(0.4)                  # frisches Bild nach der Bewegung
            r = werkzeuge.messen(frame(arm, "arm"), "marker", None, groesse_mm, name=f"{arm}-kalib")
            if not r["gefunden"]:
                raise RuntimeError("Marker nicht im Bild")
            return r["merkmal_px"], r["mm_pro_px"]
        k = werkzeuge.kalibrieren(messe, lambda dx, dy: korrigiere(arm, dx, dy, 0.0), float(schritt_mm), alt.werkzeugpunkt)
        k.speichern(arm)
        return k.to_dict()

    @reg.skill("arm.kontakt", "Kontakt ohne Kraftsensor (aus Servo-Soll/Ist und Last): zustand frei/beruehrt, "
               "Hoehenfehler in mm, Lasten und neue Ereignisse (angestossen, abgesackt, frei) seit dem letzten Aufruf.",
               arm_param, ["arm"])
    def arm_kontakt(arm):
        panel(arm)
        return lab.kontakt_melder(arm).abholen()

    # --- Anflug: Karton finden (Uebersichtskamera + Basis-Marker), darueber fahren, mit der Maske ausrichten ---
    from aufnahme import anflug as AF
    from vision import karton as KA

    def anflug_modell(arm):
        m = AF.laden(arm)
        if m is None:
            raise RuntimeError("Noch keine Anflug-Formel: einmal anflug.lernen mit dem Datensatz ausfuehren")
        return m

    def klemme(target):
        import remote_kin
        out = list(target)
        for i in range(5):
            lo, hi = remote_kin.LIMITS.get(i + 1, (0, 4095))
            if i != 4:
                out[i] = int(max(lo + 5, min(hi - 5, out[i])))
        return out

    def fahre(arm, target, grad_pro_s, min_s=0.6):
        """Eine fluessige Fahrt (alle Gelenke gleichzeitig, weich), vorher mit dem Hoehenmodell geprueft."""
        s = lab.ready_session(arm)
        start = list(s.hold or state_of(arm))
        target = klemme(target)
        ok, why = P.check_path(start, list(target[:5]) + [start[5]])
        if not ok:
            raise RuntimeError(f"Fahrt abgelehnt: {why}")
        grad = max(abs(a - b) for a, b in zip(start[:5], target[:5])) * 360 / 4096
        return s.move_smooth(target, max(min_s, grad / float(grad_pro_s)), joints=[0, 1, 2, 3, 4])

    HOCH = 2047          # Schulter/Ellbogen/Handgelenk in Mittelstellung: Arm aufrecht, tiefster Punkt ~22 cm
    SCHAU = (2047, 1100, 2047)   # "Kerze": Unterarm senkrecht nach oben - verdeckt weder Karton noch Marker

    def fahre_hoch(arm, target, grad_pro_s):
        """Weite Fahrt durch die Luft: erst aufrichten, oben zur Zielrichtung drehen, dann von oben ans Ziel.
        So streift der Arm unterwegs nie den Tisch oder den Karton."""
        s = lab.ready_session(arm)
        ist = list(s.hold or state_of(arm))
        wege = [[ist[0], HOCH, HOCH, HOCH, ist[4], ist[5]],
                [target[0], HOCH, HOCH, HOCH, target[4], ist[5]],
                list(target[:5]) + [ist[5]]]
        st = ist
        for w in wege:
            if max(abs(a - b) for a, b in zip(st[:5], w[:5])) < 15:
                continue                              # schon dort
            reached, st = fahre(arm, w, grad_pro_s)
            if not reached:
                return False, st
        return True, st

    @reg.skill("anflug.lernen", "Bestimmt aus aufgenommenen Episoden (Soll-Platzierung + Startstellung) die Formel "
               "Kartonposition -> Startstellung ueber dem Karton und die Masken-Zielwerte. Bewegt nichts.",
               {**arm_param, "datensaetze": {"type": "array", "items": {"type": "string"}}}, ["arm", "datensaetze"])
    def anflug_lernen(arm, datensaetze):
        from . import DATASETS
        m = AF.lerne([os.path.join(DATASETS, d) for d in datensaetze], arm)
        return {k: m[k] for k in ("episoden", "rest_ticks", "maske_ziel", "quellen")}

    kamlage = {}            # zuletzt gesehene Lage der Turmkamera je Arm (gilt, solange der Turm stillsteht)

    def karton_suchen(arm, img=None, pose="jetzt"):
        """Karton im Turmbild suchen. Ist der Basis-Marker verdeckt (z. B. vom eingeklappten Arm), gilt die zuletzt
        gesehene Kameralage. Was der Arm selbst verdeckt, wird aus dem 3D-Modell ausgeblendet."""
        cfg = KA.laden(arm)
        img = frame(arm, "turm") if img is None else img
        lage = KA.kamera_lage(img, cfg)
        if lage:
            kamlage[arm] = lage
        if pose == "jetzt":
            pose = lab.arm_state(arm)
        r = KA.finden(img, cfg, lage=kamlage.get(arm), pose=pose)
        r.pop("lage", None)
        try:                                            # Rohbild merken: zum Nachpruefen und Einstellen
            import time as _t
            from ki import DATA
            d = os.path.join(DATA, "karton_bilder")
            os.makedirs(d, exist_ok=True)
            lab.cams.cameras.cv2.imwrite(os.path.join(d, _t.strftime("%Y%m%d-%H%M%S") + ".jpg"), img)
        except Exception:
            pass
        from vision.zeichnen import jpeg_base64
        r["messbild_jpeg_base64"] = jpeg_base64(KA.messbild(img, r, cfg, lage=kamlage.get(arm)))
        r["_bild"], r["_pose"] = img, pose
        return r

    def ohne_intern(r):
        return {k: v for k, v in r.items() if not k.startswith("_")}

    @reg.skill("karton.finden", "Sucht den Karton in der Uebersichtskamera (Turm) ueber den Marker auf der Roboterbasis. "
               "Gibt die Platzierung (x, y in cm, winkel in Grad, wie auf der Karte) und ein Messbild. Bewegt nichts. "
               "Der Arm sollte dabei abgelegt sein (verdeckt sonst den Karton).", arm_param, ["arm"])
    def karton_finden(arm):
        panel(arm)
        return ohne_intern(karton_suchen(arm))

    @reg.skill("kamera.kalibrieren", "Kalibriert eine Kamera (Bildwinkel, Weitwinkel-Verzerrung) mit dem gedruckten "
               "Schachbrett (vision/druck/schachbrett.pdf): waehrend der Laufzeit das Brett langsam vor der Kamera "
               "bewegen - schraeg, nah, fern, in alle Bildecken. Bewegt den Arm nicht.",
               {**arm_param, "kamera": {"type": "string", "description": "Standard turm"},
                "sekunden": {"type": "number", "minimum": 10, "maximum": 100}}, ["arm"], remote_ok=False)
    def kamera_kalibrieren(arm, kamera="turm", sekunden=45):
        panel(arm)
        from vision import kamerakalib as KK
        cv2 = lab.cams.cameras.cv2
        gesammelt, groesse = KK.sammeln(lambda: lab.arm_frames(arm).get(kamera), cv2, float(sekunden))
        if len(gesammelt) < 8:
            return {"ok": False, "bilder": len(gesammelt),
                    "grund": "Zu wenige Schachbrett-Bilder (mindestens 8) - Brett ganz ins Bild, langsamer bewegen"}
        daten = KK.rechnen(gesammelt, groesse, cv2)
        KK.speichern(arm, kamera, daten)
        return {"ok": True, **{k: daten[k] for k in ("bilder", "fehler_px", "hfov")}}

    @reg.skill("karton.einmessen", "Einmal vor Ort, wenn der Marker neu klebt: Karton genau an eine bekannte Stelle "
               "legen (z. B. Testplatzierung T1 von der Karte), dann aufrufen. Bestimmt Bildwinkel der Kamera und "
               "Lage des Markers und speichert sie.",
               {**arm_param, "x": {"type": "number"}, "y": {"type": "number"}, "winkel": {"type": "number"}},
               ["arm", "x", "y", "winkel"], remote_ok=False)
    def karton_einmessen(arm, x, y, winkel):
        panel(arm)
        import time as _t
        cfg, guete, mid = KA.einmessen(frame(arm, "turm"), {"x": float(x), "y": float(y), "winkel": float(winkel)},
                                       KA.laden(arm))
        cfg["eingemessen_am"] = _t.strftime("%Y-%m-%d %H:%M:%S")
        cfg["eingemessen_mit"] = {"x": x, "y": y, "winkel": winkel, "marker": mid}
        KA.speichern(cfg, arm)
        return {"marker": mid, "hfov": cfg["hfov"], "marker_lage": cfg["marker"][str(mid)], "guete": guete}

    @reg.skill("karton.anfahren", "Faehrt den Arm langsam in die Startstellung ueber dem Karton (wie in den Aufnahmen) "
               "und schliesst den Greifer. Ohne x/y/winkel wird der Karton vorher mit karton.finden gesucht.",
               {**arm_param, "x": {"type": "number"}, "y": {"type": "number"}, "winkel": {"type": "number"},
                "grad_pro_s": {"type": "number", "minimum": 5, "maximum": 45}}, ["arm"], moves=True, remote_ok=False)
    def karton_anfahren(arm, x=None, y=None, winkel=None, grad_pro_s=30):
        panel(arm)
        m = anflug_modell(arm)
        if x is None or y is None or winkel is None:
            r = erst = karton_suchen(arm)           # zuerst schauen, solange der Arm eingeklappt ist
            if not r["gefunden"]:
                # Marker verdeckt oder Karton nicht sicher: Arm in die "Kerze" (aus dem Bild), dann nochmal schauen
                s = lab.ready_session(arm)
                ist = list(s.hold or state_of(arm))
                fahre(arm, [ist[0], *SCHAU, ist[4], ist[5]], grad_pro_s)
                import time as _t
                _t.sleep(0.6)
                r = karton_suchen(arm)
                if not r["gefunden"] and arm in kamlage:
                    # Kameralage jetzt bekannt: das erste Bild (Karton frei, Arm eingeklappt) nochmal auswerten
                    r2 = karton_suchen(arm, img=erst["_bild"], pose=erst["_pose"])
                    if r2["gefunden"]:
                        r = r2
            if not r["gefunden"]:
                r = ohne_intern(r)
                return {"ok": False, "grund": r.get("grund"), "messbild_jpeg_base64": r.get("messbild_jpeg_base64")}
            platz = r["platzierung"]
        else:
            platz = {"x": float(x), "y": float(y), "winkel": float(winkel)}
        ziel = AF.grobziel(m, platz)
        reached, st = fahre_hoch(arm, ziel, grad_pro_s)       # hoch, drehen, von oben ans Ziel
        if not reached:
            return {"ok": False, "platzierung": platz, "ziel": ziel, "ist": st,
                    "grund": "Arm ist unterwegs haengen geblieben oder nicht am Ziel angekommen (haelt dort)"}
        s = lab.ready_session(arm)
        s.move_to(list(s.hold or st)[:5] + [ziel[5]], 40, joints=[5], tol=10 ** 6)      # Greifer zu wie im Training
        return {"ok": bool(reached), "platzierung": platz, "ziel": ziel, "ist": st}

    @reg.skill("karton.ausrichten", "Feinausrichten mit der Handkamera: kleine Bewegungen (Basis, vor/zurueck, "
               "Handgelenk rollen), bis die Startmaske gruen ist und nahe an den Trainingswerten liegt. Danach kann "
               "das VLA starten. ok=false, wenn die Kartonkante nicht im Bild ist.",
               {**arm_param, "plan": {"type": "string", "description": "Aufnahmeplan mit den Maskenwerten, "
                                      "Standard kartongriffe"},
                "max_schritte": {"type": "integer", "minimum": 1, "maximum": 30}}, ["arm"], moves=True, remote_ok=False)
    def karton_ausrichten(arm, plan="kartongriffe", max_schritte=12):
        panel(arm)
        import time as _t
        import numpy as _np
        from aufnahme import maske as MS, plan as PL
        m = anflug_modell(arm)
        mcfg = PL.load_definition(plan).get("maske") or {}
        D = AF.richtungen(m)
        protokoll = []

        def messe():
            _t.sleep(0.5)                                   # frisches Bild nach der Bewegung
            res = MS.detect(frame(arm, "arm"), mcfg)
            return AF.fehler(res["werte"], m["maske_ziel"]), bool(res["ok"])

        def bewege(u):
            s = lab.ready_session(arm)
            ist = list(s.hold or state_of(arm))
            d = D @ _np.asarray(u, float)
            fahre(arm, [int(round(ist[i] + d[i])) for i in range(5)] + [ist[5]], 15, min_s=0.4)

        r = AF.ausrichten(messe, bewege, int(max_schritte), log=protokoll.append)
        r["protokoll"] = protokoll
        return r

    @reg.skill("zeit", "Uhrzeit des Harness in Sekunden (fuer Ablaufberichte).")
    def zeit():
        import time as _t
        return {"t": round(_t.monotonic(), 3)}

    @reg.skill("warte", "Wartet einige Sekunden (hoechstens 30).", {"sekunden": {"type": "number"}}, ["sekunden"])
    def warte(sekunden):
        import time as _t
        _t.sleep(min(30.0, float(sekunden)))
        return {}

    # --- Station (Physical AI Harness): Fenster und Dialoge im Harness oeffnen. Nur von diesem Rechner ---------
    STATION = ("leader", "ki", "steuermodus", "kalibrieren", "kameras", "spannung", "harness")

    @reg.skill("station.oeffnen", "Oeffnet im Harness-Fenster: leader (Leader uebernehmen, mit Freigabe-Dialog vor "
               "Ort), ki (zugewiesenes Modell fahren lassen, mit Freigabe-Dialog), steuermodus, kalibrieren, kameras, spannung oder harness (Fenster nach vorne). Die Bewegung "
               "startet erst, wenn der Mensch vor Ort im Dialog zustimmt.",
               {"was": {"type": "string", "enum": list(STATION)}, **arm_param}, ["was"],
               remote_ok=False, agent_ok=False)
    def station_oeffnen(was, arm=None):
        if was not in STATION:
            raise ValueError(f"Unbekannt: {was!r}")
        if was in ("leader", "ki", "steuermodus"):
            panel(arm or next(iter(lab.panels)))

        def harness():
            import sys
            mod = sys.modules.get("__main__")
            if not hasattr(mod, "ControlView"):       # Harness laeuft als ros.py (__main__) oder importiert
                import ros as mod
            return mod

        def run():
            try:
                if "--im-hintergrund" in sys.argv:    # Harness ohne Fenster: nichts hervorholen
                    raise RuntimeError
                lab.root.deiconify()
                lab.root.lift()
                lab.root.focus_force()
            except Exception:
                pass
            key = arm or next(iter(lab.panels))
            if was == "leader":
                lab.take_leader(key)             # fragt vor Ort: "Bist du vor Ort und stimmst zu?"
            elif was == "ki":
                lab.take_ki(key)                 # zeigt den Freigabe-Dialog vor Ort
            elif was == "steuermodus":
                harness().ControlView(lab, key)
            elif was == "kalibrieren":
                lab.open_calib()
            elif was == "kameras":
                harness().CameraWizard(lab)
            elif was == "spannung":
                lab.open_voltage()
        lab.on_ui(run)
        return {"angefragt": was, "hinweis": "Bitte im Harness-Fenster weitermachen."}

    # --- Weboberflaeche (Physical AI Harness): Station, Steuermodus, Fenster-Spiegel. Nur von diesem Rechner ---
    try:
        import webstation
        webstation.skills_anmelden(reg, lab)
    except Exception as exc:                     # Harness laeuft auch ohne Weboberflaeche
        print("Web-Station-Befehle nicht verfuegbar:", exc)

    return reg
