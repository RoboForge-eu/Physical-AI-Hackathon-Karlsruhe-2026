// Physical AI Harness by RoboForge - Oberfläche. Spricht nur mit dem lokalen Server (/api/...).
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ABSCHNITTE = ["start", "harness", "aufnehmen", "trainieren", "orchestrator", "interface", "teilen", "vorstellen"];
const TITEL = { start: "Start", harness: "Roboter einrichten", aufnehmen: "Daten aufnehmen", trainieren: "VLA trainieren",
  orchestrator: "Orchestrator & Skills", interface: "Euer Interface", teilen: "Teilen", vorstellen: "Vorstellen" };

let Z = null;          // letzter Zustand vom Server
let D = null;          // Daten (Datensätze, Modelle, Plaene, Methoden)
let sichtbar = "start";
let gestartet = false;
let offeneDatei = null;
let gelesenErinnerungen = new Set();

async function api(pfad, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-RF": "1" }, body: JSON.stringify(body) };
  const r = await fetch(pfad, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.fehler || r.statusText);
  return j;
}

function toast(text, fehler = false) {
  const d = document.createElement("div");
  d.textContent = text;
  if (fehler) d.className = "fehler";
  $("#toast").appendChild(d);
  setTimeout(() => d.remove(), fehler ? 7000 : 4000);
}
async function tu(fn, ok) {
  try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, true); }
}
function arbeit(abschnitt, was) { api("/api/arbeit", { abschnitt, was }).catch(() => {}); }

// ---------------- Kopfzeile: Glocke, Profil, Stop ----------------
function panel(id) {
  for (const p of $$(".panel")) if (p.id !== id) p.classList.remove("offen");
  $("#" + id).classList.toggle("offen");
}
$("#glocke").onclick = () => { panel("panel-plan"); for (const e of (Z?.hackathon?.erinnerungen || [])) gelesenErinnerungen.add(e.zeit); zeichneKopf(); };
$("#phase-pille").onclick = () => panel("panel-plan");
$("#profil").onclick = () => panel("panel-profil");
document.addEventListener("click", (e) => {
  if (!e.target.closest(".panel, #glocke, #profil, #phase-pille")) for (const p of $$(".panel")) p.classList.remove("offen");
});
$("#stop").onclick = () => tu(() => api("/api/skill", { name: "notablage" }), "STOP gesendet: alle Arme legen sich ab.");

function zeichneKopf() {
  const h = Z.hackathon || {};
  const ph = h.phasen || [];
  const akt = h.aktuell != null ? ph[h.aktuell] : null;
  const nxt = h.naechste != null ? ph[h.naechste] : null;
  $("#phase-pille").innerHTML = akt ? `<small>Phase bis ${esc(akt.ende)}</small><b>${esc(akt.titel)}</b>` + (nxt ? ` <span>· danach ${esc(nxt.titel)} (${esc(nxt.start)})</span>` : "")
    : `<small>Hackathon</small>${h.heute ? "Plan" : esc((h.datum || "").split("-").reverse().join("."))}`;
  $("#plan-titel").textContent = h.titel || "Hackathon-Plan";
  $("#plan-liste").innerHTML = ph.map((p, i) => `<li data-ab="${esc(p.abschnitt)}" class="${i === h.aktuell ? "jetzt" : (h.heute && h.aktuell != null && i < h.aktuell ? "vorbei" : "")}">
    <span class="zeit">${esc(p.start)}–${esc(p.ende)}</span><span><b>${esc(p.titel)}</b><br><span class="leise klein">${esc(p.text)}</span></span></li>`).join("");
  for (const li of $$("#plan-liste li")) li.onclick = () => { geheZu(li.dataset.ab); panel("panel-plan"); };
  const er = h.erinnerungen || [];
  $("#plan-erinnerungen").innerHTML = er.map((e) => `<div class="erinnerung"><b>${esc(e.zeit)}</b> ${esc(e.text)}</div>`).join("");
  const neu = er.filter((e) => !gelesenErinnerungen.has(e.zeit)).length;
  $("#glocke-zahl").textContent = neu;
  $("#glocke-zahl").classList.toggle("an", neu > 0);
  // Team
  const t = Z.team;
  $("#avatar").textContent = t ? (t.team || "?").replace(/^team\s+/i, "").slice(0, 1).toUpperCase() : "?";
  $("#profil-name").textContent = t ? t.team : "Anmelden";
  $("#profil-inhalt").innerHTML = t ? `<h3>${esc(t.team)}</h3>
    <dl class="kv"><dt>Ordner</dt><dd>teams/${esc(t.ordner)}</dd>
    <dt>Station</dt><dd>${esc(t.station?.name || "-")}</dd>
    <dt>Mitglieder</dt><dd>${esc((t.mitglieder || []).join(", ") || "-")}</dd>
    <dt>Modelle</dt><dd>${esc(t.huggingface?.modell_repo || "-")}</dd>
    <dt>Datensätze</dt><dd>${esc(t.huggingface?.datensatz_repo || "-")}</dd>
    <dt>GitHub</dt><dd>${esc(t.github?.zweig || "-")}</dd>
    <dt>Angemeldet</dt><dd>${esc(t.angemeldet || "")}</dd></dl>
    <div class="zeile" style="margin-top:10px"><button onclick="abmelden()">Abmelden</button></div>`
    : `<h3>Nicht angemeldet</h3><p>Mit dem Team-Code anmelden (Abschnitt 0 · Start).</p><button class="haupt" onclick="geheZu('start')">Zum Anmelden</button>`;
}
async function abmelden() { await tu(() => api("/api/logout", {}), "Abgemeldet."); laden(); }

