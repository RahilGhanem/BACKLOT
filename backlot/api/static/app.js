const screenplayEl = document.getElementById("screenplay");
const runBtn = document.getElementById("run");
const loadSampleBtn = document.getElementById("load-sample");
const runStatusEl = document.getElementById("run-status");
const activityLogEl = document.getElementById("activity-log");
const approvalPanel = document.getElementById("approval-panel");
const approvalSummaryEl = document.getElementById("approval-summary");
const approveYesBtn = document.getElementById("approve-yes");
const approveNoBtn = document.getElementById("approve-no");
const resultsPanel = document.getElementById("results-panel");
const resultsEl = document.getElementById("results");
const metricsPanel = document.getElementById("metrics-panel");
const metricsEl = document.getElementById("metrics");

let currentRunId = null;
let pollHandle = null;
let renderedEventCount = 0;
let lastStatus = null;

loadSampleBtn.addEventListener("click", async () => {
  const res = await fetch("/api/sample-screenplay");
  const data = await res.json();
  screenplayEl.value = data.screenplay;
});

runBtn.addEventListener("click", async () => {
  const screenplay = screenplayEl.value.trim();
  if (!screenplay) {
    runStatusEl.textContent = "Paste a screenplay first (or load the sample).";
    return;
  }
  resetPanels();
  runBtn.disabled = true;
  runStatusEl.textContent = "Starting the crew...";

  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ screenplay }),
  });
  if (!res.ok) {
    runStatusEl.textContent = "Failed to start run.";
    runBtn.disabled = false;
    return;
  }
  const data = await res.json();
  currentRunId = data.run_id;
  startPolling();
});

approveYesBtn.addEventListener("click", () => submitApproval(true));
approveNoBtn.addEventListener("click", () => submitApproval(false));

