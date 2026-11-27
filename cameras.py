"""Kameras: vier feste Plaetze, jede Kamera in einem eigenen Thread, abrufbar ist immer das neueste Bild.
Kein Zugriff auf den Servo-Bus. Wiederverwendbar fuer Testfenster, Aufzeichnung und spaeter Streaming.

Zuordnung: Die vier Kameras sind baugleich (Innomaker U20CAM), also unterscheidet nur der USB-Anschluss
sie. Jede Kamera muss deshalb immer am selben USB-Port stecken. config.json:

  "cameras": [
    {"name": "Uebersicht", "device": "USB\\VID_0C45&PID_6366&MI_00\\9&13CADBFD&0&0000"},
    ... (vier Eintraege; "device" leer = noch nicht zugeordnet)
  ]

Die OpenCV-Nummer einer Kamera (Media Foundation) wechselt beim An- und Abstecken; deshalb wird
sie bei jedem Abgleich ueber die Geraete-ID neu bestimmt.
"""
import ctypes, json, re, subprocess, sys, threading, time
try:
    from ctypes import wintypes
except (ImportError, ValueError):      # nicht Windows
    wintypes = None
from pathlib import Path

try:
    import cv2
except ImportError:          # Testfenster laeuft auch ohne OpenCV, nur ohne Kamerabilder
    cv2 = None

HERE = Path(__file__).resolve().parent
SLOTS = 4

# Status eines Platzes (fuer die Anzeige)
MISSING = "Kamera fehlt · Anschluss pruefen"
UNASSIGNED = "nicht zugeordnet"
STARTING = "verbinde ..."
NO_SIGNAL = "kein Signal · Kabel pruefen"
LIVE = "live"


# --- Media-Foundation-Geraeteliste (gleiche Reihenfolge wie OpenCV CAP_MSMF) ---
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        h = text.strip("{}").replace("-", "")
        self.Data1, self.Data2, self.Data3 = int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16)
        for i in range(8):
            self.Data4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)


SOURCE_TYPE = GUID("c60ac5fe-252a-478f-a0ef-bc8fa5f7cad3")
SOURCE_TYPE_VIDCAP = GUID("8ac3587a-4ae7-42d8-99e0-0a6013eef90f")
VIDCAP_SYMBOLIC_LINK = GUID("58f0aad8-22bf-4f8a-bb3d-d2c4978c6e2f")
FRIENDLY_NAME = GUID("60d0e559-52f8-4fa2-bbce-acdb34a8ec01")


