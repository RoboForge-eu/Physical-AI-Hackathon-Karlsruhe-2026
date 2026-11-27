// Physical AI Harness by RoboForge · Roboter-Station und Steuermodus in der Webseite.
//
// === KERN-DATEI · fuer Hackathon-Teams NICHT zum Umbauen gedacht ===
// Hier steckt die Bedienung des Harness (Arme, Kameras, Kalibrieren, Aufnehmen). Sicherheit: jede Bewegung startet erst
// nach Zustimmung vor Ort (Dialog), Stop/Ablegen geht immer, F12 = alle ablegen.
// Teams erweitern NICHT hier, sondern in teams/<team>/ (Orchestrator, Skills, ui/, plaene/) - siehe AGENTS.md dort.
//
// Bausteine:
//   SpiegelAnsicht  zeigt ein Harness-Fenster (Assistent) als Webinhalt: Texte, Knoepfe, Eingaben, Zeichnungen, Bilder
//   Wache           holt Rueckfragen/Meldungen des Harness und oeffnet neue Assistenten-Fenster
//   Station         Abschnitt "Roboter einrichten" (alles aus dem Harness-Hauptfenster)
//   Steuermodus     Kameras gross + Aufnahme (mit Aufnahmeplan); eingebettet oder im eigenen Fenster (/steuermodus)
"use strict";

const TON_KNOPF = { rot: "gefahr", gruen: "haupt", gelb: "haupt" };

