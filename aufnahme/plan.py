"""Aufnahmeplan: Definition laden, Plan anlegen (Platzierungen + Auftraege, fester Startwert), Fortschritt fuehren.

Die Bedienlogik kennt nur diese Klasse. Ein neuer kompatibler Plan = neue JSON-Datei in plaene/.

Fortschritt liegt in ki_daten/aufnahmeplaene/<plan-id>/plan.json. Er wird nach jeder Aenderung gespeichert.
"""
import copy, json, math, os, random, re, tempfile, time
from . import PLAENE, geometrie as G

FUELL = (("voll", 5, 99), ("mittel", 3, 4), ("wenig", 2, 2), ("letztes", 1, 1))   # hoechstens 2 je Sorte, also 6 Teile


def fuellstand(n):
    return next(name for name, lo, hi in FUELL if lo <= n <= hi)


def definitions(root=None):
    root = root or PLAENE
    out = []
    if os.path.isdir(root):
        for f in sorted(os.listdir(root)):
            if f.endswith(".json"):
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                out.append((d["id"], d["name"]))
    return out


def load_definition(plan_id, root=None):
    with open(os.path.join(root or PLAENE, plan_id + ".json"), encoding="utf-8") as f:
        return json.load(f)


def runs_root():
    from ki import DATA
    return os.path.join(DATA, "aufnahmeplaene")


# --- Plan anlegen -------------------------------------------------------------------------------
def make_orders(defn, rounds, seed):
    """Reihenfolge aller Teile jeder Runde + Befehlsart (allgemein/spezifisch). Reproduzierbar."""
    rng = random.Random(seed)
    usage = {}                          # (teil, fuellstand) -> Anzahl
    target = float(defn.get("spezifisch_anteil", 0.3))
    total = spec = 0
    last_seq = None
    out = []
    for r in rounds:
        counts = dict(defn["ladungen"][r["ladung"]])
        n = sum(counts.values())
        seq = None
        for _attempt in range(5):        # keine identische Reihenfolge wie die Runde davor
            c = dict(counts)
            cand = []
            for k in range(n):
                cls = fuellstand(n - k)
                parts = [p for p, v in c.items() if v > 0]
                parts.sort(key=lambda p: (usage.get((p, cls), 0), rng.random()))
                cand.append(parts[0])
                c[parts[0]] -= 1
            if cand != last_seq:
                seq = cand
                break
        seq = seq or cand
        last_seq = seq
        c = dict(counts)
        orders = []
        for k, part in enumerate(seq):
            cls = fuellstand(n - k)
            usage[(part, cls)] = usage.get((part, cls), 0) + 1
            eligible = c[part] >= 2
            art = "allgemein"
            if eligible and (total == 0 or spec / max(1, total) < target) and rng.random() < 0.85:
                art = "spezifisch"
            total += 1
            spec += art == "spezifisch"
            orders.append({"teil": part, "art": art, "status": "offen"})
            c[part] -= 1
        out.append(orders)
    return out


def light_phase(defn, runde):
    """Lichtphase einer Runde (Plan-Feld 'licht': Liste mit 'ab_runde'), sonst None."""
    phase = None
    for ph in sorted(defn.get("licht") or [], key=lambda p: p["ab_runde"]):
        if runde >= ph["ab_runde"]:
            phase = ph
    return phase


def used_placements(defn, root=None):
    """Platzierungen frueherer Plaene ('vermeide_plaene'), damit ein Folgeplan neue Kartonpositionen bekommt.
    Nimmt den gespeicherten Fortschritt (mit Ersatzplatzierungen), sonst die reproduzierbar erzeugten.
    Gibt (trainings-platzierungen, tests des ersten Plans) zurueck."""
    used, tests = [], None
    for pid in defn.get("vermeide_plaene") or []:
        path = os.path.join(root or runs_root(), pid, "plan.json")
        data = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        else:
            old = load_definition(pid)
            pool = G.candidates(old["geometrie"])
            places = G.generate([row[3] for row in old["runden"]], old["geometrie"], old["seed"], pool=pool)
            data = {"runden": [{"platzierung": p} for p in places], "tests": _tests(old, pool, places)}
        used += [r["platzierung"] for r in data["runden"] if r.get("platzierung")]
        used += [t["platzierung"] for t in data.get("tests", []) if t.get("platzierung")]
        if tests is None:
            tests = data.get("tests")
    return used, tests