def _vcall(obj, index, restype, *args):
    """Aufruf einer COM-Methode ueber die vtable. args: ctypes-Objekte, uebergeben per Adresse."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *[ctypes.c_void_p] * len(args))
    return proto(vtbl[index])(obj, *[ctypes.addressof(a) for a in args])


_mf_lock = threading.Lock()
_mf_ready = False


def list_devices():
    """[(opencv_index, geraete_id, name)] in Media-Foundation-Reihenfolge. Leer, wenn nicht ermittelbar.
    Dazu OAK-D-Kameras (depthai), falls installiert: Index "oak:<id>", Geraete-ID "OAK"."""
    out = mac_devices() if sys.platform == "darwin" else _windows_devices()
    try:
        import oak
        out = list(out) + oak.geraete()
    except Exception:
        pass
    return out


def neue_kamera(index, device="", **kw):
    """Passende Aufnahme fuer ein Geraet: OAK-D ueber depthai, sonst OpenCV."""
    if isinstance(index, str) and index.startswith("oak:"):
        import oak
        return oak.OakKamera(index, device, **kw)
    return Camera(index, device, **kw)


def mac_devices(run=subprocess.run):
    """macOS: Kameras aus 'system_profiler SPCameraDataType' (gleiche Reihenfolge wie OpenCV/AVFoundation).
    Geraete-ID = 'MAC:' + Unique-ID der Kamera (bleibt gleich, solange sie am selben USB-Anschluss steckt)."""
    try:
        out = run(["system_profiler", "SPCameraDataType", "-json"], capture_output=True, text=True, timeout=10).stdout
        cams = json.loads(out or "{}").get("SPCameraDataType", [])
    except Exception:
        return []
    devices = []
    for i, c in enumerate(cams):
        uid = str(c.get("spcamera_unique-id") or c.get("spcamera_model-id") or f"index{i}")
        devices.append((i, "MAC:" + uid.upper(), str(c.get("_name") or f"Kamera {i + 1}")))
    return devices


def capture_backend():
    """OpenCV-Schnittstelle je System: Windows Media Foundation, macOS AVFoundation, sonst Standard."""
    if cv2 is None:
        return 0
    if sys.platform == "win32":
        return cv2.CAP_MSMF
    if sys.platform == "darwin":
        return getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)
    return cv2.CAP_ANY


def _windows_devices():
    global _mf_ready
    try:
        ole32 = ctypes.windll.ole32
        mfplat = ctypes.windll.mfplat
        mf = ctypes.windll.mf
    except (AttributeError, OSError):
        return []
    with _mf_lock:
        ole32.CoInitializeEx(None, 0)                 # schon initialisiert ist kein Fehler
        if not _mf_ready:
            if mfplat.MFStartup(0x00020070, 0) != 0:
                return []
            _mf_ready = True
        attrs = ctypes.c_void_p()
        if mfplat.MFCreateAttributes(ctypes.byref(attrs), 1) != 0:
            return []
        devices = []
        try:
            # IMFAttributes::SetGUID = vtable 24
            _vcall(attrs, 24, ctypes.c_long, SOURCE_TYPE, SOURCE_TYPE_VIDCAP)
            arr = ctypes.POINTER(ctypes.c_void_p)()
            count = wintypes.UINT()
            if mf.MFEnumDeviceSources(attrs, ctypes.byref(arr), ctypes.byref(count)) != 0:
                return []
            for i in range(count.value):
                act = ctypes.c_void_p(arr[i])
                vals = []
                for key in (VIDCAP_SYMBOLIC_LINK, FRIENDLY_NAME):
                    s = ctypes.c_wchar_p()
                    n = wintypes.UINT()
                    # IMFAttributes::GetAllocatedString = vtable 13
                    hr = _vcall(act, 13, ctypes.c_long, key, s, n)
                    vals.append(s.value if hr == 0 else "")
                    if hr == 0:
                        ole32.CoTaskMemFree(s)
                _vcall(act, 2, wintypes.ULONG)          # Release
                devices.append((i, device_id(vals[0]), vals[1]))
            ole32.CoTaskMemFree(arr)
        finally:
            _vcall(attrs, 2, wintypes.ULONG)
        return devices


def device_id(symbolic_link):
    r"""\\?\usb#vid_0c45&pid_6366&mi_00#9&183af011&0&0000#{...}\global -> USB\VID_0C45&PID_6366&MI_00\9&183AF011&0&0000"""
    m = re.match(r"\\\\\?\\([^#]+)#([^#]+)#([^#]+)#", symbolic_link or "")
    if not m:
        return (symbolic_link or "").upper()
    return "\\".join(m.groups()).upper()


# --- Konfiguration ---
def load_slots():
    """Vier Plaetze [{'name', 'device'}], fehlende werden aufgefuellt."""
    try:
        cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        raw = cfg.get("cameras", [])
    except (OSError, ValueError):
        raw = []
    slots = []
    for i in range(SLOTS):
        e = raw[i] if isinstance(raw, list) and i < len(raw) and isinstance(raw[i], dict) else {}
        slots.append({"name": str(e.get("name") or f"Kamera {i + 1}"), "device": str(e.get("device") or "").upper()})
    return slots


def assign(slots, devices):
    """Ordnet erkannte Geraete den Plaetzen zu: erst feste Zuordnung aus der Konfiguration, dann
    noch unbekannte Geraete der Reihe nach auf freie Plaetze (vorlaeufig, bis sie benannt sind).
    Gibt [(opencv_index oder None, geraete_id, fest_zugeordnet)] je Platz zurueck."""
    by_id = {d[1]: d[0] for d in devices}
    known = {s["device"] for s in slots if s["device"]}
    spare = [d for d in devices if d[1] not in known]
    out = []
    for s in slots:
        if s["device"]:
            out.append((by_id.get(s["device"]), s["device"], True))
        elif spare:
            idx, dev, _ = spare.pop(0)
            out.append((idx, dev, False))
        else:
            out.append((None, "", False))
    return out


