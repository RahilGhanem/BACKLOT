/* ---------- element refs ---------- */
const screenplayEl = document.getElementById("screenplay");
const runBtn = document.getElementById("run");
const loadSampleBtn = document.getElementById("load-sample");
const loadReplanDemoBtn = document.getElementById("load-replan-demo");
const runStatusEl = document.getElementById("run-status");
const withPrevizEl = document.getElementById("with-previz");

const crewPanel = document.getElementById("crew-panel");
const crewTrackEl = document.getElementById("crew-track");
const replanBannerEl = document.getElementById("replan-banner");
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
  script: `<img src="${encodeURI("/icons/Script Supervisor.png")}" alt="Script Supervisor" />`,
  film: `<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M16 4v16M3 9h5M16 9h5M3 15h5M16 15h5"/></svg>`,
  calendar: `<img src="${encodeURI("/icons/1st-AD Scheduler.png")}" alt="1st-AD Scheduler" />`,
  dollar: `<img src="${encodeURI("/icons/Budget Agent.png")}" alt="Budget Agent" />`,
  alert: `<img src="${encodeURI("/icons/Risk Continuity.png")}" alt="Risk / Continuity" />`,
  check: `<img src="${encodeURI("/icons/Approval Gate.png")}" alt="Approval Gate" />`,
  users: `<img src="${encodeURI("/icons/Resource Agent.png")}" alt="Resource Agent" />`,
  package: `<img src="${encodeURI("/icons/Package Assembler.png")}" alt="Package Assembler" />`,
};

const AGENT_DEFS = [
  { key: "script_supervisor", label: "Script Supervisor", hint: "Parses the screenplay into a scene breakdown", icon: ICONS.script },
  { key: "previz_agent", label: "Previz", hint: "Imagen storyboards, Veo animatic, Lyria cue", icon: ICONS.film, optional: true },
  { key: "first_ad_scheduler", label: "1st-AD Scheduler", hint: "Builds the stripboard shoot schedule", icon: ICONS.calendar },
  { key: "budget_agent", label: "Budget Agent", hint: "Grounded in studio data via ClickHouse MCP", icon: ICONS.dollar },
  { key: "risk_agent", label: "Risk / Continuity", hint: "Critiques the schedule and budget", icon: ICONS.alert },
  { key: "approval_gate", label: "Approval Gate", hint: "Producer signs off the budget band", icon: ICONS.check },
  { key: "resource_agent", label: "Resource Agent", hint: "Grounded in studio data via ClickHouse MCP", icon: ICONS.users },
  { key: "package_assembler", label: "Package Assembler", hint: "Combines everything into the package", icon: ICONS.package },
];
const STATUS_LABEL = { pending: "Pending", active: "Working", done: "Done", skipped: "Skipped", error: "Error" };
const STEPS = ["input", "crew", "approval", "done"];
// Mirrors MAX_REPLANS + 1 in backlot/orchestrator/line_producer.py (the
// loop runs at most MAX_REPLANS re-plans, i.e. MAX_REPLANS + 1 attempts
// total) — purely cosmetic (the "attempt N of 3" label), never enforced
// client-side.
const MAX_REPLAN_ATTEMPTS = 3;

/* ---------- run state ---------- */
let currentRunId = null;
let currentWithPreviz = false;
let currentPackage = null;
let pollHandle = null;
let renderedEventCount = 0;
let approvalShown = false;
let activeTabId = null;

/* ---------- setup actions ---------- */
loadSampleBtn.addEventListener("click", async () => {
  const res = await fetch("/api/sample-screenplay");
  const data = await res.json();
  screenplayEl.value = data.screenplay;
});

