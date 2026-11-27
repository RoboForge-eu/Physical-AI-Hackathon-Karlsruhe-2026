"""Web-Station: bringt die Funktionen des Harness-Fensters in die Weboberflaeche (Physical AI Harness, 127.0.0.1:8780).

=== KERN-DATEI · fuer Hackathon-Teams NICHT zum Umbauen gedacht ===================================================
Teams bauen in teams/<team>/ (Orchestrator, Skills, Interface, Trainingsplaene). Siehe teams/_vorlage/AGENTS.md.
====================================================================================================================

Drei Teile:
  1. Pumpe:    Befehle aus der Weboberflaeche laufen im Fenster-Thread des Harness (Tk ist nicht threadsicher).
               ui_call() wartet auf das Ergebnis; die Pumpe laeuft auch waehrend offener Rueckfragen weiter.
  2. Spiegel:  Assistenten des Harness (Kalibrieren, Kameras zuordnen, Spannung, Arbeitsbereich, Fernzugang, die
               Plan-Ansicht des Steuermodus) laufen unveraendert, ihr Fenster bleibt aber versteckt. Die Webseite
               bekommt den Inhalt als Baum (Texte, Knoepfe, Eingaben, Zeichnungen als SVG) und klickt Knoepfe.
  3. Rueckfragen: messagebox-Fragen aus gespiegelten Fenstern erscheinen in der Webseite (Ja/Nein). Ohne Antwort
               gilt nach 3 Minuten "Nein" (sicher). Fragen aus dem normalen Harness-Fenster bleiben dort.

Sicherheit: Alle Befehle hier sind nur lokal erlaubt (nicht ueber das Internet, nicht fuer den Agenten). Bewegungen
starten nur nach Zustimmung des Menschen vor Ort (Dialog in der Webseite, die nur auf diesem Rechner laeuft).
Wird die Webseite geschlossen, holt der Harness versteckte Fenster nach 60 s wieder nach vorne.
"""
import base64, collections, itertools, queue, sys, threading, time, types
import tkinter as tk
from tkinter import messagebox

LAB = None
PUMPE = queue.Queue()
SPIEGEL = {}                    # Tk-Pfad des Fensters -> {"win", "titel", "art", "seit"}
FRAGEN = {}                     # id -> {"titel", "text", "art", "ev", "antwort"}
MELDUNGEN = collections.deque(maxlen=12)
_IDS = itertools.count(1)
_ORIG = {}
LETZTER_BESUCH = [0.0]          # wann die Webseite zuletzt nachgefragt hat (monotonic)
WEB_TIMEOUT_S = 60
# Von der Weboberflaeche gestartet (Harness-Fenster minimiert): ALLE Rueckfragen des Harness (z. B. Freigabe einer
# Arbeitssitzung fuer den Orchestrator) erscheinen in der Webseite, solange sie offen ist.
WEB_ALLE = "--im-hintergrund" in sys.argv
FRAGE_TIMEOUT_S = 180


# ------------------------------------------------------------------------------------------------ 1. Pumpe
def installieren(lab):
    """Einmal beim Start des Harness (ros.py ruft das auf)."""
    global LAB
    LAB = lab
    for name in ("askyesno", "askokcancel", "askyesnocancel", "askretrycancel",
                 "showinfo", "showwarning", "showerror"):
        if name not in _ORIG:
            _ORIG[name] = getattr(messagebox, name)
            setattr(messagebox, name, _dialog(name, _ORIG[name]))
    lab.root.after(50, _pumpe)


def _pumpe():
    if LAB is None:
        return
    try:
        LAB.root.after(40, _pumpe)          # zuerst neu planen: laeuft auch in verschachtelten Dialog-Schleifen
    except tk.TclError:
        return
    abarbeiten()
    _verwaiste_fenster()


def abarbeiten():
    for _ in range(50):
        try:
            fn = PUMPE.get_nowait()
        except queue.Empty:
            return
        fn()


def ui_call(fn, timeout=8.0):
    """fn im Fenster-Thread ausfuehren und das Ergebnis zurueckgeben (Fehler werden weitergereicht)."""
    if threading.current_thread() is threading.main_thread():
        return fn()
    fertig, box = threading.Event(), {}

    def run():
        try:
            box["r"] = fn()
        except Exception as exc:              # noqa: BLE001 - wird an den Aufrufer gereicht
            box["e"] = exc
        finally:
            fertig.set()
    PUMPE.put(run)
    if not fertig.wait(timeout):
        raise TimeoutError("Der Harness antwortet gerade nicht (beschaeftigt). Bitte gleich nochmal.")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def ui_spaeter(fn):
    """fn im Fenster-Thread starten, ohne zu warten (fuer Knoepfe, die selbst Dialoge oeffnen)."""
    def run():
        try:
            fn()
        except Exception as exc:              # noqa: BLE001
            MELDUNGEN.append({"titel": "Fehler", "text": str(exc), "art": "fehler", "zeit": time.time()})
    PUMPE.put(run)


def besuch():
    LETZTER_BESUCH[0] = time.monotonic()


# ------------------------------------------------------------------------------------------------ 3. Rueckfragen
def gespiegelt(widget):
    if widget is None:
        return False
    try:
        return str(widget.winfo_toplevel()) in SPIEGEL
    except (tk.TclError, AttributeError):
        return False


def _dialog(name, orig):
    def f(title=None, message=None, **kw):
        parent = kw.get("parent")
        web = gespiegelt(parent) or WEB_ALLE
        if not web or time.monotonic() - LETZTER_BESUCH[0] > WEB_TIMEOUT_S:
            return orig(title, message, **kw)
        if parent is None or not gespiegelt(parent):
            parent = LAB.root
        if name.startswith("show"):
            MELDUNGEN.append({"titel": title or "", "text": message or "", "zeit": time.time(),
                              "art": {"showerror": "fehler", "showwarning": "warnung"}.get(name, "info")})
            return "ok"
        return frage(parent, title, message, name)
    return f


