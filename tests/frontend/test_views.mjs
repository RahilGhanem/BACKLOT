import fs from 'fs';
import vm from 'vm';
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(new URL('../../backlot/api/static/views.js', import.meta.url), 'utf8'), ctx);
const V = ctx.BACKLOT_VIEWS;

const pkgPath = process.env.BACKLOT_PACKAGE || new URL('../fixtures/sample_package.json', import.meta.url);
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
const metrics = { task_completed: true, tool_calls: 9, tool_errors: 0, tool_success_rate: 1.0,
  grounded_rate: 0.96, grounded_claims: 22, ungrounded_claims: 2,
  total_tokens: 203226, prompt_tokens: 180000, candidates_tokens: 23226,
  total_latency_seconds: 1583.68 };
const events = [
  { author: 'script_supervisor', timestamp: 1000, text: 'x', tool_calls: [] },
  { author: 'budget_agent', timestamp: 1010, text: null, tool_calls: ['list_tables'] },
  { author: 'budget_agent', timestamp: 1020, text: null, tool_calls: ['run_query'] },
  { author: 'risk_agent', timestamp: 1040, text: 'y', tool_calls: [] },
  { author: 'budget_agent', timestamp: 1060, text: null, tool_calls: ['run_query'] },
  { author: 'resource_agent', timestamp: 1090, text: null, tool_calls: ['run_query'] },
];

const checks = [];
function run(name, fn, mustInclude) {
  try {
    const html = fn();
    if (typeof html !== 'string' || !html.length) throw new Error('empty output');
    for (const m of (mustInclude || [])) {
      if (!html.includes(m)) throw new Error(`missing expected content: ${m}`);
    }
    if (/undefined|\[object Object\]|NaN/.test(html)) {
      throw new Error('output contains undefined/NaN/[object Object]');
    }
    checks.push([name, 'PASS', html.length]);
  } catch (e) {
    checks.push([name, 'FAIL: ' + e.message, 0]);
  }
}

V.resetProvenance();
run('overview', () => V.renderOverview(pkg, metrics, 'completed', events, false, 'r1'), ['slate', 'spine', 'Shooting board', '209,500', 'Grounding']);
run('overview-running', () => V.renderOverview({breakdown: pkg.breakdown}, null, 'running', events.slice(0,1), false, 'r1'), ['slate', 'spine']);
run('overview-awaiting', () => V.renderOverview(pkg, null, 'awaiting_approval', events, false, 'r1'), ['Producer decision required']);
run('overview-replan', () => V.renderOverview(pkg, metrics, 'completed', events, false, 'r1'), ['spine-arc', 'pass 2']);
run('breakdown', () => V.renderBreakdown(pkg), ['scene-card', 'Shoot day', 'req req-']);
run('stripboard', () => V.renderStripboard(pkg), ['strip-', 'board-scene', 'DAY 1']);
run('budget', () => V.renderBudget(pkg, events), ['data-table', 'ungrounded', 'data-prov']);
run('risk', () => V.renderRisk(pkg), ['risk-card', 'data-goto-scene', 'data-goto-day']);
run('resources', () => V.renderResources(pkg, events), ['pick-list', 'data-prov']);
run('package', () => V.renderPackage(pkg, metrics, 'completed'), ['Scorecard', 'Ungrounded claims', '203,226']);
run('timeline', () => V.renderTimeline(events, metrics), ['tl-bar', 'budget_agent', 'tl-rerun']);
run('previz-empty', () => V.renderPreviz(null, 'r1'), ['empty-state']);
run('overview-empty', () => V.renderOverview({}, null, null, [], false, null), ['No production loaded', 'spine']);
run('breakdown-empty', () => V.renderBreakdown({}), ['empty-state']);

// provenance drawer round-trip
V.resetProvenance();
V.renderBudget(pkg, events);
run('provenance', () => V.renderProvenance(V.getProvenance(0), pkg), ['prov-trace', 'budget_agent', 'clickhouse:', 'Decision']);

// XSS safety
V.resetProvenance();
const evil = JSON.parse(JSON.stringify(pkg));
evil.breakdown.scenes[0].synopsis = '<img src=x onerror=alert(1)>';
run('xss-escaped', () => {
  const h = V.renderBreakdown(evil);
  if (h.includes('<img src=x')) throw new Error('UNESCAPED HTML INJECTED');
  return h;
}, ['&lt;img']);

let fails = 0;
for (const [n, s, len] of checks) {
  if (s !== 'PASS') fails++;
  console.log(`  ${s === 'PASS' ? 'PASS' : 'FAIL'}  ${n.padEnd(18)} ${s === 'PASS' ? len + ' chars' : s}`);
}
console.log(fails ? `\n${fails} FAILED` : `\nall ${checks.length} renderer checks passed`);
process.exit(fails ? 1 : 0);