// ---------------- Navigation und "wo war ich?" ----------------
function geheZu(ab) { const el = document.getElementById(ab); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }
let ansehenTimer = null;
const beob = new IntersectionObserver((eintraege) => {
  for (const e of eintraege) if (e.isIntersecting) sichtbar = e.target.id;
  for (const a of $$("nav.wege a")) a.classList.toggle("aktiv", a.dataset.ab === sichtbar);
  if (!gestartet) return;
  clearTimeout(ansehenTimer);
  ansehenTimer = setTimeout(() => {
    const el = document.getElementById(sichtbar);
    api("/api/ansehen", { abschnitt: sichtbar, scroll: Math.round(window.scrollY - el.offsetTop) }).catch(() => {});
  }, 1200);
}, { rootMargin: "-45% 0px -50% 0px" });
for (const id of ABSCHNITTE) beob.observe(document.getElementById(id));

function zumStartpunkt() {
  const s = Z.start || {};
  const el = document.getElementById(s.abschnitt);
  if (el && s.abschnitt !== "start") {
    window.scrollTo({ top: el.offsetTop - 76 + (s.scroll > 0 ? s.scroll : 0), behavior: "auto" });
    toast(`Weiter bei „${TITEL[s.abschnitt] || s.abschnitt}“ (${s.grund})`);
  }
  setTimeout(() => (gestartet = true), 800);
}

function zeichneNav() {
  const erl = (Z.zustand && Z.zustand.erledigt) || {};
  for (const a of $$("nav.wege a")) a.classList.toggle("erledigt", !!erl[a.dataset.ab] && a.dataset.ab !== sichtbar);
  const g = Z.zustand?.gearbeitet;
  $("#zuletzt").textContent = g ? `Zuletzt: ${g.was} (${new Date(g.zeit * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })})` : "";
  const akt = Z.hackathon?.aktuell != null ? Z.hackathon.phasen[Z.hackathon.aktuell].abschnitt : null;
  for (const s of $$("main section")) s.classList.toggle("markiert", s.id === akt);
}