// ================================================================== SpiegelAnsicht
class SpiegelAnsicht {
  constructor(el, fid, { takt = 400, onZu } = {}) {
    this.el = el; this.fid = fid; this.takt = takt; this.onZu = onZu;
    this.sig = ""; this.bilder = {}; this.aus = false; this.ziehZeit = 0;
    el.classList.add("spiegel");
    el.addEventListener("click", (e) => this.klick(e));
    el.addEventListener("change", (e) => this.aendern(e));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("input[data-sp]")) this.aendern(e); });
    el.addEventListener("pointerdown", (e) => this.maus(e, "druck"));
    el.addEventListener("pointermove", (e) => { if (e.buttons) this.maus(e, "zieh"); });
    el.addEventListener("pointerup", (e) => this.maus(e, "los"));
    el.addEventListener("wheel", (e) => { if (e.target.closest(".sp-zeichnung")) { e.preventDefault(); this.maus(e, e.deltaY < 0 ? "rad+" : "rad-"); } }, { passive: false });
    this.laden();
    this.timer = setInterval(() => this.laden(), takt);
    this.bildTimer = setInterval(() => this.bilderLaden(), 220);
  }
  stop() { this.aus = true; clearInterval(this.timer); clearInterval(this.bildTimer); }
  async laden() {
    if (this.aus || this.laedt || document.hidden) return;
    this.laedt = true;
    try {
      const z = await skill("spiegel.zustand", { id: this.fid });
      const sig = JSON.stringify(z.baum);
      if (sig !== this.sig) { this.sig = sig; this.zeichnen(z.baum); }
    } catch (e) {
      if (/geschlossen/.test(e.message)) { this.stop(); if (this.onZu) this.onZu(); }
    } finally { this.laedt = false; }
  }
  zeichnen(baum) {
    const fokus = document.activeElement?.dataset?.sp && this.el.contains(document.activeElement) ? document.activeElement.dataset.sp : null;
    const wert = fokus ? document.activeElement.value : null;
    this.el.innerHTML = baum ? this.html(baum) : `<p class="leise">leer</p>`;
    for (const img of $$("img[data-bild]", this.el)) { const alt = this.bilder[img.dataset.bild]; if (alt) img.src = alt; }
    if (fokus) { const f = $(`[data-sp="${CSS.escape(fokus)}"]`, this.el); if (f) { f.focus(); if (wert != null && "value" in f) f.value = wert; } }
    this.bilderLaden(true);
  }
  html(n) {
    if (!n) return "";
    const kinder = (k) => (k || []).map((c) => this.html(c)).join("");
    const p = esc(n.pfad || "");
    switch (n.typ) {
      case "gruppe":
        return `<div class="sp-gruppe${n.rahmen ? " rahmen" : ""}${n.ton ? " ton-" + n.ton : ""}">${n.titel ? `<div class="sp-titel">${esc(n.titel)}</div>` : ""}${kinder(n.kinder)}</div>`;
      case "zeile":
        return `<div class="sp-zeile${n.gitter ? " gitter" : ""}" style="--n:${(n.kinder || []).length}">${kinder(n.kinder)}</div>`;
      case "luecke": return `<span class="sp-luecke"></span>`;
      case "linie": return `<hr class="sp-linie">`;
      case "text": {
        const cls = ["sp-text", n.fett && "fett", n.groesse >= 14 && "gross", n.groesse >= 18 && "sehr-gross", n.mono && "mono",
          n.ton && "ton-" + n.ton, n.farbe && "farbe-" + n.farbe].filter(Boolean).join(" ");
        return `<div class="${cls}">${esc(n.text)}</div>`;
      }
      case "knopf":
        return `<button data-sp="${p}" data-art="klick" class="${TON_KNOPF[n.ton] || ""}"${n.aus ? " disabled" : ""}>${esc(n.text)}</button>`;
      case "haken":
        return `<label class="sp-haken"><input type="checkbox" data-sp="${p}" data-art="klick"${n.an ? " checked" : ""}${n.aus ? " disabled" : ""}> ${esc(n.text)}</label>`;
      case "wahl":
        return `<button data-sp="${p}" data-art="klick" class="sp-wahl${n.an ? " an" : ""}"${n.aus ? " disabled" : ""}>${esc(n.text)}</button>`;
      case "eingabe":
        if (n.optionen && n.nur_liste)
          return `<select data-sp="${p}" data-art="setzen"${n.aus ? " disabled" : ""}>${n.optionen.map((o) => `<option${o === n.wert ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
        if (n.optionen) {
          const lid = "dl" + Math.random().toString(36).slice(2, 8);
          return `<input data-sp="${p}" data-art="setzen" list="${lid}" value="${esc(n.wert)}"${n.aus ? " disabled" : ""}><datalist id="${lid}">${n.optionen.map((o) => `<option value="${esc(o)}">`).join("")}</datalist>`;
        }
        return `<input data-sp="${p}" data-art="setzen" ${n.zahl ? 'inputmode="decimal" style="width:80px"' : ""} value="${esc(n.wert)}"${n.aus ? " disabled" : ""}>`;
      case "regler":
        return `<input type="range" data-sp="${p}" data-art="setzen" min="${n.von}" max="${n.bis}" step="any" value="${n.wert}"${n.aus ? " disabled" : ""}>`;
      case "fortschritt":
        return `<div class="balken" style="min-width:220px"><i style="width:${Math.min(100, (100 * n.wert) / (n.max || 100))}%"></i></div>`;
      case "protokoll": return `<pre class="log sp-log">${esc(n.text)}</pre>`;
      case "liste":
        return `<div class="sp-liste">${n.zeilen.map((z, i) => `<div data-sp="${p}" data-art="setzen" data-wert="${i}" class="${n.gewaehlt.includes(i) ? "an" : ""}">${esc(z)}</div>`).join("")}</div>`;
      case "tabelle":
        return `<table class="sp-tabelle"><tr>${n.spalten.map((s) => `<th>${esc(s)}</th>`).join("")}</tr>${n.zeilen.map((z) =>
          `<tr data-sp="${p}" data-art="setzen" data-wert="${esc(z.id)}" class="${n.gewaehlt.includes(z.id) ? "an" : ""}">${z.werte.map((w) => `<td>${esc(w)}</td>`).join("")}</tr>`).join("")}</table>`;
      case "zeichnung": return `<div class="sp-zeichnung" data-zeichnung="${p}">${n.svg}</div>`;
      case "bild":
        return `<div class="sp-bild${n.klickbar ? " klickbar" : ""}" data-bildpfad="${p}"><img data-bild="${p}" data-live="${n.foto ? 0 : 1}" alt=""><span class="leer">${esc(n.text || "kein Bild")}</span></div>`;
      default: return "";
    }
  }
  bilderLaden(alle = false) {
    if (this.aus || document.hidden) return;
    for (const img of $$("img[data-bild]", this.el)) {
      if (!alle && img.dataset.live !== "1") continue;
      if (img.dataset.laedt === "1") continue;
      img.dataset.laedt = "1";
      const n = new Image();
      n.onload = () => { img.src = n.src; this.bilder[img.dataset.bild] = n.src; img.nextElementSibling.style.display = "none"; img.dataset.laedt = "0"; };
      n.onerror = () => { img.dataset.laedt = "0"; };
      n.src = `/api/spiegelbild?id=${encodeURIComponent(this.fid)}&pfad=${encodeURIComponent(img.dataset.bild)}&breite=1100&t=${Date.now()}`;
    }
  }
  async aktion(args) {
    try { await skill("spiegel.aktion", { id: this.fid, ...args }); } catch (e) { toast(e.message, true); }
    setTimeout(() => this.laden(), 120);
  }
  klick(e) {
    const bild = e.target.closest(".sp-bild.klickbar img");
    if (bild) {
      const r = bild.getBoundingClientRect();
      return this.aktion({ pfad: bild.dataset.bild, art: "bildklick", x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height });
    }
    const t = e.target.closest("[data-sp]");
    if (!t || t.disabled) return;
    if (t.dataset.art === "klick") { e.preventDefault(); this.aktion({ pfad: t.dataset.sp, art: "klick" }); }
    else if (t.dataset.wert !== undefined) this.aktion({ pfad: t.dataset.sp, art: "setzen", wert: t.dataset.wert });
  }
  aendern(e) {
    const t = e.target.closest("[data-sp][data-art='setzen']");
    if (!t || t.dataset.wert !== undefined) return;
    this.aktion({ pfad: t.dataset.sp, art: "setzen", wert: t.value });
  }
  maus(e, was) {
    const z = e.target.closest(".sp-zeichnung");
    const svg = z && $("svg", z);
    if (!svg) return;
    if (was === "zieh") { const t = performance.now(); if (t - this.ziehZeit < 60) return; this.ziehZeit = t; }
    if (was === "druck") z.setPointerCapture?.(e.pointerId);
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    skill("spiegel.aktion", { id: this.fid, pfad: z.dataset.zeichnung, art: "setzen", wert: was, x: p.x, y: p.y }).catch(() => {});
  }
}