def frage(parent, titel, text, art="askyesno"):
    """Frage an die Webseite und (in einer Dialog-Schleife wie bei Tk) auf die Antwort warten."""
    fid = next(_IDS)
    ev = threading.Event()
    FRAGEN[fid] = {"id": fid, "titel": titel or "", "text": text or "", "art": art, "ev": ev, "antwort": None}
    ende = time.monotonic() + FRAGE_TIMEOUT_S
    try:
        while not ev.is_set() and time.monotonic() < ende:
            if time.monotonic() - LETZTER_BESUCH[0] > WEB_TIMEOUT_S:
                break                          # Webseite weg: sicher mit "Nein" antworten
            try:
                parent.update()
            except tk.TclError:
                break
            abarbeiten()
            time.sleep(0.03)
    finally:
        eintrag = FRAGEN.pop(fid, {})
    a = eintrag.get("antwort")
    if art == "askyesnocancel":
        return None if a is None else bool(a)
    return bool(a)


def antworten(fid, antwort):
    e = FRAGEN.get(int(fid))
    if e is None:
        raise ValueError("Diese Frage ist nicht mehr offen.")
    e["antwort"] = bool(antwort)
    e["ev"].set()
    return {"ok": True}


def fragen_und_meldungen(nach=0.0):
    return {"fragen": [{k: v for k, v in e.items() if k not in ("ev", "antwort")} for e in list(FRAGEN.values())],
            "meldungen": [m for m in list(MELDUNGEN) if m["zeit"] > nach]}


# ------------------------------------------------------------------------------------------------ 2. Spiegel
def alle_fenster(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Toplevel):
            out.append(c)
        out.extend(alle_fenster(c))
    return out


def verstecken(win):
    """Unsichtbar, aber 'offen' (ausserhalb des Bildschirms): so haben Zeichnungen und Texte ihre echte Groesse."""
    try:
        win.overrideredirect(True)             # kein Eintrag in der Taskleiste
        win.attributes("-alpha", 0.0)
        win.attributes("-topmost", False)
    except tk.TclError:
        pass
    win.geometry("1500x900+-6000+-6000")


def zurueckholen(win):
    try:
        win.overrideredirect(False)
        win.attributes("-alpha", 1.0)
    except tk.TclError:
        pass
    win.geometry("+120+80")
    win.deiconify()
    win.lift()


def aufnehmen(win, art="assistent"):
    verstecken(win)
    SPIEGEL[str(win)] = {"win": win, "titel": win.title(), "art": art, "seit": time.time()}
    return str(win)


def oeffnen(fn, art="assistent"):
    """fn oeffnet ein oder mehrere Harness-Fenster; diese werden versteckt und gespiegelt. Ergebnis: ihre IDs."""
    def run():
        vorher = {str(t) for t in alle_fenster(LAB.root)}
        fn()
        neu = [t for t in alle_fenster(LAB.root) if str(t) not in vorher]
        return [aufnehmen(t, art) for t in neu]
    return ui_call(run)


def _kinder_aufnehmen():
    """Fenster, die ein gespiegeltes Fenster selbst oeffnet (Unterdialoge), auch spiegeln."""
    for t in alle_fenster(LAB.root):
        if str(t) in SPIEGEL:
            continue
        try:
            if str(t.master.winfo_toplevel()) in SPIEGEL:
                aufnehmen(t, SPIEGEL[str(t.master.winfo_toplevel())]["art"])
        except (tk.TclError, AttributeError):
            pass


def _aufraeumen():
    for k, e in list(SPIEGEL.items()):
        try:
            if not e["win"].winfo_exists():
                del SPIEGEL[k]
        except tk.TclError:
            del SPIEGEL[k]


def _verwaiste_fenster():
    """Webseite seit 60 s weg: versteckte Assistenten wieder im Harness-Fenster zeigen (nichts geht verloren)."""
    if not SPIEGEL or time.monotonic() - LETZTER_BESUCH[0] < WEB_TIMEOUT_S:
        return
    for k, e in list(SPIEGEL.items()):
        if e["art"] == "assistent":
            try:
                zurueckholen(e["win"])
            except tk.TclError:
                pass
            del SPIEGEL[k]


def liste():
    def run():
        _aufraeumen()
        _kinder_aufnehmen()
        return [{"id": k, "titel": e["titel"], "art": e["art"]} for k, e in SPIEGEL.items()]
    return ui_call(run)


def _fenster(fid):
    e = SPIEGEL.get(fid)
    if e is None or not e["win"].winfo_exists():
        raise ValueError("Dieses Fenster ist schon geschlossen.")
    return e["win"]


def _widget(fid, pfad):
    win = _fenster(fid)
    if not (pfad == fid or pfad.startswith(fid + ".")):
        raise ValueError("Element gehoert nicht zu diesem Fenster")
    return win.nametowidget(pfad)


def _text(w):
    try:
        tv = str(w.cget("textvariable"))
        if tv:
            return str(w.getvar(tv))
    except tk.TclError:
        pass
    try:
        return str(w.cget("text"))
    except tk.TclError:
        return ""


def _aus(w):
    try:
        if hasattr(w, "instate"):
            return bool(w.instate(["disabled"]))
        return str(w.cget("state")) == "disabled"
    except tk.TclError:
        return False