// ---------------- 0 Start ----------------
function zeichneStart() {
  const t = Z.team;
  $("#aufgabe-text").textContent = (Z.hackathon && Z.hackathon.aufgabe) || "";
  const lb = $("#login-bereich");
  if (t) {
    if (lb.dataset.zustand !== "an:" + t.ordner) {
      lb.dataset.zustand = "an:" + t.ordner;
      lb.innerHTML = `<p style="font-size:20px;font-weight:600;margin:0 0 6px">${esc(t.team)}</p>
        <dl class="kv"><dt>Ordner</dt><dd>teams/${esc(t.ordner)}</dd>${t.station?.name ? `<dt>Station</dt><dd>${esc(t.station.name)}</dd>` : ""}</dl>
        <div class="zeile" style="margin-top:10px"><button class="haupt" onclick="geheZu('harness')">Weiter zu 1 · Roboter</button></div>`;
    }
  } else if (lb.dataset.zustand !== "aus") {
    lb.dataset.zustand = "aus";
    lb.innerHTML = `<p class="klein">Team-Code vom Zettel an eurer Station eingeben. Damit kommen eure Kalibrierung,
      der Team-Ordner und die Zugänge zum Teilen automatisch.</p>
      <div class="zeile"><input id="code" placeholder="z. B. BLAU-4821" style="flex:1;text-transform:uppercase">
      <button class="gelb" id="login-knopf">Anmelden</button></div>
      <p class="klein leise" style="margin-top:8px">${Z.pakete ? Z.pakete + " Team-Paket(e) auf diesem Rechner." : "Noch kein Team-Paket auf diesem Rechner (Ordner stationspakete)."}</p>`;
    const go = async () => {
      const r = await tu(() => api("/api/login", { code: $("#code").value }));
      if (r) { toast(`Willkommen, ${r.team.team}!`); for (const h of r.hinweise || []) toast(h); laden(); }
    };
    $("#login-knopf").onclick = go;
    $("#code").onkeydown = (e) => { if (e.key === "Enter") go(); };
  }
  const g = Z.geraet;
  if (g) {
    $("#geraet-info").innerHTML = `<dl class="kv"><dt>Rechenwerk</dt><dd>${esc(g.name || g.geraet)}${g.speicher_gb ? ` · ${g.speicher_gb} GB` : ""}</dd>
      <dt>System</dt><dd>${esc({ win32: "Windows", darwin: "macOS", linux: "Linux" }[g.system] || g.system)}</dd>
      <dt>KI-Umgebung</dt><dd>${g.ki_umgebung === false ? "fehlt (siehe README)" : "ok"}</dd>
      <dt>Empfehlung</dt><dd>${esc((g.empfehlung || "").toUpperCase())}</dd></dl>
      <p class="klein leise" style="margin:8px 0 0">${esc(g.text || "")}</p>`;
  }
}

// ---------------- 1 Harness ----------------
let kameraTakt = 0;
function zeichneHarness() {
  const h = Z.harness;
  const st = $("#harness-status");
  if (h.verbunden) {
    st.className = "hinweis"; st.innerHTML = `<span class="punkt an"></span> Harness verbunden · ${h.arme.length} Arm(e)`;
  } else {
    st.className = "hinweis warn";
    st.innerHTML = `<span class="punkt aus"></span> Harness läuft nicht. <button class="haupt" onclick="harnessStarten()">Harness starten</button>
      <span class="klein leise">(öffnet das Harness-Fenster; dort werden Bewegungen bestätigt)</span>`;
  }
  const box = $("#arme");
  const sig = JSON.stringify(h.arme.map((a) => [a.arm, a.running, a.status, a.ki_model, a.kameras]));
  if (box.dataset.sig !== sig) {
    box.dataset.sig = sig;
    box.innerHTML = h.arme.map((a) => `<div class="karte" style="margin-bottom:10px">
      <div class="kkopf" style="height:40px"><span class="punkt ${a.running ? "an" : ""}"></span><b>${esc(a.label)}</b>
        <span class="leise">${esc(a.status || "")}</span><span style="flex:1"></span>
        <button class="haupt" onclick="station('leader','${esc(a.arm)}')">Leader übernehmen</button>
        <button onclick="station('steuermodus','${esc(a.arm)}')">Steuermodus</button>
        <button class="gefahr" onclick="ablegen('${esc(a.arm)}')">Stop · ablegen</button></div>
      <div class="kameras">${(a.kameras || []).map((k) => `<div class="kamera"><div class="name"><span>${esc(k)}</span></div>
        <div class="bild"><img data-arm="${esc(a.arm)}" data-kamera="${esc(k)}" alt=""><span class="leer">kein Bild</span></div></div>`).join("")}</div>
    </div>`).join("") || `<p class="leise">Keine Arme gefunden.</p>`;
    const sel = $("#aufnahme-arm"), alt = sel.value;
    sel.innerHTML = h.arme.map((a) => `<option value="${esc(a.arm)}">${esc(a.label)}</option>`).join("");
    if (alt) sel.value = alt;
    sel.hidden = h.arme.length < 2;            // ein Setup pro Team: keine Auswahl noetig
  }
}
function kamerasAktualisieren() {
  if (!Z || !Z.harness.verbunden || !["harness", "aufnehmen"].includes(sichtbar) || document.hidden) return;
  for (const img of $$("#arme img")) {
    const n = new Image();
    n.onload = () => { img.src = n.src; img.nextElementSibling.style.display = "none"; };
    n.onerror = () => { img.removeAttribute("src"); img.nextElementSibling.style.display = ""; };
    n.src = `/api/kamera?arm=${encodeURIComponent(img.dataset.arm)}&kamera=${encodeURIComponent(img.dataset.kamera)}&t=${++kameraTakt}`;
  }
}
setInterval(kamerasAktualisieren, 700);
async function harnessStarten() { await tu(() => api("/api/harness/starten", {}), "Harness startet ... (ca. 10 s)"); }
async function station(was, arm, abschnitt) {
  const args = { was }; if (arm) args.arm = arm;
  await tu(() => api("/api/skill", { name: "station.oeffnen", args, abschnitt: abschnitt || "harness" }),
    was === "leader" || was === "ki" ? "Bitte im Harness-Fenster bestätigen (Mensch vor Ort)." : "Im Harness-Fenster geöffnet.");
}
async function ablegen(arm) { await tu(() => api("/api/skill", { name: "arm.ablegen", args: { arm } }), "Arm legt sich ab."); }

