// Chat page for the Recruiting Copilot. No framework, no third-party scripts (CSP: 'self' only).
// Answers can quote resume text, so everything is escaped before the light markdown formatting.
"use strict";

const $ = (id) => document.getElementById(id);
let sessionId = null;

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// **bold**, `code`, "- " / "1. " lists and paragraphs. Applied to already-escaped text only.
function render(text) {
  const lines = escapeHtml(text).split("\n");
  let html = "", list = null;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.trim();
    const ul = line.match(/^[-*•]\s+(.*)/), ol = line.match(/^\d+[.)]\s+(.*)/);
    if (ul || ol) {
      const want = ul ? "ul" : "ol";
      if (list !== want) { close(); html += `<${want}>`; list = want; }
      html += `<li>${inline((ul || ol)[1])}</li>`;
    } else if (line) {
      close(); html += `<p>${inline(line)}</p>`;
    } else {
      close();
    }
  }
  close();
  return html;
}

function addMessage(kind, text, meta) {
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.innerHTML = render(text);
  if (meta) {
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}

async function getJson(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function chip(listId, id, label, question) {
  const li = document.createElement("li");
  const b = document.createElement("button");
  b.type = "button";
  b.innerHTML = `<span class="id">${escapeHtml(id)}</span>${escapeHtml(label || "")}`;
  b.addEventListener("click", () => { $("q").value = question; $("q").focus(); });
  li.appendChild(b);
  $(listId).appendChild(li);
}

async function loadSidebar() {
  try {
    const me = await getJson("/api/me");
    if (me.user) $("user").textContent = `Signed in as ${me.user}`;
  } catch (_) { /* local dev without sign-in */ }
  try {
    for (const j of await getJson("/api/jobs")) chip("jobs", j.job_id, j.title, `Who are the top 5 candidates for ${j.job_id}, and why?`);
    for (const r of await getJson("/api/requests")) chip("requests", r.request_id, r.title, `Who can I submit for ${r.request_id}?`);
    const held = await getJson("/api/held");
    if (held.length) {
      $("held-section").hidden = false;
      for (const h of held) {
        const li = document.createElement("li");
        const kinds = [...new Set(h.findings.map((f) => f.type.replace("_", " ")))].join(", ");
        li.innerHTML = `<strong>${escapeHtml(h.candidate_id)}</strong>${escapeHtml(kinds)}`;
        $("held").appendChild(li);
      }
    }
  } catch (e) {
    addMessage("bot blocked", "Couldn't load jobs and requests. Check that the API is running.");
  }
}

async function ask(question) {
  $("send").disabled = true;
  addMessage("user", question);
  const pending = addMessage("bot thinking", "Checking guardrails, then asking the agent…");
  const started = performance.now();
  try {
    const r = await fetch("/api/chat", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId }),
    });
    const data = await r.json();
    pending.remove();
    if (data.session_id) sessionId = data.session_id;
    if (!r.ok) { addMessage("bot blocked", data.error || data.detail || `Error ${r.status}`); return; }
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    const bits = [`${secs}s`];
    if (data.tools && data.tools.length) bits.push(`tools: ${[...new Set(data.tools)].join(", ")}`);
    if (data.checks && data.checks.length) bits.push(`guardrails: ${data.checks.join(", ")}`);
    addMessage(data.blocked ? "bot blocked" : "bot", data.answer, bits.join(" · "));
  } catch (e) {
    pending.remove();
    addMessage("bot blocked", "Network error. Try again.");
  } finally {
    $("send").disabled = false;
    $("q").focus();
  }
}

$("ask").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q) return;
  $("q").value = "";
  ask(q);
});
$("q").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask").requestSubmit(); }
});
loadSidebar();
