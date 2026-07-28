/* ---------- element refs ---------- */
const screenplayEl = document.getElementById("screenplay");
const runBtn = document.getElementById("run");
const loadSampleBtn = document.getElementById("load-sample");
const runStatusEl = document.getElementById("run-status");
const withPrevizEl = document.getElementById("with-previz");

const crewPanel = document.getElementById("crew-panel");
const crewTrackEl = document.getElementById("crew-track");
const activityLogEl = document.getElementById("activity-log");
const toggleLogBtn = document.getElementById("toggle-log");

const approvalBackdrop = document.getElementById("approval-backdrop");
const approvalBudgetEl = document.getElementById("approval-budget");
const approveYesBtn = document.getElementById("approve-yes");
const approveNoBtn = document.getElementById("approve-no");

const resultsPanel = document.getElementById("results-panel");
const tabsEl = document.getElementById("result-tabs");
const tabPanelsEl = document.getElementById("tab-panels");
const downloadBtn = document.getElementById("download-json");
const metricsEl = document.getElementById("metrics");

const stepperEls = [...document.querySelectorAll("#stepper li")];
const layoutEl = document.querySelector(".layout");

const RUN_BTN_IDLE = runBtn.innerHTML;

/* ---------- icons ---------- */
const ICONS = {
  script: `<svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M15 3v4h4"/><path d="M8 12h8M8 15.5h8M8 8.5h4"/></svg>`,
  film: `<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M16 4v16M3 9h5M16 9h5M3 15h5M16 15h5"/></svg>`,
  calendar: `<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path d="M7.5 14h2M11 14h2M14.5 14h2M7.5 17h2M11 17h2"/></svg>`,
  dollar: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5c0-1.4 1.2-2 2.5-2s2.5.7 2.5 2c0 2.5-5 1.5-5 4 0 1.3 1.2 2 2.5 2s2.5-.6 2.5-2"/></svg>`,
  alert: `<svg viewBox="0 0 24 24"><path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4"/><circle cx="12" cy="16.8" r=".6" fill="currentColor" stroke="none"/></svg>`,
  check: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/></svg>`,
  users: `<svg viewBox="0 0 24 24"><circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20v-1a5 5 0 0 1 5-5h0a5 5 0 0 1 5 5v1"/><path d="M14.5 14.2A4 4 0 0 1 21 17.3V19"/></svg>`,
  package: `<svg viewBox="0 0 24 24"><path d="M12 3 3 7.5 12 12l9-4.5L12 3Z"/><path d="M3 7.5V17l9 4.5 9-4.5V7.5"/><path d="M12 12v9.5"/></svg>`,
};

const AGENT_DEFS = [
  { key: "script_supervisor", label: "Script Supervisor", hint: "Parses the screenplay into a scene breakdown", icon: ICONS.script },
  { key: "previz_agent", label: "Previz", hint: "Imagen storyboards, Veo animatic, Lyria cue", icon: ICONS.film, optional: true },
  { key: "first_ad_scheduler", label: "1st-AD Scheduler", hint: "Builds the stripboard shoot schedule", icon: ICONS.calendar },
  { key: "budget_agent", label: "Budget Agent", hint: "Grounded in studio data via IBM MCP", icon: ICONS.dollar },
  { key: "risk_agent", label: "Risk / Continuity", hint: "Critiques the schedule and budget", icon: ICONS.alert },
  { key: "approval_gate", label: "Approval Gate", hint: "Producer signs off the budget band", icon: ICONS.check },
  { key: "resource_agent", label: "Resource Agent", hint: "Grounded in studio data via IBM MCP", icon: ICONS.users },
  { key: "package_assembler", label: "Package Assembler", hint: "Combines everything into the package", icon: ICONS.package },
];
const STATUS_LABEL = { pending: "Pending", active: "Working", done: "Done", skipped: "Skipped", error: "Error" };
const STEPS = ["input", "crew", "approval", "done"];