def _schrift(w):
    try:
        import tkinter.font as tkfont
        f = w.cget("font")
        if not f:
            return {}
        a = tkfont.Font(root=w, font=f).actual()
        return {"fett": a.get("weight") == "bold", "groesse": abs(int(a.get("size") or 0)),
                "mono": a.get("family", "").lower() in ("consolas", "courier new", "courier")}
    except (tk.TclError, ValueError):
        return {}


def _farbe(w, opt):
    try:
        c = str(w.cget(opt))
        if not c or c.startswith("System"):
            return None
        r, g, b = (v // 257 for v in w.winfo_rgb(c))
        return f"#{r:02x}{g:02x}{b:02x}"
    except tk.TclError:
        return None


def _ton(hexfarbe):
    """Farbe grob einordnen (die Webseite hat eigene, ruhige Farben)."""
    if not hexfarbe:
        return None
    r, g, b = int(hexfarbe[1:3], 16), int(hexfarbe[3:5], 16), int(hexfarbe[5:7], 16)
    if r > 150 and g < 90 and b < 90:
        return "rot"
    if g > r + 30 and g > b:
        return "gruen"
    if r > 180 and g > 140 and b < 110:
        return "gelb"
    if b > r + 40:
        return "blau"
    return None


def _canvas_svg(c):
    w, h = c.winfo_width(), c.winfo_height()
    if w < 20 or h < 20:
        try:
            w, h = int(float(c.cget("width"))), int(float(c.cget("height")))
        except (tk.TclError, ValueError):
            w, h = max(1, c.winfo_reqwidth()), max(1, c.winfo_reqheight())
    teile = []
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    for i in c.find_all():
        try:
            if c.itemcget(i, "state") == "hidden":
                continue
            t = c.type(i)
            xy = c.coords(i)
            col = lambda o: (c.itemcget(i, o) or "none")
            if t == "line":
                pts = " ".join(f"{xy[k]:.1f},{xy[k + 1]:.1f}" for k in range(0, len(xy) - 1, 2))
                dash = ' stroke-dasharray="4 3"' if c.itemcget(i, "dash") else ""
                teile.append(f'<polyline points="{pts}" fill="none" stroke="{esc(col("fill"))}" '
                             f'stroke-width="{esc(c.itemcget(i, "width") or 1)}"{dash}/>')
            elif t == "polygon":
                pts = " ".join(f"{xy[k]:.1f},{xy[k + 1]:.1f}" for k in range(0, len(xy) - 1, 2))
                teile.append(f'<polygon points="{pts}" fill="{esc(col("fill"))}" stroke="{esc(col("outline"))}" '
                             f'stroke-width="{esc(c.itemcget(i, "width") or 1)}"/>')
            elif t in ("rectangle", "oval") and len(xy) == 4:
                x0, y0, x1, y1 = xy
                if t == "rectangle":
                    teile.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" '
                                 f'fill="{esc(col("fill"))}" stroke="{esc(col("outline"))}" '
                                 f'stroke-width="{esc(c.itemcget(i, "width") or 1)}"/>')
                else:
                    teile.append(f'<ellipse cx="{(x0 + x1) / 2:.1f}" cy="{(y0 + y1) / 2:.1f}" rx="{(x1 - x0) / 2:.1f}" '
                                 f'ry="{(y1 - y0) / 2:.1f}" fill="{esc(col("fill"))}" stroke="{esc(col("outline"))}" '
                                 f'stroke-width="{esc(c.itemcget(i, "width") or 1)}"/>')
            elif t == "text" and len(xy) >= 2:
                anchor = c.itemcget(i, "anchor") or "center"
                ta = "start" if "w" in anchor else "end" if "e" in anchor and anchor != "center" else "middle"
                dy = "0.9em" if anchor.startswith("n") else "0" if anchor.startswith("s") else "0.35em"
                import tkinter.font as tkfont
                try:
                    gr = abs(int(tkfont.Font(root=c, font=c.itemcget(i, "font")).actual().get("size") or 9)) * 1.33
                except (tk.TclError, ValueError):
                    gr = 12
                zeilen = str(c.itemcget(i, "text")).split("\n")
                tsp = "".join(f'<tspan x="{xy[0]:.1f}" dy="{dy if k == 0 else "1.2em"}">{esc(z)}</tspan>'
                              for k, z in enumerate(zeilen))
                teile.append(f'<text x="{xy[0]:.1f}" y="{xy[1]:.1f}" fill="{esc(col("fill"))}" font-size="{gr:.0f}" '
                             f'text-anchor="{ta}" font-family="Segoe UI, sans-serif">{tsp}</text>')
        except (tk.TclError, IndexError):
            continue
    bg = _farbe(c, "background") or "#111111"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">'
            f'<rect width="{w}" height="{h}" fill="{bg}"/>' + "".join(teile) + "</svg>")


