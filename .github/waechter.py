"""Ordner-Waechter (laeuft auf GitHub, nur vom Hauptzweig aus).

Fuer jeden Zweig origin/team/<name>: Ordner teams/<name>/ in main durch den Stand im Team-Zweig ersetzen.
Alles andere aus dem Team-Zweig wird ignoriert. Grosse Dateien und Modell-/Videodateien werden uebersprungen
(die gehoeren auf Hugging Face).
"""
import os, re, shutil, subprocess

MAX_BYTES = 20 * 2**20
SPERRE = (".safetensors", ".pt", ".pth", ".bin", ".ckpt", ".mp4", ".npz", ".onnx")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main():
    branches = [b.strip() for b in git("branch", "-r", "--format=%(refname:short)").splitlines()]
    for b in branches:
        if not b.startswith("origin/team/"):
            continue
        name = b[len("origin/team/"):]
        if not NAME.match(name) or name.startswith("_"):
            print("uebersprungen (Name):", b)
            continue
        ziel = os.path.join("teams", name)
        files = []
        for line in git("ls-tree", "-r", "-l", b, "--", f"teams/{name}/").splitlines():
            meta, path = line.split("\t", 1)
            mode, typ, sha, size = meta.split()
            if typ != "blob" or mode == "120000":
                continue
            if size != "-" and int(size) > MAX_BYTES or path.lower().endswith(SPERRE):
                print("  zu gross / nicht erlaubt:", path)
                continue
            files.append((path, sha))
        if os.path.isdir(ziel):
            shutil.rmtree(ziel)
        for path, sha in files:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = subprocess.run(["git", "cat-file", "blob", sha], check=True, capture_output=True).stdout
            with open(path, "wb") as f:
                f.write(data)
        subprocess.run(["git", "add", "-A", "--", ziel], check=True)
        print(f"{name}: {len(files)} Dateien")


if __name__ == "__main__":
    main()