// ---------------- 2 Aufnehmen ----------------
async function zeichnePlan() {
  const id = $("#plan-wahl").value;
  if (!id) return;
  const p = await tu(() => api("/api/plan?id=" + encodeURIComponent(id)));
  if (!p) return;
  const g = p.geometrie, s = 9, W = (g.tisch_breite || 100) * s, H = ((g.tisch_tiefe || 50) + 4) * s;
  const X = (x) => W / 2 + x * s, Y = (y) => H - 2 * s - y * s;
  const ring = (r) => `M ${X(-r)} ${Y(0)} A ${r * s} ${r * s} 0 0 1 ${X(r)} ${Y(0)}`;
  const akt = p.runden.find((r) => r.status !== "fertig");
  const formen = p.runden.map((r) => {
    if (!r.ecken.length) return "";
    const farbe = r === akt ? "#e8b230" : r.status === "fertig" ? "#b98a1c" : "#9ba0a8";
    const op = r === akt ? 0.9 : r.status === "fertig" ? 0.45 : 0.08;
    const rand = `fill="${farbe}" fill-opacity="${op}" stroke="${farbe}" stroke-width="${r === akt ? 3 : 1}"`;
    if (p.objekt && p.objekt.form === "rund")
      return `<circle cx="${X(r.x)}" cy="${Y(r.y)}" r="${(g.laenge / 2) * s}" ${rand}><title>Runde ${r.runde}</title></circle>`;
    const pts = r.ecken.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ");
    return `<polygon points="${pts}" ${rand}><title>Runde ${r.runde}</title></polygon>`;
  }).join("");
  const nr = akt ? `<text x="${X(akt.x)}" y="${Y(akt.y) + 5}" text-anchor="middle" font-weight="800" font-size="15" fill="#111">${akt.runde}</text>` : "";
  $("#plan-karte").innerHTML = `<svg class="plan-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Plan-Karte">
    <path d="${ring(g.r_aussen)} L ${X(g.r_innen)} ${Y(0)} A ${g.r_innen * s} ${g.r_innen * s} 0 0 0 ${X(-g.r_innen)} ${Y(0)} Z" fill="rgba(232,178,48,.05)" stroke="#3a3e45" stroke-dasharray="4 4"/>
    <line x1="0" y1="${Y(0)}" x2="${W}" y2="${Y(0)}" stroke="#6c717a" stroke-width="2"/>
    <rect x="${X(-5)}" y="${Y(0)}" width="${10 * s}" height="${2 * s}" fill="#2a2d32" stroke="#6c717a"/>
    <text x="${X(0)}" y="${Y(0) + 13}" text-anchor="middle" fill="#9ba0a8" font-size="11" font-family="monospace">ARM</text>
    ${formen}${nr}
    <text x="10" y="18" font-size="12" fill="#6c717a" font-family="monospace">Tischkante unten · Kreise ${g.r_innen}–${g.r_aussen} cm um die Armbasis</text></svg>
    <p style="margin:10px 0 4px"><b>${esc(p.name)}</b> · ${p.fertig} von ${p.runden.length} Runden fertig${p.vorschau ? " (Vorschau, noch nicht begonnen)" : ""}
    ${akt ? ` · nächste: <b>Runde ${akt.runde}</b> bei x ${akt.x} cm, y ${akt.y} cm` : ""}</p>
    <p class="klein leise">${esc(p.beschreibung || "")} Datensatz: <code>${esc(p.datensatz)}</code> · empfohlene Methode: ${esc((p.methode || "").toUpperCase())}</p>`;
}
$("#plan-wahl").onchange = zeichnePlan;