// Assistent als Ueberlagerung (Kalibrieren, Kameras zuordnen, ...)
const offeneAssistenten = new Map();
function assistentZeigen(fid, titel) {
  if (offeneAssistenten.has(fid)) return;
  const ebene = document.createElement("div");
  ebene.className = "ebene";
  ebene.innerHTML = `<div class="dialog gross"><div class="dkopf"><b>${esc(titel || "Harness")}</b><span style="flex:1"></span>
      <button class="klein-knopf" data-a="zeigen" title="Dieses Fenster stattdessen im Harness-Fenster öffnen">Im Harness-Fenster</button>
      <button class="klein-knopf" data-a="zu">Schließen</button></div><div class="dinhalt" data-inhalt></div></div>`;
  document.body.appendChild(ebene);
  const zu = () => { ansicht.stop(); ebene.remove(); offeneAssistenten.delete(fid); };
  const ansicht = new SpiegelAnsicht($("[data-inhalt]", ebene), fid, { onZu: zu });
  offeneAssistenten.set(fid, zu);
  ebene.addEventListener("click", async (e) => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (a === "zu") { await skill("spiegel.schliessen", { id: fid }).catch(() => {}); zu(); }
    if (a === "zeigen") { await skill("spiegel.zeigen", { id: fid }).catch(() => {}); zu(); toast("Im Harness-Fenster geöffnet."); }
  });
}

// ================================================================== Wache (Rueckfragen, Meldungen, neue Fenster)
const Wache = {
  nach: Date.now() / 1000, fragen: new Map(), assistenten: true, laeuft: false,
  async takt() {
    if (this.laeuft || document.hidden) return;
    this.laeuft = true;
    try {
      const z = await skill("web.zustand", { nach: this.nach });
      for (const m of z.meldungen) { this.nach = Math.max(this.nach, m.zeit); toast(`${m.titel ? m.titel + ": " : ""}${m.text}`, m.art === "fehler"); }
      const offen = new Set(z.fragen.map((f) => f.id));
      for (const [id, zu] of this.fragen) if (!offen.has(id)) { zu(); this.fragen.delete(id); }
      for (const f of z.fragen) if (!this.fragen.has(f.id)) this.frage(f);
      if (this.assistenten) for (const w of z.fenster) if (w.art === "assistent") assistentZeigen(w.id, w.titel);
    } catch (e) { /* Harness nicht verbunden */ } finally { this.laeuft = false; }
  },
  frage(f) {
    const ebene = document.createElement("div");
    ebene.className = "ebene oben";
    const [ja, nein] = f.art === "askokcancel" ? ["OK", "Abbrechen"] : ["Ja", "Nein"];
    ebene.innerHTML = `<div class="dialog"><div class="dkopf"><b>${esc(f.titel || "Rückfrage")}</b><span class="leise klein">&nbsp;· Harness</span></div>
      <div class="dinhalt">${esc(f.text).replace(/\n/g, "<br>")}</div>
      <div class="dfuss"><button data-a="0">${nein}</button><button data-a="1" class="haupt">${ja}</button></div></div>`;
    const zu = () => ebene.remove();
    this.fragen.set(f.id, zu);
    ebene.addEventListener("click", async (e) => {
      const b = e.target.closest("button[data-a]"); if (!b) return;
      zu(); this.fragen.delete(f.id);
      await skill("web.antwort", { id: f.id, antwort: b.dataset.a === "1" }).catch((err) => toast(err.message, true));
    });
    document.body.appendChild(ebene);
  },
  start(assistenten = true) { this.assistenten = assistenten; setInterval(() => this.takt(), 900); },
};