def knoten(w):
    """Widget -> Baum fuer die Webseite. Nur sichtbare (gepackte) Elemente."""
    k = w.winfo_class()
    p = str(w)
    if k in ("TScrollbar", "Scrollbar", "Menu"):
        return None
    if k in ("TSeparator",):
        return {"typ": "linie", "pfad": p}
    if hasattr(w, "web_bild_quelle"):                        # Kamerabild (z. B. Wrist-Cam der Plan-Ansicht)
        return {"typ": "bild", "pfad": p, "klickbar": hasattr(w, "web_klick"), "text": _text(w)}
    if k in ("Label", "TLabel"):
        img = ""
        try:
            img = str(w.cget("image"))
        except tk.TclError:
            pass
        t = _text(w)
        if img and not t.strip():
            return {"typ": "bild", "pfad": p, "foto": True}
        if not t.strip():
            return None
        return {"typ": "text", "pfad": p, "text": t, **_schrift(w), "ton": _ton(_farbe(w, "background")),
                "farbe": _ton(_farbe(w, "foreground"))}
    if k in ("Button", "TButton"):
        img = ""
        try:
            img = str(w.cget("image"))
        except tk.TclError:
            pass
        t = _text(w)
        return {"typ": "knopf", "pfad": p, "text": t or ("Bild ansehen" if img else "…"), "aus": _aus(w),
                "ton": _ton(_farbe(w, "background"))}
    if k in ("Checkbutton", "TCheckbutton"):
        try:
            var = str(w.cget("variable"))
            an = str(w.getvar(var)) in ("1", "True", str(w.cget("onvalue")))
        except tk.TclError:
            an = False
        return {"typ": "haken", "pfad": p, "text": _text(w), "an": an, "aus": _aus(w)}
    if k in ("Radiobutton", "TRadiobutton"):
        try:
            an = str(w.getvar(str(w.cget("variable")))) == str(w.cget("value"))
        except tk.TclError:
            an = False
        return {"typ": "wahl", "pfad": p, "text": _text(w), "an": an, "aus": _aus(w)}
    if k in ("Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox"):
        d = {"typ": "eingabe", "pfad": p, "wert": w.get(), "aus": _aus(w)}
        if k == "TCombobox":
            d["optionen"] = [str(v) for v in (w.cget("values") or ())]
            d["nur_liste"] = str(w.cget("state")) == "readonly"
        if k in ("Spinbox", "TSpinbox"):
            d["zahl"] = True
        return d
    if k in ("Scale", "TScale"):
        return {"typ": "regler", "pfad": p, "wert": float(w.get()), "von": float(w.cget("from")),
                "bis": float(w.cget("to")), "aus": _aus(w)}
    if k in ("TProgressbar",):
        return {"typ": "fortschritt", "pfad": p, "wert": float(w.cget("value") or 0),
                "max": float(w.cget("maximum") or 100)}
    if k == "Text":
        return {"typ": "protokoll", "pfad": p, "text": w.get("1.0", "end-1c")[-6000:]}
    if k == "Listbox":
        return {"typ": "liste", "pfad": p, "zeilen": list(w.get(0, "end")), "gewaehlt": list(w.curselection())}
    if k == "Treeview":
        cols = list(w.cget("columns") or ())
        return {"typ": "tabelle", "pfad": p, "spalten": [w.heading(c, "text") or c for c in cols],
                "zeilen": [{"id": i, "werte": [str(v) for v in w.item(i, "values")]} for i in w.get_children()],
                "gewaehlt": list(w.selection())}
    if k == "Canvas":
        return {"typ": "zeichnung", "pfad": p, "svg": _canvas_svg(w)}
    # Behaelter: Frame, LabelFrame, Toplevel-Inhalt
    kinder = _ordnen(w)
    titel = _text(w) if k in ("Labelframe", "TLabelframe") else ""
    if not kinder and not titel:
        return None
    return {"typ": "gruppe", "pfad": p, "titel": titel, "kinder": kinder, "rahmen": bool(titel),
            "ton": _ton(_farbe(w, "background"))}


def _ordnen(w):
    """Kinder in Lese-Reihenfolge: pack (oben/unten = Zeilen, links/rechts = nebeneinander), grid (Zeilen)."""
    out = []
    try:
        gepackt = w.pack_slaves()
    except tk.TclError:
        gepackt = []
    zeile, rechts, unten = [], [], []

    def zeile_schliessen():
        nonlocal zeile, rechts
        if zeile or rechts:
            out.append({"typ": "zeile", "kinder": zeile + ([{"typ": "luecke"}] if rechts else []) + rechts[::-1]})
        zeile, rechts = [], []
    for c in gepackt:
        n = knoten(c)
        if n is None:
            continue
        side = str(c.pack_info().get("side", "top"))
        if side == "left":
            zeile.append(n)
        elif side == "right":
            rechts.append(n)
        elif side == "bottom":
            unten.insert(0, n)
        else:
            zeile_schliessen()
            out.append(n)
    zeile_schliessen()
    out.extend(unten)
    try:
        gitter = w.grid_slaves()
    except tk.TclError:
        gitter = []
    if gitter:
        zeilen = {}
        for c in gitter:
            info = c.grid_info()
            zeilen.setdefault(int(info.get("row", 0)), []).append((int(info.get("column", 0)), c))
        for r in sorted(zeilen):
            ks = [knoten(c) for _, c in sorted(zeilen[r], key=lambda t: t[0])]
            ks = [n for n in ks if n is not None]
            if ks:
                out.append({"typ": "zeile", "kinder": ks, "gitter": True} if len(ks) > 1 else ks[0])
    try:
        for c in w.place_slaves():
            n = knoten(c)
            if n is not None:
                out.append(n)
    except tk.TclError:
        pass
    return out


def zustand(fid):
    def run():
        _kinder_aufnehmen()
        win = _fenster(fid)
        return {"id": fid, "titel": win.title(), "baum": knoten(win)}
    return ui_call(run)


