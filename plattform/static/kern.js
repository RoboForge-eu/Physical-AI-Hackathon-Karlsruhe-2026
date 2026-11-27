// Physical AI Harness by RoboForge · gemeinsame Hilfen fuer alle Seiten (Hauptseite, Steuermodus-Fenster).
//
// === KERN-DATEI · fuer Hackathon-Teams NICHT zum Umbauen gedacht ===
// Teams bauen in teams/<team>/ (orchestrator.py, skills/, ui/, plaene/). Eigene Oberflaeche: teams/<team>/ui/index.html.
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(pfad, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-RF": "1" }, body: JSON.stringify(body) };
  const r = await fetch(pfad, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.fehler || r.statusText);
  return j;
}
// Harness-Befehl (Skill) aufrufen; Ergebnis direkt
async function skill(name, args = {}, abschnitt) {
  const r = await api("/api/skill", { name, args, abschnitt });
  return r.ergebnis;
}

function toast(text, fehler = false) {
  let box = $("#toast");
  if (!box) { box = document.createElement("div"); box.id = "toast"; document.body.appendChild(box); }
  const d = document.createElement("div");
  d.textContent = text;
  if (fehler) d.className = "fehler";
  box.appendChild(d);
  setTimeout(() => d.remove(), fehler ? 7000 : 4000);
}
async function tu(fn, ok) {
  try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, true); }
}

// Dialog im Stil der Seite (statt confirm/alert). Ergebnis: true/false.
function dialog({ titel, text, ja = "OK", nein = "Abbrechen", gefahr = false, nurOk = false }) {
  return new Promise((fertig) => {
    const ebene = document.createElement("div");
    ebene.className = "ebene";
    ebene.innerHTML = `<div class="dialog" role="dialog" aria-modal="true">
      <div class="dkopf">${esc(titel || "")}</div>
      <div class="dinhalt">${esc(text || "").replace(/\n/g, "<br>")}</div>
      <div class="dfuss">${nurOk ? "" : `<button data-a="0">${esc(nein)}</button>`}
        <button data-a="1" class="${gefahr ? "gefahr-voll" : "haupt"}">${esc(ja)}</button></div></div>`;
    const zu = (a) => { ebene.remove(); document.removeEventListener("keydown", taste, true); fertig(a); };
    const taste = (e) => { if (e.key === "Escape") { e.stopPropagation(); zu(false); } };
    ebene.addEventListener("click", (e) => { const b = e.target.closest("button[data-a]"); if (b) zu(b.dataset.a === "1"); });
    document.addEventListener("keydown", taste, true);
    document.body.appendChild(ebene);
    $("button[data-a='0']", ebene)?.focus();
  });
}

function eingabeAktiv() {
  const a = document.activeElement;
  return a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT" || a.isContentEditable);
}