// ================================================================== Freigabe (vor Ort) und Stop
async function uebernehmen(arm) {
  const f = await tu(() => skill("station.freigabe", { arm }));
  if (!f) return;
  if (f.fehler) return toast(f.fehler, true);
  const ok = await dialog({ titel: f.titel, text: f.text, ja: "Ich bin vor Ort · Bewegung starten", nein: "Abbrechen", gefahr: true });
  if (!ok) return;
  await tu(() => skill("station.uebernehmen", { arm, zustimmung: true }, "harness"), "Freigegeben · Arm fährt hoch.");
}
async function ablegen(arm) { await tu(() => skill("arm.ablegen", { arm }), "Arm legt sich ab."); }
async function alleAblegen() { await tu(() => skill("notablage"), "Alle Arme legen sich ab."); }
document.addEventListener("keydown", (e) => { if (e.key === "F12") { e.preventDefault(); alleAblegen(); } });

function badgeHtml(b) {
  return b && b.text ? `<span class="badge${b.ton ? " ton-" + b.ton : ""}">${esc(b.text)}</span>` : "";
}

// ================================================================== Station (Abschnitt 1)
const Station = {
  el: null, z: null, sig: "", laedt: false, kameraTakt: 0,
  init(el) { this.el = el; },
  async laden() {
    if (!this.el || this.laedt) return;
    this.laedt = true;
    try { this.z = await skill("station.zustand"); this.zeichnen(); }
    catch (e) { this.el.innerHTML = `<p class="leise">${esc(e.message)}</p>`; this.sig = ""; }
    finally { this.laedt = false; }
  },
  zeichnen() {
    const z = this.z;
    const sig = JSON.stringify([z.arme.map((a) => [a.arm, a.kameras]), z.weitere_kameras]);
    if (sig !== this.sig) { this.sig = sig; this.aufbauen(); }
    $("[data-f=leader]", this.el).textContent = z.leader;
    $("[data-f=sim]", this.el).hidden = !z.sim;
    $("[data-f=update]", this.el).textContent = z.update || "";
    $("[data-f=netz]", this.el).textContent = z.netz.join("\n");
    $("[data-f=video]", this.el).textContent = z.video_an ? "Video-Streaming stoppen" : "Video-Streaming starten";
    $("[data-f=kalibrieren]", this.el).disabled = !z.kalibrieren_an;
    $("[data-f=spannung]", this.el).disabled = !z.spannung_an;
    $("[data-f=alle]", this.el).disabled = !z.alle_ablegen_an;
    $("[data-f=simknopf]", this.el).textContent = z.sim ? "Zurück zu echten Armen" : "Simulation starten";
    for (const a of z.arme) {
      const k = $(`[data-arm="${CSS.escape(a.arm)}"]`, this.el);
      if (!k) continue;
      $("[data-f=badge]", k).innerHTML = badgeHtml(a.badge);
      $("[data-f=status]", k).textContent = a.status;
      $("[data-f=board]", k).textContent = a.board;
      $("[data-f=info]", k).textContent = a.info || "";
      const take = $("[data-f=take]", k); take.textContent = a.uebernehmen.text; take.disabled = !a.uebernehmen.an;
      $("[data-f=stop]", k).disabled = !a.stop_an;
      for (const b of $$("[data-quelle]", k)) { b.classList.toggle("an", b.dataset.quelle === a.quelle); b.disabled = a.laeuft; }
      $("[data-f=ki]", k).hidden = a.quelle !== "ki";
      $("[data-f=kiinfo]", k).textContent = a.ki_modell ? `Zugewiesen: ${a.ki_modell}${a.ki_aufgabe ? " · " + a.ki_aufgabe : ""}` : "Noch kein Modell zugewiesen.";
      const sel = $("[data-f=kimodell]", k);
      const modelle = ((typeof D !== "undefined" && D && D.modelle) || []).map((m) => m.name);
      if (sel.dataset.sig !== modelle.join("|")) {
        sel.dataset.sig = modelle.join("|");
        sel.innerHTML = modelle.map((m) => `<option${m === a.ki_modell ? " selected" : ""}>${esc(m)}</option>`).join("") || `<option value="">(noch kein Modell)</option>`;
      }
      const fern = $("[data-f=fern]", k); fern.hidden = !a.fern; fern.textContent = a.fern;
      $("[data-f=fernknopf]", k).hidden = a.quelle !== "remote";
      const log = $("[data-f=log]", k);
      if (log.textContent !== a.log) { const unten = log.scrollTop + log.clientHeight >= log.scrollHeight - 10; log.textContent = a.log; if (unten) log.scrollTop = log.scrollHeight; }
    }
  },
  aufbauen() {
    const z = this.z;
    this.el.innerHTML = `
      <div class="station-leiste"><span class="punkt an"></span><span data-f="leader" class="mono"></span>
        <span class="marke-klein gelb" data-f="sim" hidden>Simulation</span><span data-f="update" class="rot-text"></span>
        <span style="flex:1"></span><button class="gefahr" data-f="alle" onclick="alleAblegen()" title="Alle laufenden Arme: Greifer auf, ablegen (F12)">Alle ablegen · F12</button></div>
      ${z.arme.map((a) => `<div class="karte arm" data-arm="${esc(a.arm)}">
        <div class="kkopf hoch"><span data-f="badge"></span><b>${esc(a.label)}</b><span data-f="status" class="leise"></span>
          <span style="flex:1"></span>
          <span class="segment" title="Wer steuert den Arm?">
            <button data-quelle="lokal" onclick="quelle('${esc(a.arm)}','lokal')">Leader</button>
            <button data-quelle="ki" onclick="quelle('${esc(a.arm)}','ki')">KI-Modell</button>
            <button data-quelle="remote" onclick="quelle('${esc(a.arm)}','remote')">Remote</button></span>
          <button class="haupt" data-f="take" onclick="uebernehmen('${esc(a.arm)}')">Leader übernehmen</button>
          <button class="gefahr" data-f="stop" onclick="ablegen('${esc(a.arm)}')">Stop · ablegen</button></div>
        <div class="kinhalt">
          <div class="zeile klein"><span data-f="board" class="mono leise"></span><span data-f="info" class="mono"></span><span style="flex:1"></span>
            <button onclick="steuermodusZeigen('${esc(a.arm)}')">Steuermodus</button>
            <button onclick="steuermodusFenster('${esc(a.arm)}')">Steuermodus in neuem Fenster</button></div>
          <div class="zeile" data-f="ki" hidden style="margin-top:8px"><span class="leise klein">Modell</span><select data-f="kimodell" style="min-width:220px"></select>
            <input data-f="kiaufgabe" placeholder="Aufgabe (leer = aus dem Modell)" style="flex:1;min-width:200px">
            <button onclick="kiZuweisen('${esc(a.arm)}')">Zuweisen</button><span data-f="kiinfo" class="klein leise"></span></div>
          <div class="hinweis" data-f="fern" hidden style="margin-top:8px;white-space:pre-line"></div>
          <div class="zeile" style="margin-top:6px"><button data-f="fernknopf" hidden onclick="assistent('fernzugang','${esc(a.arm)}')">Fernzugriff verwalten</button></div>
        </div>
        <div class="kameras">${a.kameras.map((c) => `<div class="kamera"><div class="name"><span>${c.slot + 1} · ${esc(c.name)}</span>
            <button class="klein-knopf" onclick="assistent('kameras', null, ${c.slot})" title="Nur diesen Platz neu zuordnen">Neu zuordnen</button></div>
          <div class="bild"><img data-arm="${esc(a.arm)}" data-kamera="${esc(c.key)}" alt=""><span class="leer">kein Bild</span></div></div>`).join("")}</div>
        <details class="protokoll"><summary>Protokoll</summary><pre class="log" data-f="log"></pre></details>
      </div>`).join("")}
      ${(z.weitere_kameras || []).length ? `<div class="karte arm"><div class="kkopf"><b>Weitere Kameras</b>
          <span class="leise">gehören zu keinem Arm · zum Experimentieren (Skills kamera.platz_bild, kamera.tiefe)</span></div>
        <div class="kameras">${z.weitere_kameras.map((c) => `<div class="kamera"><div class="name"><span>${c.slot + 1} · ${esc(c.name)}${c.oak ? " · Tiefe: kamera.tiefe" : ""}</span>
            <button class="klein-knopf" onclick="assistent('kameras', null, ${c.slot})">Neu zuordnen</button></div>
          <div class="bild"><img data-platz="${c.slot}" alt=""><span class="leer">kein Bild</span></div></div>`).join("")}</div></div>` : ""}
      <div class="raster" style="margin-top:10px">
        <div class="karte"><div class="kkopf"><b>Einrichten</b></div><div class="kinhalt"><div class="zeile">
          <button onclick="assistent('kameras')">Kameras zuordnen</button>
          <button data-f="kalibrieren" onclick="assistent('kalibrieren')">Arme kalibrieren</button>
          <button data-f="spannung" onclick="assistent('spannung')">Spannung messen</button>
          <button onclick="assistent('arbeitsbereich')">Arbeitsbereich</button></div>
          <p class="klein leise" style="margin:8px 0 0">Kalibrieren und Spannung messen gehen nur, wenn alle Arme abgelegt sind.</p></div></div>
        <div class="karte"><div class="kkopf"><b>Netz</b><span class="leise">Fernsteuerung · Übertragung</span></div><div class="kinhalt">
          <pre class="mono klein leise" data-f="netz" style="margin:0 0 8px;white-space:pre-wrap"></pre>
          <div class="zeile"><button data-f="video" onclick="video()">Video-Streaming starten</button>
            <button onclick="assistent('fernzugang_erstellen')">Fernzugang erstellen</button></div></div></div>
        <div class="karte"><div class="kkopf"><b>Harness</b></div><div class="kinhalt"><div class="zeile">
          <button onclick="neustart()">Harness neu starten</button>
          <button data-f="simknopf" onclick="neustart('umschalten')">Simulation starten</button></div>
          <p class="klein leise" style="margin:8px 0 0">Neu starten geht nur, wenn alle Arme abgelegt sind. Trainings laufen weiter.</p></div></div>
      </div>`;
  },
  kameras(breite = 640) {
    if (!this.el) return;
    for (const img of $$(".kamera img[data-kamera], .kamera img[data-platz]", this.el)) kameraBild(img, breite);
  },
};