// ---------------- Daten (Datensätze, Modelle, Plaene) ----------------
async function datenLaden() {
  const d = await api("/api/daten").catch(() => null);
  if (!d) return;
  const alt = JSON.stringify(D);
  D = d;
  if (alt === JSON.stringify(d)) return;
  const pw = $("#plan-wahl"), pv = pw.value;
  pw.innerHTML = d.plaene.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  pw.value = pv || (d.plaene.find((p) => p.id === "elektrodose") ? "elektrodose" : (d.plaene[0] || {}).id || "");
  if (!pv) zeichnePlan();
  $("#datensaetze").innerHTML = d.datensaetze.length ? `<table><tr><th>Name</th><th>Episoden</th><th>Aufgabe</th></tr>${d.datensaetze.map((s) =>
    `<tr><td><code>${esc(s.name)}</code></td><td>${s.episoden}</td><td>${esc(s.task)}</td></tr>`).join("")}</table>` : `<p class="leise" style="padding:10px;margin:0">Noch keine Aufnahmen.</p>`;
  const ds = $("#tr-datensatz"), dv = ds.value;
  ds.innerHTML = d.datensaetze.map((s) => `<option value="${esc(s.name)}">${esc(s.name)} (${s.episoden})</option>`).join("");
  if (dv) ds.value = dv;
  const ms = $("#tr-methode"), mv = ms.value;
  ms.innerHTML = d.methoden.map((m) => `<option value="${esc(m.key)}">${esc(m.label)}</option>`).join("");
  ms.value = mv || (Z?.geraet?.empfehlung) || "act";
  methodeGewaehlt(!mv);
  $("#modelle").innerHTML = d.modelle.length ? `<table><tr><th>Modell</th><th>Methode</th><th>Datensatz</th><th></th></tr>${d.modelle.map((m) =>
    `<tr><td><code>${esc(m.name)}</code></td><td>${esc(m.method)}</td><td>${esc(m.dataset ? m.dataset.split(/[\\/]/).pop() : "")}</td>
     <td><button onclick="modellTesten('${esc(m.name)}')">Am Arm testen</button></td></tr>`).join("")}</table>` : `<p class="leise" style="padding:10px;margin:0">Noch kein fertiges Modell.</p>`;
  $("#hf-modell").innerHTML = d.modelle.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}</option>`).join("") || `<option value="">(noch kein Modell)</option>`;
  zeichneVorstellung();
}
function methodeGewaehlt(setzeSchritte = true) {
  const m = (D?.methoden || []).find((x) => x.key === $("#tr-methode").value);
  if (!m) return;
  const dev = Z?.geraet?.geraet;
  if (setzeSchritte) $("#tr-schritte").value = dev === "cuda" ? m.default_steps : Math.min(m.default_steps, m.key === "act" ? 20000 : 5000);
  $("#tr-hinweis").textContent = m.description + (dev !== "cuda" && m.key !== "act" ? " Achtung: ohne NVIDIA-Grafikkarte sehr langsam." : "");
}
$("#tr-methode").onchange = () => methodeGewaehlt(true);
$("#tr-start").onclick = async () => {
  const r = await tu(() => api("/api/training/start", { datensatz: $("#tr-datensatz").value, methode: $("#tr-methode").value, schritte: +$("#tr-schritte").value }));
  if (r) toast(`Training ${r.name} gestartet.`);
};
async function modellTesten(name) {
  const arm = $("#aufnahme-arm").value || (Z.harness.arme[0] || {}).arm;
  if (!arm) return toast("Harness nicht verbunden.", true);
  const ok = await tu(() => api("/api/skill", { name: "ki.modell_waehlen", args: { arm, modell: name } }));
  if (ok) station("ki", arm, "trainieren");
}

// ---------------- 3 Trainings ----------------
function zeit(s) { if (s == null) return ""; s = Math.round(s); const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h} h ${m} min` : `${m} min`; }
function zeichneTrainings() {
  const g = Z.geraet;
  if (g) $("#geraet-hinweis").innerHTML = `<b>${esc(g.name || g.geraet)}:</b> ${esc(g.text)}`;
  const tr = Z.training || [];
  const knopf = (t, was, text, cls = "") => `<button class="${cls}" onclick="trAktion('${esc(t.name)}','${was}')">${text}</button>`;
  $("#trainings").innerHTML = tr.length ? `<table><tr><th>Training</th><th>Zustand</th><th>Fortschritt</th><th>Rest</th><th></th></tr>${tr.slice().reverse().map((t) => {
    const pct = t.steps ? Math.min(100, (100 * (t.step || 0)) / t.steps) : 0;
    const farbe = t.state === "fertig" ? "gruen" : t.state === "fehler" ? "rot" : t.state.includes("paus") ? "gelb" : "";
    const aktionen = [
      t.state === "training" ? knopf(t, "pause", "Pausieren") : "",
      t.state.includes("pausiert") ? knopf(t, "fortsetzen", "Fortsetzen", "gelb") : "",
      ["wartet", "training", "umwandeln", "pausiert", "wartet (pausiert)"].includes(t.state) ? knopf(t, "abbrechen", "Abbrechen", "gefahr") : "",
      t.weiter_ab ? knopf(t, "weiter", `Weiter ab ${t.weiter_ab}`, "haupt") : "",
    ].join(" ");
    return `<tr><td><code>${esc(t.name)}</code><br><span class="klein leise">${esc(t.method)} · ${esc(t.dataset)} · ${t.episodes || "?"} Ep.</span></td>
      <td><span class="marke-klein ${farbe}">${esc(t.state)}</span><br><span class="klein leise">${esc((t.message || "").slice(0, 90))}</span></td>
      <td><div class="balken ${t.state === "fertig" ? "gruen" : ""}"><i style="width:${pct}%"></i></div><span class="klein">${t.step || 0} / ${t.steps || "?"}${t.loss != null ? " · Fehler " + Number(t.loss).toFixed(3) : ""}</span></td>
      <td>${zeit(t.eta_s)}</td><td>${aktionen}</td></tr>`;
  }).join("")}</table>` : `<p class="leise" style="padding:10px;margin:0">Noch kein Training.</p>`;
}
async function trAktion(name, was) {
  if (was === "abbrechen" && !confirm(`Training ${name} wirklich abbrechen?`)) return;
  await tu(() => api("/api/training/aktion", { name, was }), "OK");
}