/* ---------- run state ---------- */
let currentRunId = null;
let currentWithPreviz = false;
let currentPackage = null;
let pollHandle = null;
let renderedEventCount = 0;
let approvalShown = false;

/* ---------- setup actions ---------- */
loadSampleBtn.addEventListener("click", async () => {
  const res = await fetch("/api/sample-screenplay");
  const data = await res.json();
  screenplayEl.value = data.screenplay;
});

runBtn.addEventListener("click", async () => {
  const screenplay = screenplayEl.value.trim();
  if (!screenplay) {
    setStatus("Paste a screenplay first (or load the sample).", "error");
    return;
  }
  resetForNewRun();
  currentWithPreviz = withPrevizEl.checked;
  setRunBtnBusy("Starting the crew…");
  setStatus("Starting the crew…");
  setStep("crew");

  let res;
  try {
    res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screenplay, with_previz: currentWithPreviz }),
    });
  } catch {
    setStatus("Could not reach the BACKLOT server.", "error");
    resetRunBtn();
    return;
  }
  if (!res.ok) {
    setStatus("Failed to start run.", "error");
    resetRunBtn();
    return;
  }
  const data = await res.json();
  currentRunId = data.run_id;
  layoutEl.classList.add("has-run");
  crewPanel.classList.remove("hidden");
  renderCrew([], "running");
  startPolling();
});

toggleLogBtn.addEventListener("click", () => {
  const nowHidden = activityLogEl.classList.toggle("hidden");
  toggleLogBtn.textContent = nowHidden ? "Show detailed log ▾" : "Hide detailed log ▴";
  toggleLogBtn.setAttribute("aria-expanded", String(!nowHidden));
});

approveYesBtn.addEventListener("click", () => submitApproval(true));
approveNoBtn.addEventListener("click", () => submitApproval(false));

downloadBtn.addEventListener("click", () => {
  if (!currentPackage) return;
  const blob = new Blob([JSON.stringify(currentPackage, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `backlot_package_${currentRunId || "run"}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

/* ---------- approval ---------- */
async function submitApproval(approved) {
  approveYesBtn.disabled = true;
  approveNoBtn.disabled = true;
  try {
    await fetch(`/api/runs/${currentRunId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, reason: "" }),
    });
  } finally {
    approvalBackdrop.classList.add("hidden");
    approvalShown = false;
    approveYesBtn.disabled = false;
    approveNoBtn.disabled = false;
  }
}

function showApproval(pendingBudget) {
  approvalBackdrop.classList.remove("hidden");
  approvalShown = true;
  if (!pendingBudget) {
    approvalBudgetEl.innerHTML = `<p class="empty-state">Waiting for the budget details…</p>`;
    return;
  }
  approvalBudgetEl.innerHTML = `
    <div class="approval-total"><span class="currency">${escapeHtml(pendingBudget.currency)}</span> ${Number(pendingBudget.total_estimated_cost).toLocaleString()}</div>
    ${renderBudgetTable(pendingBudget.line_items)}
  `;
}

/* ---------- polling ---------- */
function resetForNewRun() {
  currentRunId = null;
  currentPackage = null;
  renderedEventCount = 0;
  approvalShown = false;
  activityLogEl.innerHTML = "";
  crewPanel.classList.add("hidden");
  resultsPanel.classList.add("hidden");
  approvalBackdrop.classList.add("hidden");
  setStep("input");
}

function startPolling() {
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = setInterval(pollRun, 1200);
  pollRun();
}