function kameraBild(img, breite) {
  if (img.dataset.laedt === "1") return;
  img.dataset.laedt = "1";
  const n = new Image();
  n.onload = () => { img.src = n.src; img.nextElementSibling.style.display = "none"; img.dataset.laedt = "0"; };
  n.onerror = () => { img.removeAttribute("src"); img.nextElementSibling.style.display = ""; img.dataset.laedt = "0"; };
  n.src = img.dataset.platz != null ? `/api/kamera?platz=${img.dataset.platz}&breite=${breite}&t=${Date.now()}`
    : `/api/kamera?arm=${encodeURIComponent(img.dataset.arm)}&kamera=${encodeURIComponent(img.dataset.kamera)}&breite=${breite}&t=${Date.now()}`;
}

async function quelle(arm, q) { await tu(() => skill("station.quelle", { arm, quelle: q })); Station.laden(); }
async function kiZuweisen(arm) {
  const k = $(`[data-arm="${CSS.escape(arm)}"]`, Station.el);
  const modell = $("[data-f=kimodell]", k).value, aufgabe = $("[data-f=kiaufgabe]", k).value.trim();
  if (!modell) return toast("Noch kein fertiges Modell.", true);
  await tu(() => skill("ki.modell_waehlen", aufgabe ? { arm, modell, aufgabe } : { arm, modell }), `Modell ${modell} zugewiesen.`);
}
async function assistent(was, arm, slot) {
  const args = { was }; if (arm) args.arm = arm; if (slot != null) args.slot = slot;
  const r = await tu(() => skill("station.assistent", args, "harness"));
  if (r) for (const id of r.fenster || []) assistentZeigen(id, "");
}
async function video() {
  const an = !(Station.z && Station.z.video_an);
  await tu(() => skill("station.video", { an }), an ? "Video-Streaming startet." : "Video-Streaming gestoppt.");
}
async function neustart(sim) {
  const ok = await dialog({ titel: sim ? "Simulation" : "Harness neu starten",
    text: sim ? (Station.z?.sim ? "Simulation beenden und mit den echten Armen neu starten?" : "Harness im Simulationsmodus neu starten?\n\nKein echter Arm bewegt sich, kein COM-Port wird geöffnet.")
      : "Harness jetzt neu starten? Die Seite verbindet sich danach von selbst wieder.", ja: "Neu starten" });
  if (ok) await tu(() => skill("station.neustart", sim ? { sim } : {}), "Harness startet neu ...");
}
function steuermodusFenster(arm) {
  window.open(`/steuermodus?arm=${encodeURIComponent(arm)}`, "steuermodus-" + arm, "width=1500,height=950");
}

