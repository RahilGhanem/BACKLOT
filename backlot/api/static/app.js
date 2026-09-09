/* Run engine, router and DOM wiring.
 *
 * API:
 *   GET  /api/sample-screenplay | /api/replan-demo-screenplay
 *   POST /api/runs                {screenplay, with_previz}
 *   GET  /api/runs/{id}
 *   POST /api/runs/{id}/approve   {approved, reason}
 *
 * Rendering lives in views.js.
 */
(function () {
  "use strict";

  var V = BACKLOT_VIEWS;
  var esc = V.escapeHtml;

  /* ---------- element refs ---------- */
  var screenplayEl = document.getElementById("screenplay");
  var runBtn = document.getElementById("run");
  var loadSampleBtn = document.getElementById("load-sample");
  var loadReplanDemoBtn = document.getElementById("load-replan-demo");
  var runStatusEl = document.getElementById("run-status");
  var withPrevizEl = document.getElementById("with-previz");
  var openPackageEl = document.getElementById("open-package");
  var runChip = document.getElementById("run-chip");

  var crewTrackEl = document.getElementById("crew-track");
  var replanBannerEl = document.getElementById("replan-banner");
  var activityLogEl = document.getElementById("activity-log");
  var toggleLogBtn = document.getElementById("toggle-log");
  var timelineEl = document.getElementById("agent-timeline");

  var approvalBackdrop = document.getElementById("approval-backdrop");
  var approvalBudgetEl = document.getElementById("approval-budget");
  var approveYesBtn = document.getElementById("approve-yes");
  var approveNoBtn = document.getElementById("approve-no");

  var downloadBtn = document.getElementById("download-json");
  var railListEl = document.getElementById("rail-list");
  var railGroundValue = document.getElementById("rail-ground-value");
  var railGroundSub = document.getElementById("rail-ground-sub");
  var pipelineMapEl = document.getElementById("pipeline-map");

  var provDrawer = document.getElementById("prov-drawer");
  var provBackdrop = document.getElementById("prov-backdrop");
  var provBody = document.getElementById("prov-body");
  var provClose = document.getElementById("prov-close");

  var stepperEls = [].slice.call(document.querySelectorAll("#stepper li"));
  var RUN_BTN_IDLE = runBtn.innerHTML;

  /* ---------- agent definitions (unchanged identity) ---------- */
  var ICONS = {
    script: '<img src="' + encodeURI("/icons/small/Script Supervisor.png") + '" alt="" />',
    film: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M16 4v16M3 9h5M16 9h5M3 15h5M16 15h5"/></svg>',
    calendar: '<img src="' + encodeURI("/icons/small/1st-AD Scheduler.png") + '" alt="" />',
    dollar: '<img src="' + encodeURI("/icons/small/Budget Agent.png") + '" alt="" />',
    alert: '<img src="' + encodeURI("/icons/small/Risk Continuity.png") + '" alt="" />',
    check: '<img src="' + encodeURI("/icons/small/Approval Gate.png") + '" alt="" />',
    users: '<img src="' + encodeURI("/icons/small/Resource Agent.png") + '" alt="" />',
    package: '<img src="' + encodeURI("/icons/small/Package Assembler.png") + '" alt="" />',
  };

  var AGENT_DEFS = [
    { key: "script_supervisor", label: "Script Supervisor", hint: "Parses the screenplay into a scene breakdown", icon: ICONS.script },
    { key: "previz_agent", label: "Previz", hint: "Imagen storyboards, Veo animatic, Lyria cue", icon: ICONS.film, optional: true },
    { key: "first_ad_scheduler", label: "1st-AD Scheduler", hint: "Builds the stripboard shoot schedule", icon: ICONS.calendar },
    { key: "budget_agent", label: "Budget Agent", hint: "Grounded in studio data via ClickHouse MCP", icon: ICONS.dollar },
    { key: "risk_agent", label: "Risk / Continuity", hint: "Critiques the schedule and budget", icon: ICONS.alert },
    { key: "approval_gate", label: "Approval Gate", hint: "Producer signs off the budget band", icon: ICONS.check },
    { key: "resource_agent", label: "Resource Agent", hint: "Grounded in studio data via ClickHouse MCP", icon: ICONS.users },
    { key: "package_assembler", label: "Package Assembler", hint: "Combines everything into the package", icon: ICONS.package },
  ];
  var STATUS_LABEL = { pending: "Pending", active: "Working", done: "Done", skipped: "Skipped", error: "Error" };
  var REPLAN_LOOP_AGENTS = ["first_ad_scheduler", "budget_agent", "risk_agent"];
  var MAX_REPLAN_ATTEMPTS = 3; // mirrors MAX_REPLANS + 1 in line_producer.py (cosmetic label only)

  /* `ready` gates navigation: a view is offered once its data exists. */
  var ROUTES = [
    { id: "setup", label: "Screenplay", glyph: "◧", ready: function () { return true; } },
    { id: "crew", label: "Crew", glyph: "◈", ready: function () { return !!currentRunId; } },
    // Always reachable: with no run loaded it shows the idle control room.
    { id: "overview", label: "Overview", glyph: "◉", ready: function () { return true; } },
    { id: "breakdown", label: "Scenes", glyph: "▤", ready: function () { return !!pkgField("breakdown"); } },
    { id: "schedule", label: "Stripboard", glyph: "▥", ready: function () { return !!pkgField("schedule"); } },
    { id: "budget", label: "Budget", glyph: "▦", ready: function () { return !!pkgField("budget"); } },
    { id: "risk", label: "Risk", glyph: "▲", ready: function () { return !!pkgField("risk_report"); } },
    { id: "resources", label: "Resources", glyph: "▧", ready: function () { return !!pkgField("resources"); } },
    { id: "previz", label: "Previz", glyph: "▶", ready: function () { return !!pkgField("previz"); } },
    { id: "package", label: "Package", glyph: "⬢", ready: function () { return hasAny(); } },
  ];

  /* ---------- run state ---------- */
  var currentRunId = null;
  var currentWithPreviz = false;
  var currentPackage = null;   // package || partial_state (whatever exists)
  var currentMetrics = null;
  var currentStatus = null;
  var currentEvents = [];
  var pollHandle = null;
  var renderedEventCount = 0;
  var approvalShown = false;
  var lastFocused = null;
  var appliedView = null; // which view the DOM currently reflects

  function pkgField(k) {
    return currentPackage && currentPackage[k];
  }
  function hasAny() {
    return !!(currentPackage && Object.keys(currentPackage).length);
  }

  /* ---------- router ---------- */

  function currentView() {
    var id = (location.hash || "").replace(/^#\/?/, "");
    return ROUTES.some(function (r) { return r.id === id; }) ? id : "setup";
  }

  /* Applies the route synchronously as well as setting the hash, since
     `hashchange` fires asynchronously and gotoAnchor needs the new DOM. */
  function navigate(id, opts) {
    if (location.hash !== "#/" + id) location.hash = "#/" + id;
    applyRoute(opts);
  }

  function applyRoute(opts) {
    var id = currentView();
    var route = ROUTES.filter(function (r) { return r.id === id; })[0];
    // Fall back when the data behind the view does not exist.
    if (route && !route.ready()) {
      id = hasAny() ? "overview" : "setup";
    }
    appliedView = id;
    document.querySelectorAll(".view").forEach(function (v) {
      v.classList.toggle("is-active", v.dataset.view === id);
    });
    renderRail();
    renderView(id);
    updateGroundChip();
    if (!(opts && opts.keepScroll)) window.scrollTo({ top: 0, behavior: "instant" in document.body.style ? "instant" : "auto" });
  }

  /* Only act when the hash points somewhere the DOM isn't showing, i.e.
     the back/forward case. navigate() has already rendered the rest, and
     re-rendering here would wipe the cross-link flash. */
  window.addEventListener("hashchange", function () {
    if (currentView() !== appliedView) applyRoute();
  });

  function renderRail() {
    var active = currentView();
    railListEl.innerHTML = ROUTES.map(function (r) {
      var ready = r.ready();
      return (
        '<li><a class="rail-item' + (r.id === active ? " is-active" : "") + (ready ? "" : " is-locked") +
        '" href="#/' + r.id + '"' + (ready ? "" : ' aria-disabled="true" tabindex="-1"') +
        (r.id === active ? ' aria-current="page"' : "") + '>' +
        '<span class="rail-glyph" aria-hidden="true">' + r.glyph + "</span>" +
        '<span class="rail-label">' + esc(r.label) + "</span></a></li>"
      );
    }).join("");
  }

  /* ---------- view rendering ---------- */

  function renderView(id) {
    V.resetProvenance();
    var pkg = currentPackage || {};
    switch (id) {
      case "overview":
        setHTML("overview-body", V.renderOverview(pkg, currentMetrics, currentStatus, currentEvents, currentWithPreviz, currentRunId));
        break;
      case "breakdown":
        setHTML("breakdown-body", V.renderBreakdown(pkg));
        break;
      case "schedule":
        setHTML("schedule-body", V.renderStripboard(pkg));
        break;
      case "budget":
        setHTML("budget-body", V.renderBudget(pkg, currentEvents));
        break;
      case "risk":
        setHTML("risk-body", V.renderRisk(pkg));
        break;
      case "resources":
        setHTML("resources-body", V.renderResources(pkg, currentEvents));
        break;
      case "previz":
        setHTML("previz-body", V.renderPreviz(pkg.previz, currentRunId));
        break;
      case "package":
        setHTML("package-body", V.renderPackage(pkg, currentMetrics, currentStatus));
        break;
      case "crew":
        timelineEl.innerHTML = V.renderTimeline(currentEvents, currentMetrics);
        break;
    }
  }

  function setHTML(elId, html) {
    var el = document.getElementById(elId);
    if (el) el.innerHTML = html;
  }

  /** Re-render whichever view is on screen (called on every poll tick). */
  function refreshActiveView() {
    renderView(currentView());
    renderRail();
    updateGroundChip();
  }

  function updateGroundChip() {
    var rate = currentMetrics && currentMetrics.grounded_rate != null
      ? currentMetrics.grounded_rate
      : (currentPackage ? V.deriveGrounding(currentPackage).rate : null);
    if (rate != null) {
      railGroundValue.textContent = V.pct(rate);
      railGroundValue.className = "rail-ground-value " + (rate >= 0.9 ? "is-good" : "is-warn");
    } else {
      railGroundValue.textContent = "—";
      railGroundValue.className = "rail-ground-value";
    }
    var store = currentPackage ? V.groundingStore(currentPackage) : null;
    railGroundSub.textContent = store ? "grounded in " + store : "grounded";
  }

  /* ---------- setup page actions ---------- */

  loadSampleBtn.addEventListener("click", async function () {
    try {
      var res = await fetch("/api/sample-screenplay");
      var data = await res.json();
      screenplayEl.value = data.screenplay;
      setStatus("Sample screenplay loaded.");
    } catch (e) {
      setStatus("Could not load the sample screenplay.", "error");
    }
  });

  loadReplanDemoBtn.addEventListener("click", async function () {
    try {
      var res = await fetch("/api/replan-demo-screenplay");
      var data = await res.json();
      screenplayEl.value = data.screenplay;
      setStatus("Loaded the re-plan demo — six consecutive night exteriors, built to trigger the bounded re-plan loop.");
    } catch (e) {
      setStatus("Could not load the re-plan demo.", "error");
    }
  });

  runBtn.addEventListener("click", async function () {
    var screenplay = screenplayEl.value.trim();
    if (!screenplay) {
      setStatus("Paste a screenplay first (or load the sample).", "error");
      screenplayEl.focus();
      return;
    }
    resetForNewRun();
    currentWithPreviz = withPrevizEl.checked;
    setRunBtnBusy("Starting the crew…");
    setStatus("Starting the crew…");
    setStep("crew");

    var res;
    try {
      res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ screenplay: screenplay, with_previz: currentWithPreviz }),
      });
    } catch (e) {
      setStatus("Could not reach the BACKLOT server.", "error");
      resetRunBtn();
      return;
    }
    if (!res.ok) {
      setStatus("Failed to start run.", "error");
      resetRunBtn();
      return;
    }
    var data = await res.json();
    currentRunId = data.run_id;
    renderCrew([], "running");
    navigate("crew");
    startPolling();
  });

  toggleLogBtn.addEventListener("click", function () {
    var nowHidden = !activityLogEl.hidden;
    activityLogEl.hidden = nowHidden;
    toggleLogBtn.textContent = nowHidden ? "Show console ▾" : "Hide console ▴";
    toggleLogBtn.setAttribute("aria-expanded", String(!nowHidden));
  });

  approveYesBtn.addEventListener("click", function () { submitApproval(true); });
  approveNoBtn.addEventListener("click", function () { submitApproval(false); });

  downloadBtn.addEventListener("click", function () {
    if (!currentPackage) return;
    var blob = new Blob([JSON.stringify(currentPackage, null, 2)], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "backlot_package_" + (currentRunId || "run") + ".json";
    a.click();
    URL.revokeObjectURL(url);
  });

  /* Reopens a downloaded package for review without running the crew.
     A package with no metrics block reports none. */
  openPackageEl.addEventListener("change", async function (ev) {
    var file = ev.target.files && ev.target.files[0];
    if (!file) return;
    try {
      var data = JSON.parse(await file.text());
      // Accept a raw package, or a {package, metrics} wrapper.
      var pkg = data && typeof data.package === "object" && data.package ? data.package : data;
      var known = ["breakdown", "schedule", "budget", "risk_report", "resources", "approval", "previz"];
      if (!pkg || !known.some(function (k) { return pkg[k]; })) {
        setStatus("That file does not look like a BACKLOT package.", "error");
        return;
      }
      if (pollHandle) clearInterval(pollHandle);
      currentRunId = null;
      currentEvents = [];
      currentPackage = pkg;
      currentMetrics = (data && data.metrics) || null;
      currentStatus = "loaded";
      currentWithPreviz = !!pkg.previz;
      renderedEventCount = 0;
      activityLogEl.innerHTML = "";
      setStep("done");
      setRunChip("loaded");
      setStatus("Opened “" + file.name + "” — viewing a saved package. No agents ran.", "ok");
      navigate("overview");
    } catch (e) {
      setStatus("Could not read that file as JSON.", "error");
    } finally {
      ev.target.value = "";
    }
  });

  /* ---------- provenance drawer + cross-link navigation ---------- */

  document.addEventListener("click", function (ev) {
    var provBtn = ev.target.closest("[data-prov]");
    if (provBtn) {
      openProvenance(Number(provBtn.dataset.prov));
      return;
    }
    var toView = ev.target.closest("[data-goto-view]");
    if (toView) {
      navigate(toView.dataset.gotoView);
      return;
    }
    var toScene = ev.target.closest("[data-goto-scene]");
    if (toScene) {
      gotoAnchor("breakdown", "scene-" + toScene.dataset.gotoScene);
      return;
    }
    var toDay = ev.target.closest("[data-goto-day]");
    if (toDay) {
      gotoAnchor("schedule", "day-" + toDay.dataset.gotoDay);
      return;
    }
  });

  function gotoAnchor(view, anchorId) {
    // keepScroll: applyRoute would otherwise fight the scrollIntoView below.
    navigate(view, { keepScroll: true });
    window.requestAnimationFrame(function () {
      var el = document.getElementById(anchorId);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("is-flash");
        setTimeout(function () { el.classList.remove("is-flash"); }, 1400);
      }
    });
  }

  function openProvenance(i) {
    var entry = V.getProvenance(i);
    if (!entry) return;
    lastFocused = document.activeElement;
    provBody.innerHTML = V.renderProvenance(entry, currentPackage);
    provDrawer.hidden = false;
    provBackdrop.hidden = false;
    document.body.classList.add("is-locked");
    provClose.focus();
  }

  function closeProvenance() {
    provDrawer.hidden = true;
    provBackdrop.hidden = true;
    document.body.classList.remove("is-locked");
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  provClose.addEventListener("click", closeProvenance);
  provBackdrop.addEventListener("click", closeProvenance);

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !provDrawer.hidden) closeProvenance();
  });

  /* ---------- approval ---------- */

  async function submitApproval(approved) {
    approveYesBtn.disabled = true;
    approveNoBtn.disabled = true;
    try {
      await fetch("/api/runs/" + currentRunId + "/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: approved, reason: "" }),
      });
    } finally {
      closeApproval();
      approveYesBtn.disabled = false;
      approveNoBtn.disabled = false;
    }
  }

  function showApproval(pendingBudget) {
    approvalBackdrop.hidden = false;
    approvalShown = true;
    document.body.classList.add("is-locked");
    if (!pendingBudget) {
      approvalBudgetEl.innerHTML = '<p class="empty-state">Waiting for the budget details…</p>';
    } else {
      approvalBudgetEl.innerHTML =
        '<div class="approval-total"><span class="currency">' +
        esc(pendingBudget.currency) + "</span> " +
        Number(pendingBudget.total_estimated_cost).toLocaleString() + "</div>" +
        renderApprovalTable(pendingBudget.line_items || []);
    }
    approveYesBtn.focus();
  }

  function closeApproval() {
    approvalBackdrop.hidden = true;
    approvalShown = false;
    document.body.classList.remove("is-locked");
  }

  /** Non-interactive: the gate is for reading the figures, not exploring. */
  function renderApprovalTable(lineItems) {
    var rows = lineItems
      .map(function (item) {
        var badge = item.grounded
          ? '<span class="badge grounded">grounded</span>'
          : '<span class="badge ungrounded">ungrounded</span>';
        var sources = (item.source_records || [])
          .map(function (r) { return esc(r.record_id); })
          .join(", ") || "—";
        return (
          "<tr><td>" + esc(item.label) + "</td><td class='num'>" +
          esc(item.currency) + " " + Number(item.amount).toLocaleString() +
          "</td><td>" + badge + "</td><td class='src'>" + sources + "</td></tr>"
        );
      })
      .join("");
    return (
      '<div class="table-wrap"><table class="data-table"><thead><tr><th>Label</th><th class="num">Amount</th>' +
      "<th>Grounded</th><th>Sources</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
    );
  }

  /* ---------- polling ---------- */

  function resetForNewRun() {
    currentRunId = null;
    currentPackage = null;
    currentMetrics = null;
    currentStatus = null;
    currentEvents = [];
    renderedEventCount = 0;
    approvalShown = false;
    activityLogEl.innerHTML = "";
    replanBannerEl.hidden = true;
    replanBannerEl.innerHTML = "";
    closeApproval();
    setStep("input");
    renderRail();
  }

  function startPolling() {
    if (pollHandle) clearInterval(pollHandle);
    pollHandle = setInterval(pollRun, 1200);
    pollRun();
  }

  async function pollRun() {
    var res;
    try {
      res = await fetch("/api/runs/" + currentRunId);
    } catch (e) {
      return; // transient hiccup; next tick retries
    }
    if (!res.ok) return;
    var data = await res.json();

    currentEvents = data.events || [];
    currentStatus = data.status;
    currentMetrics = data.metrics || currentMetrics;

    renderCrew(currentEvents, data.status);
    appendNewLogEntries(currentEvents);
    setRunChip(data.status);

    if (data.status === "awaiting_approval") {
      setStep("approval");
      setStatus("Awaiting your approval of the budget band…");
      if (!approvalShown) showApproval(data.pending_budget);
    } else if (approvalShown) {
      closeApproval();
    }

    var isFinal = ["completed", "rejected", "error"].indexOf(data.status) !== -1;

    // Progressive: show whatever exists so far, exactly as before.
    var inProgress = data.package || data.partial_state;
    if (inProgress && Object.keys(inProgress).length) {
      currentPackage = inProgress;
    }
    refreshActiveView();

    if (data.status === "completed" || data.status === "rejected") {
      clearInterval(pollHandle);
      resetRunBtn();
      setStep("done");
      setStatus(
        data.status === "completed" ? "Package complete." : "Budget rejected — package assembled without resources.",
        data.status === "completed" ? "ok" : "error"
      );
      if (currentView() === "crew") navigate("overview");
      else refreshActiveView();
    } else if (data.status === "error") {
      clearInterval(pollHandle);
      resetRunBtn();
      setStatus("Error: " + (data.error || "unknown error"), "error");
      refreshActiveView();
    }
  }

  /* ---------- crew rendering ---------- */

  /* Shared with the spine so both render the same agent state. */
  var countBlocks = V.countBlocks;
  var computeCrewState = V.computeCrewState;

  function updateReplanBanner(events) {
    var authors = events.map(function (e) { return e.author; });
    var attempts = Math.max.apply(null, REPLAN_LOOP_AGENTS.map(function (k) { return countBlocks(authors, k); }).concat([0]));
    if (attempts <= 1) {
      replanBannerEl.hidden = true;
      replanBannerEl.innerHTML = "";
      return;
    }
    replanBannerEl.hidden = false;
    replanBannerEl.innerHTML =
      '<span class="replan-tag" aria-hidden="true">RE-PLAN</span>' +
      '<span class="replan-banner-text"><strong>Re-plan loop triggered</strong> — Risk/Continuity flagged a structural ' +
      "problem in the schedule. Scheduler → Budget → Risk re-ran <strong>attempt " +
      attempts + " of " + MAX_REPLAN_ATTEMPTS + "</strong>.</span>";
  }

  function latestActivityFor(events, key) {
    for (var i = events.length - 1; i >= 0; i--) {
      var ev = events[i];
      if (ev.author !== key) continue;
      if (ev.tool_calls && ev.tool_calls.length) return "→ calling " + ev.tool_calls.join(", ");
      if (ev.text) return "→ " + ev.text;
      return "→ working…";
    }
    return "";
  }

  function renderCrew(events, status) {
    var defs = AGENT_DEFS.filter(function (d) { return !d.optional || currentWithPreviz; });
    var authors = events.map(function (e) { return e.author; });
    var lastAuthor = authors.length ? authors[authors.length - 1] : null;

    updateReplanBanner(events);

    crewTrackEl.innerHTML = defs
      .map(function (def) {
        var state = computeCrewState(def.key, authors, lastAuthor, status);
        var blocks = countBlocks(authors, def.key);
        var repeatBadge = blocks > 1 ? '<span class="crew-repeat">re-plan ×' + blocks + "</span>" : "";
        var activity = state === "active" ? latestActivityFor(events, def.key) : "";
        var subtitle = activity || def.hint;
        return (
          '<li class="crew-card is-' + state + '">' +
          '<span class="crew-icon">' + def.icon + "</span>" +
          '<span class="crew-body"><span class="crew-name">' + esc(def.label) + " " + repeatBadge + "</span>" +
          '<span class="crew-hint' + (activity ? " is-live" : "") + '">' + esc(subtitle) + "</span></span>" +
          '<span class="crew-status"><span class="dot"></span>' + STATUS_LABEL[state] + "</span></li>"
        );
      })
      .join("");
  }

  function appendNewLogEntries(events) {
    for (var i = renderedEventCount; i < events.length; i++) {
      var ev = events[i];
      var li = document.createElement("li");
      var toolBadges = (ev.tool_calls || [])
        .map(function (t) { return '<span class="tool">' + esc(t) + "</span>"; })
        .join("");
      var time = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : "";
      li.innerHTML =
        '<span class="tstamp">' + time + "</span>" +
        '<span class="agent">' + esc(ev.author) + "</span>" +
        esc(ev.text || "") + toolBadges;
      activityLogEl.appendChild(li);
    }
    renderedEventCount = events.length;
    activityLogEl.scrollTop = activityLogEl.scrollHeight;
  }

  /* ---------- chrome ---------- */

  function setStep(stepKey) {
    var STEPS = ["input", "crew", "approval", "done"];
    var idx = STEPS.indexOf(stepKey);
    stepperEls.forEach(function (li) {
      var i = STEPS.indexOf(li.dataset.step);
      li.classList.toggle("is-current", i === idx);
      li.classList.toggle("is-done", i < idx);
    });
  }

  function setStatus(text, kind) {
    runStatusEl.textContent = text || "";
    runStatusEl.className = "status" + (kind ? " is-" + kind : "");
  }

  function setRunChip(status) {
    if (!status) { runChip.hidden = true; return; }
    var map = {
      running: ["Running", "is-run"],
      awaiting_approval: ["Awaiting approval", "is-warn"],
      completed: ["Completed", "is-ok"],
      rejected: ["Rejected", "is-bad"],
      error: ["Error", "is-bad"],
      loaded: ["Saved package", ""],
    };
    var m = map[status] || [status, ""];
    runChip.hidden = false;
    runChip.textContent = m[0];
    runChip.className = "run-chip " + m[1];
  }

  function setRunBtnBusy(label) {
    runBtn.disabled = true;
    runBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span>' + esc(label);
  }

  function resetRunBtn() {
    runBtn.disabled = false;
    runBtn.innerHTML = RUN_BTN_IDLE;
  }

  /* ---------- init ---------- */
  pipelineMapEl.innerHTML = V.renderPipelineMap(AGENT_DEFS.filter(function (d) { return !d.optional; }));
  renderRail();
  applyRoute();
  setStep("input");
})();