def aktion(fid, pfad, art="klick", wert=None, x=None, y=None):
    """Element im gespiegelten Fenster bedienen. Knoepfe laufen ohne Warten (sie koennen Rueckfragen stellen)."""
    def finden():
        return _widget(fid, pfad)
    if art == "klick":
        w = ui_call(finden)
        ui_spaeter(w.invoke)
        return {"ok": True}
    if art == "bildklick":
        w = ui_call(finden)
        ui_spaeter(lambda: w.web_klick(float(x), float(y)))
        return {"ok": True}

    def setzen():
        w = finden()
        k = w.winfo_class()
        if k == "TCombobox":
            w.set(str(wert))
            w.event_generate("<<ComboboxSelected>>")
        elif k in ("Entry", "TEntry", "Spinbox", "TSpinbox"):
            st = str(w.cget("state"))
            if st == "readonly":
                w.configure(state="normal")
            w.delete(0, "end")
            w.insert(0, str(wert))
            if st == "readonly":
                w.configure(state=st)
            w.event_generate("<Return>")
            w.event_generate("<FocusOut>")
        elif k in ("Scale", "TScale"):
            w.set(float(wert))
        elif k == "Treeview":
            w.selection_set(str(wert))
            w.event_generate("<<TreeviewSelect>>")
        elif k == "Listbox":
            w.selection_clear(0, "end")
            w.selection_set(int(wert))
            w.event_generate("<<ListboxSelect>>")
        elif k == "Canvas":                           # Maus auf Zeichnungen (Arbeitsbereich drehen/zoomen)
            ereignis = {"druck": "<ButtonPress-1>", "zieh": "<B1-Motion>", "los": "<ButtonRelease-1>"}.get(str(wert))
            if ereignis:
                w.event_generate(ereignis, x=int(float(x)), y=int(float(y)))
            elif str(wert) in ("rad+", "rad-"):
                w.event_generate("<MouseWheel>", x=int(float(x or 0)), y=int(float(y or 0)),
                                 delta=120 if wert == "rad+" else -120)
        else:
            raise ValueError(f"{k} laesst sich nicht setzen")
        return {"ok": True}
    return ui_call(setzen)


def bild(fid, pfad, breite=960):
    """JPEG eines Bild-Elements (Kamerabild mit web_bild_quelle, sonst das Tk-Foto als PNG)."""
    def run():
        w = _widget(fid, pfad)
        if hasattr(w, "web_bild_quelle"):
            img = w.web_bild_quelle()
            if img is None:
                return None
            cv2 = LAB.cams.cameras.cv2
            h, b = img.shape[:2]
            if b > breite:
                img = cv2.resize(img, (breite, int(h * breite / b)))
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
            return ("image/jpeg", jpg.tobytes())
        name = str(w.cget("image"))
        if not name:
            return None
        return ("image/png", base64.b64decode(w.tk.call(name, "data", "-format", "png")))
    r = ui_call(run)
    if r is None:
        raise ValueError("Noch kein Bild")
    return {"typ": r[0], "base64": base64.b64encode(r[1]).decode()}


def schliessen(fid):
    def run():
        win = SPIEGEL.get(fid, {}).get("win")
        if win is None or not win.winfo_exists():
            SPIEGEL.pop(fid, None)
            return {"ok": True}
        h = win.protocol("WM_DELETE_WINDOW")
        if h:
            win.tk.call(h)
        else:
            win.destroy()
        return {"ok": True}
    ui_spaeter(run)
    return {"ok": True}


def zeigen(fid):
    """Gespiegeltes Fenster wieder im Harness zeigen (z. B. wenn etwas in der Webseite fehlt)."""
    def run():
        e = SPIEGEL.pop(fid, None)
        if e:
            zurueckholen(e["win"])
        return {"ok": True}
    return ui_call(run)


# ------------------------------------------------------------------------------------------------ Station (Roboter)
def _ros():
    """Das laufende Harness-Modul (ros.py laeuft als __main__; ein zweiter Import wuerde alles neu anlegen)."""
    import sys
    mod = sys.modules.get("__main__")
    if hasattr(mod, "ControlView") and hasattr(mod, "Lab"):
        return mod
    import ros
    return ros


def _tk_label(w):
    try:
        return {"text": str(w.cget("text")), "ton": _ton(_farbe(w, "background"))}
    except tk.TclError:
        return {"text": "", "ton": None}


def station_zustand():
    lab = LAB

    def run():
        R = _ros()
        arme = []
        for key, p in lab.panels.items():
            log = ""
            try:
                log = p.log.get("1.0", "end-1c")[-3000:]
            except tk.TclError:
                pass
            arme.append({
                "arm": key, "label": p.label, "board": p.board.get(), "status": p.status.get(),
                "info": p.remote_info.get(), "badge": _tk_label(p.badge), "quelle": p.source.get(),
                "laeuft": p.running, "stoppt": p.stopping, "modus": p.mode,
                "uebernehmen": {"text": _text(p.take_button), "an": not _aus(p.take_button)},
                "stop_an": not _aus(p.stop_button),
                "ki_modell": p.ki_model and p.ki_model.replace("\\", "/").rsplit("/", 1)[-1], "ki_aufgabe": p.ki_task,
                "fern": p.ctl_text.get() if p.ctl_box.winfo_manager() else "",
                "kameras": [{"slot": s, "name": lab.cams.manager.slots[s]["name"], "key": lab.cam_key(s)}
                            for s in p.slots],
                "log": log})
        return {
            "leader": lab.leader_state.get(), "update": lab.update_note.get(), "sim": bool(getattr(R, "SIM", False)),
            "netz": [lab.net_server.get(), lab.net_down.get(), lab.net_up.get(), lab.net_video.get()],
            "video_an": bool(lab.streamer is not None and getattr(lab.streamer, "running", False)),
            "weitere_kameras": [{"slot": i, "name": s["name"], "oak": str(s.get("device", "")).upper().startswith("OAK")}
                                for i, s in enumerate(lab.cams.manager.slots)
                                if i not in {x for p in lab.panels.values() for x in p.slots}],
            "spannung_an": not _aus(lab.volt_button), "kalibrieren_an": not _aus(lab.calib_button),
            "alle_ablegen_an": not _aus(lab.stop_all_button), "module": lab.module_state.get(),
            "arme": arme}
    return ui_call(run)


