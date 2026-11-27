# Fuer Veranstalter: Einrichtung des Repos (einmalig)

1. **Ruleset fuer `main`** (Settings → Rules → Rulesets → New branch ruleset):
   - Ziel: Standardzweig `main`
   - *Restrict updates*, *Restrict deletions*, *Block force pushes* einschalten
   - Bypass: nur **Deploy keys**
2. **Deploy-Key fuer den Waechter:** lokal `ssh-keygen -t ed25519 -f waechter -N ""`.
   - `waechter.pub` → Settings → Deploy keys → *Allow write access*
   - Inhalt von `waechter` (privat) → Settings → Secrets → Actions → `WAECHTER_DEPLOY_KEY`
   - Danach beide Dateien lokal loeschen.
3. **Token fuer die Teams:** Fine-grained Personal Access Token, nur dieses Repo, Berechtigung
   *Contents: Read and write* (NICHT *Workflows*, NICHT *Administration*). Er kommt in die Team-Pakete
   (`github.token`). Wegen des Rulesets kann damit niemand nach `main` schreiben, nur in die Team-Zweige.
4. **Actions** muessen erlaubt sein (Settings → Actions → General). Test: Actions → Ordner-Waechter → *Run workflow*.
5. Nach dem Hackathon: Token loeschen (Settings → Developer settings → Tokens).