// ---------------- 4 Orchestrator ----------------
async function ladeOrch() {
  const o = await api("/api/orchestrator").catch(() => null);
  if (!o) return;
  $("#orch-status").textContent = o.laeuft ? "läuft" : (o.code != null ? `beendet (${o.code})` : "aus");
  $("#orch-status").className = "marke-klein " + (o.laeuft ? "gruen" : "");
  const log = $("#orch-log"); const unten = log.scrollTop + log.clientHeight >= log.scrollHeight - 10;
  log.textContent = o.log || "Noch keine Ausgabe.";
  if (unten) log.scrollTop = log.scrollHeight;
  const sig = JSON.stringify(o.dateien.map((d) => d.pfad));
  const liste = $("#dateiliste");
  if (liste.dataset.sig !== sig) {
    liste.dataset.sig = sig;
    liste.innerHTML = o.dateien.filter((d) => d.text).map((d) => `<div data-pfad="${esc(d.pfad)}">${esc(d.pfad)}</div>`).join("") || `<div class="leise">Nach dem Anmelden erscheint hier euer Team-Ordner.</div>`;
    for (const el of $$("#dateiliste div[data-pfad]")) el.onclick = () => oeffne(el.dataset.pfad);
  }
  for (const el of $$("#dateiliste div[data-pfad]")) el.classList.toggle("gewaehlt", el.dataset.pfad === offeneDatei);
  if (!offeneDatei && o.dateien.find((d) => d.pfad === "orchestrator.py")) oeffne("orchestrator.py");
}
async function oeffne(pfad) {
  const ta = $("#datei-inhalt");
  if (offeneDatei && ta.dataset.geaendert === "1" && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
  const d = await tu(() => api("/api/datei?pfad=" + encodeURIComponent(pfad)));
  if (!d) return;
  offeneDatei = pfad; ta.value = d.inhalt; ta.dataset.geaendert = "0";
  $("#datei-name").textContent = pfad;
  for (const el of $$("#dateiliste div[data-pfad]")) el.classList.toggle("gewaehlt", el.dataset.pfad === pfad);
}
$("#datei-inhalt").addEventListener("input", (e) => { e.target.dataset.geaendert = "1"; $("#datei-name").textContent = offeneDatei + " ●"; });
$("#datei-inhalt").addEventListener("keydown", (e) => {
  if (e.key === "Tab") { e.preventDefault(); const t = e.target, s = t.selectionStart; t.setRangeText("    ", s, t.selectionEnd, "end"); t.dispatchEvent(new Event("input")); }
  if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); speichern(); }
});
async function speichern() {
  if (!offeneDatei) return;
  const ok = await tu(() => api("/api/datei", { pfad: offeneDatei, inhalt: $("#datei-inhalt").value, abschnitt: "orchestrator" }), "Gespeichert.");
  if (ok) { $("#datei-inhalt").dataset.geaendert = "0"; $("#datei-name").textContent = offeneDatei; }
}
async function neueDatei() {
  const p = prompt("Neue Datei im Team-Ordner, z. B. skills/fach_pruefen.py");
  if (!p) return;
  if (await tu(() => api("/api/datei", { pfad: p, inhalt: "" }))) { await ladeOrch(); oeffne(p); }
}
async function orch(was) {
  if (was === "start" && $("#datei-inhalt").dataset.geaendert === "1") await speichern();
  await tu(() => api("/api/orchestrator/" + was, {}), was === "start" ? "Orchestrator gestartet." : "Orchestrator beendet.");
  setTimeout(ladeOrch, 600);
}
async function ladeSkills() {
  const s = await api("/api/skills").catch(() => null);
  if (!s) { $("#skill-liste").innerHTML = `<p class="leise">Harness nicht verbunden.</p>`; return; }
  $("#skill-liste").innerHTML = `<table><tr><th>Skill</th><th>Beschreibung</th></tr>${s.map((x) => {
    const f = x.function || x; return `<tr><td><code>${esc(f.name)}</code></td><td>${esc(f.description)}</td></tr>`; }).join("")}</table>`;
}

