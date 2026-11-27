"""Laeuft in der KI-Umgebung: laedt einen Ordner auf den Hugging Face Hub (Modell oder Datensatz).

Token kommt aus der Umgebungsvariable HF_TOKEN (nie aus der Befehlszeile).

  python plattform/hf_hochladen.py --repo RoboForge/team-blau-modelle --ordner <pfad> --unterordner act-1 --typ model
"""
import argparse, os, sys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ordner", required=True)
    ap.add_argument("--unterordner", default="")
    ap.add_argument("--typ", default="model", choices=["model", "dataset"])
    ap.add_argument("--karte", default="")
    a = ap.parse_args(argv)
    from huggingface_hub import HfApi
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN fehlt", flush=True)
        return 2
    api = HfApi(token=token)
    print(f"Verbinde mit Hugging Face ({a.repo}) ...", flush=True)
    try:
        api.create_repo(a.repo, repo_type=a.typ, exist_ok=True, private=False)
    except Exception as exc:          # fein eingeschraenkter Token darf evtl. nicht anlegen: Repo existiert dann schon
        print(f"Hinweis: Repo anlegen nicht moeglich ({exc.__class__.__name__}), versuche direkt hochzuladen.",
              flush=True)
    sub = a.unterordner.strip("/")
    n = sum(len(f) for _, _, f in os.walk(a.ordner))
    size = sum(os.path.getsize(os.path.join(r, x)) for r, _, fs in os.walk(a.ordner) for x in fs)
    print(f"Lade {n} Dateien hoch ({size / 2**20:.0f} MB) nach {sub or '/'} ...", flush=True)
    api.upload_folder(repo_id=a.repo, repo_type=a.typ, folder_path=a.ordner, path_in_repo=sub or None,
                      commit_message=f"{sub or 'Upload'} (Physical AI Harness)",
                      ignore_patterns=["**/training_state/**", "**/optimizer*", "*.tmp"])
    if a.karte and os.path.exists(a.karte) and os.path.getsize(a.karte):
        api.upload_file(path_or_fileobj=a.karte, path_in_repo=(sub + "/README.md") if sub else "README.md",
                        repo_id=a.repo, repo_type=a.typ, commit_message="Beschreibung")
    print("Hochladen fertig.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
