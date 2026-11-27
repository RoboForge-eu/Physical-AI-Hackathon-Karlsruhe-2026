"""Baut die App "RoboForge Fernsteuerung" als fertiges Programm (ohne Python-Installation beim Bediener).

  python build_fernsteuerung.py

Windows: Ergebnis in dist/RoboForge Fernsteuerung/ (Ordner mit .exe) und als ZIP daneben.
macOS:   auf einem Mac ausfuehren (PyInstaller baut immer fuer das System, auf dem er laeuft);
         Ergebnis ist eine .app. Ohne Signatur warnt macOS beim ersten Start (Rechtsklick -> Oeffnen).
"""
import os, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "RoboForge Fernsteuerung"


def main():
    icon = os.path.join(HERE, "icons", "fernsteuerung.ico")
    if sys.platform == "darwin":
        # ICNS kann PNG-Bilder direkt enthalten; sips ist auf jedem Mac vorhanden.
        icon_dir = os.path.join(HERE, "build", "mac-icon")
        os.makedirs(icon_dir, exist_ok=True)
        png = os.path.join(HERE, "icons", "fernsteuerung.png")
        chunks = []
        for size, kind in ((128, b"ic07"), (256, b"ic08"), (512, b"ic09"), (1024, b"ic10")):
            target = os.path.join(icon_dir, f"{size}.png")
            subprocess.run(["sips", "-z", str(size), str(size), png, "--out", target],
                           check=True, stdout=subprocess.DEVNULL)
            with open(target, "rb") as image:
                data = image.read()
            chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
        data = b"".join(chunks)
        icon = os.path.join(HERE, "build", "fernsteuerung.icns")
        with open(icon, "wb") as image:
            image.write(b"icns" + struct.pack(">I", len(data) + 8) + data)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
            "--name", NAME, "--collect-all", "livekit",
            "--icon", icon,
            "--add-data", os.path.join(HERE, "icons") + os.pathsep + "icons",
            # nur, was die App braucht: kein Harness, keine KI, kein Training
            "--exclude-module", "torch", "--exclude-module", "lerobot", "--exclude-module", "matplotlib",
            "--exclude-module", "anthropic", "--exclude-module", "websockets",
            "--distpath", os.path.join(HERE, "build", "neu"), "--workpath", os.path.join(HERE, "build"),
            "--specpath", os.path.join(HERE, "build"),
            os.path.join(HERE, "fernsteuerung.py")]
    # Erst in build/neu bauen: eine laufende App in dist/ sperrt ihre Dateien und darf nicht kaputtgehen
    shutil.rmtree(os.path.join(HERE, "build", "neu"), ignore_errors=True)
    subprocess.run(args, check=True, cwd=HERE)
    fresh = os.path.join(HERE, "build", "neu", NAME)
    out = os.path.join(HERE, "dist", NAME)
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    try:
        if os.path.exists(out):
            shutil.rmtree(out)
        shutil.copytree(fresh, out)
    except OSError:
        out = fresh
        print("Hinweis: dist/ ist belegt (App laeuft noch?) - neue Version liegt in", fresh)
    if sys.platform == "win32":
        zip_base = os.path.join(HERE, "dist", NAME.replace(" ", "_") + "_Windows")
        shutil.make_archive(zip_base, "zip", os.path.dirname(fresh), NAME)
        print("Fertig:", out, "und", zip_base + ".zip")
    elif sys.platform == "darwin":
        app_new, app_out = fresh + ".app", os.path.join(HERE, "dist", NAME + ".app")
        if os.path.exists(app_new):
            shutil.rmtree(app_out, ignore_errors=True)
            shutil.copytree(app_new, app_out, symlinks=True)      # .app enthaelt Verknuepfungen
        print("Fertig:", app_out)
    else:
        print("Fertig:", out)


if __name__ == "__main__":
    main()