loadReplanDemoBtn.addEventListener("click", async () => {
  const res = await fetch("/api/replan-demo-screenplay");
  const data = await res.json();
  screenplayEl.value = data.screenplay;
  setStatus("Loaded the re-plan demo — six consecutive night exteriors, built to trigger the bounded re-plan loop.");
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
  activeTabId = null;
  activityLogEl.innerHTML = "";
  replanBannerEl.classList.add("hidden");
  replanBannerEl.innerHTML = "";
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

  const isFinal = ["completed", "rejected", "error"].includes(data.status);

  // Render progressively: as soon as ANY crew member has produced
  // something (the breakdown, the schedule, ...), show it — don't wait
  // for the whole run to finish. This is the same renderResults() the
  // final view uses; partial_state just has fewer keys filled in yet.
  const inProgressPkg = data.package || data.partial_state;
  if (inProgressPkg && Object.keys(inProgressPkg).length) {
    renderResults(inProgressPkg, isFinal);
  }

  if (data.status === "completed" || data.status === "rejected") {
    clearInterval(pollHandle);
    resetRunBtn();
    setStep("done");
    setStatus(
      data.status === "completed" ? "Package complete." : "Budget rejected — package assembled without resources.",
      data.status === "completed" ? "ok" : "error"
    );
    renderMetrics(data.metrics);
  } else if (data.status === "error") {
    clearInterval(pollHandle);
    resetRunBtn();
    setStatus(`Error: ${data.error || "unknown error"}`, "error");
    if (data.metrics) renderMetrics(data.metrics);
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

// The three sub-agents the bounded re-plan loop actually re-runs together
// (see backlot/orchestrator/line_producer.py) — used to detect a re-plan
// and drive the unmistakable banner below, independent of the small
// per-card "re-plan ×N" pill.
const REPLAN_LOOP_AGENTS = ["first_ad_scheduler", "budget_agent", "risk_agent"];

function updateReplanBanner(events) {
  const authors = events.map((e) => e.author);
  const attempts = Math.max(0, ...REPLAN_LOOP_AGENTS.map((key) => countBlocks(authors, key)));
  if (attempts <= 1) {
    replanBannerEl.classList.add("hidden");
    replanBannerEl.innerHTML = "";
    return;
  }
  replanBannerEl.classList.remove("hidden");
  replanBannerEl.innerHTML = `
    <span class="replan-banner-icon">🔁</span>
    <span class="replan-banner-text">
      <strong>Re-plan loop triggered</strong> — Risk/Continuity flagged a structural
      problem in the schedule. Scheduler → Budget → Risk re-ran
      <strong>attempt ${attempts} of ${MAX_REPLAN_ATTEMPTS}</strong>.
    </span>`;
}

function renderCrew(events, status) {
  const defs = AGENT_DEFS.filter((d) => !d.optional || currentWithPreviz);
  const authors = events.map((e) => e.author);
  const lastAuthor = authors.length ? authors[authors.length - 1] : null;

  updateReplanBanner(events);

  crewTrackEl.innerHTML = defs
    .map((def) => {
      const state = computeCrewState(def, authors, lastAuthor, status);
      const blocks = countBlocks(authors, def.key);
      const repeatBadge = blocks > 1 ? `<span class="crew-repeat">re-plan ×${blocks}</span>` : "";
      // While a card is active, show what it's actually doing right now
      // (the latest tool call / message for that agent) instead of the
      // static description — this is the live "what is the system doing"
      // visibility, not just a pending/done dot.
      const activity = state === "active" ? latestActivityFor(events, def.key) : "";
      const subtitle = activity || def.hint;
      return `
      <li class="crew-card is-${state}">
        <span class="crew-icon">${def.icon}</span>
        <span class="crew-body">
          <span class="crew-name">${escapeHtml(def.label)} ${repeatBadge}</span>
          <span class="crew-hint${activity ? " is-live" : ""}">${escapeHtml(subtitle)}</span>
        </span>
        <span class="crew-status"><span class="dot"></span>${STATUS_LABEL[state]}</span>
      </li>`;
    })
    .join("");
}

function latestActivityFor(events, key) {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev.author !== key) continue;
    if (ev.tool_calls && ev.tool_calls.length) return `→ calling ${ev.tool_calls.join(", ")}`;
    if (ev.text) return `→ ${ev.text}`;
    return "→ working…";
  }
  return "";
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

/* ---------- results ----------
   Called repeatedly while a run is still in progress (with whatever
   partial_state has filled in so far) and once more at the end with the
   final package — so tabs appear one by one as each crew member finishes,
   rather than all at once at the very end. `isFinal` controls whether a
   still-missing section renders as "not produced yet" (in progress) or
   "not produced" (run is over, it's just not coming). */
function renderResults(pkg, isFinal) {
  resultsPanel.classList.remove("hidden");
  currentPackage = pkg;
  if (!pkg) {
    tabsEl.innerHTML = "";
    tabPanelsEl.innerHTML = `<p class="empty-state">No package produced.</p>`;
    return;
  }

  const tabs = [];
  if (pkg.breakdown) tabs.push({ id: "breakdown", label: "Breakdown", html: renderBreakdownTab(pkg) });
  if (pkg.schedule) tabs.push({ id: "schedule", label: "Schedule", html: renderScheduleTab(pkg) });
  if (pkg.budget) {
    tabs.push({ id: "budget", label: "Budget", html: renderBudgetFullTab(pkg.budget) });
  } else if (isFinal) {
    tabs.push({ id: "budget", label: "Budget", html: emptyTab("No budget produced.") });
  }
  if (pkg.risk_report) {
    tabs.push({ id: "risk", label: "Risk", html: renderRiskTab(pkg.risk_report) });
  } else if (isFinal) {
    tabs.push({ id: "risk", label: "Risk", html: emptyTab("No risk report produced.") });
  }
  if (pkg.resources) {
    tabs.push({ id: "resources", label: "Resources", html: renderResourcesTab(pkg.resources) });
  } else if (isFinal) {
    tabs.push({ id: "resources", label: "Resources", html: emptyTab("Not produced (budget was rejected, or the run stopped early).") });
  }
  if (pkg.previz) tabs.push({ id: "previz", label: "Previz", html: renderPrevizTab(pkg.previz) });

  if (!tabs.length) {
    tabsEl.innerHTML = "";
    tabPanelsEl.innerHTML = `<p class="empty-state">Waiting for the crew's first results…</p>`;
    return;
  }

  // Keep whichever tab the user is looking at selected as new tabs appear
  // around it, instead of jumping back to the first tab on every poll.
  const activeId = tabs.some((t) => t.id === activeTabId) ? activeTabId : tabs[0].id;
  activeTabId = activeId;

  tabsEl.innerHTML = tabs
    .map((t) => `<button class="tab-btn${t.id === activeId ? " is-active" : ""}" data-tab="${t.id}" role="tab">${escapeHtml(t.label)}</button>`)
    .join("");
  tabPanelsEl.innerHTML = tabs
    .map((t) => `<div class="tab-panel${t.id === activeId ? "" : " hidden"}" data-tab-panel="${t.id}">${t.html}</div>`)
    .join("");

  tabsEl.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTabId = btn.dataset.tab;
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