# --- Aufnahme ---
_open_lock = threading.Lock()


class Camera:
    def __init__(self, index, device="", width=1280, height=720, fps=30):
        self.index, self.device = index, device
        self.width, self.height, self.fps = width, height, fps
        self.frame = None
        self.frame_time = None
        self.rate = 0.0
        self.error = None
        self.opened = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.settings = None                    # nach lock(): gelesene Werte (Belichtung, Weissabgleich, Fokus)
        self._lock_req = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"camera{index}")

    def start(self):
        self._thread.start()
        return self

    def stop(self, wait=True):
        self._stop.set()
        if wait:
            self._thread.join(timeout=2)

    @property
    def alive(self):
        return self._thread.is_alive()

    def latest(self):
        with self._lock:
            return self.frame, self.frame_time

    def lock(self, timeout=1.5):
        """Belichtung, Weissabgleich und Fokus auf die aktuellen Werte festsetzen (soweit die Kamera es kann).
        Laeuft im Kamera-Thread; gibt die gelesenen Werte zurueck (None = keine Antwort)."""
        self.settings = None
        self._lock_req.set()
        t = time.monotonic()
        while self.settings is None and time.monotonic() - t < timeout:
            time.sleep(0.05)
        return self.settings

    def _apply_lock(self, cap):
        props = {"belichtung": cv2.CAP_PROP_EXPOSURE, "weissabgleich": cv2.CAP_PROP_WB_TEMPERATURE,
                 "fokus": cv2.CAP_PROP_FOCUS}
        values = {k: cap.get(v) for k, v in props.items()}
        result = {}
        for name, auto, prop in (("belichtung", cv2.CAP_PROP_AUTO_EXPOSURE, cv2.CAP_PROP_EXPOSURE),
                                 ("weissabgleich", cv2.CAP_PROP_AUTO_WB, cv2.CAP_PROP_WB_TEMPERATURE),
                                 ("fokus", cv2.CAP_PROP_AUTOFOCUS, cv2.CAP_PROP_FOCUS)):
            ok_auto = cap.set(auto, 0)                          # Automatik aus
            ok_val = cap.set(prop, values[name]) if values[name] not in (None, -1) else False
            result[name] = {"wert": values[name], "fest": bool(ok_auto or ok_val)}
        self.settings = result

    def _run(self):
        if cv2 is None:
            self.error = "OpenCV fehlt (pip install opencv-python)"
            return
        # Media Foundation: 30 fps in 1280x720 (MJPG). DirectShow liefert hier nur YUY2 mit 10 fps.
        # Oeffnen dauert ca. 4,5 s je Kamera; nacheinander, damit sie sich nicht gegenseitig blockieren.
        with _open_lock:
            if self._stop.is_set():
                return
            cap = cv2.VideoCapture(self.index, capture_backend())
            if not cap.isOpened():
                self.error = "laesst sich nicht oeffnen"
                cap.release()
                return
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.opened = True
        n, t0, fails = 0, time.monotonic(), 0
        try:
            while not self._stop.is_set():
                if self._lock_req.is_set():
                    self._lock_req.clear()
                    try:
                        self._apply_lock(cap)
                    except Exception as exc:
                        self.settings = {"fehler": str(exc)}
                ok, frame = cap.read()
                now = time.monotonic()
                if not ok:
                    fails += 1
                    if fails > 30:
                        self.error = "liefert keine Bilder mehr"
                        return
                    time.sleep(0.03)
                    continue
                fails = 0
                self.error = None
                with self._lock:
                    self.frame, self.frame_time = frame, now
                n += 1
                if now - t0 >= 1.0:
                    self.rate, n, t0 = n / (now - t0), 0, now
        finally:
            cap.release()