def create(defn, root=None):
    """Legt den Plan an: alle Trainings- und die Testplatzierungen, Auftragslisten. Gibt PlanRun zurueck."""
    geo = defn["geometrie"]
    pool = G.candidates(geo)
    rounds = [{"runde": n, "session": s, "platzierung_id": pid, "ausrichtung_soll": a, "ladung": l,
               "anordnung": o} for n, s, pid, a, l, o in defn["runden"]]
    schon, old_tests = used_placements(defn, root)          # Folgeplan: nur neue Kartonpositionen
    places = G.generate([r["ausrichtung_soll"] for r in rounds], geo, defn["seed"], schon=schon, pool=pool,
                        abstand_min=defn.get("neu_abstand_min", 4.0) if schon else 0.0)
    for r, p in zip(rounds, places):
        r["platzierung"] = p
        ph = light_phase(defn, r["runde"])
        if ph:
            r["licht"] = ph["id"]
    # Testplatzierungen: im Folgeplan dieselben wie im ersten Plan (Datensaetze bleiben vergleichbar/mischbar)
    tests = old_tests if (old_tests and defn.get("tests_wie_vorplan")) else _tests(defn, pool, places)
    orders = make_orders(defn, rounds, defn["seed"] + 1)
    for r, o in zip(rounds, orders):
        r.update(auftraege=o, status="offen", behalten=[], nicht_greifbar=[], fehlend=0)
    data = {"plan_id": defn["id"], "plan_version": defn.get("version", 1), "angelegt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seed": defn["seed"], "runden": rounds, "tests": tests, "aktuelle_runde": 0, "protokoll": []}
    run = PlanRun(defn, data, root)
    run.log("Plan angelegt")
    lae = [r for r in rounds if r["platzierung"].get("ersatz_fuer")]
    if lae:
        run.log(f"{len(lae)} Runden 'laengs' geometrisch nicht moeglich, ersetzt durch "
                f"{', '.join(sorted({r['platzierung']['ausrichtung'] for r in lae}))}")
    run.save()
    return run


def _tests(defn, pool, train):
    out = []
    for t in defn.get("tests", []):
        opts = [c for c in pool if c[3] == t["ausrichtung"]]
        if not opts:
            out.append({**t, "platzierung": None, "moeglich": False,
                        "hinweis_ist": f"'{t['ausrichtung']}' passt geometrisch nicht in den Halbring"})
            continue
        def dist(c):
            return min(math.hypot(c[0] - q["x"], c[1] - q["y"]) + 0.15 * min(abs(c[2] - q["winkel"]) % 180,
                       180 - abs(c[2] - q["winkel"]) % 180) for q in train)
        if t.get("lage") == "mitte":
            key = lambda c: dist(c) - 0.8 * math.hypot(c[0], c[1] - 28)
        elif t.get("lage") == "rand":
            key = lambda c: dist(c) + 1.0 * abs(c[0])          # weit links oder rechts im Halbring
        else:
            key = dist
        x, y, w, k = max(opts, key=key)
        out.append({**t, "moeglich": True, "platzierung": {"x": x, "y": y, "winkel": w, "ausrichtung": k,
                                                           "seite": G.approach_side(x, y, w)}})
    return out