// ================================================================== Steuermodus
class Steuermodus {
  constructor(el, arm, { fenster = false, aktiv = () => true } = {}) {
    this.el = el; this.arm = arm; this.fenster = fenster; this.aktiv = aktiv; this.z = null; this.plan = null; this.planId = null;
    this.aufbauen();
    this.laden();
    this.timer = setInterval(() => this.laden(), 450);
    this.kamTimer = setInterval(() => this.kameras(), fenster ? 260 : 600);
    this.taste = (e) => this.tasten(e);
    document.addEventListener("keydown", this.taste);
  }
  stop() { clearInterval(this.timer); clearInterval(this.kamTimer); document.removeEventListener("keydown", this.taste); if (this.plan) this.plan.stop(); }
  aufbauen() {
    this.el.innerHTML = `<div class="steuer">
      <div class="steuer-kopf"><span data-s="badge"></span><b data-s="label">Steuermodus</b><span data-s="status" class="leise"></span>
        <span style="flex:1"></span>
        <button class="haupt" data-s="take">Leader übernehmen</button>
        <button class="gefahr" data-s="stop">Stop · ablegen</button>
        ${this.fenster ? "" : `<button data-s="fenster" title="Als Übersicht über den Roboter in einem eigenen Fenster">In neuem Fenster öffnen</button>`}</div>
      <div class="steuer-leiste">
        <b>Aufnahme</b>
        <label class="feld-inline">Datensatz <input data-s="datensatz" list="sm-ds-${esc(this.arm)}" style="width:190px"></label>
        <datalist id="sm-ds-${esc(this.arm)}"></datalist>
        <label class="feld-inline">Aufgabe <input data-s="aufgabe" list="sm-auf-${esc(this.arm)}" style="width:300px"></label>
        <datalist id="sm-auf-${esc(this.arm)}"></datalist>
        <button class="rec" data-s="start">● Start <kbd>F5</kbd></button>
        <button data-s="rstop">■ Stop <kbd>F6</kbd></button>
        <button class="haupt" data-s="behalten">Behalten <kbd>F7</kbd></button>
        <button data-s="verwerfen">Verwerfen <kbd>F8</kbd></button>
        <span data-s="info" class="mono gelb-text"></span></div>
      <div class="steuer-leiste">
        <b>Startpose</b><span data-s="start-info" class="mono klein"></span>
        <button class="klein-knopf" data-s="startpose">Aktuelle Stellung als Startpose</button>
        <span style="flex:1"></span>
        <label class="feld-inline">Aufnahmeplan <select data-s="plan"><option value="">(ohne Plan)</option></select></label></div>
      <div data-s="planansicht" class="steuer-plan" hidden></div>
      <div class="kameras steuer-kameras" data-s="kameras"></div></div>`;
    const s = (n) => $(`[data-s=${n}]`, this.el);
    s("take").onclick = () => uebernehmen(this.arm);
    s("stop").onclick = () => ablegen(this.arm);
    if (s("fenster")) s("fenster").onclick = () => steuermodusFenster(this.arm);
    s("start").onclick = () => this.aufnahme("start");
    s("rstop").onclick = () => this.aufnahme("stop");
    s("behalten").onclick = () => this.aufnahme("behalten");
    s("verwerfen").onclick = () => this.aufnahme("verwerfen");
    s("startpose").onclick = async () => {
      if (await dialog({ titel: "Startpose", text: "Aktuelle Stellung als Startpose speichern?\n\nNeue Episoden sollten danach von hier beginnen. Ältere Episoden mit anderer Startpose am besten löschen.", ja: "Speichern" }))
        tu(() => skill("steuer.startpose", { arm: this.arm, zustimmung: true }), "Startpose gespeichert.");
    };
    s("plan").onchange = async (e) => {
      const r = await tu(() => skill("steuer.plan", { arm: this.arm, plan: e.target.value }, "aufnehmen"));
      if (!r) e.target.value = this.planId || "";
      this.laden();
    };
  }
  async laden() {
    if (this.laedt || document.hidden) return;
    this.laedt = true;
    try { this.z = await skill("steuer.zustand", { arm: this.arm }); this.zeichnen(); }
    catch (e) { $("[data-s=status]", this.el).textContent = e.message; }
    finally { this.laedt = false; }
  }
  zeichnen() {
    const z = this.z, s = (n) => $(`[data-s=${n}]`, this.el);
    if (this.fenster) document.title = `Steuermodus · ${z.label}`;
    s("label").textContent = z.label;
    s("badge").innerHTML = badgeHtml(z.badge);
    s("status").textContent = z.status;
    s("take").textContent = z.uebernehmen.text; s("take").disabled = !z.uebernehmen.an;
    s("stop").disabled = !z.stop_an;
    const a = z.aufnahme, plan = !!z.plan;
    s("start").disabled = plan ? false : !(a.zustand === "bereit" && z.folgt);
    s("rstop").disabled = a.zustand !== "nimmt_auf";
    s("behalten").disabled = s("verwerfen").disabled = a.zustand !== "wartet_entscheidung";
    s("datensatz").disabled = s("aufgabe").disabled = plan;
    const n = a.episoden != null ? `${a.episoden} Episoden` : "";
    s("info").textContent = a.zustand === "nimmt_auf" ? `● AUFNAHME ${a.sekunden.toFixed(1)} s · ${n}  (F6 = Stop)`
      : a.zustand === "wartet_entscheidung" ? `${a.sekunden.toFixed(1)} s aufgenommen · F7 behalten / F8 verwerfen`
      : plan ? "Aufnahme steuert der Plan (unten)" : n + (z.folgt ? "  (F5 = Start)" : "  · Aufnahme nur, während der Arm dem Leader folgt");
    s("info").classList.toggle("rec-an", a.zustand === "nimmt_auf");
    for (const [feld, liste] of [["datensatz", z.optionen.datensatz], ["aufgabe", z.optionen.aufgabe]]) {
      const inp = s(feld);
      if (!inp.dataset.init) { inp.dataset.init = "1"; inp.value = z.eingabe[feld] || liste[0] || ""; }
      const dl = $(`#${inp.getAttribute("list").replace(/([^\w-])/g, "\\$1")}`);
      const sig = liste.join("|");
      if (dl && dl.dataset.sig !== sig) { dl.dataset.sig = sig; dl.innerHTML = liste.map((o) => `<option value="${esc(o)}">`).join(""); }
    }
    const sp = z.startpose;
    s("start-info").textContent = sp.ok === true ? "✔ in Startpose  " + sp.text : sp.ok === false ? "✖ nicht in Startpose  " + sp.text : sp.text;
    s("start-info").className = "mono klein " + (sp.ok === true ? "gelb-text" : sp.ok === false ? "rot-text" : "leise");
    const sel = s("plan"), psig = z.plaene.map((p) => p.id).join("|");
    if (sel.dataset.sig !== psig) { sel.dataset.sig = psig; sel.innerHTML = `<option value="">(ohne Plan)</option>` + z.plaene.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join(""); }
    if (document.activeElement !== sel) sel.value = z.plan ? z.plan.id : "";
    // Plan-Ansicht (gespiegelt aus dem Harness)
    const fid = z.plan ? z.plan.spiegel : null;
    if (fid !== (this.plan && this.plan.fid)) {
      if (this.plan) { this.plan.stop(); this.plan = null; }
      s("planansicht").hidden = !fid; s("planansicht").innerHTML = "";
      if (fid) this.plan = new SpiegelAnsicht(s("planansicht"), fid, { takt: 300 });
    }
    this.planId = z.plan ? z.plan.id : null;
    const ksig = JSON.stringify(z.kameras);
    if (s("kameras").dataset.sig !== ksig) {
      s("kameras").dataset.sig = ksig;
      s("kameras").innerHTML = z.kameras.map((c) => `<div class="kamera"><div class="name"><span>${c.slot + 1} · ${esc(c.name)}</span></div>
        <div class="bild"><img data-arm="${esc(this.arm)}" data-kamera="${esc(c.key)}" alt=""><span class="leer">kein Bild</span></div></div>`).join("");
    }
  }
  kameras() {
    if (document.hidden || !this.aktiv()) return;
    for (const img of $$("[data-s=kameras] img", this.el)) kameraBild(img, this.fenster ? 1100 : 800);
  }
  async aufnahme(aktion) {
    const args = { arm: this.arm, aktion };
    if (aktion === "start" && !this.z?.plan) { args.datensatz = $("[data-s=datensatz]", this.el).value.trim(); args.aufgabe = $("[data-s=aufgabe]", this.el).value.trim(); }
    await tu(() => skill("steuer.aufnahme", args, "aufnehmen"));
    setTimeout(() => this.laden(), 150);
  }
  tasten(e) {
    if (!this.aktiv() || eingabeAktiv() || $(".ebene")) return;
    const f = { F5: "start", F6: "stop", F7: "behalten", F8: "verwerfen" }[e.key];
    if (f) { e.preventDefault(); return this.aufnahme(f); }
    if (this.z?.plan && (e.key === "F3" || e.key === "F4" || /^[1-9]$/.test(e.key))) {
      e.preventDefault();
      skill("steuer.taste", { arm: this.arm, taste: e.key }).catch((err) => toast(err.message, true));
    }
  }
}