class CameraManager:
    """Haelt die vier Plaetze aktuell: erkennt An- und Abstecken und startet/stoppt die Aufnahme.
    poll() regelmaessig (z. B. alle 2 s) aus einem Hintergrund-Thread aufrufen."""
    SIGNAL_TIMEOUT = 2.0

    def __init__(self, slots=None, lister=list_devices, factory=None):
        self.slots = slots or load_slots()
        self.lister = lister
        self.factory = factory or neue_kamera
        self.cams = [None] * SLOTS
        self.devices = [""] * SLOTS
        self.fixed = [False] * SLOTS
        self.present = [False] * SLOTS
        self.lock = threading.Lock()

    def poll(self):
        devices = self.lister()
        plan = assign(self.slots, devices)
        with self.lock:
            for i, (idx, dev, fixed) in enumerate(plan):
                cam = self.cams[i]
                self.devices[i], self.fixed[i], self.present[i] = dev, fixed, idx is not None
                # Eine laufende Aufnahme bleibt, auch wenn sich die Nummer durch Abstecken einer
                # anderen Kamera verschoben hat; neu geoeffnet wird nur, was fehlt oder abgebrochen ist.
                same = cam is not None and cam.device == dev and cam.alive
                if idx is None or not same:
                    if cam is not None:
                        cam.stop(wait=False)
                        self.cams[i] = None
                    if idx is not None:
                        self.cams[i] = self.factory(idx, dev).start()

    def status(self, i, now=None):
        """(text, kamera oder None) fuer Platz i."""
        now = time.monotonic() if now is None else now
        with self.lock:
            cam, present, fixed, dev = self.cams[i], self.present[i], self.fixed[i], self.devices[i]
        if not present:
            return (MISSING if self.slots[i]["device"] else UNASSIGNED), None
        if cam is None:
            return STARTING, None
        if cam.error and not cam.alive:
            return f"{NO_SIGNAL} ({cam.error})", cam
        frame, t = cam.latest()
        if frame is None:
            return STARTING, cam
        if now - t > self.SIGNAL_TIMEOUT:
            return NO_SIGNAL, cam
        return (LIVE if fixed else LIVE + " · noch nicht benannt"), cam

    def stop(self):
        with self.lock:
            for cam in self.cams:
                if cam is not None:
                    cam.stop(wait=False)
            self.cams = [None] * SLOTS


# --- Zuordnung per Abdecken (Assistent in ros.py) ---
COVER_RATIO = 0.45        # abgedeckt = Helligkeit unter 45 % des Ausgangswerts ...
COVER_MAX = 45            # ... und absolut dunkel (0-255)
COVER_HOLD_S = 0.7        # so lange dunkel, bevor es zaehlt


def brightness(frame):
    """Mittlere Helligkeit eines Bildes (0-255), grob und schnell."""
    return float(frame[::8, ::8].mean())


class CoverDetector:
    """Findet die eine Kamera, die gerade abgedeckt wird: deutlich dunkler als zu Beginn des Schritts,
    fuer COVER_HOLD_S, und als einzige. Bereits zugeordnete Geraete werden ignoriert."""

    def __init__(self, baselines, ignore=()):
        self.base = {d: b for d, b in baselines.items() if d not in set(ignore)}
        self.since = {}

    def update(self, values, now):
        """values: {geraet: helligkeit}. Gibt das abgedeckte Geraet zurueck oder None."""
        dark = [d for d, v in values.items() if d in self.base
                and v < COVER_MAX and v < COVER_RATIO * max(self.base[d], 1.0)]
        for d in list(self.since):
            if d not in dark:
                del self.since[d]
        for d in dark:
            self.since.setdefault(d, now)
        held = [d for d in dark if now - self.since[d] >= COVER_HOLD_S]
        return held[0] if len(held) == 1 and len(dark) == 1 else None


def complete_assignment(old, new, live):
    """Vollstaendige Zuordnung aus einer teilweisen.
    old: bisherige Geraete je Platz (Liste); new: {platz: geraet} neu zugeordnet; live: angeschlossene Geraete.
    - Neu zugeordnete Plaetze bekommen ihr Geraet.
    - Wird ein Geraet neu vergeben, das bisher ein ANDERER Platz hatte, bekommt dieser Platz das frei gewordene
      Geraet (Tausch) - sonst bleibt er leer.
    - Bleibt am Ende genau ein angeschlossenes Geraet unbenutzt und genau ein Platz ohne angeschlossenes Geraet,
      werden die beiden verbunden (z. B. Kamera an anderem USB-Anschluss).
    Gibt {platz: geraet} fuer alle Plaetze zurueck."""
    result = {i: (old[i] if i < len(old) else "") for i in range(SLOTS)}
    for slot, dev in new.items():
        freed = result[slot]
        for other in range(SLOTS):
            if other != slot and other not in new and result[other] == dev:
                result[other] = freed if freed and freed not in new.values() else ""
        result[slot] = dev
    live = [d for d in live if d]
    unused = [d for d in live if d not in result.values()]
    missing = [i for i in range(SLOTS) if i not in new and result[i] not in live]
    if len(unused) == 1 and len(missing) == 1:
        result[missing[0]] = unused[0]
    return result