# --- Fortschritt --------------------------------------------------------------------------------
class PlanRun:
    def __init__(self, defn, data, root=None):
        self.defn, self.data = defn, data
        self.dir = os.path.join(root or runs_root(), defn["id"])
        # Anflugseite immer nach der aktuellen Regel (geometrie.approach_side), nie die gespeicherte uebernehmen:
        # 25.11. hat ein noch laufender alter Harness die korrigierten Seiten wieder ueberschrieben.
        for r in list(data.get("runden") or []) + list(data.get("tests") or []):
            p = r.get("platzierung")
            if isinstance(p, dict) and all(k in p for k in ("x", "y", "winkel")):
                p["seite"] = G.approach_side(p["x"], p["y"], p["winkel"])

    @classmethod
    def open(cls, plan_id, root=None, plan_root=None):
        """Vorhandenen Fortschritt laden oder den Plan neu anlegen."""
        defn = load_definition(plan_id, plan_root)
        path = os.path.join(root or runs_root(), plan_id, "plan.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return cls(defn, json.load(f), root)
        return create(defn, root)

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = os.path.join(self.dir, "plan.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, os.path.join(self.dir, "plan.json"))

    def log(self, text):
        self.data["protokoll"].append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}")

    # --- Kameraschaerfe: einmal messen, im Plan merken, spaeter vergleichen (Objektive werden von Hand gedreht) ---
    def schaerfe(self):
        """{kamera: {"wert", "zeit"}} - gespeicherte Bezugswerte des Plans."""
        return self.data.get("schaerfe") or {}

    def schaerfe_speichern(self, werte):
        """werte: {kamera: schaerfewert}. Ueberschreibt nur die gemessenen Kameras und speichert."""
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ref = self.data.setdefault("schaerfe", {})
        for cam, v in werte.items():
            ref[cam] = {"wert": round(float(v), 1), "zeit": stamp}
        self.log("Schaerfe gemessen: " + ", ".join(f"{c} {v:.0f}" for c, v in werte.items()))
        self.save()

    def schaerfe_vergleich(self, aktuell, toleranz=0.8):
        """aktuell: {kamera: wert} -> {kamera: (jetzt, bezug oder None, ok)}. ok: mindestens 80 % des Bezugs."""
        ref = self.schaerfe()
        out = {}
        for cam, v in aktuell.items():
            b = (ref.get(cam) or {}).get("wert")
            out[cam] = (v, b, b is None or v >= toleranz * b)
        return out

    # --- Lesen ---
    @property
    def rounds(self):
        return self.data["runden"]

    def round(self, i=None):
        i = self.data["aktuelle_runde"] if i is None else i
        return self.rounds[i] if 0 <= i < len(self.rounds) else None

    def finished(self):
        return self.data["aktuelle_runde"] >= len(self.rounds)

    def current_order_index(self):
        r = self.round()
        if r is None:
            return None
        return next((i for i, o in enumerate(r["auftraege"]) if o["status"] == "offen"), None)

    def current(self):
        """(runde, auftrag, index) oder (runde, None, None) wenn die Runde fertig ist."""
        r = self.round()
        i = self.current_order_index()
        return r, (r["auftraege"][i] if i is not None else None), i

    def content(self, r=None):
        """Kartoninhalt jetzt (vor dem aktuellen Griff): Ladung minus erledigte Griffe."""
        r = r or self.round()
        c = dict(self.defn["ladungen"][r["ladung"]])
        for o in r["auftraege"]:
            if o["status"] == "erledigt":
                c[o["teil"]] -= 1
        return c

    def content_text(self, c):
        b = self.defn["bauteile"]
        parts = [f"{n} {b[p]['plural'] if n != 1 else b[p]['kurz']}" for p, n in c.items() if n > 0]
        return ", ".join(parts) or "leer"

    def lage_text(self, zeile, spalte):
        return self.defn["lage_woerter"][zeile][spalte]

    def task_text(self, auftrag, lage=None):
        b = self.defn["bauteile"][auftrag["teil"]]
        if auftrag["art"] == "spezifisch" and lage:
            return b["spezifisch"].replace("{lage}", lage)
        return b["allgemein"]

    def split(self, r=None):
        return "train"

    def stats(self):
        """Soll/Ist je Bauteil und je Session."""
        soll, ist = {}, {}
        for r in self.rounds:
            for p, n in self.defn["ladungen"][r["ladung"]].items():
                soll[p] = soll.get(p, 0) + n
            for e in r["behalten"]:
                ist[e["teil"]] = ist.get(e["teil"], 0) + 1
        return soll, ist

    def episode_belongs(self, r, order, info):
        """Eine geloeschte Episodennummer kann inzwischen wieder vergeben worden sein."""
        return (info.get("plan"), info.get("session"), info.get("runde"),
                info.get("zielbauteil"), info.get("befehlsart"), info.get("lage")) == (
                self.defn["id"], r["session"], r["runde"], order["teil"], order["art"], order.get("lage"))

    def repeat_session(self, session, dataset, trash=None):
        """Nimmt die Episoden einer Session aus dem Datensatz und oeffnet ihre Runden erneut."""
        rounds = [r for r in self.rounds if r["session"] == session]
        if not rounds:
            raise ValueError(f"Session {session} fehlt im Plan")
        return self._repeat(rounds, f"session_{session}_", f"Session {session}", dataset, trash)

    def repeat_round(self, runde, dataset, trash=None):
        """Nur eine Runde: ihre Episoden in den Papierkorb, Runde an derselben Kartonposition neu."""
        rounds = [r for r in self.rounds if r["runde"] == runde]
        if not rounds:
            raise ValueError(f"Runde {runde} fehlt im Plan")
        return self._repeat(rounds, f"runde_{runde}_", f"Runde {runde}", dataset, trash)

    def repeat_order(self, runde, index, dataset, trash=None):
        """Einen einzelnen Griff neu aufnehmen: seine Episode in den Papierkorb, Auftrag wieder offen.
        Liegt die Runde nicht mehr auf dem Tisch, muss der Karton dafuer neu hingelegt werden (Status 'offen').
        Gibt den Ordner im Papierkorb (oder None) zurueck."""
        from ki.episodes import TRASH
        r = next((q for q in self.rounds if q["runde"] == runde), None)
        if r is None or not 0 <= index < len(r["auftraege"]):
            raise ValueError("Griff gibt es nicht")
        order = r["auftraege"][index]
        if order["status"] != "erledigt":
            raise ValueError("Dieser Griff ist noch nicht aufgenommen")
        ep = order.get("episode")
        target = None
        if ep and ep in dataset.episodes() and re.fullmatch(r"ep_\d+", ep) \
                and self.episode_belongs(r, order, dataset.episode_info(ep)):
            d = os.path.join(trash or TRASH, dataset.name)
            os.makedirs(d, exist_ok=True)
            target = os.path.join(d, f"{ep}_runde{runde}_griff{index + 1}_{time.strftime('%Y%m%d-%H%M%S')}")
            os.rename(os.path.join(dataset.path, ep), target)
        active = self.round()
        order["status"] = "offen"
        order.pop("episode", None)
        order.pop("lage", None)
        r["behalten"] = [b for b in r["behalten"] if b.get("episode") != ep]
        if active is not r:
            if active is not None and active["status"] == "bereit":
                active["status"] = "offen"           # aktueller Karton wird gleich weggeraeumt
            r["status"] = "offen"                    # Karton dieser Runde neu hinlegen
            r.pop("fertig", None)
        r["einzeln_wiederholt"] = r.get("einzeln_wiederholt", 0) + 1
        self._next_open_round()
        self.log(f"Runde {runde} Griff {index + 1}: {ep} verworfen, wird neu aufgenommen")
        self.save()
        return target

    def _repeat(self, rounds, prefix, name, dataset, trash=None):
        from ki.episodes import TRASH
        ids = {id(r) for r in rounds}
        available = set(dataset.episodes())
        remove = set()
        for r in rounds:
            for order in r["auftraege"]:
                ep = order.get("episode")
                if ep not in available:
                    continue
                if re.fullmatch(r"ep_\d+", ep) and self.episode_belongs(r, order, dataset.episode_info(ep)):
                    remove.add(ep)

        previous = copy.deepcopy(self.data)
        moved = []
        try:
            if remove:
                target = os.path.join(trash or TRASH, dataset.name)
                os.makedirs(target, exist_ok=True)
                batch = tempfile.mkdtemp(prefix=prefix, dir=target)
                for ep in sorted(remove):
                    src, dst = os.path.join(dataset.path, ep), os.path.join(batch, ep)
                    if os.path.normcase(os.path.realpath(src)) != os.path.join(
                            os.path.normcase(os.path.realpath(dataset.path)), ep):
                        raise ValueError(f"Ungueltiger Episodenordner: {ep}")
                    os.rename(src, dst)
                    moved.append((src, dst))
            active = self.round()
            if active and id(active) not in ids and active["status"] == "bereit":
                active["status"] = "offen"   # Karton beim Fortsetzen erneut positionieren
            for r in rounds:
                r.update(status="offen", behalten=[], nicht_greifbar=[], fehlend=0, wiederholung=True)
                r.pop("bestaetigt", None)
                r.pop("fertig", None)
                r["auftraege"] = r.pop("auftraege_vor_tausch", r["auftraege"])
                for order in r["auftraege"]:
                    order.update(status="offen")
                    order.pop("episode", None)
                    order.pop("lage", None)
            if prefix.startswith("session_"):
                self.data["wiederholung_session"] = rounds[0]["session"]
            self._next_open_round()
            self.log(f"{name} zurueckgesetzt: {len(moved)} Episoden im Papierkorb")
            self.save()
        except Exception:
            self.data = previous
            for src, dst in reversed(moved):
                os.rename(dst, src)
            raise
        return len(moved)

    # --- Aendern ---
    def confirm_round(self):
        r = self.round()
        if r is None:
            raise RuntimeError("Plan ist abgeschlossen")
        r["status"] = "bereit"
        r["bestaetigt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log(f"Runde {r['runde']}: {(self.defn.get('objekt') or {}).get('name', 'Karton')} liegt bereit "
                 f"({r['platzierung']['ausrichtung']})")
        self.save()

    def unreachable(self):
        """Aktuelle Platzierung nicht erreichbar: Ersatz derselben Klasse (sonst schraeg) erzeugen."""
        r = self.round()
        if r.get("wiederholung"):
            raise ValueError("Bei der Wiederholung bleibt die Kartonposition gleich")
        old = r["platzierung"]
        r.setdefault("unerreichbar", []).append(old)
        others = [q["platzierung"] for q in self.rounds] + r["unerreichbar"]
        klasse = old.get("ersatz_fuer") or old["ausrichtung"]
        seed = self.data["seed"] + 1000 * r["runde"] + len(r["unerreichbar"])
        pool = [c for c in G.candidates(self.defn["geometrie"])
                if all(math.hypot(c[0] - q["x"], c[1] - q["y"]) > 3 for q in r["unerreichbar"])]
        new = G.generate([klasse], self.defn["geometrie"], seed, schon=others, pool=pool)[0]
        r["platzierung"] = new
        r["status"] = "offen"
        self.log(f"Runde {r['runde']}: Platzierung nicht erreichbar, Ersatz {new['ausrichtung']}")
        self.save()
        return new

    def keep(self, episode, lage=None, extra=None):
        """Griff behalten: Auftrag erledigt, Episode vermerken, ggf. zur naechsten Runde."""
        r, o, i = self.current()
        if o is None:
            raise RuntimeError("Kein offener Auftrag")
        if o["art"] == "spezifisch" and not lage:
            raise ValueError("Bei einem spezifischen Auftrag muss die Lage angetippt sein")
        o["status"] = "erledigt"
        o["episode"] = episode
        if lage:
            o["lage"] = lage
        r["behalten"].append({"episode": episode, "teil": o["teil"], "art": o["art"], **(extra or {})})
        self.log(f"Runde {r['runde']} Griff {i + 1}: {o['teil']} behalten ({episode})")
        self._advance_if_done()
        self.save()

    def not_graspable(self, beispiel):
        """Zielbauteil verdeckt: mit dem naechsten offenen Auftrag eines anderen Bauteils tauschen.
        Gibt es keinen, endet die Runde (fehlende Griffe werden gezaehlt)."""
        r, o, i = self.current()
        if o is None:
            return None
        r["nicht_greifbar"].append(beispiel)
        j = next((k for k in range(i + 1, len(r["auftraege"]))
                  if r["auftraege"][k]["status"] == "offen" and r["auftraege"][k]["teil"] != o["teil"]), None)
        if j is None:
            missing = [a for a in r["auftraege"] if a["status"] == "offen"]
            for a in missing:
                a["status"] = "ausgelassen"
            r["fehlend"] = r.get("fehlend", 0) + len(missing)
            self.log(f"Runde {r['runde']}: kein anderes Bauteil offen, Runde beendet ({len(missing)} Griffe fehlen)")
            self._advance_if_done()
            self.save()
            return "runde_beendet"
        if "auftraege_vor_tausch" not in r:
            r["auftraege_vor_tausch"] = copy.deepcopy(r["auftraege"])
        r["auftraege"][i], r["auftraege"][j] = r["auftraege"][j], r["auftraege"][i]
        self._recheck_arts(r)
        self.log(f"Runde {r['runde']}: {o['teil']} nicht greifbar, getauscht mit Griff {j + 1}")
        self.save()
        return "getauscht"

    def _recheck_arts(self, r):
        c = self.content(r)
        for a in r["auftraege"]:
            if a["status"] != "offen":
                continue
            if a["art"] == "spezifisch" and c[a["teil"]] < 2:
                a["art"] = "allgemein"
            c[a["teil"]] -= 1

    def _advance_if_done(self):
        r = self.round()
        if r is not None and all(a["status"] != "offen" for a in r["auftraege"]):
            r["status"] = "fertig"
            r["fertig"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._next_open_round()
            self.log(f"Runde {r['runde']} fertig: {len(r['behalten'])} behalten")

    def _next_open_round(self):
        session = self.data.get("wiederholung_session")
        if session is not None:
            for i, r in enumerate(self.rounds):
                if r["session"] == session and r["status"] != "fertig":
                    self.data["aktuelle_runde"] = i
                    return
            self.data.pop("wiederholung_session")
        self.data["aktuelle_runde"] = next((i for i, r in enumerate(self.rounds) if r["status"] != "fertig"),
                                          len(self.rounds))

    def coverage(self):
        """Abdeckung: behaltene Griffe nach Bauteil, Fuellstand, Befehlsart, Ausrichtung."""
        cov = {"bauteil": {}, "fuellstand": {}, "art": {}, "ausrichtung": {}}
        for r in self.rounds:
            for e in r["behalten"]:
                for key, val in (("bauteil", e["teil"]), ("fuellstand", e.get("fuellstand")), ("art", e["art"]),
                                 ("ausrichtung", r["platzierung"]["ausrichtung"])):
                    cov[key][val] = cov[key].get(val, 0) + 1
        return cov