async function pollRun() {
  let res;
  try {
    res = await fetch(`/api/runs/${currentRunId}`);
  } catch {
    return; // transient network hiccup; next tick retries
  }
  if (!res.ok) return;
  const data = await res.json();

  renderCrew(data.events || [], data.status);
  appendNewLogEntries(data.events || []);

  if (data.status === "awaiting_approval") {
    setStep("approval");
    setStatus("Awaiting your approval of the budget band…");
    if (!approvalShown) showApproval(data.pending_budget);
  } else if (approvalShown) {
    approvalBackdrop.classList.add("hidden");
    approvalShown = false;
  }

  if (data.status === "completed" || data.status === "rejected") {
    clearInterval(pollHandle);
    resetRunBtn();
    setStep("done");
    setStatus(
      data.status === "completed" ? "Package complete." : "Budget rejected — package assembled without resources.",
      data.status === "completed" ? "ok" : "error"
    );
    renderResults(data.package);
    renderMetrics(data.metrics);
  } else if (data.status === "error") {
    clearInterval(pollHandle);
    resetRunBtn();
    setStatus(`Error: ${data.error || "unknown error"}`, "error");
    if (data.package) {
      renderResults(data.package);
      renderMetrics(data.metrics);
    }
  }
}

/* ---------- stepper ---------- */
function setStep(stepKey) {
  const idx = STEPS.indexOf(stepKey);
  stepperEls.forEach((li) => {
    const liIdx = STEPS.indexOf(li.dataset.step);
    li.classList.toggle("is-current", liIdx === idx);
    li.classList.toggle("is-done", liIdx < idx);
  });
}

function setStatus(text, kind) {
  runStatusEl.textContent = text;
  runStatusEl.classList.toggle("is-error", kind === "error");
  runStatusEl.classList.toggle("is-ok", kind === "ok");
}

function setRunBtnBusy(label) {
  runBtn.disabled = true;
  runBtn.innerHTML = `<span class="btn-spinner"></span> ${escapeHtml(label)}`;
}

function resetRunBtn() {
  runBtn.disabled = false;
  runBtn.innerHTML = RUN_BTN_IDLE;
}

/* ---------- crew visualization ---------- */
function countBlocks(authors, key) {
  let count = 0;
  let prev = null;
  for (const a of authors) {
    if (a === key && prev !== key) count++;
    prev = a;
  }
  return count;
}

function computeCrewState(def, authors, lastAuthor, status) {
  const hasRun = authors.includes(def.key);
  if (def.key === "approval_gate" && status === "awaiting_approval") return "active";
  if (def.key === "resource_agent" && status === "rejected") return "skipped";
  if (status === "error" && def.key === lastAuthor) return "error";
  if (["completed", "rejected", "error"].includes(status)) return hasRun ? "done" : "pending";
  if (hasRun && def.key === lastAuthor) return "active";
  if (hasRun) return "done";
  return "pending";
}

function renderCrew(events, status) {
  const defs = AGENT_DEFS.filter((d) => !d.optional || currentWithPreviz);
  const authors = events.map((e) => e.author);
  const lastAuthor = authors.length ? authors[authors.length - 1] : null;

  crewTrackEl.innerHTML = defs
    .map((def) => {
      const state = computeCrewState(def, authors, lastAuthor, status);
      const blocks = countBlocks(authors, def.key);
      const repeatBadge = blocks > 1 ? `<span class="crew-repeat">re-plan ×${blocks}</span>` : "";
      return `
      <li class="crew-card is-${state}">
        <span class="crew-icon">${def.icon}</span>
        <span class="crew-body">
          <span class="crew-name">${escapeHtml(def.label)} ${repeatBadge}</span>
          <span class="crew-hint">${escapeHtml(def.hint)}</span>
        </span>
        <span class="crew-status"><span class="dot"></span>${STATUS_LABEL[state]}</span>
      </li>`;
    })
    .join("");
}

function appendNewLogEntries(events) {
  for (let i = renderedEventCount; i < events.length; i++) {
    const ev = events[i];
    const li = document.createElement("li");
    const toolBadges = (ev.tool_calls || [])
      .map((t) => `<span class="tool">${escapeHtml(t)}</span>`)
      .join("");
    const time = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : "";
    li.innerHTML = `<span class="tstamp">${time}</span><span class="agent">${escapeHtml(ev.author)}</span>${escapeHtml(ev.text || "")}${toolBadges}`;
    activityLogEl.appendChild(li);
  }
  renderedEventCount = events.length;
  activityLogEl.scrollTop = activityLogEl.scrollHeight;
}

