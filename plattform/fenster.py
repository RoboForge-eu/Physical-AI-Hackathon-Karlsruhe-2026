"""Oeffnet die Oberflaeche als eigenes App-Fenster (Edge/Chrome im App-Modus, ohne Adressleiste).

Gibt es keinen passenden Browser, oeffnet sich der normale Standardbrowser.
"""
import os, shutil, subprocess, sys, webbrowser

from . import DATEN

KANDIDATEN_WIN = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
]
KANDIDATEN_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def browser_finden():
    if sys.platform == "win32":
        for k in KANDIDATEN_WIN:
            p = os.path.expandvars(k)
            if os.path.isfile(p):
                return p
    elif sys.platform == "darwin":
        for p in KANDIDATEN_MAC:
            if os.path.isfile(p):
                return p
    for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        p = shutil.which(n)
        if p:
            return p
    return None


def befehl(url, exe):
    profil = os.path.join(DATEN, "app-fenster")     # eigenes Profil: eigenes Fenster, eigene Taskleisten-Gruppe
    # Eigenes, leeres Profil ohne Anmeldung: Edge meldet neue Profile sonst automatisch mit dem Windows-Konto an
    # und zeigt Sync-Hinweise ("Wir synchronisieren jetzt Ihre Browserdaten ..."). Fuer die App unnoetig.
    return [exe, f"--app={url}", f"--user-data-dir={profil}", "--window-size=1500,950",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--disable-features=msImplicitSignin,msEdgeSyncConsent,msShowSyncPromo,SigninPromo",
            "--disable-signin-promo"]


def oeffnen(url):
    exe = browser_finden()
    if not exe:
        webbrowser.open(url)
        return "browser"
    os.makedirs(DATEN, exist_ok=True)
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(befehl(url, exe), **kw)
        return "fenster"
    except OSError:
        webbrowser.open(url)
        return "browser"
