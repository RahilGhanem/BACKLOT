/* View renderers for the production control room.
 *
 * Scene/day/risk relationships come from schedule.days[].scene_numbers
 * and risk.flags[].affected_scene_numbers / affected_shoot_days.
 * Global rather than a module: classic script, no build step.
 */
var BACKLOT_VIEWS = (function () {
  "use strict";

  /* ---------------- utils ---------------- */

  function escapeHtml(str) {
    return String(str == null ? "" : str).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function money(amount, currency) {
    if (amount == null || isNaN(amount)) return "—";
    return (currency ? currency + " " : "") + Number(amount).toLocaleString();
  }

  function pct(value) {
    if (value === null || value === undefined) return "—";
    return Math.round(value * 100) + "%";
  }

  function plural(n, one, many) {
    return n + " " + (n === 1 ? one : many || one + "s");
  }

  function empty(message, hint) {
    return (
      '<div class="empty-state"><p>' +
      escapeHtml(message) +
      "</p>" +
      (hint ? '<p class="empty-hint">' + escapeHtml(hint) + "</p>" : "") +
      "</div>"
    );
  }

  /* ---------------- provenance registry ----------------
   * Grounded values get a clickable badge that opens the drawer. We keep
   * the real source_records in a registry rather than stuffing them into
   * DOM attributes. Reset on every render pass. */

  var PROV = [];

  function resetProvenance() {
    PROV = [];
  }

  function provEntry(entry) {
    PROV.push(entry);
    return PROV.length - 1;
  }

  function getProvenance(i) {
    return PROV[i];
  }

  /** Grounded badges open the provenance drawer; ungrounded ones are inert. */
  function groundBadge(item, agent, tools) {
    var records = item.source_records || [];
    if (!item.grounded) {
      return '<span class="badge ungrounded" title="Not backed by a studio-data record">ungrounded</span>';
    }
    var idx = provEntry({
      label: item.label || item.need || "Value",
      amount: item.amount,
      currency: item.currency,
      notes: item.notes,
      records: records,
      agent: agent,
      tools: tools || [],
    });
    return (
      '<button class="badge grounded is-clickable" data-prov="' +
      idx +
      '" type="button" title="Show where this came from">grounded' +
      (records.length ? " · " + records.length : "") +
      "</button>"
    );
  }

  /* ---------------- cross-link index ---------------- */

  /** Indexes scenes against shoot days and risk flags. */
  function buildIndex(pkg) {
    var idx = {
      sceneToDay: {},   // scene_number -> [day_number, ...] (numbers can repeat)
      sceneRisks: {},   // scene_number -> [flag]
      dayRisks: {},     // day_number   -> [flag]
      sceneById: {},    // scene_number -> [scene, ...]  (numbers can repeat)
      duplicateNumbers: [], // scene numbers used by more than one scene
      dayByNumber: {},  // day_number   -> day
    };

    // Scene numbers can repeat, so keep every scene rather than overwriting.
    var scenes = (pkg.breakdown && pkg.breakdown.scenes) || [];
    scenes.forEach(function (s) {
      var k = String(s.scene_number);
      (idx.sceneById[k] = idx.sceneById[k] || []).push(s);
    });
    Object.keys(idx.sceneById).forEach(function (k) {
      if (idx.sceneById[k].length > 1) idx.duplicateNumbers.push(k);
    });

    var days = (pkg.schedule && pkg.schedule.days) || [];
    days.forEach(function (d) {
      idx.dayByNumber[String(d.day_number)] = d;
      (d.scene_numbers || []).forEach(function (sn) {
        var k = String(sn);
        (idx.sceneToDay[k] = idx.sceneToDay[k] || []).push(d.day_number);
      });
    });

    var flags = (pkg.risk_report && pkg.risk_report.flags) || [];
    flags.forEach(function (f) {
      (f.affected_scene_numbers || []).forEach(function (sn) {
        (idx.sceneRisks[String(sn)] = idx.sceneRisks[String(sn)] || []).push(f);
      });
      (f.affected_shoot_days || []).forEach(function (dn) {
        (idx.dayRisks[String(dn)] = idx.dayRisks[String(dn)] || []).push(f);
      });
    });

    return idx;
  }

  /** Grounded/ungrounded claim counts, for packages saved without a
   *  metrics block. Same definition as backlot/metrics.py: budget line
   *  items plus crew and location picks. */
  function deriveGrounding(pkg) {
    var g = 0, u = 0;
    function tally(list) {
      (list || []).forEach(function (x) { if (x.grounded) g++; else u++; });
    }
    if (pkg.budget) tally(pkg.budget.line_items);
    if (pkg.resources) {
      tally(pkg.resources.crew_picks);
      tally(pkg.resources.location_picks);
    }
    var total = g + u;
    return { grounded: g, ungrounded: u, rate: total ? g / total : null, total: total };
  }

  /** Resolves a scene to its shoot day. Scene numbers can repeat, so
   *  ambiguity is broken on location; returns null if still ambiguous. */
  function dayForScene(idx, scene) {
    var days = idx.sceneToDay[String(scene.scene_number)] || [];
    if (days.length === 1) return days[0];
    if (!days.length) return null;
    var match = days.filter(function (dn) {
      var d = idx.dayByNumber[String(dn)];
      return d && d.location === scene.location;
    });
    return match.length === 1 ? match[0] : null;
  }

  /** Names the backing store from the provenance actually present, so the
   *  UI can never claim a source the records don't show. */
  function groundingStore(pkg) {
    var prefixes = {};
    function scan(list, key) {
      (list || []).forEach(function (x) {
        (x.source_records || []).forEach(function (r) {
          if (r.source) prefixes[String(r.source).split(":")[0]] = true;
        });
      });
    }
    if (pkg) {
      scan(pkg.budget && pkg.budget.line_items);
      scan(pkg.resources && pkg.resources.crew_picks);
      scan(pkg.resources && pkg.resources.location_picks);
    }
    var keys = Object.keys(prefixes);
    if (!keys.length) return null;
    if (keys.length === 1 && keys[0] === "clickhouse") return "ClickHouse";
    if (keys.length === 1 && keys[0] === "mcp_shim") return "the local dataset";
    return keys.join(", ");
  }

  var SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };

  function severityBadge(sev) {
    return '<span class="badge severity-' + escapeHtml(sev) + '">' + escapeHtml(sev) + "</span>";
  }

  function riskDots(flags) {
    if (!flags || !flags.length) return "";
    var counts = { high: 0, medium: 0, low: 0 };
    flags.forEach(function (f) {
      if (counts[f.severity] !== undefined) counts[f.severity]++;
    });
    return (
      '<span class="risk-dots" title="' +
      escapeHtml(plural(flags.length, "risk flag")) +
      '">' +
      Object.keys(counts)
        .filter(function (k) { return counts[k]; })
        .map(function (k) {
          return '<i class="rd rd-' + k + '">' + counts[k] + "</i>";
        })
        .join("") +
      "</span>"
    );
  }

  /* ---------------- stripboard colour convention ----------------
   * The real 1st-AD board: white = INT day, yellow = EXT day,
   * blue = INT night, green = EXT night. Anything that doesn't map
   * cleanly (DAWN/DUSK/CONTINUOUS/UNSPECIFIED) stays neutral and keeps
   * its literal label rather than being forced into a colour. */
  function stripClass(intExt, timeOfDay) {
    var isNight = timeOfDay === "NIGHT";
    var isDay = timeOfDay === "DAY";
    if (!isNight && !isDay) return "strip-other";
    if (intExt === "INT") return isDay ? "strip-int-day" : "strip-int-night";
    if (intExt === "EXT") return isDay ? "strip-ext-day" : "strip-ext-night";
    return "strip-other"; // INT/EXT
  }


  /* ================= CONTROL ROOM ================= */

  /* Spine stations. `view` is where each station's output lives, so the
     spine doubles as navigation. Shared with app.js. */
  var CREW_STATIONS = [
    { key: "script_supervisor", icon: "Script Supervisor.png", short: "Script", full: "Script Supervisor", view: "breakdown",
      hint: "Parses the screenplay into a scene breakdown" },
    { key: "previz_agent", short: "Previz", full: "Previz", view: "previz", optional: true,
      hint: "Imagen storyboards, Veo animatic, Lyria cue" },
    { key: "first_ad_scheduler", icon: "1st-AD Scheduler.png", short: "Schedule", full: "1st-AD Scheduler", view: "schedule",
      hint: "Builds the stripboard shoot schedule" },
    { key: "budget_agent", icon: "Budget Agent.png", short: "Budget", full: "Budget Agent", view: "budget", grounded: true,
      hint: "Grounded in studio data over MCP" },
    { key: "risk_agent", icon: "Risk Continuity.png", short: "Risk", full: "Risk / Continuity", view: "risk",
      hint: "Critiques the schedule and budget" },
    { key: "approval_gate", icon: "Approval Gate.png", short: "Approval", full: "Approval Gate", view: "overview", human: true,
      hint: "A producer signs off the budget band" },
    { key: "resource_agent", icon: "Resource Agent.png", short: "Resources", full: "Resource Agent", view: "resources", grounded: true,
      hint: "Grounded in studio data over MCP" },
    { key: "package_assembler", icon: "Package Assembler.png", short: "Package", full: "Package Assembler", view: "package",
      hint: "Combines everything into the package" },
  ];

  /* Consecutive events from one author form a block; a second block
     means the agent ran again on a re-plan. */
  function countBlocks(authors, key) {
    var blocks = 0, inBlock = false;
    for (var i = 0; i < authors.length; i++) {
      if (authors[i] === key) {
        if (!inBlock) { blocks++; inBlock = true; }
      } else { inBlock = false; }
    }
    return blocks;
  }

  function computeCrewState(key, authors, lastAuthor, status) {
    var hasRun = authors.indexOf(key) !== -1;
    if (key === "approval_gate" && status === "awaiting_approval") return "active";
    if (key === "resource_agent" && status === "rejected") return "skipped";
    if (status === "error" && key === lastAuthor) return "error";
    if (["completed", "rejected", "error"].indexOf(status) !== -1) return hasRun ? "done" : "pending";
    if (hasRun && key === lastAuthor) return "active";
    if (hasRun) return "done";
    return "pending";
  }

  /* The value a station has produced, or null. */
  function stationOutput(key, pkg) {
    switch (key) {
      case "script_supervisor":
        return pkg.breakdown ? plural((pkg.breakdown.scenes || []).length, "scene") : null;
      case "previz_agent":
        return pkg.previz ? "generated" : null;
      case "first_ad_scheduler":
        return pkg.schedule ? plural(pkg.schedule.total_shoot_days, "day") : null;
      case "budget_agent":
        return pkg.budget ? money(pkg.budget.total_estimated_cost, pkg.budget.currency) : null;
      case "risk_agent":
        return pkg.risk_report ? plural((pkg.risk_report.flags || []).length, "flag") : null;
      case "approval_gate":
        return pkg.approval ? (pkg.approval.approved ? "Approved" : "Rejected") : null;
      case "resource_agent":
        return pkg.resources
          ? plural((pkg.resources.crew_picks || []).length + (pkg.resources.location_picks || []).length, "pick")
          : null;
      case "package_assembler":
        return pkg.resources || pkg.approval ? "Assembled" : null;
    }
    return null;
  }

  /* ---------------- the slate ----------------
     A production slate, not a stat bar: it says which production this
     control room is looking at. Empty before a run, by design. */
  function renderSlate(pkg, status, runId) {
    var bd = pkg.breakdown, sch = pkg.schedule, bg = pkg.budget;
    var title = (bd && bd.title) || (bg && bg.title) || null;
    var live = status === "running" || status === "awaiting_approval";

    var fields = [
      ["Scenes", bd ? (bd.scenes || []).length : null],
      ["Pages", bd && bd.total_estimated_pages != null ? bd.total_estimated_pages : null],
      ["Shoot days", sch ? sch.total_shoot_days : null],
      ["Budget", bg ? money(bg.total_estimated_cost, bg.currency) : null],
    ];

    return (
      '<section class="slate' + (live ? " is-live" : "") + '" aria-label="Production slate">' +
      '<div class="slate-clap" aria-hidden="true"></div>' +
      '<div class="slate-body">' +
      '<div class="slate-main">' +
      '<span class="slate-k">Production</span>' +
      '<h3 class="slate-title">' + (title ? escapeHtml(title) : "No production loaded") + "</h3>" +
      '<span class="slate-sub">' +
      (status === "loaded"
        ? "Saved package — reopened for review, no agents ran"
        : live
        ? "The crew is working"
        : status === "completed"
        ? "Run complete"
        : status === "rejected"
        ? "Budget rejected — plan stopped before resources"
        : status === "error"
        ? "Run stopped early"
        : "Load a screenplay to begin") +
      "</span></div>" +
      '<dl class="slate-fields">' +
      fields
        .map(function (f) {
          return (
            "<div><dt>" + escapeHtml(f[0]) + "</dt><dd>" +
            (f[1] == null ? '<span class="slate-empty">—</span>' : escapeHtml(String(f[1]))) +
            "</dd></div>"
          );
        })
        .join("") +
      "</dl></div></section>"
    );
  }

  /* ---------------- the spine (signature) ----------------
     Every station carries the real value it produced. The connector fills
     only where data has actually flowed. When Risk sent the plan back, a
     real arc is drawn from Risk to the Scheduler and the stations it
     re-ran are marked with their pass count — a second planning pass, not
     a status label. */
  function renderSpine(pkg, events, status, withPreviz) {
    var stations = CREW_STATIONS.filter(function (s) { return !s.optional || withPreviz; });
    var authors = (events || []).map(function (e) { return e.author; });
    var lastAuthor = authors.length ? authors[authors.length - 1] : null;

    // A reopened package has no event log, so state comes from what each station produced.
    var savedPackage = status === "loaded";
    var rejected = !!(pkg.approval && pkg.approval.approved === false);

    var model = stations.map(function (s) {
      var out = stationOutput(s.key, pkg);
      var state;
      if (savedPackage) {
        state = out ? "done" : (s.key === "resource_agent" && rejected ? "skipped" : "pending");
      } else {
        state = computeCrewState(s.key, authors, lastAuthor, status);
      }
      return { def: s, state: state, passes: countBlocks(authors, s.key), out: out };
    });

    var maxPasses = Math.max.apply(null, model.map(function (m) { return m.passes; }).concat([0]));
    // The risk report records the re-plan; a saved package cannot know the pass count.
    var replanFromReport = !!(pkg.risk_report && pkg.risk_report.replan_requested);
    var replanned = maxPasses > 1 || (savedPackage && replanFromReport);

    var items = model
      .map(function (m, i) {
        var d = m.def;
        var cls = ["stn", "is-" + m.state];
        if (d.grounded) cls.push("is-grounded");
        if (d.human) cls.push("is-human");
        if (m.passes > 1) cls.push("is-rerun");
        return (
          '<li class="' + cls.join(" ") + '">' +
          '<button type="button" class="stn-btn" data-goto-view="' + d.view + '"' +
          ' title="' + escapeHtml(d.full + " — " + d.hint) + '">' +
          '<span class="stn-node" aria-hidden="true">' +
          (d.icon
            ? '<img src="' + encodeURI("/icons/small/" + d.icon) + '" alt="" />'
            : "<i></i>") +
          "</span>" +
          '<span class="stn-name">' + escapeHtml(d.short) + "</span>" +
          '<span class="stn-out">' +
          (m.out ? escapeHtml(m.out) : '<em class="stn-wait">' +
            (m.state === "active" ? "working" : m.state === "skipped" ? "skipped" : "—") + "</em>") +
          "</span>" +
          (m.passes > 1 ? '<span class="stn-pass">pass ' + m.passes + "</span>" : "") +
          "</button></li>"
        );
      })
      .join("");

    // Stations are equal columns, so a centre is (i + 0.5) / n.
    var arc = "";
    if (replanned) {
      var n = model.length;
      var iSched = model.findIndex(function (m) { return m.def.key === "first_ad_scheduler"; });
      var iRisk = model.findIndex(function (m) { return m.def.key === "risk_agent"; });
      if (iSched >= 0 && iRisk > iSched) {
        var x1 = ((iRisk + 0.5) / n) * 100;
        var x2 = ((iSched + 0.5) / n) * 100;
        arc =
          '<svg class="spine-arc" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden="true">' +
          '<path d="M ' + x1 + ' 1 C ' + x1 + ' 18, ' + x2 + ' 18, ' + x2 + ' 2" ' +
          'vector-effect="non-scaling-stroke" />' +
          '<path class="spine-arrow" d="M ' + x2 + ' 2 l -1.2 4 M ' + x2 + ' 2 l 1.2 4" ' +
          'vector-effect="non-scaling-stroke" />' +
          "</svg>";
      }
    }

    return (
      '<section class="spine' + (replanned ? " has-replan" : "") + '" aria-label="Production pipeline">' +
      '<header class="spine-head">' +
      "<h3>Production pipeline</h3>" +
      '<span class="hint">' +
      (replanned
        ? (maxPasses > 1
            ? "Risk sent the plan back — " + maxPasses + " planning passes"
            : "Risk sent the plan back")
        : "screenplay → crew → package") +
      "</span></header>" +
      '<div class="spine-stage" style="--stations:' + model.length + '">' +
      '<ol class="spine-rail">' + items + "</ol>" +
      arc +
      "</div>" +
      (replanned
        ? '<p class="spine-note"><span class="replan-tag">RE-PLAN</span>' +
          (maxPasses > 1
            ? "The Scheduler, Budget and Risk agents ran again on a revised plan. The values above are from the latest pass."
            : "The risk report records that a re-plan was requested. A saved package does not carry the event log, so the number of passes is not known here.") +
          "</p>"
        : "") +
      (function () {
        var store = groundingStore(pkg);
        if (!store) return "";
        return '<p class="spine-floor"><span class="floor-label">' + escapeHtml(store) + "</span>" +
          "Budget and Resources query the studio dataset over MCP. Values they produce carry a source record.</p>";
      })() +
      "</section>"
    );
  }

  /* ---------------- the day board ----------------
     The production plan as days, not rows: what shoots, where, with whom,
     and what the Risk agent flagged against each day. */
  function renderBoard(pkg) {
    var sch = pkg.schedule;
    if (!sch || !(sch.days || []).length) return "";
    var idx = buildIndex(pkg);
    var maxPages = Math.max.apply(
      null, sch.days.map(function (d) { return Number(d.total_pages) || 0; }).concat([0.001])
    );

    var cols = sch.days
      .map(function (d) {
        var risks = idx.dayRisks[String(d.day_number)] || [];
        var worst = risks.reduce(function (acc, f) {
          return SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[acc] ? f.severity : acc;
        }, "low");
        var scenes = (d.scene_numbers || [])
          .map(function (sn) {
            return '<button class="bd-scene" type="button" data-goto-scene="' + escapeHtml(String(sn)) +
              '">' + escapeHtml(String(sn)) + "</button>";
          })
          .join("");
        return (
          '<article class="bd-col ' + stripClass(d.int_ext, d.time_of_day) +
          (risks.length ? " has-risk risk-" + worst : "") + '">' +
          '<button class="bd-head" type="button" data-goto-day="' + escapeHtml(String(d.day_number)) + '">' +
          '<span class="bd-day">Day ' + escapeHtml(String(d.day_number)) + "</span>" +
          '<span class="bd-loc">' + escapeHtml(d.location) + "</span>" +
          '<span class="bd-tod">' + escapeHtml(d.int_ext) + " · " + escapeHtml(d.time_of_day) + "</span>" +
          "</button>" +
          '<div class="bd-pages" title="' + escapeHtml(d.total_pages + " pages") + '">' +
          '<i style="height:' + Math.max((Number(d.total_pages) || 0) / maxPages * 100, 6) + '%"></i>' +
          "</div>" +
          (scenes ? '<div class="bd-scenes">' + scenes + "</div>" : "") +
          '<div class="bd-foot">' +
          '<span class="bd-meta">' + escapeHtml(String(d.total_pages)) + " pg</span>" +
          ((d.cast_called || []).length
            ? '<span class="bd-meta">' + d.cast_called.length + " cast</span>"
            : "") +
          (risks.length ? riskDots(risks) : "") +
          "</div></article>"
        );
      })
      .join("");

    return (
      '<section class="panel board-panel"><div class="panel-head">' +
      "<h3>Shooting board</h3>" +
      '<span class="hint">' + escapeHtml(plural(sch.days.length, "shoot day")) +
      (sch.max_pages_per_day != null ? " · " + Number(sch.max_pages_per_day).toFixed(2) + " pages/day target" : "") +
      "</span></div>" +
      '<div class="bd-scroll"><div class="bd-grid">' + cols + "</div></div>" +
      "</section>"
    );
  }

  /* ================= OVERVIEW ================= */

  function renderOverview(pkg, metrics, status, events, withPreviz, runId) {
    pkg = pkg || {};
    var has = Object.keys(pkg).length > 0;
    var html = "";

    /* 1. WHAT production is this */
    html += renderSlate(pkg, status, runId);

    /* 2. HOW it was produced — the signature element. Shown even before a
          run so the control room explains itself while idle. */
    html += renderSpine(pkg, events, status, withPreviz);

    if (!has) {
      html += empty(
        "No production loaded yet.",
        "Paste or load a screenplay on the Screenplay page, or reopen a package you downloaded earlier."
      );
      return html;
    }

    /* 3. The decision, when there is one to state */
    var ap = pkg.approval;
    if (status === "awaiting_approval") {
      html +=
        '<div class="callout is-warn is-decision"><strong>Producer decision required</strong>' +
        "<span>The crew has costed the plan and paused. Nothing is committed to crew or locations until you approve.</span></div>";
    } else if (ap) {
      html +=
        '<div class="callout ' + (ap.approved ? "is-ok" : "is-bad") + ' is-decision">' +
        "<strong>" + (ap.approved ? "Budget approved by a human" : "Budget rejected by a human") + "</strong>" +
        "<span>" + escapeHtml(ap.reason || "") + "</span></div>";
    }

    /* 4. The plan */
    html += renderBoard(pkg);

    /* 5. Intelligence band — budget shape, risk posture, grounding */
    var band = [];
    if (pkg.budget) band.push(renderBudgetShape(pkg.budget));
    if (pkg.risk_report && (pkg.risk_report.flags || []).length) band.push(renderRiskSummaryPanel(pkg.risk_report));
    band.push(renderGroundingPanel(pkg, metrics));
    html += '<div class="intel-band">' + band.join("") + "</div>";

    return html;
  }

  /* Largest line items first; the tail is summarised, not bucketed. */
  function renderBudgetShape(bg) {
    var items = (bg.line_items || []).slice().sort(function (a, b) {
      return (Number(b.amount) || 0) - (Number(a.amount) || 0);
    });
    if (!items.length) return "";
    var total = items.reduce(function (s, i) { return s + (Number(i.amount) || 0); }, 0);
    var top = items.slice(0, 6);
    var rest = items.slice(6);
    var restSum = rest.reduce(function (s, i) { return s + (Number(i.amount) || 0); }, 0);

    var rows = top
      .map(function (i) {
        var amt = Number(i.amount) || 0;
        var share = total ? (amt / total) * 100 : 0;
        return (
          '<li' + (i.grounded ? "" : ' class="is-ungrounded"') + '>' +
          '<span class="bs-label">' + escapeHtml(i.label) + "</span>" +
          '<span class="bs-track"><i style="width:' + share + '%"></i></span>' +
          '<span class="bs-amt">' + money(i.amount, "") + "</span></li>"
        );
      })
      .join("");

    return (
      '<div class="panel"><div class="panel-head"><h3>Where the money is</h3>' +
      '<button class="link-btn" type="button" data-goto-view="budget">All line items →</button></div>' +
      '<ul class="budget-shape">' + rows + "</ul>" +
      (rest.length
        ? '<p class="hint">' + plural(rest.length, "smaller line item") + " totalling " +
          money(restSum, bg.currency) + " not shown.</p>"
        : "") +
      "</div>"
    );
  }

  /* Grounding, stated plainly, with a route into the evidence. */
  function renderGroundingPanel(pkg, metrics) {
    var haveMetric = metrics && (metrics.grounded_claims != null || metrics.ungrounded_claims != null);
    var derived = deriveGrounding(pkg);
    var g = haveMetric ? (metrics.grounded_claims || 0) : derived.grounded;
    var u = haveMetric ? (metrics.ungrounded_claims || 0) : derived.ungrounded;
    var total = g + u;

    if (!total) {
      return (
        '<div class="panel"><div class="panel-head"><h3>Grounding</h3></div>' +
        empty("Nothing costed yet.", "Grounding appears once the Budget or Resource agent has produced claims.") +
        "</div>"
      );
    }

    // List the ungrounded claims rather than only the rate.
    var gaps = [];
    (pkg.budget && pkg.budget.line_items || []).forEach(function (i) {
      if (!i.grounded) gaps.push(i.label);
    });
    ["crew_picks", "location_picks"].forEach(function (k) {
      ((pkg.resources && pkg.resources[k]) || []).forEach(function (p) {
        if (!p.grounded) gaps.push(p.need);
      });
    });

    return (
      '<div class="panel"><div class="panel-head"><h3>Grounding</h3>' +
      '<span class="hint">' + (haveMetric ? "measured this run" : "counted from this package") + "</span></div>" +
      '<div class="ground-figure"><span class="gf-rate">' + pct(g / total) + "</span>" +
      '<span class="gf-sub">' + g + " of " + total + " claims carry a record in " +
      escapeHtml(groundingStore(pkg) || "the studio dataset") + "</span></div>" +
      '<div class="ledger-bar" role="img" aria-label="' + escapeHtml(g + " grounded, " + u + " ungrounded") + '">' +
      '<span class="lb-good" style="width:' + (g / total) * 100 + '%"></span>' +
      '<span class="lb-bad" style="width:' + (u / total) * 100 + '%"></span></div>' +
      (gaps.length
        ? '<div class="ground-gaps"><span class="lbl">Not grounded</span><ul>' +
          gaps.map(function (x) { return "<li>" + escapeHtml(x) + "</li>"; }).join("") +
          "</ul></div>"
        : '<p class="hint ground-clean">Every claim in this package is backed by a source record.</p>') +
      "</div>"
    );
  }

  function renderRiskSummaryPanel(rk) {
    var flags = rk.flags || [];
    var counts = { high: 0, medium: 0, low: 0 };
    var byCat = {};
    flags.forEach(function (f) {
      if (counts[f.severity] !== undefined) counts[f.severity]++;
      byCat[f.category] = (byCat[f.category] || 0) + 1;
    });
    var max = Math.max.apply(null, Object.keys(byCat).map(function (k) { return byCat[k]; }).concat([1]));
    return (
      '<div class="panel"><div class="panel-head"><h3>Risk posture</h3>' +
      '<span class="hint">' + (rk.schedule_feasible ? "schedule feasible" : "schedule flagged infeasible") + "</span></div>" +
      '<div class="sev-row">' +
      ["high", "medium", "low"]
        .map(function (s) {
          return (
            '<div class="sev-chip sev-' + s + (counts[s] ? "" : " is-zero") + '">' +
            '<span class="sev-n">' + counts[s] + '</span><span class="sev-l">' + s + "</span></div>"
          );
        })
        .join("") +
      "</div>" +
      // Identical counts carry no shape, so fall back to chips.
      (max > 1
        ? '<ul class="cat-bars">' +
          Object.keys(byCat)
            .sort(function (a, b) { return byCat[b] - byCat[a]; })
            .map(function (c) {
              return (
                "<li><span class='cat-name'>" + escapeHtml(c) + "</span>" +
                "<span class='cat-track'><i style='width:" + (byCat[c] / max) * 100 + "%'></i></span>" +
                "<span class='cat-n'>" + byCat[c] + "</span></li>"
              );
            })
            .join("") +
          "</ul>"
        : '<ul class="cat-chips">' +
          Object.keys(byCat).sort().map(function (c) {
            return "<li>" + escapeHtml(c) + "<b>" + byCat[c] + "</b></li>";
          }).join("") +
          "</ul>") +
      (rk.replan_requested
        ? '<p class="hint replan-note"><span class="replan-tag">RE-PLAN</span>' + escapeHtml(rk.replan_reason || "") + "</p>"
        : "") +
      "</div>"
    );
  }

  /* ================= BREAKDOWN (scene intelligence) ================= */

  function renderBreakdown(pkg) {
    if (!pkg || !pkg.breakdown) {
      return empty("No breakdown yet.", "The Script Supervisor produces this first.");
    }
    var bd = pkg.breakdown;
    var idx = buildIndex(pkg);
    var scenes = bd.scenes || [];
    if (!scenes.length) return empty("The breakdown contains no scenes.");

    var head =
      '<div class="stat-strip">' +
      '<span><b>' + scenes.length + "</b> scenes</span>" +
      '<span><b>' + escapeHtml(String(bd.total_estimated_pages)) + "</b> pages</span>" +
      '<span><b>' + ((bd.unique_cast || []).length) + "</b> cast</span>" +
      '<span><b>' + ((bd.unique_locations || []).length) + "</b> locations</span>" +
      "</div>";

    // The first scene with a number owns `scene-<n>`; duplicates get a suffix.
    var seenNumber = {};
    var cards = scenes
      .map(function (s) {
        var sn = String(s.scene_number);
        seenNumber[sn] = (seenNumber[sn] || 0) + 1;
        var anchor = "scene-" + sn + (seenNumber[sn] > 1 ? "-" + seenNumber[sn] : "");
        var isDup = (idx.sceneById[sn] || []).length > 1;
        var day = dayForScene(idx, s);
        var risks = idx.sceneRisks[sn] || [];
        // Only non-empty requirement categories are shown.
        var reqs = [];
        (s.cast || []).forEach(function (c) { reqs.push(["cast", c]); });
        (s.vehicles || []).forEach(function (v) { reqs.push(["vehicle", v]); });
        (s.props || []).forEach(function (p) { reqs.push(["prop", p]); });
        (s.vfx || []).forEach(function (v) { reqs.push(["vfx", v]); });
        (s.stunts || []).forEach(function (v) { reqs.push(["stunt", v]); });

        return (
          '<article class="scene-card" id="' + anchor + '">' +
          '<header class="scene-head">' +
          '<span class="scene-no' + (isDup ? " is-dup" : "") + '" ' +
          (isDup ? 'title="This scene number is used by more than one scene"' : "") + ">" +
          escapeHtml(sn) + "</span>" +
          '<div class="scene-titles">' +
          '<h4>' + escapeHtml(s.slugline || s.location) + "</h4>" +
          '<p class="scene-meta">' +
          '<span class="pill ' + stripClass(s.int_ext, s.time_of_day) + '">' +
          escapeHtml(s.int_ext) + " · " + escapeHtml(s.time_of_day) + "</span>" +
          '<span class="hint">' + escapeHtml(String(s.estimated_page_count)) + " pages</span>" +
          (day != null
            ? '<button class="chip-link" data-goto-day="' + escapeHtml(String(day)) +
              '" type="button">Shoot day ' + escapeHtml(String(day)) + "</button>"
            : ((idx.sceneToDay[sn] || []).length > 1
                ? '<span class="chip-muted">scheduled on days ' + escapeHtml(idx.sceneToDay[sn].join(", ")) + ' (ambiguous number)</span>'
                : '<span class="chip-muted">not scheduled</span>')) +
          "</p></div>" +
          riskDots(risks) +
          "</header>" +
          '<p class="scene-synopsis">' + escapeHtml(s.synopsis || "") + "</p>" +
          (reqs.length
            ? '<div class="req-chips">' +
              reqs
                .map(function (r) {
                  return '<span class="req req-' + r[0] + '"><i>' + r[0] + "</i>" + escapeHtml(r[1]) + "</span>";
                })
                .join("") +
              "</div>"
            : "") +
          (s.notes ? '<p class="scene-note">' + escapeHtml(s.notes) + "</p>" : "") +
          (risks.length
            ? '<ul class="scene-risks">' +
              risks
                .map(function (f) {
                  return "<li>" + severityBadge(f.severity) + "<span>" + escapeHtml(f.description) + "</span></li>";
                })
                .join("") +
              "</ul>"
            : "") +
          "</article>"
        );
      })
      .join("");

    // Duplicate scene numbers are a breakdown defect worth surfacing.
    var dupNotice = idx.duplicateNumbers.length
      ? '<div class="callout is-warn"><strong>Duplicate scene numbers</strong><span>' +
        escapeHtml(
          "Number" + (idx.duplicateNumbers.length > 1 ? "s " : " ") +
          idx.duplicateNumbers.join(", ") +
          (idx.duplicateNumbers.length > 1 ? " are" : " is") +
          " used by more than one scene in this breakdown."
        ) + "</span></div>"
      : "";
    return head + dupNotice + '<div class="scene-grid">' + cards + "</div>";
  }

  /* ================= STRIPBOARD ================= */

  function renderStripboard(pkg) {
    if (!pkg || !pkg.schedule) {
      return empty("No schedule yet.", "The 1st-AD Scheduler produces this after the breakdown.");
    }
    var sch = pkg.schedule;
    var idx = buildIndex(pkg);
    var days = sch.days || [];
    if (!days.length) return empty("The schedule contains no shoot days.");

    var legend =
      '<div class="board-legend">' +
      [
        ["strip-int-day", "INT · DAY"],
        ["strip-ext-day", "EXT · DAY"],
        ["strip-int-night", "INT · NIGHT"],
        ["strip-ext-night", "EXT · NIGHT"],
        ["strip-other", "other"],
      ]
        .map(function (l) {
          return '<span class="lg"><i class="' + l[0] + '"></i>' + l[1] + "</span>";
        })
        .join("") +
      "</div>";

    var stats =
      '<div class="stat-strip">' +
      '<span><b>' + days.length + "</b> shoot days</span>" +
      (sch.max_pages_per_day != null
        ? '<span><b>' + Number(sch.max_pages_per_day).toFixed(2) + "</b> pages/day target</span>"
        : "") +
      ((sch.unscheduled_scenes || []).length
        ? '<span class="is-warn"><b>' + sch.unscheduled_scenes.length + "</b> unscheduled</span>"
        : "") +
      "</div>";

    var board = days
      .map(function (d) {
        var risks = idx.dayRisks[String(d.day_number)] || [];
        var scenes = (d.scene_numbers || []).map(function (sn) {
          var candidates = idx.sceneById[String(sn)] || [];
          var s = candidates[0];
          if (candidates.length > 1) {
            // Break the tie on location; if still ambiguous, show the number alone.
            var byLoc = candidates.filter(function (c) { return c.location === d.location; });
            s = byLoc.length === 1 ? byLoc[0] : null;
          }
          return (
            '<button class="board-scene" data-goto-scene="' + escapeHtml(String(sn)) + '" type="button">' +
            "<b>" + escapeHtml(String(sn)) + "</b>" +
            (s ? "<span>" + escapeHtml(s.slugline || s.location) + "</span>"
               : (candidates.length > 1 ? '<span class="ambiguous">duplicate scene number</span>' : "")) +
            "</button>"
          );
        });
        return (
          '<article class="strip ' + stripClass(d.int_ext, d.time_of_day) + '" id="day-' + escapeHtml(String(d.day_number)) + '">' +
          '<div class="strip-rail"><span class="strip-day">DAY ' + escapeHtml(String(d.day_number)) + "</span></div>" +
          '<div class="strip-body">' +
          '<div class="strip-top">' +
          "<h4>" + escapeHtml(d.location) + "</h4>" +
          '<span class="strip-tag">' + escapeHtml(d.int_ext) + " · " + escapeHtml(d.time_of_day) + "</span>" +
          '<span class="hint">' + escapeHtml(String(d.total_pages)) + " pages</span>" +
          riskDots(risks) +
          "</div>" +
          (scenes.length ? '<div class="strip-scenes">' + scenes.join("") + "</div>" : "") +
          ((d.cast_called || []).length
            ? '<p class="strip-cast"><span class="lbl">Cast called</span>' +
              d.cast_called.map(function (c) { return '<span class="cast-chip">' + escapeHtml(c) + "</span>"; }).join("") +
              "</p>"
            : "") +
          (d.notes ? '<p class="strip-note">' + escapeHtml(d.notes) + "</p>" : "") +
          "</div></article>"
        );
      })
      .join("");

    var solver = sch.solver_notes
      ? '<p class="solver-note"><span class="lbl">Scheduler</span>' + escapeHtml(sch.solver_notes) + "</p>"
      : "";

    return stats + legend + '<div class="board">' + board + "</div>" + solver;
  }

  /* ================= BUDGET ================= */

  function renderBudget(pkg, events) {
    if (!pkg || !pkg.budget) {
      return empty("No budget yet.", "The Budget Agent produces this from the schedule.");
    }
    var bg = pkg.budget;
    var items = bg.line_items || [];
    var tools = toolsUsedBy(events, "budget_agent");

    var grounded = items.filter(function (i) { return i.grounded; });
    var ungrounded = items.filter(function (i) { return !i.grounded; });
    var maxAmt = Math.max.apply(null, items.map(function (i) { return Number(i.amount) || 0; }).concat([1]));

    var header =
      '<div class="budget-hero">' +
      '<div class="budget-total"><span class="currency">' + escapeHtml(bg.currency || "") + "</span>" +
      '<span class="amount">' + Number(bg.total_estimated_cost || 0).toLocaleString() + "</span></div>" +
      '<div class="budget-split">' +
      "<span><b>" + grounded.length + "</b> grounded</span>" +
      "<span" + (ungrounded.length ? ' class="is-warn"' : "") + "><b>" + ungrounded.length + "</b> ungrounded</span>" +
      "<span><b>" + items.length + "</b> line items</span>" +
      "</div></div>";

    var warn = ungrounded.length
      ? '<div class="callout is-warn"><strong>' +
        plural(ungrounded.length, "line item") +
        " could not be grounded</strong><span>These carry no studio-data record. Treat them as estimates to confirm manually, not as costed figures.</span></div>"
      : "";

    var rows = items
      .map(function (item) {
        var amt = Number(item.amount) || 0;
        return (
          '<tr class="' + (item.grounded ? "" : "is-ungrounded") + '">' +
          "<td>" + escapeHtml(item.label) +
          (item.notes ? '<br/><span class="hint">' + escapeHtml(item.notes) + "</span>" : "") +
          "</td>" +
          '<td class="num">' + money(item.amount, item.currency) + "</td>" +
          '<td class="barcell"><span class="bar"><i style="width:' + (amt / maxAmt) * 100 + '%"></i></span></td>' +
          "<td>" + groundBadge(item, "budget_agent", tools) + "</td>" +
          "</tr>"
        );
      })
      .join("");

    return (
      header +
      warn +
      '<div class="panel"><div class="table-wrap"><table class="data-table">' +
      "<thead><tr><th>Line item</th><th class='num'>Amount</th><th>Share</th><th>Source</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div></div>"
    );
  }

  /* ================= RISK ================= */

  function renderRisk(pkg) {
    if (!pkg || !pkg.risk_report) {
      return empty("No risk report yet.", "The Risk / Continuity agent critiques the schedule and budget.");
    }
    var rk = pkg.risk_report;
    var flags = (rk.flags || []).slice().sort(function (a, b) {
      return (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
    });
    if (!flags.length) {
      return (
        renderRiskSummaryPanel(rk) +
        empty("No risks were flagged.", "The Risk agent reviewed the plan and raised nothing.")
      );
    }
    var idx = buildIndex(pkg);

    var cards = flags
      .map(function (f) {
        var scenes = (f.affected_scene_numbers || []).map(function (sn) {
          return '<button class="chip-link" data-goto-scene="' + escapeHtml(String(sn)) + '" type="button">Scene ' + escapeHtml(String(sn)) + "</button>";
        });
        var days = (f.affected_shoot_days || []).map(function (dn) {
          return '<button class="chip-link" data-goto-day="' + escapeHtml(String(dn)) + '" type="button">Day ' + escapeHtml(String(dn)) + "</button>";
        });
        return (
          '<article class="risk-card sev-' + escapeHtml(f.severity) + '">' +
          '<header><span class="risk-cat">' + escapeHtml(f.category) + "</span>" + severityBadge(f.severity) + "</header>" +
          "<p class='risk-desc'>" + escapeHtml(f.description) + "</p>" +
          (f.recommendation
            ? '<p class="risk-rec"><span class="lbl">Recommendation</span>' + escapeHtml(f.recommendation) + "</p>"
            : "") +
          (scenes.length || days.length
            ? '<footer class="risk-links">' +
              (scenes.length ? '<span class="lbl">Scenes</span>' + scenes.join("") : "") +
              (days.length ? '<span class="lbl">Days</span>' + days.join("") : "") +
              "</footer>"
            : "") +
          "</article>"
        );
      })
      .join("");

    return renderRiskSummaryPanel(rk) + '<div class="risk-grid">' + cards + "</div>";
  }

  /* ================= RESOURCES ================= */

  function renderResources(pkg, events) {
    if (!pkg || !pkg.resources) {
      return empty(
        "No resource picks yet.",
        "The Resource Agent only runs after a human approves the budget band."
      );
    }
    var res = pkg.resources;
    var tools = toolsUsedBy(events, "resource_agent");

    function group(title, picks) {
      if (!picks || !picks.length) return "";
      return (
        '<div class="panel"><div class="panel-head"><h3>' + escapeHtml(title) + "</h3>" +
        '<span class="hint">' + escapeHtml(plural(picks.length, "pick")) + "</span></div>" +
        '<ul class="pick-list">' +
        picks
          .map(function (p) {
            return (
              '<li class="pick' + (p.grounded ? "" : " is-ungrounded") + '">' +
              '<div class="pick-main">' +
              '<span class="pick-need">' + escapeHtml(p.need) + "</span>" +
              '<span class="pick-rec">' + escapeHtml(p.recommendation) + "</span>" +
              (p.notes ? '<span class="hint">' + escapeHtml(p.notes) + "</span>" : "") +
              "</div>" +
              groundBadge(p, "resource_agent", tools) +
              "</li>"
            );
          })
          .join("") +
        "</ul></div>"
      );
    }

    return group("Crew", res.crew_picks) + group("Locations", res.location_picks);
  }

  /* ================= PREVIZ ================= */

  function renderPreviz(previz, runId) {
    if (!previz) {
      return empty(
        "Previz was not generated for this run.",
        "Tick “Generate previz” before running the crew. It calls Imagen / Veo / Lyria and costs real money."
      );
    }
    function url(serverPath) {
      var filename = String(serverPath).split(/[\\/]/).pop();
      return "/previz/" + runId + "/" + filename;
    }
    var html = '<div class="previz-gallery">';
    (previz.storyboard_paths || []).forEach(function (p) {
      html += '<img src="' + url(p) + '" alt="Storyboard frame" loading="lazy" />';
    });
    if (previz.animatic_path && !String(previz.animatic_path).endsWith(".uri.txt")) {
      html += '<video controls src="' + url(previz.animatic_path) + '"></video>';
    }
    if (previz.music_cue_path) {
      html += '<audio controls src="' + url(previz.music_cue_path) + '"></audio>';
    }
    html += "</div>";
    (previz.warnings || []).forEach(function (w) {
      html += '<p class="previz-warning">' + escapeHtml(w) + "</p>";
    });
    return html;
  }

  /* ================= PACKAGE / SCORECARD ================= */

  function renderPackage(pkg, metrics, status) {
    var html = "";
    var produced = [
      ["Breakdown", pkg && pkg.breakdown],
      ["Schedule", pkg && pkg.schedule],
      ["Budget", pkg && pkg.budget],
      ["Risk report", pkg && pkg.risk_report],
      ["Approval", pkg && pkg.approval],
      ["Resources", pkg && pkg.resources],
      ["Previz", pkg && pkg.previz],
    ];
    html +=
      '<div class="panel"><div class="panel-head"><h3>Contents</h3>' +
      '<span class="hint">what this run produced</span></div>' +
      '<ul class="contents-list">' +
      produced
        .map(function (p) {
          return (
            '<li class="' + (p[1] ? "is-yes" : "is-no") + '">' +
            '<span class="ci">' + (p[1] ? "✓" : "—") + "</span>" +
            escapeHtml(p[0]) + "</li>"
          );
        })
        .join("") +
      "</ul></div>";

    if (!metrics) {
      html += empty(
        status === "running" ? "The scorecard appears when the run finishes." : "No metrics were recorded for this run."
      );
      return html;
    }

    var tiles = [
      ["Task completed", metrics.task_completed ? "Yes" : "No", metrics.task_completed],
      ["Tool calls", metrics.tool_calls != null ? metrics.tool_calls : "—", null],
      ["Tool errors", metrics.tool_errors != null ? metrics.tool_errors : "—", metrics.tool_errors === 0 ? true : metrics.tool_errors > 0 ? false : null],
      ["Tool success", pct(metrics.tool_success_rate), metrics.tool_success_rate == null ? null : metrics.tool_success_rate >= 0.9],
      ["Grounded rate", pct(metrics.grounded_rate), metrics.grounded_rate == null ? null : metrics.grounded_rate >= 0.9],
      ["Grounded claims", metrics.grounded_claims != null ? metrics.grounded_claims : "—", null],
      ["Ungrounded claims", metrics.ungrounded_claims != null ? metrics.ungrounded_claims : "—", metrics.ungrounded_claims === 0 ? true : null],
      ["Total tokens", metrics.total_tokens != null ? Number(metrics.total_tokens).toLocaleString() : "—", null],
      ["Latency (s)", metrics.total_latency_seconds != null ? metrics.total_latency_seconds : "—", null],
    ];

    html +=
      '<div class="panel"><div class="panel-head"><h3>Scorecard</h3></div>' +
      '<div class="metric-grid">' +
      tiles
        .map(function (t) {
          var cls = t[2] === true ? " is-good" : t[2] === false ? " is-bad" : "";
          return (
            '<div class="metric-tile' + cls + '"><div class="value">' + escapeHtml(String(t[1])) +
            '</div><div class="label">' + escapeHtml(t[0]) + "</div></div>"
          );
        })
        .join("") +
      "</div>";

    if (metrics.prompt_tokens != null || metrics.candidates_tokens != null) {
      html +=
        '<p class="hint token-split">Tokens — prompt ' +
        Number(metrics.prompt_tokens || 0).toLocaleString() +
        " · output " +
        Number(metrics.candidates_tokens || 0).toLocaleString() +
        "</p>";
    }
    html += "</div>";

    return html;
  }

  /* ================= AGENT TIMELINE ================= */

  /** Gantt from event timestamps: one bar per contiguous run of an agent. */
  function renderTimeline(events, metrics) {
    if (!events || !events.length) {
      return empty("The timeline fills in as agents run.");
    }
    var stamped = events.filter(function (e) { return e.timestamp; });
    if (!stamped.length) return empty("No timestamps recorded yet.");

    var t0 = Math.min.apply(null, stamped.map(function (e) { return e.timestamp; }));
    var t1 = Math.max.apply(null, stamped.map(function (e) { return e.timestamp; }));
    var span = Math.max(t1 - t0, 0.001);

    // Consecutive events from one author form a block.
    var blocks = [];
    stamped.forEach(function (e) {
      var last = blocks[blocks.length - 1];
      if (last && last.author === e.author) {
        last.end = e.timestamp;
        last.tools = last.tools.concat(e.tool_calls || []);
      } else {
        blocks.push({ author: e.author, start: e.timestamp, end: e.timestamp, tools: (e.tool_calls || []).slice() });
      }
    });

    var seen = {};
    return (
      '<ul class="timeline">' +
      blocks
        .map(function (b) {
          seen[b.author] = (seen[b.author] || 0) + 1;
          var left = ((b.start - t0) / span) * 100;
          var width = Math.max(((b.end - b.start) / span) * 100, 1.5);
          var dur = (b.end - b.start).toFixed(1);
          return (
            '<li class="tl-row"><span class="tl-name">' +
            escapeHtml(b.author) +
            (seen[b.author] > 1 ? ' <i class="tl-rerun">#' + seen[b.author] + "</i>" : "") +
            '</span><span class="tl-track">' +
            '<i class="tl-bar" style="left:' + left + "%;width:" + width + '%" title="' +
            escapeHtml(dur + "s" + (b.tools.length ? " · " + b.tools.join(", ") : "")) +
            '"></i></span>' +
            '<span class="tl-dur">' + dur + "s</span></li>"
          );
        })
        .join("") +
      "</ul>" +
      (metrics && metrics.total_latency_seconds != null
        ? '<p class="hint">Total ' + metrics.total_latency_seconds + "s across " + blocks.length + " agent blocks.</p>"
        : "")
    );
  }

  /* ================= PROVENANCE DRAWER ================= */

  /** Tool names an agent genuinely invoked in this run. */
  function toolsUsedBy(events, author) {
    var names = {};
    (events || []).forEach(function (e) {
      if (e.author === author) (e.tool_calls || []).forEach(function (t) { names[t] = true; });
    });
    return Object.keys(names);
  }

  /** Other claims in the package citing the same record. */
  function alsoCiting(pkg, recordIds, selfLabel) {
    var wanted = {}, hits = [];
    recordIds.forEach(function (r) { wanted[r] = true; });
    function scan(list, nameKey) {
      (list || []).forEach(function (x) {
        var label = x[nameKey];
        if (label === selfLabel) return;
        (x.source_records || []).forEach(function (r) {
          if (wanted[r.record_id] && hits.indexOf(label) === -1) hits.push(label);
        });
      });
    }
    if (pkg) {
      scan(pkg.budget && pkg.budget.line_items, "label");
      scan(pkg.resources && pkg.resources.crew_picks, "need");
      scan(pkg.resources && pkg.resources.location_picks, "need");
    }
    return hits;
  }

  /** Traces a decision back to its source row. Steps with nothing
   *  recorded are marked as such. */
  function renderProvenance(entry, pkg) {
    if (!entry) return empty("Nothing selected.");
    var records = entry.records || [];
    var tables = [];
    records.forEach(function (r) {
      if (r.source && tables.indexOf(r.source) === -1) tables.push(r.source);
    });
    var ids = records.map(function (r) { return r.record_id; });
    var others = alsoCiting(pkg, ids, entry.label);

    var steps = [
      {
        k: "Decision",
        v: entry.label,
        extra: entry.amount != null ? money(entry.amount, entry.currency) : null,
      },
      {
        k: "Agent",
        v: entry.agent || null,
        note: entry.agent === "budget_agent"
          ? "costed this line against historical studio data"
          : entry.agent === "resource_agent"
          ? "selected this from the studio's crew and location libraries"
          : null,
      },
      {
        k: "Tool",
        v: entry.tools && entry.tools.length ? entry.tools.join(", ") : null,
        note: entry.tools && entry.tools.length
          ? "invoked over MCP during this run"
          : "not recorded in this package (event log is not saved with a downloaded package)",
      },
      {
        k: "Dataset",
        v: tables.length ? tables.join(", ") : null,
        note: tables.length ? "queried through the official mcp-clickhouse server" : null,
      },
    ];

    var chain = steps
      .map(function (s, i) {
        return (
          '<li class="tr-step' + (s.v ? "" : " is-missing") + '">' +
          '<span class="tr-n" aria-hidden="true">' + (i + 1) + "</span>" +
          '<div class="tr-body"><span class="tr-k">' + escapeHtml(s.k) + "</span>" +
          '<span class="tr-v">' + (s.v ? escapeHtml(s.v) : "not recorded") + "</span>" +
          (s.extra ? '<span class="tr-extra">' + escapeHtml(s.extra) + "</span>" : "") +
          (s.note ? '<span class="tr-note">' + escapeHtml(s.note) + "</span>" : "") +
          "</div></li>"
        );
      })
      .join("");

    return (
      '<ol class="prov-trace">' + chain + "</ol>" +
      (entry.notes ? '<p class="prov-notes">' + escapeHtml(entry.notes) + "</p>" : "") +
      '<h3 class="prov-h">Source record' + (records.length === 1 ? "" : "s") + "</h3>" +
      (records.length
        ? '<ul class="prov-records">' +
          records
            .map(function (r) {
              return (
                "<li><code>" + escapeHtml(r.record_id) + "</code>" +
                (r.summary ? "<p>" + escapeHtml(r.summary) + "</p>" : "") +
                (r.source ? '<span class="prov-src">' + escapeHtml(r.source) + "</span>" : "") +
                "</li>"
              );
            })
            .join("") +
          "</ul>"
        : empty("This value carries no source record.", "It was not grounded in studio data.")) +
      (others.length
        ? '<div class="prov-also"><span class="lbl">Same record also used by</span><ul>' +
          others.map(function (o) { return "<li>" + escapeHtml(o) + "</li>"; }).join("") +
          "</ul></div>"
        : "")
    );
  }

  /* ================= pipeline map (setup page) ================= */

  function renderPipelineMap(defs) {
    return defs
      .map(function (d, i) {
        return (
          '<li class="pm-step">' +
          '<span class="pm-n">' + (i + 1) + "</span>" +
          '<span class="pm-body"><b>' + escapeHtml(d.label) + "</b>" +
          "<span>" + escapeHtml(d.hint) + "</span></span></li>"
        );
      })
      .join("");
  }

  return {
    escapeHtml: escapeHtml,
    money: money,
    pct: pct,
    empty: empty,
    resetProvenance: resetProvenance,
    getProvenance: getProvenance,
    groundBadge: groundBadge,
    buildIndex: buildIndex,
    groundingStore: groundingStore,
    CREW_STATIONS: CREW_STATIONS,
    countBlocks: countBlocks,
    computeCrewState: computeCrewState,
    deriveGrounding: deriveGrounding,
    renderOverview: renderOverview,
    renderBreakdown: renderBreakdown,
    renderStripboard: renderStripboard,
    renderBudget: renderBudget,
    renderRisk: renderRisk,
    renderResources: renderResources,
    renderPreviz: renderPreviz,
    renderPackage: renderPackage,
    renderTimeline: renderTimeline,
    renderProvenance: renderProvenance,
    renderPipelineMap: renderPipelineMap,
    toolsUsedBy: toolsUsedBy,
  };
})();