/* ---------- results ---------- */
function renderResults(pkg) {
  resultsPanel.classList.remove("hidden");
  currentPackage = pkg;
  if (!pkg) {
    tabsEl.innerHTML = "";
    tabPanelsEl.innerHTML = `<p class="empty-state">No package produced.</p>`;
    return;
  }

  const tabs = [
    { id: "breakdown", label: "Breakdown", html: renderBreakdownTab(pkg) },
    { id: "schedule", label: "Schedule", html: renderScheduleTab(pkg) },
    { id: "budget", label: "Budget", html: pkg.budget ? renderBudgetFullTab(pkg.budget) : emptyTab("No budget produced.") },
    { id: "risk", label: "Risk", html: pkg.risk_report ? renderRiskTab(pkg.risk_report) : emptyTab("No risk report produced.") },
    {
      id: "resources",
      label: "Resources",
      html: pkg.resources ? renderResourcesTab(pkg.resources) : emptyTab("Not produced (budget was rejected)."),
    },
  ];
  if (pkg.previz) tabs.push({ id: "previz", label: "Previz", html: renderPrevizTab(pkg.previz) });

  tabsEl.innerHTML = tabs
    .map((t, i) => `<button class="tab-btn${i === 0 ? " is-active" : ""}" data-tab="${t.id}" role="tab">${escapeHtml(t.label)}</button>`)
    .join("");
  tabPanelsEl.innerHTML = tabs
    .map((t, i) => `<div class="tab-panel${i === 0 ? "" : " hidden"}" data-tab-panel="${t.id}">${t.html}</div>`)
    .join("");

  tabsEl.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      tabsEl.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      tabPanelsEl.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
      tabPanelsEl.querySelector(`[data-tab-panel="${btn.dataset.tab}"]`).classList.remove("hidden");
    });
  });
}

function emptyTab(message) {
  return `<p class="empty-state">${escapeHtml(message)}</p>`;
}

function renderBreakdownTab(pkg) {
  const rows = pkg.breakdown.scenes
    .map(
      (s) => `
    <tr>
      <td>${escapeHtml(s.scene_number)}</td>
      <td>${escapeHtml(s.location)}<br/><span class="hint">${s.int_ext} · ${s.time_of_day}</span></td>
      <td>${escapeHtml(s.synopsis)}</td>
      <td>${(s.cast || []).map(escapeHtml).join(", ")}</td>
      <td>${s.estimated_page_count}</td>
    </tr>`
    )
    .join("");
  return `<table><tr><th>#</th><th>Location</th><th>Synopsis</th><th>Cast</th><th>Pages</th></tr>${rows}</table>
    <p class="hint">${pkg.breakdown.scenes.length} scene(s) · ${pkg.breakdown.total_estimated_pages} estimated pages</p>`;
}

function renderScheduleTab(pkg) {
  const rows = pkg.schedule.days
    .map(
      (day) => `
    <tr>
      <td>${day.day_number}</td>
      <td>${escapeHtml(day.location)}</td>
      <td>${day.int_ext}</td>
      <td>${day.time_of_day}</td>
      <td>${day.scene_numbers.join(", ")}</td>
      <td>${day.total_pages}</td>
    </tr>`
    )
    .join("");
  return `<table><tr><th>Day</th><th>Location</th><th>Int/Ext</th><th>Time</th><th>Scenes</th><th>Pages</th></tr>${rows}</table>
    <p class="hint">${pkg.schedule.total_shoot_days} shoot day(s) at ${pkg.schedule.max_pages_per_day} pages/day target</p>`;
}

function renderBudgetTable(lineItems) {
  const rows = lineItems
    .map((item) => {
      const badge = item.grounded
        ? `<span class="badge grounded">grounded</span>`
        : `<span class="badge ungrounded">ungrounded</span>`;
      const sources = (item.source_records || []).map((r) => escapeHtml(r.record_id)).join(", ") || "—";
      return `<tr><td>${escapeHtml(item.label)}</td><td>${escapeHtml(item.currency)} ${Number(item.amount).toLocaleString()}</td><td>${badge}</td><td>${sources}</td></tr>`;
    })
    .join("");
  return `<table><tr><th>Label</th><th>Amount</th><th>Grounded</th><th>Sources</th></tr>${rows}</table>`;
}

