"""OAK-D Lite (Luxonis) als zusaetzliche Uebersichtskamera zum Experimentieren.

Die OAK-D Lite ist keine normale Webcam: sie braucht die Bibliothek depthai (pip install depthai). Ohne depthai oder
ohne Geraet passiert nichts, die anderen Kameras laufen normal weiter.

Einbindung: In config.json einen Kamera-Platz mit "device": "OAK" belegen (Hackathon-Vorlage: Platz 3,
"Uebersicht 2 · OAK-D Lite"). Der Harness zeigt dann das Farbbild wie bei jeder Kamera. Zusaetzlich misst die OAK
Entfernungen (Stereo-Tiefe): OakKamera.latest_depth() -> Tiefe in mm je Pixel (oder None).

Unterstuetzt depthai 3.x (aktuell) und 2.x. Getestet ist die Schnittstelle nur ohne Geraet; mit Geraet bitte einmal
pruefen (Harness: Kamera-Kachel zeigt "live").
"""
import threading, time

try:
    import depthai as dai
except Exception:                               # nicht installiert: OAK einfach nicht anbieten
    dai = None

KENNUNG = "OAK"                                 # Geraete-ID im Kamera-Platz (config.json)
_AKTIV = {}                                     # geraete_id -> laufende OakKamera (verschwindet sonst aus der Liste)
_liste_cache = (0.0, [])


def verfuegbar():
    return dai is not None


def _geraete_id(info):
    for name in ("getDeviceId", "getMxId"):
        f = getattr(info, name, None)
        if f:
            try:
                return str(f())
            except Exception:
                pass
    return str(getattr(info, "name", "oak"))


def geraete(max_alter=5.0):
    """[(index, geraete_id, name)] wie cameras.list_devices(). Die erste OAK heisst "OAK", weitere "OAK:<id>"."""
    global _liste_cache
    if dai is None:
        return []
    jetzt = time.monotonic()
    if jetzt - _liste_cache[0] < max_alter:
        gefunden = _liste_cache[1]
    else:
        try:
            gefunden = [_geraete_id(i) for i in dai.Device.getAllAvailableDevices()]
        except Exception:
            gefunden = []
        _liste_cache = (jetzt, gefunden)
    ids = list(dict.fromkeys(list(_AKTIV) + gefunden))   # laufende OAK bleibt in der Liste (sie ist dann "belegt")
    out = []
    for n, mx in enumerate(ids):
        out.append((f"oak:{mx}", KENNUNG if n == 0 else f"{KENNUNG}:{mx}", "OAK-D Lite"))
    return out


def ist_oak(device):
    return str(device or "").upper().startswith(KENNUNG)