def station_quelle(arm, quelle):
    if quelle not in ("lokal", "remote", "ki"):
        raise ValueError("Quelle: lokal, remote oder ki")

    def run():
        p = LAB.panels[arm]
        if p.running:
            raise RuntimeError("Erst ablegen, dann die Steuerung wechseln.")
        p.source.set(quelle)
        LAB.update_buttons()
        return {"ok": True}
    return ui_call(run)


def station_freigabe(arm):
    """Text der Freigabe-Frage (Leader oder KI), die die Webseite vor Ort zeigt."""
    def run():
        p = LAB.panels[arm]
        src = p.source.get()
        if src == "ki":
            fehler, text, _ = LAB.ki_text(arm)
            return {"titel": "KI-Steuerung freigeben", "text": text, "fehler": fehler, "quelle": src}
        if src == "remote":
            return {"titel": "Remote uebernehmen", "quelle": src, "fehler": None,
                    "text": f"{p.label} wird fuer die Fernsteuerung bereitgemacht (langsam). Bist du vor Ort?"}
        others, text = LAB.leader_text(arm)
        return {"titel": "Bewegung freigeben", "text": text, "fehler": None, "quelle": src}
    return ui_call(run)


def station_uebernehmen(arm, zustimmung):
    if zustimmung is not True:
        raise PermissionError("Ohne Zustimmung vor Ort bewegt sich nichts.")

    def pruefen():
        p = LAB.panels[arm]
        if _aus(p.take_button):
            raise RuntimeError(f"Uebernehmen geht gerade nicht: {p.status.get()} · {p.board.get()}")
        return p.source.get()
    src = ui_call(pruefen)
    if src == "remote":
        ui_spaeter(lambda: LAB.take_remote(arm))
    else:
        ui_spaeter(lambda: LAB.take_leader(arm, bestaetigt=True))
    return {"ok": True}


def station_assistent(was, arm=None, slot=None):
    """Harness-Assistent in der Webseite oeffnen (gespiegelt)."""
    R = _ros()
    lab = LAB
    arm = arm or next(iter(lab.panels))
    belegt = ui_call(lambda: lab.process is not None or bool(lab.running()))
    if was in ("kalibrieren", "spannung"):
        offen = [k for k, e in SPIEGEL.items() if e["titel"].lower().startswith(("anschlag", "arme kalib", "spannung"))]
        if belegt:
            raise RuntimeError("Erst alle Arme ablegen. Kalibrieren und Spannung messen brauchen die Ports der Boards.")
        if ui_call(lambda: lab.volt is not None or lab.calib is not None) and not offen:
            raise RuntimeError("Kalibrierung oder Spannungsmessung ist schon im Harness-Fenster offen.")
    if was == "kalibrieren":
        return {"fenster": oeffnen(lab.open_calib)}
    if was == "spannung":
        return {"fenster": oeffnen(lab.open_voltage)}
    if was == "kameras":
        return {"fenster": oeffnen(lambda: R.CameraWizard(lab, [int(slot)] if slot is not None else None))}
    if was == "arbeitsbereich":
        return {"fenster": oeffnen(lambda: R.AreaWindow(lab))}
    if was == "fernzugang":
        if not (lab.remote and lab.remote[0] is not None):
            raise RuntimeError("Der Remote-Server laeuft nicht (startet, sobald ein Arm auf Remote steht).")
        return {"fenster": oeffnen(lambda: R.AccessDialog(lab, arm))}
    if was == "fernzugang_erstellen":
        return {"fenster": oeffnen(lab.remote_access)}
    raise ValueError(f"Unbekannt: {was!r}")


def station_video(an):
    import stream_livekit
    if an:
        cfg, why = stream_livekit.load_config()
        if cfg is None:
            raise RuntimeError(f"LiveKit ist nicht eingerichtet: {why}")

    def run():
        laeuft = LAB.streamer is not None and LAB.streamer.running
        if bool(an) != bool(laeuft):
            LAB.toggle_stream()
        return {"ok": True}
    return ui_call(run)


def station_neustart(sim=None):
    R = _ros()

    def run():
        if LAB.process is not None:
            raise RuntimeError("Erst alle Arme ablegen (Stop), dann neu starten.")
        return True
    ui_call(run)
    neu_sim = (not R.SIM) if sim == "umschalten" else None
    ui_spaeter(lambda: LAB.restart(sim=neu_sim))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ Steuermodus
PLAENE = {}                     # arm -> {"panel", "win", "id", "plan"}


def _plan_klasse():
    import planui
    import tkinter as tk_

    class WebPlanPanel(planui.PlanPanel):
        """Plan-Ansicht fuer die Webseite: gleiche Logik, Kamerabild und Bild-Klicks ueber die Webseite."""
        web_bild = None

        def _build(self):
            super()._build()
            self.cam.web_bild_quelle = lambda: self.web_bild
            self.cam.web_klick = self._web_klick

        def _show(self, img):
            self.web_bild = img
            self._shown = (img.shape[1], img.shape[0])

        def _web_klick(self, fx, fy):
            r, o, _ = self.run.current()
            if self.pending and o and o["art"] == "spezifisch" and 0 <= fx < 1 and 0 <= fy < 1:
                self.lage = (int(3 * fy), int(3 * fx))
                self.refresh_all()

        def _enlarge_frame(self, r, order, frame=None):
            if frame is None:
                frame = self._last_frame(r, order, self._review_dataset())
            if frame is None:
                messagebox.showinfo("Letztes Bild", "Das Kameravideo ist nicht verfügbar.", parent=self)
                return
            win = tk_.Toplevel(self)
            win.title(f"Letztes Bild · Runde {r['runde']} · {order.get('episode', 'aktuelle Aufnahme')}")
            lbl = tk_.Label(win, text="")
            lbl.web_bild_quelle = lambda: frame
            lbl.pack()
            tk_.Button(win, text="Schließen", command=win.destroy).pack(pady=4)
    return WebPlanPanel


