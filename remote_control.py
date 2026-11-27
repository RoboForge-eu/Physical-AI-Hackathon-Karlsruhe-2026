"""Wer darf den Arm steuern? Kontrolle auf Zeit, Warteschlange, Anfragen, Admin (Harness).

Reine Logik ohne Netz, Zeit kommt von aussen (testbar).
- Wer zuerst "Steuern" klickt (claim), bekommt die Kontrolle fuer die gewuenschte Zeit (1..Limit Minuten).
- Andere sind Zuschauer: sie koennen anfragen (Bediener entscheidet) oder sich anstellen (Warteschlange).
- Ist die Zeit um, gibt der Bediener ab oder geht er, kommt der Naechste aus der Warteschlange dran.
- Der Admin (Harness) sieht alles, kann Geraete entfernen, Zeit verlaengern und Geraete mit eigenem Limit merken.
"""

DEFAULT_MAX_MIN = 30


class ControlDesk:
    def __init__(self, max_min=DEFAULT_MAX_MIN, devices=None):
        self.max_min = max_min          # Standard-Limit fuer alle (Minuten), im Harness einstellbar
        self.devices = devices if devices is not None else {}   # Geraete-ID -> {"name", "max_min"}
        self.info = {}                  # cid -> {"device", "name", "want_min"}
        self.holder = None
        self.since = None
        self.until = None
        self.queue = []
        self.request_from = None        # cid, der gerade um Uebergabe bittet
        self.extend_wanted = False      # Bediener bittet den Admin um Verlaengerung
        self.notices = []               # (cid, {"t":"notice", ...}) fuer den Server
        self.version = 0                # zaehlt Aenderungen (Server schickt dann sofort neue Infos)

    # --- Hilfen ---
    def name(self, cid):
        return (self.info.get(cid) or {}).get("name") or str(cid)

    def device(self, cid):
        return (self.info.get(cid) or {}).get("device")

    def limit(self, cid):
        """Hoechstdauer in Minuten fuer dieses Geraet: gemerkte Geraete koennen laenger."""
        dev = self.devices.get(self.device(cid) or "")
        return max(self.max_min, int(dev.get("max_min", 0))) if dev else self.max_min

    def _want(self, cid, minutes=None):
        if minutes is None:
            minutes = (self.info.get(cid) or {}).get("want_min") or self.limit(cid)
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            minutes = self.limit(cid)
        return max(1.0, min(minutes, float(self.limit(cid))))

    def _notice(self, cid, kind, text, **extra):
        if cid is not None:
            self.notices.append((cid, {"t": "notice", "kind": kind, "text": text, **extra}))

    def _changed(self):
        self.version += 1

    # --- Clients ---
    def join(self, cid, device=None, name=None):
        old = self.info.get(cid, {})
        self.info[cid] = {"device": device or old.get("device"), "name": name or old.get("name"),
                          "want_min": old.get("want_min")}
        self._changed()

    def leave(self, cid, now):
        self.info.pop(cid, None)
        if cid in self.queue:
            self.queue.remove(cid)
        if self.request_from == cid:
            self.request_from = None
        if cid == self.holder:
            self._next(now)
        self._changed()

    # --- Kontrolle ---
    def _grant(self, cid, minutes, now):
        if cid in self.queue:
            self.queue.remove(cid)
        self.holder, self.since = cid, now
        self.until = now + self._want(cid, minutes) * 60
        self.request_from, self.extend_wanted = None, False
        self._notice(cid, "granted", f"Du steuerst jetzt ({self._want(cid, minutes):.0f} min).")
        self._changed()

    def _next(self, now):
        self.holder = self.since = self.until = None
        self.request_from, self.extend_wanted = None, False
        while self.queue:
            nxt = self.queue.pop(0)
            if nxt in self.info:
                self._grant(nxt, None, now)
                break
        self._changed()

    def claim(self, cid, minutes, now):
        """Steuern klicken. True, wenn dieser Client jetzt die Kontrolle hat."""
        if cid not in self.info:
            self.join(cid)
        self.info[cid]["want_min"] = self._want(cid, minutes)
        if self.holder is None:
            self._grant(cid, minutes, now)
        return self.holder == cid

    def release(self, cid, now):
        if cid == self.holder:
            self._next(now)

    def enqueue(self, cid, minutes=None):
        if cid not in self.info:
            self.join(cid)
        if minutes is not None:
            self.info[cid]["want_min"] = self._want(cid, minutes)
        if cid != self.holder and cid not in self.queue:
            self.queue.append(cid)
            self._changed()

    def dequeue(self, cid):
        if cid in self.queue:
            self.queue.remove(cid)
            self._changed()

    def request(self, cid, minutes=None):
        """Zuschauer bittet den Bediener um die Kontrolle."""
        if self.holder is None or cid == self.holder:
            return
        if minutes is not None and cid in self.info:
            self.info[cid]["want_min"] = self._want(cid, minutes)
        self.request_from = cid
        self._notice(self.holder, "request", f"{self.name(cid)} moechte steuern. Kontrolle abgeben?",
                     von=self.name(cid))
        self._notice(cid, "info", "Anfrage gesendet - der Bediener entscheidet.")
        self._changed()

    def answer(self, cid, accept, now):
        if cid != self.holder or self.request_from is None:
            return
        req, self.request_from = self.request_from, None
        if accept and req in self.info:
            self._notice(cid, "info", f"Kontrolle an {self.name(req)} abgegeben.")
            self._grant(req, None, now)
        else:
            self._notice(req, "declined", "Der Bediener behaelt die Kontrolle.")
        self._changed()

    def ask_extend(self, cid):
        if cid == self.holder:
            self.extend_wanted = True
            self._notice(cid, "info", "Verlaengerung beim Admin angefragt.")
            self._changed()

    # --- Admin (Harness) ---
    def kick(self, cid, now):
        if cid not in self.info:
            return
        self._notice(cid, "kicked", "Der Admin hat dir die Kontrolle entzogen.")
        if cid in self.queue:
            self.queue.remove(cid)
        if cid == self.holder:
            self._next(now)
        self._changed()

    def extend(self, minutes):
        if self.holder is not None:
            self.until += float(minutes) * 60
            self.extend_wanted = False
            self._notice(self.holder, "extended", f"Der Admin hat deine Zeit um {float(minutes):.0f} min verlaengert.")
            self._changed()

    def remember(self, cid, max_min, name=None):
        """Geraet merken, mit eigenem Hoechstwert (Minuten)."""
        dev = self.device(cid)
        if not dev:
            return False
        self.devices[dev] = {"name": name or self.name(cid), "max_min": int(max_min)}
        self._changed()
        return True

    def set_max(self, minutes):
        self.max_min = max(1, int(minutes))
        self._changed()

    # --- Takt ---
    def tick(self, now):
        if self.holder is not None and self.until is not None and now >= self.until:
            self._notice(self.holder, "expired", "Deine Zeit ist um - die Kontrolle ist abgegeben.")
            self._next(now)

    # --- Ansichten ---
    def wait_s(self, cid, now):
        """Geschaetzte Wartezeit in s fuer einen Platz in der Warteschlange."""
        if cid not in self.queue:
            return None
        t = max(0.0, (self.until or now) - now) if self.holder is not None else 0.0
        for c in self.queue[:self.queue.index(cid)]:
            t += self._want(c) * 60
        return t

    def view(self, cid, now):
        """Was ein Client ueber die Kontrolle wissen muss ({"t":"control"})."""
        mine = cid == self.holder
        return {"t": "control", "role": "operator" if mine else "spectator",
                "holder": self.name(self.holder) if self.holder is not None else None,
                "left_s": round(self.until - now) if mine and self.until else None,
                "holder_left_s": round(self.until - now) if self.holder is not None and self.until else None,
                "queue_pos": self.queue.index(cid) + 1 if cid in self.queue else None,
                "wait_s": round(self.wait_s(cid, now)) if cid in self.queue else None,
                "queue_len": len(self.queue), "max_min": self.limit(cid),
                "request_from": self.name(self.request_from) if mine and self.request_from is not None else None,
                "remembered": bool(self.devices.get(self.device(cid) or ""))}

    def overview(self, now):
        """Fuer das Kontrollpanel im Harness."""
        rows = []
        for cid, inf in self.info.items():
            role = ("Bediener" if cid == self.holder else
                    f"Warteschlange {self.queue.index(cid) + 1}" if cid in self.queue else "Zuschauer")
            rows.append({"cid": cid, "name": self.name(cid), "device": inf.get("device"), "role": role,
                         "limit": self.limit(cid), "remembered": bool(self.devices.get(inf.get("device") or ""))})
        return {"holder": self.holder, "holder_name": self.name(self.holder) if self.holder is not None else None,
                "left_s": max(0, round(self.until - now)) if self.holder is not None and self.until else None,
                "max_min": self.max_min, "extend_wanted": self.extend_wanted,
                "request_from": self.name(self.request_from) if self.request_from is not None else None,
                "clients": rows}

    def pop_notices(self):
        n, self.notices = self.notices, []
        return n