function renderBudgetFullTab(budget) {
  return `
    <div class="approval-total"><span class="currency">${escapeHtml(budget.currency)}</span> ${Number(budget.total_estimated_cost).toLocaleString()}</div>
    ${renderBudgetTable(budget.line_items)}
  `;
}

function renderRiskTab(risk) {
  if (!risk.flags.length) return emptyTab("No risks flagged.");
  const rows = risk.flags
    .map(
      (flag) => `
    <tr>
      <td>${escapeHtml(flag.category)}</td>
      <td><span class="badge severity-${flag.severity}">${escapeHtml(flag.severity)}</span></td>
      <td>${escapeHtml(flag.description)}</td>
      <td>${escapeHtml(flag.recommendation)}</td>
    </tr>`
    )
    .join("");
  const replan = risk.replan_requested
    ? `<p class="hint">A re-plan was requested: ${escapeHtml(risk.replan_reason)}</p>`
    : "";
  return `<table><tr><th>Category</th><th>Severity</th><th>Description</th><th>Recommendation</th></tr>${rows}</table>${replan}`;
}

function renderResourcesTab(resources) {
  const picks = [...resources.crew_picks, ...resources.location_picks];
  if (!picks.length) return emptyTab("No resource picks produced.");
  const rows = picks
    .map((pick) => {
      const badge = pick.grounded
        ? `<span class="badge grounded">grounded</span>`
        : `<span class="badge ungrounded">ungrounded</span>`;
      return `<tr><td>${escapeHtml(pick.need)}</td><td>${escapeHtml(pick.recommendation)}</td><td>${badge}</td></tr>`;
    })
    .join("");
  return `<table><tr><th>Need</th><th>Recommendation</th><th>Grounded</th></tr>${rows}</table>`;
}

function renderPrevizTab(previz) {
  let html = `<div class="previz-gallery">`;
  for (const p of previz.storyboard_paths) {
    html += `<img src="${previzUrl(p)}" alt="storyboard frame" loading="lazy" />`;
  }
  if (previz.animatic_path && !previz.animatic_path.endsWith(".uri.txt")) {
    html += `<video controls src="${previzUrl(previz.animatic_path)}"></video>`;
  }
  if (previz.music_cue_path) {
    html += `<audio controls src="${previzUrl(previz.music_cue_path)}"></audio>`;
  }
  html += `</div>`;
  for (const w of previz.warnings || []) {
    html += `<p class="previz-warning">${escapeHtml(w)}</p>`;
  }
  return html;
}

function previzUrl(serverPath) {
  const filename = serverPath.split(/[\\/]/).pop();
  return `/previz/${currentRunId}/${filename}`;
}

/* ---------- metrics ---------- */
function renderMetrics(metrics) {
  if (!metrics) return;
  const tiles = [
    ["Task completed", metrics.task_completed ? "Yes" : "No", metrics.task_completed],
    ["Tool calls", metrics.tool_calls, null],
    ["Tool success", formatPct(metrics.tool_success_rate), metrics.tool_success_rate === null ? null : metrics.tool_success_rate >= 0.9],
    ["Grounded rate", formatPct(metrics.grounded_rate), metrics.grounded_rate === null ? null : metrics.grounded_rate >= 0.9],
    ["Total tokens", metrics.total_tokens ?? "—", null],
    ["Latency (s)", metrics.total_latency_seconds, null],
  ];
  metricsEl.innerHTML = `<div class="metric-grid">${tiles
    .map(([label, value, good]) => {
      const cls = good === true ? " is-good" : good === false ? " is-bad" : "";
      return `<div class="metric-tile${cls}"><div class="value">${value}</div><div class="label">${escapeHtml(label)}</div></div>`;
    })
    .join("")}</div>`;
}

function formatPct(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/* ---------- utils ---------- */
function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