def steuer_plan(arm, plan_id):
    """Aufnahmeplan im Steuermodus an (plan_id) oder aus (leer). Ergebnis: Spiegel-ID der Plan-Ansicht."""
    def run():
        alt = PLAENE.pop(arm, None)
        if alt:
            try:
                alt["win"].destroy()
            except tk.TclError:
                pass
            SPIEGEL.pop(str(alt["win"]), None)
        if not plan_id:
            return {"spiegel": None}
        win = tk.Toplevel(LAB.root)
        win.title(f"Aufnahmeplan · {LAB.panels[arm].label}")
        fid = aufnehmen(win, "plan")
        view = types.SimpleNamespace(lab=LAB, key=arm, panel=LAB.panels[arm])
        try:
            panel = _plan_klasse()(win, view, plan_id)
        except Exception:
            win.destroy()
            SPIEGEL.pop(fid, None)
            raise
        panel.pack(fill="both", expand=True)
        PLAENE[arm] = {"panel": panel, "win": win, "id": plan_id, "spiegel": fid}
        return {"spiegel": fid}
    return ui_call(run, timeout=20)


def _startpose(arm):
    from ki import poses
    start = poses.load().get(arm, {}).get("_start")
    state = LAB.arm_state(arm)
    if start is None:
        return {"text": "noch keine festgelegt", "ok": None}
    if state is None:
        return {"text": "Abstand erst sichtbar, wenn der Arm dem Leader folgt", "ok": None}
    deg = [abs(a - b) * 360 / 4096 for a, b in zip(state, start)]
    ok = all(d <= 4.0 for d in deg[:5]) and deg[5] <= 10
    names = ("Bas", "Sch", "Ell", "HdB", "HdD", "Gr")
    return {"text": "  ".join(f"{n} {d:4.1f}°" for n, d in zip(names, deg)), "ok": ok}


def steuer_zustand(arm):
    def run():
        from ki import history, episodes as ep_mod
        from aufnahme import plan as plan_mod
        p = LAB.panels[arm]
        rec = LAB.recorders.get(arm)
        st = rec.state if rec else "bereit"
        folgt = p.running and p.mode == "lokal" and p.status.get().startswith("Folgt")
        ds = getattr(p, "web_dataset", None)
        pl = PLAENE.get(arm)
        return {
            "arm": arm, "label": p.label, "status": p.status.get(), "badge": _tk_label(p.badge),
            "laeuft": p.running, "folgt": folgt, "quelle": p.source.get(),
            "uebernehmen": {"text": _text(p.take_button), "an": not _aus(p.take_button)},
            "stop_an": not _aus(p.stop_button),
            "aufnahme": {"zustand": st, "sekunden": round((rec.frames if rec else 0) / 30, 1),
                         "episoden": len(ds.episodes()) if ds is not None else None,
                         "datensatz": ds.meta.get("name") if ds is not None else None},
            "eingabe": {"datensatz": getattr(p, "rec_name", ""), "aufgabe": getattr(p, "rec_task", "")},
            "optionen": {"datensatz": history.options("datensatz", [d.meta.get("name") for d in ep_mod.datasets()]),
                         "aufgabe": history.options("aufgabe", [d.meta.get("task") for d in ep_mod.datasets()])},
            "startpose": _startpose(arm),
            "plaene": [{"id": i, "name": n} for i, n in plan_mod.definitions()],
            "plan": {"id": pl["id"], "spiegel": pl["spiegel"]} if pl else None,
            "kameras": [{"slot": s, "name": LAB.cams.manager.slots[s]["name"], "key": LAB.cam_key(s)}
                        for s in p.slots]}
    return ui_call(run)


def steuer_aufnahme(arm, aktion, datensatz=None, aufgabe=None):
    """start / stop / behalten / verwerfen. Mit Aufnahmeplan steuert die Plan-Ansicht die Episoden."""
    pl = PLAENE.get(arm)

    def run():
        from ki import history
        p = LAB.panels[arm]
        if pl:
            panel = pl["panel"]
            {"start": panel.key_start, "stop": panel.key_stop,
             "behalten": lambda: panel.decide(True), "verwerfen": lambda: panel.decide(False)}[aktion]()
            return {"ok": True}
        if aktion == "start":
            p.rec_name, p.rec_task = datensatz or "", aufgabe or ""
            history.remember(p.rec_name, p.rec_task)
            p.web_dataset = LAB.record_start(arm, p.rec_name, p.rec_task)
        elif aktion == "stop":
            LAB.record_stop(arm)
        elif aktion in ("behalten", "verwerfen"):
            LAB.record_decide(arm, aktion == "behalten")
        else:
            raise ValueError("Aktion: start, stop, behalten, verwerfen")
        return {"ok": True}
    if pl:                                       # Plan-Knoepfe koennen Rueckfragen stellen
        ui_spaeter(run)
        return {"ok": True}
    return ui_call(run)


def steuer_taste(arm, taste):
    """Tasten der Plan-Ansicht: F3 (bereit), F4 (nicht greifbar), 1-9 (Lage)."""
    pl = PLAENE.get(arm)
    if not pl:
        return {"ok": False}
    panel = pl["panel"]
    if taste == "F3":
        ui_spaeter(panel.key_ready)
    elif taste == "F4":
        ui_spaeter(panel.not_graspable)
    elif str(taste).isdigit() and 1 <= int(taste) <= 9:
        ui_spaeter(lambda: panel.key_lage(int(taste)))
    return {"ok": True}