// ---------------- 6 Teilen ----------------
async function teilen(was) {
  const body = was === "code" ? { nachricht: $("#git-nachricht").value } : was === "modell" ? { modell: $("#hf-modell").value, datensatz: $("#hf-datensatz").checked } : {};
  if (was === "modell" && !body.modell) return toast("Noch kein Modell zum Teilen.", true);
  await tu(() => api("/api/teilen/" + was, body), "Läuft ...");
}
function zeichneTeilen() {
  const a = Z.aufgaben || {};
  for (const [key, el] of [["code", "#log-code"], ["holen", "#log-code"], ["modell", "#log-modell"]]) {
    const st = a[key]; if (!st) continue;
    if (key === "code" && a.holen && a.holen.start > st.start) continue;
    if (key === "holen" && a.code && a.code.start > st.start) continue;
    const pre = $(el); pre.hidden = false;
    pre.textContent = st.zeilen.join("\n") + (st.laeuft ? "\n..." : st.ok ? "\nfertig." : "\nFEHLER");
    pre.scrollTop = pre.scrollHeight;
  }
  const t = Z.team;
  $("#hf-ziel").textContent = t ? `Ziel: huggingface.co/${t.huggingface?.modell_repo || "?"}` : "Bitte zuerst anmelden.";
}
async function gitInfo() {
  const g = await api("/api/git").catch(() => null);
  if (!g) return;
  $("#git-info").innerHTML = g.klon ? `Repo: ${esc(g.url)}<br>Zweig: <b>${esc(g.zweig)}</b>${g.soll_zweig && g.soll_zweig !== g.zweig ? ` (wird beim Hochladen ${esc(g.soll_zweig)})` : ""}`
    : `<span class="marke-klein gelb">nicht möglich</span> ${esc(g.grund)}`;
}