class OakKamera:
    """Gleiche Schnittstelle wie cameras.Camera: start, stop, alive, latest, lock, error, rate."""

    def __init__(self, index, device=KENNUNG, width=1280, height=720, fps=30):
        self.index, self.device = index, device
        self.mxid = str(index).split(":", 1)[1] if ":" in str(index) else None
        self.width, self.height, self.fps = width, height, fps
        self.frame = self.frame_time = None
        self.depth = None
        self.rate = 0.0
        self.error = None
        self.opened = False
        self.settings = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"oak-{self.mxid or 'erste'}")

    def start(self):
        self._thread.start()
        return self

    def stop(self, wait=True):
        self._stop.set()
        if wait:
            self._thread.join(timeout=3)

    @property
    def alive(self):
        return self._thread.is_alive()

    def latest(self):
        with self._lock:
            return self.frame, self.frame_time

    def latest_depth(self):
        """Tiefe in Millimetern (uint16, 0 = unbekannt) oder None."""
        with self._lock:
            return self.depth

    def lock(self, timeout=1.5):
        self.settings = {"hinweis": "OAK: Belichtung wird nicht festgesetzt"}
        return self.settings

    def _bild(self, frame, depth=None):
        now = time.monotonic()
        with self._lock:
            self.frame, self.frame_time = frame, now
            if depth is not None:
                self.depth = depth
        self._n += 1
        if now - self._t0 >= 1.0:
            self.rate, self._n, self._t0 = self._n / (now - self._t0), 0, now

    def _run(self):
        if dai is None:
            self.error = "depthai fehlt (pip install depthai)"
            return
        self._n, self._t0 = 0, time.monotonic()
        try:
            if hasattr(dai.node, "XLinkOut"):
                self._run_v2()
            else:
                self._run_v3()
        except Exception as exc:
            self.error = f"OAK: {exc}"
        finally:
            _AKTIV.pop(self.mxid or "erste", None)

    def _geraet_info(self):
        if not self.mxid or self.mxid == "erste":
            return None
        try:
            return dai.DeviceInfo(self.mxid)
        except Exception:
            return None

    def _run_v3(self):
        info = self._geraet_info()
        device = dai.Device(info) if info is not None else dai.Device()
        mx = _geraete_id(device.getDeviceInfo()) if hasattr(device, "getDeviceInfo") else (self.mxid or "erste")
        _AKTIV[mx] = self
        with dai.Pipeline(device) as p:
            cam = p.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            q_rgb = cam.requestOutput((self.width, self.height), dai.ImgFrame.Type.BGR888i, fps=self.fps) \
                .createOutputQueue(maxSize=2, blocking=False)
            q_tiefe = None
            try:                                      # Tiefe ist ein Zusatz; ohne geht es auch
                stereo = p.create(dai.node.StereoDepth).build(autoCreateCameras=True)
                q_tiefe = stereo.depth.createOutputQueue(maxSize=2, blocking=False)
            except Exception:
                q_tiefe = None
            p.start()
            self.opened = True
            while not self._stop.is_set() and p.isRunning():
                msg = q_rgb.tryGet()
                if msg is None:
                    time.sleep(0.005)
                    continue
                d = q_tiefe.tryGet() if q_tiefe is not None else None
                self.error = None
                self._bild(msg.getCvFrame(), d.getFrame() if d is not None else None)

    def _run_v2(self):
        p = dai.Pipeline()
        cam = p.create(dai.node.ColorCamera)
        cam.setBoardSocket(dai.CameraBoardSocket.CAM_A if hasattr(dai.CameraBoardSocket, "CAM_A") else dai.CameraBoardSocket.RGB)
        cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam.setPreviewSize(self.width, self.height)
        cam.setInterleaved(False)
        cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        cam.setFps(self.fps)
        x = p.create(dai.node.XLinkOut)
        x.setStreamName("rgb")
        cam.preview.link(x.input)
        try:
            links, rechts = p.create(dai.node.MonoCamera), p.create(dai.node.MonoCamera)
            links.setBoardSocket(dai.CameraBoardSocket.CAM_B)
            rechts.setBoardSocket(dai.CameraBoardSocket.CAM_C)
            st = p.create(dai.node.StereoDepth)
            links.out.link(st.left)
            rechts.out.link(st.right)
            xd = p.create(dai.node.XLinkOut)
            xd.setStreamName("tiefe")
            st.depth.link(xd.input)
            mit_tiefe = True
        except Exception:
            mit_tiefe = False
        info = self._geraet_info()
        with (dai.Device(p, info) if info is not None else dai.Device(p)) as device:
            _AKTIV[self.mxid or "erste"] = self
            q = device.getOutputQueue("rgb", maxSize=2, blocking=False)
            qd = device.getOutputQueue("tiefe", maxSize=2, blocking=False) if mit_tiefe else None
            self.opened = True
            while not self._stop.is_set():
                msg = q.tryGet()
                if msg is None:
                    time.sleep(0.005)
                    continue
                d = qd.tryGet() if qd is not None else None
                self.error = None
                self._bild(msg.getCvFrame(), d.getFrame() if d is not None else None)