async function submitApproval(approved) {
  approveYesBtn.disabled = true;
  approveNoBtn.disabled = true;
  await fetch(`/api/runs/${currentRunId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, reason: "" }),
  });
  approvalPanel.classList.add("hidden");
}

function resetPanels() {
  activityLogEl.innerHTML = "";
  renderedEventCount = 0;
  lastStatus = null;
  approvalPanel.classList.add("hidden");
  resultsPanel.classList.add("hidden");
  metricsPanel.classList.add("hidden");
  approveYesBtn.disabled = false;
  approveNoBtn.disabled = false;
}

function startPolling() {
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = setInterval(pollRun, 1200);
  pollRun();
}

async function pollRun() {
  const res = await fetch(`/api/runs/${currentRunId}`);
  if (!res.ok) return;
  const data = await res.json();

  appendNewEvents(data.events || []);

  if (data.status !== lastStatus) {
    lastStatus = data.status;
    runStatusEl.textContent = `Status: ${data.status}`;
  }

  if (data.status === "awaiting_approval") {
    showApproval(data.events);
  } else {
    approvalPanel.classList.add("hidden");
  }

  if (data.status === "completed" || data.status === "rejected") {
    clearInterval(pollHandle);
    runBtn.disabled = false;
    renderResults(data.package);
    renderMetrics(data.metrics);
  } else if (data.status === "error") {
    clearInterval(pollHandle);
    runBtn.disabled = false;
    runStatusEl.textContent = `Error: ${data.error || "unknown error"}`;
  }
}

function appendNewEvents(events) {
  for (let i = renderedEventCount; i < events.length; i++) {
    const ev = events[i];
    const li = document.createElement("li");
    const toolBadges = (ev.tool_calls || [])
      .map((t) => `<span class="tool">${escapeHtml(t)}</span>`)
      .join("");
    li.innerHTML = `<span class="agent">${escapeHtml(ev.author)}</span>${escapeHtml(
      ev.text || ""
    )}${toolBadges}`;
    activityLogEl.appendChild(li);
  }
  renderedEventCount = events.length;
  activityLogEl.scrollTop = activityLogEl.scrollHeight;
}

function showApproval(events) {
  // Find the budget agent's line items from the most recent event stream
  // isn't directly available here (events are just a log), so pull the
  // budget out of the running package state via a light heuristic: the
  // API doesn't expose partial state, so we just prompt generically.
  approvalPanel.classList.remove("hidden");
  approvalSummaryEl.innerHTML =
    "<p>The Budget and Risk agents have finished. Approve to let the Resource Agent propose crew and locations.</p>";
}

function renderResults(pkg) {
  resultsPanel.classList.remove("hidden");
  if (!pkg) {
    resultsEl.innerHTML = "<p>No package produced.</p>";
    return;
  }
  let html = "";

  html += `<div class="section-title">Schedule</div>`;
  html += `<table><tr><th>Day</th><th>Location</th><th>Int/Ext</th><th>Time</th><th>Scenes</th><th>Pages</th></tr>`;
  for (const day of pkg.schedule.days) {
    html += `<tr><td>${day.day_number}</td><td>${escapeHtml(day.location)}</td><td>${day.int_ext}</td><td>${day.time_of_day}</td><td>${day.scene_numbers.join(", ")}</td><td>${day.total_pages}</td></tr>`;
  }
  html += `</table>`;

  if (pkg.budget) {
    html += `<div class="section-title">Budget — ${pkg.budget.currency} ${pkg.budget.total_estimated_cost.toLocaleString()}</div>`;
    html += `<table><tr><th>Label</th><th>Amount</th><th>Grounded</th><th>Sources</th></tr>`;
    for (const item of pkg.budget.line_items) {
      const badge = item.grounded
        ? `<span class="badge grounded">grounded</span>`
        : `<span class="badge ungrounded">ungrounded</span>`;
      const sources = (item.source_records || []).map((r) => r.record_id).join(", ");
      html += `<tr><td>${escapeHtml(item.label)}</td><td>${item.currency} ${item.amount.toLocaleString()}</td><td>${badge}</td><td>${escapeHtml(sources)}</td></tr>`;
    }
    html += `</table>`;
  }

  if (pkg.risk_report) {
    html += `<div class="section-title">Risk report</div>`;
    if (pkg.risk_report.flags.length === 0) {
      html += `<p>No risks flagged.</p>`;
    } else {
      html += `<table><tr><th>Category</th><th>Severity</th><th>Description</th><th>Recommendation</th></tr>`;
      for (const flag of pkg.risk_report.flags) {
        html += `<tr><td>${escapeHtml(flag.category)}</td><td><span class="badge severity-${flag.severity}">${flag.severity}</span></td><td>${escapeHtml(flag.description)}</td><td>${escapeHtml(flag.recommendation)}</td></tr>`;
      }
      html += `</table>`;
    }
  }

  if (pkg.approval) {
    const badge = pkg.approval.approved
      ? `<span class="badge grounded">approved</span>`
      : `<span class="badge ungrounded">rejected</span>`;
    html += `<div class="section-title">Approval</div><p>${badge} ${escapeHtml(pkg.approval.reason)}</p>`;
  }

  if (pkg.resources) {
    html += `<div class="section-title">Resources</div>`;
    html += `<table><tr><th>Need</th><th>Recommendation</th><th>Grounded</th></tr>`;
    for (const pick of [...pkg.resources.crew_picks, ...pkg.resources.location_picks]) {
      const badge = pick.grounded
        ? `<span class="badge grounded">grounded</span>`
        : `<span class="badge ungrounded">ungrounded</span>`;
      html += `<tr><td>${escapeHtml(pick.need)}</td><td>${escapeHtml(pick.recommendation)}</td><td>${badge}</td></tr>`;
    }
    html += `</table>`;
  } else {
    html += `<div class="section-title">Resources</div><p>Not produced (budget was rejected).</p>`;
  }

  resultsEl.innerHTML = html;
}

function renderMetrics(metrics) {
  if (!metrics) return;
  metricsPanel.classList.remove("hidden");
  const tiles = [
    ["Task completed", metrics.task_completed ? "yes" : "no"],
    ["Tool calls", metrics.tool_calls],
    ["Tool success rate", formatPct(metrics.tool_success_rate)],
    ["Grounded rate", formatPct(metrics.grounded_rate)],
    ["Total tokens", metrics.total_tokens ?? "—"],
    ["Total latency (s)", metrics.total_latency_seconds],
  ];
  metricsEl.innerHTML = `<div class="metric-grid">${tiles
    .map(
      ([label, value]) =>
        `<div class="metric-tile"><div class="value">${value}</div><div class="label">${label}</div></div>`
    )
    .join("")}</div>`;
}

function formatPct(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