def steuer_startpose(arm, zustimmung):
    if zustimmung is not True:
        raise PermissionError("Bitte bestaetigen.")

    def run():
        from ki import poses
        state = LAB.arm_state(arm)
        if state is None:
            raise RuntimeError("Keine aktuelle Stellung: der Arm muss dem Leader folgen.")
        poses.save_pose(arm, "_start", state)
        return {"ok": True}
    return ui_call(run)


# ------------------------------------------------------------------------------------------------ Skills
def skills_anmelden(reg, lab):
    """Befehle fuer die Weboberflaeche. Nur lokal (nicht remote, nicht fuer den Agenten)."""
    arm_p = {"arm": {"type": "string", "enum": list(lab.panels)}}
    nur_hier = dict(remote_ok=False, agent_ok=False)

    def bes(fn):
        def f(*a, **kw):
            besuch()
            return fn(*a, **kw)
        return f

    reg.skill("web.zustand", "Weboberflaeche: Fragen, Meldungen und gespiegelte Fenster.",
              {"nach": {"type": "number"}}, **nur_hier)(bes(lambda nach=0: {**fragen_und_meldungen(nach),
                                                                            "fenster": liste()}))
    reg.skill("web.antwort", "Antwort auf eine Rueckfrage (vor Ort).", {"id": {"type": "integer"},
              "antwort": {"type": "boolean"}}, ["id", "antwort"], **nur_hier)(bes(antworten))
    reg.skill("spiegel.zustand", "Inhalt eines gespiegelten Harness-Fensters.", {"id": {"type": "string"}}, ["id"],
              **nur_hier)(bes(zustand))
    reg.skill("spiegel.aktion", "Element eines gespiegelten Fensters bedienen.",
              {"id": {"type": "string"}, "pfad": {"type": "string"}, "art": {"type": "string"}, "wert": {},
               "x": {"type": "number"}, "y": {"type": "number"}}, ["id", "pfad"], **nur_hier)(bes(aktion))
    reg.skill("spiegel.bild", "Bild eines gespiegelten Fensters.", {"id": {"type": "string"},
              "pfad": {"type": "string"}, "breite": {"type": "integer"}}, ["id", "pfad"], **nur_hier)(bes(bild))
    reg.skill("spiegel.schliessen", "Gespiegeltes Fenster schliessen.", {"id": {"type": "string"}}, ["id"],
              **nur_hier)(bes(schliessen))
    reg.skill("spiegel.zeigen", "Gespiegeltes Fenster im Harness zeigen.", {"id": {"type": "string"}}, ["id"],
              **nur_hier)(bes(zeigen))
    reg.skill("station.zustand", "Alles aus dem Harness-Fenster: Leader, Boards, Arme, Netz.", **nur_hier)(
        bes(station_zustand))
    reg.skill("station.quelle", "Steuerung eines Arms waehlen: lokal (Leader), remote oder ki.",
              {**arm_p, "quelle": {"type": "string"}}, ["arm", "quelle"], **nur_hier)(bes(station_quelle))
    reg.skill("station.freigabe", "Text der Freigabe-Frage vor dem Uebernehmen.", arm_p, ["arm"], **nur_hier)(
        bes(station_freigabe))
    reg.skill("station.uebernehmen", "Leader/KI/Remote uebernehmen, NACH Zustimmung vor Ort (zustimmung=true).",
              {**arm_p, "zustimmung": {"type": "boolean"}}, ["arm", "zustimmung"], **nur_hier)(bes(station_uebernehmen))
    reg.skill("station.assistent", "Harness-Assistent in der Webseite oeffnen: kalibrieren, kameras, spannung, "
              "arbeitsbereich, fernzugang, fernzugang_erstellen.",
              {"was": {"type": "string"}, "arm": {"type": "string"}, "slot": {"type": "integer"}}, ["was"],
              **nur_hier)(bes(station_assistent))
    reg.skill("station.video", "Video-Streaming (LiveKit) an/aus.", {"an": {"type": "boolean"}}, ["an"], **nur_hier)(
        bes(station_video))
    reg.skill("station.neustart", "Harness neu starten (sim='umschalten' wechselt Simulation/echte Arme).",
              {"sim": {"type": "string"}}, **nur_hier)(bes(station_neustart))
    reg.skill("steuer.zustand", "Steuermodus eines Arms: Status, Aufnahme, Startpose, Plaene.", arm_p, ["arm"],
              **nur_hier)(bes(steuer_zustand))
    reg.skill("steuer.aufnahme", "Aufnahme: start, stop, behalten, verwerfen.",
              {**arm_p, "aktion": {"type": "string"}, "datensatz": {"type": "string"}, "aufgabe": {"type": "string"}},
              ["arm", "aktion"], **nur_hier)(bes(steuer_aufnahme))
    reg.skill("steuer.plan", "Aufnahmeplan im Steuermodus waehlen (leer = ohne Plan).",
              {**arm_p, "plan": {"type": "string"}}, ["arm"], **nur_hier)(bes(lambda arm, plan="": steuer_plan(arm, plan)))
    reg.skill("steuer.taste", "Taste der Plan-Ansicht: F3, F4, 1-9.", {**arm_p, "taste": {"type": "string"}},
              ["arm", "taste"], **nur_hier)(bes(steuer_taste))
    reg.skill("steuer.startpose", "Aktuelle Stellung als Startpose speichern (nach Bestaetigung).",
              {**arm_p, "zustimmung": {"type": "boolean"}}, ["arm", "zustimmung"], **nur_hier)(bes(steuer_startpose))