def save_assignment(devices_by_slot, path=None):
    """Schreibt die Geraete-IDs der Plaetze in config.json (Namen bleiben)."""
    path = path or (HERE / "config.json")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cams = cfg.get("cameras", [])
    while len(cams) < SLOTS:
        cams.append({"name": f"Kamera {len(cams) + 1}", "device": ""})
    for slot, dev in devices_by_slot.items():
        cams[slot]["device"] = dev
    cfg["cameras"] = cams
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


# --- Schaerfe-Test ---------------------------------------------------------
FOCUS_MIN = 25.0          # darunter: zu wenig Struktur im Bild, kein Urteil moeglich
FOCUS_CLEAR = 600.0       # darueber: sicher scharf, auch ohne Drehen am Objektiv (bewusst hoch)
FOCUS_KEEP = 0.85         # scharf = mindestens 85 % des besten Werts seit Teststart
FOCUS_SWEEP = 1.3         # bester Wert >= 1,3 x schlechtester: Objektiv wurde durch den Fokus gedreht


def sharpness(frame):
    """Schaerfewert: Varianz des Laplace-Bilds im mittleren Bildbereich (hoeher = schaerfer).
    Gerechnet auf fester Groesse, damit Werte zwischen Kameras vergleichbar sind."""
    h, w = frame.shape[:2]
    crop = frame[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    gray = cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class FocusMeter:
    """Begleitet das Scharfstellen: misst laufend, merkt sich den besten Wert und meldet "scharf",
    sobald das Bild nah am besten Wert ist (und das Objektiv einmal durch den Fokus gedreht wurde
    oder das Bild ohnehin sicher scharf ist)."""

    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.value = None
        self.best = 0.0
        self.worst = None

    def update(self, frame):
        v = sharpness(frame)
        self.value = v if self.value is None else self.value + self.alpha * (v - self.value)
        self.best = max(self.best, self.value)
        self.worst = self.value if self.worst is None else min(self.worst, self.value)
        return self.result()

    def result(self):
        v, best = self.value or 0.0, self.best
        swept = self.worst is not None and best >= FOCUS_SWEEP * max(self.worst, 1.0)
        if best < FOCUS_MIN:
            ok, hint = False, "zu wenig Struktur - etwas Kontrastreiches (Schrift) vor die Kamera halten"
        elif v >= FOCUS_CLEAR:
            ok, hint = True, "scharf"
        elif v >= FOCUS_KEEP * best and swept:
            ok, hint = True, "scharf (bester Punkt)"
        elif not swept:
            ok, hint = False, "Objektiv langsam einmal ganz durchdrehen"
        else:
            ok, hint = False, "weiterdrehen - war schon schaerfer"
        return {"value": v, "best": best, "ratio": v / best if best else 0.0, "ok": ok, "hint": hint}


def draw_focus(img, res):
    """Zeichnet Schaerfebalken und Wert unten ins (kleine) Vorschaubild."""
    h, w = img.shape[:2]
    color = (60, 180, 60) if res["ok"] else (40, 160, 230)
    cv2.rectangle(img, (0, h - 26), (w, h), (20, 20, 20), -1)
    bar = int((w - 120) * min(1.0, res["ratio"]))
    cv2.rectangle(img, (8, h - 18), (8 + bar, h - 8), color, -1)
    cv2.rectangle(img, (8, h - 18), (w - 112, h - 8), (200, 200, 200), 1)
    cv2.putText(img, f"{res['value']:.0f}/{res['best']:.0f}", (w - 104, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (235, 235, 235), 1, cv2.LINE_AA)
    return img