// ---------------- 7 Vorstellen ----------------
let vorstellungText = null;
async function ladeVorstellung() {
  if (!Z.team) { vorstellungText = ""; return zeichneVorstellung(); }
  const d = await api("/api/datei?pfad=vorstellung.md").catch(() => ({ inhalt: "" }));
  vorstellungText = d.inhalt || "";
  if (document.activeElement !== $("#v-edit")) $("#v-edit").value = vorstellungText;
  zeichneVorstellung();
}
function zeichneVorstellung() {
  const t = Z?.team;
  $("#v-team").textContent = t ? t.team : "Euer Team";
  const ep = (D?.datensaetze || []).reduce((n, s) => n + s.episoden, 0);
  const fertig = (Z?.training || []).filter((x) => x.state === "fertig").length;
  $("#v-zahlen").innerHTML = `<div><b>${ep}</b>Episoden aufgenommen</div><div><b>${fertig}</b>Modelle trainiert</div>
    <div><b>${(D?.modelle || []).length}</b>Modelle verfügbar</div>`;
  $("#v-text").textContent = vorstellungText || "Schreibt hier, was euer System kann: Aufgabe, Ablauf, Skills, was gut lief, was nicht.";
}
async function vorstellungSpeichern() {
  if (await tu(() => api("/api/datei", { pfad: "vorstellung.md", inhalt: $("#v-edit").value, abschnitt: "vorstellen" }), "Gespeichert.")) {
    vorstellungText = $("#v-edit").value; zeichneVorstellung();
  }
}
function praesentation() {
  document.body.classList.toggle("praesentation");
  $("#praes-knopf").textContent = document.body.classList.contains("praesentation") ? "Präsentation beenden (Esc)" : "Präsentationsmodus";
  geheZu("vorstellen");
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("praesentation")) praesentation(); });

// ---------------- Takt ----------------
let teamVorher = undefined;
async function laden() {
  try { Z = await api("/api/zustand"); } catch (e) { $("#harness-status").textContent = "Plattform-Server nicht erreichbar."; return; }
  zeichneKopf(); zeichneNav(); zeichneStart(); zeichneHarness(); zeichneTrainings(); zeichneTeilen();
  const teamJetzt = Z.team ? Z.team.ordner : null;
  if (teamJetzt !== teamVorher) {
    teamVorher = teamJetzt; offeneDatei = null;
    $("#team-ordner-hinweis").innerHTML = teamJetzt ? `Euer Team-Ordner: <code>teams/${esc(teamJetzt)}</code> · Dateien hier bearbeiten oder den Ordner im Editor öffnen.`
      : "Bitte zuerst anmelden (Abschnitt 0), dann erscheint hier euer Team-Ordner.";
    $("#team-ui").src = teamJetzt ? "/team-ui/" : "about:blank";
    ladeOrch(); gitInfo(); ladeVorstellung();
  }
  if (!gestartet && !laden.einmal) { laden.einmal = true; zumStartpunkt(); }
}
async function init() {
  await laden();
  await datenLaden();
  ladeSkills();
  setInterval(laden, 2000);
  setInterval(datenLaden, 10000);
  setInterval(() => { if (sichtbar === "orchestrator") ladeOrch(); }, 2000);
  setInterval(() => { if (sichtbar === "teilen") gitInfo(); }, 10000);
}
init();
