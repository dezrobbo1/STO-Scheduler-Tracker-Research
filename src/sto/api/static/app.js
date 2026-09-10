"use strict";

const projects = document.querySelector("#project");
const calculateButton = document.querySelector("#calculate");
const createProjectForm = document.querySelector("#create-project");
const importForm = document.querySelector("#import-schedule");
const fileInput = document.querySelector("#schedule-file");
const status = document.querySelector("#status");
const scenarioSection = document.querySelector("#scenario-section");
const scenarioForm = document.querySelector("#scenario-form");
const activitySelect = document.querySelector("#activity");
const durationInput = document.querySelector("#duration-hours");
const applyScenario = document.querySelector("#apply-scenario");
const resetScenario = document.querySelector("#reset-scenario");
const exportScenario = document.querySelector("#export-scenario");
const mode = document.querySelector("#mode");
const versionState = document.querySelector("#version-state");
const changeSummary = document.querySelector("#change-summary");
const provenanceSection = document.querySelector("#provenance-section");
const provenance = document.querySelector("#provenance");
const rowsSection = document.querySelector("#rows-section");
const body = document.querySelector("#rows tbody");
const chartSection = document.querySelector("#chart-section");
const chart = document.querySelector("#chart");
const summariesSection = document.querySelector("#summaries-section");
const summaryBody = document.querySelector("#summaries tbody");

let currentState = null;
let refreshGeneration = 0;

function say(message, kind) {
  status.textContent = message;
  if (kind) status.dataset.kind = kind; else delete status.dataset.kind;
}

function moment(value) {
  return value ? value.replace("T", " ").slice(0, 19) : "";
}

function span(start, finish) {
  if (!start) return "";
  return moment(start) + (finish && finish !== start ? " → " + moment(finish) : "");
}

function hours(seconds) {
  return seconds === null || seconds === undefined ? "" : (seconds / 3600).toFixed(2).replace(/0+$/, "").replace(/\.$/, "") + " h";
}

async function json(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
      if (typeof detail === "object") detail = detail.message ?? detail.code ?? JSON.stringify(detail);
    } catch (error) { /* keep status text */ }
    const failure = new Error(detail);
    failure.status = response.status;
    throw failure;
  }
  return response.json();
}

function statusDate(result) {
  if (result.status_time) return moment(result.status_time);
  if (result.status_time_outside_window) return "discarded by the scheduling window policy";
  return "none in the file";
}

function edgeSummary(edges) {
  const perCode = new Map();
  for (const edge of edges ?? []) perCode.set(edge.code, (perCode.get(edge.code) ?? 0) + 1);
  return [...perCode].sort((a, b) => b[1] - a[1]).map(([code, n]) => code + " ×" + n).join(", ");
}

function instant(value) {
  if (!value) return NaN;
  const parts = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(value);
  if (!parts) return NaN;
  return Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]), Number(parts[4]), Number(parts[5]), Number(parts[6] ?? 0));
}

function comparisonMoments(state) {
  const values = [];
  for (const result of [state.baseline, state.scenario]) {
    if (!result) continue;
    for (const row of result.activities) {
      if (!row.early_start) continue;
      for (const key of ["source_start", "source_finish", "early_start", "early_finish"]) {
        if (row[key]) values.push(instant(row[key]));
      }
    }
  }
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return null;
  const from = Math.min(...finite);
  const to = Math.max(...finite);
  const padding = 12 * 60 * 60 * 1000;
  return to > from ? { from, span: to - from } : { from: from - padding, span: 2 * padding };
}

function band(scale, start, finish, className) {
  if (!scale || !start) return null;
  const from = instant(start);
  const to = instant(finish ?? start);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  const element = document.createElement("span");
  element.className = className;
  let left = ((from - scale.from) / scale.span) * 100;
  const width = Math.max(((to - from) / scale.span) * 100, 0.4);
  left = Math.max(0, Math.min(100 - width, left));
  element.style.left = left + "%";
  element.style.width = Math.max(0, Math.min(100 - left, width)) + "%";
  return element;
}

function classifyMovement(baseline, scenario, changedUid) {
  if (!scenario) return "";
  if (baseline.activity_uid === changedUid) return "edited";
  if (baseline.early_start !== scenario.early_start || baseline.early_finish !== scenario.early_finish) return "downstream";
  return "";
}

function disposition(row) {
  if (row.disposition === "excluded") return {label: "unsupported / excluded", kind: "excluded"};
  if ((row.assumptions ?? []).some((code) => code.includes("CONSTRAINT"))) return {label: "deferred constraint support", kind: "assumed"};
  if ((row.assumptions ?? []).length) return {label: "calculated with assumption", kind: "assumed"};
  return {label: "calculated normally", kind: "normal"};
}

function detail(row) {
  if (row.disposition === "excluded") return [row.exclusion_code, row.exclusion_detail].filter(Boolean).join(": ");
  return (row.assumptions ?? []).join(", ");
}

function calculationDetail(row) {
  const values = [];
  if (row.late_start) values.push("late " + span(row.late_start, row.late_finish));
  if (row.total_float_seconds !== null) values.push("TF " + hours(row.total_float_seconds));
  if (row.free_float_seconds !== null) values.push("FF " + hours(row.free_float_seconds));
  if (row.critical !== null) values.push(row.critical ? "critical" : "not critical");
  if (row.progress_state) values.push("progress " + row.progress_state);
  if (row.placed_by) values.push("placed by " + row.placed_by);
  if (row.late_placed_by) values.push("late bound " + row.late_placed_by);
  if (row.constraint_override) values.push("constraint override " + row.constraint_override);
  if (row.agrees_with_source !== null) {
    values.push(row.agrees_with_source ? "source dates agree" : "source dates differ");
  }
  return values.join(" · ");
}

function describe(state) {
  const result = state.scenario ?? state.baseline;
  provenance.replaceChildren();
  if (!result) { provenanceSection.hidden = true; return; }
  const facts = [
    ["Baseline version", state.baseline_version_id],
    ["Active version", state.current_version_id + " (" + state.current_kind + ")"],
    ["Document", result.canonical_hash],
    ["Result", result.fingerprint],
    ["Window", moment(result.horizon_start) + " → " + moment(result.horizon_finish)],
    ["Progress policy", result.progress_policy],
    ["Status date", statusDate(result)],
    ["Activities", result.counts.activities + " (" + result.counts.scheduled + " scheduled)"],
    ["Relationships", edgeSummary(result.relationships) || "all in the ordinary cohort"],
  ];
  for (const [term, value] of facts) {
    const dt = document.createElement("dt"); dt.textContent = term;
    const dd = document.createElement("dd"); dd.textContent = value;
    provenance.append(dt, dd);
  }
  provenanceSection.hidden = false;
}

function drawChart(state) {
  chart.replaceChildren();
  const baseline = state.baseline;
  if (!baseline) { chartSection.hidden = true; return; }
  const scale = comparisonMoments(state);
  const scenarioRows = new Map((state.scenario?.activities ?? []).map((row) => [row.activity_uid, row]));
  const ordered = baseline.activities.filter((row) => row.early_start).sort((a, b) => a.early_start.localeCompare(b.early_start));
  for (const row of ordered) {
    const scenario = scenarioRows.get(row.activity_uid);
    const movement = classifyMovement(row, scenario, state.change?.activity_uid);
    const line = document.createElement("div"); line.className = "gantt-row";
    if (movement) line.dataset.movement = movement;
    const label = document.createElement("span"); label.className = "gantt-label";
    const name = document.createElement("span"); name.className = "gantt-name";
    name.textContent = (row.code ? row.code + "  " : "") + (row.name ?? ""); name.title = name.textContent;
    label.append(name);
    if (movement) {
      const tag = document.createElement("span"); tag.className = "move-tag";
      tag.textContent = movement === "edited" ? "edited" : "moved"; label.append(tag);
    }
    const track = document.createElement("span"); track.className = "track";
    for (const item of [
      band(scale, row.source_start, row.source_finish, "bar imported"),
      band(scale, row.early_start, row.early_finish, "bar baseline"),
      scenario && band(scale, scenario.early_start, scenario.early_finish, "bar scenario"),
    ]) if (item) track.append(item);
    line.append(label, track); chart.append(line);
  }
  chartSection.hidden = false;
}

function populateActivities(state) {
  const previous = activitySelect.value;
  activitySelect.replaceChildren();
  for (const item of state.eligible_activities) {
    activitySelect.append(new Option((item.code ? item.code + " — " : "") + item.name, item.activity_uid));
  }
  if ([...activitySelect.options].some((option) => option.value === previous)) activitySelect.value = previous;
  if (!activitySelect.value && activitySelect.options.length) activitySelect.selectedIndex = 0;
  activitySelect.disabled = !activitySelect.options.length;
  applyScenario.disabled = !activitySelect.options.length || !state.baseline;
  syncDuration();
}

function syncDuration() {
  if (!currentState) return;
  const selected = currentState.eligible_activities.find((item) => item.activity_uid === activitySelect.value);
  if (!selected) { durationInput.value = ""; return; }
  const seconds = currentState.change?.activity_uid === selected.activity_uid ? currentState.change.after_seconds : selected.planned_duration_seconds;
  durationInput.value = String(seconds / 3600);
}

function renderRows(state) {
  body.replaceChildren();
  if (!state.baseline) { rowsSection.hidden = true; return; }
  const eligible = new Set(state.eligible_activities.map((row) => row.activity_uid));
  const scenarioRows = new Map((state.scenario?.activities ?? []).map((row) => [row.activity_uid, row]));
  for (const row of state.baseline.activities) {
    const scenario = scenarioRows.get(row.activity_uid);
    const active = scenario ?? row;
    const movement = classifyMovement(row, scenario, state.change?.activity_uid);
    const tr = document.createElement("tr"); tr.dataset.disposition = active.disposition;
    if (movement) tr.dataset.movement = movement;
    const editCell = document.createElement("td");
    if (eligible.has(row.activity_uid)) {
      const button = document.createElement("button"); button.type = "button"; button.textContent = "Select";
      button.dataset.activityUid = row.activity_uid; editCell.append(button);
    }
    tr.append(editCell);
    const dispositionInfo = disposition(active);
    const values = [
      [row.code ?? "", ""], [row.name ?? "", "name"],
      [dispositionInfo.label, "disposition"], [span(row.source_start, row.source_finish), ""],
      [span(row.early_start, row.early_finish), ""],
      [scenario ? span(scenario.early_start, scenario.early_finish) : "—", ""],
      [movement === "edited" ? "duration edited" : movement === "downstream" ? "downstream moved" : "", ""],
      [calculationDetail(active), "calculation-detail"],
      [detail(active), "detail"],
    ];
    for (const [value, className] of values) {
      const td = document.createElement("td"); td.textContent = value;
      if (className) td.className = className;
      if (className === "disposition") td.dataset.kind = dispositionInfo.kind;
      if ((className === "name" || className === "detail") && value) td.title = value;
      tr.append(td);
    }
    body.append(tr);
  }
  rowsSection.hidden = false;
}

function renderSummaries(state) {
  summaryBody.replaceChildren();
  const result = state.scenario ?? state.baseline;
  if (!result) { summariesSection.hidden = true; return; }
  for (const row of result.summaries) {
    const tr = document.createElement("tr");
    for (const [value, className] of [
      [row.code ?? "", ""], [row.name ?? "", "name"],
      [span(row.source_start, row.source_finish), ""],
      [row.span_start ? span(row.span_start, row.span_finish) : "nothing placed beneath it", ""],
      [String(row.placed ?? 0), ""],
    ]) {
      const td = document.createElement("td"); td.textContent = value;
      if (className) td.className = className; tr.append(td);
    }
    summaryBody.append(tr);
  }
  summariesSection.hidden = false;
}

function render(state) {
  currentState = state;
  scenarioSection.hidden = false;
  mode.textContent = state.current_kind;
  mode.dataset.kind = state.current_kind;
  versionState.textContent = "Baseline " + state.baseline_version_id.slice(0, 8) + " · active " + state.current_version_id.slice(0, 8);
  changeSummary.textContent = state.change ? "Changed planned duration from " + hours(state.change.before_seconds) + " to " + hours(state.change.after_seconds) + "." : "No active scenario. The imported baseline is unchanged.";
  resetScenario.disabled = !state.scenario;
  exportScenario.href = "/api/projects/" + state.project_id + "/scenario/export";
  exportScenario.setAttribute("download", "sto-scenario-" + state.project_id + ".json");
  applyScenario.textContent = state.scenario ? "Update scenario" : "Create scenario";
  populateActivities(state);
  describe(state);
  drawChart(state);
  renderRows(state);
  renderSummaries(state);
  if (!state.baseline) say("Schedule imported. Calculate the baseline to enable supported duration edits.");
}

function selectedProject(projectId) {
  return projects.value === projectId;
}

function renderedImport(state, imported) {
  return Boolean(state && selectedProject(imported.project_id) &&
    state.project_id === imported.project_id &&
    state.baseline_version_id === imported.version_id);
}

function renderedCalculation(state, calculation) {
  return Boolean(state && selectedProject(calculation.project_id) && state.baseline &&
    state.project_id === calculation.project_id &&
    state.baseline_version_id === calculation.version_id &&
    state.baseline.version_id === calculation.version_id &&
    state.baseline.calculation_id === calculation.calculation_id);
}

function renderedScenario(state, projectId, activityUid, seconds) {
  return Boolean(state && selectedProject(projectId) && state.scenario && state.change &&
    state.project_id === projectId && state.current_kind === "scenario" &&
    state.current_version_id === state.scenario.version_id &&
    state.current_version_id === state.change.scenario_version_id &&
    state.change.activity_uid === activityUid && state.change.after_seconds === seconds);
}

function resetIsDisabled(state) {
  return !state || !state.scenario;
}

function beginRefresh() {
  refreshGeneration += 1;
  return refreshGeneration;
}

function currentRefresh(generation, projectId) {
  return generation === refreshGeneration && selectedProject(projectId);
}

async function show(projectId) {
  if (!projectId || !selectedProject(projectId)) return null;
  const generation = beginRefresh();
  currentState = null;
  for (const section of [scenarioSection, provenanceSection, chartSection, rowsSection, summariesSection]) section.hidden = true;
  try {
    const state = await json("/api/projects/" + projectId + "/planner");
    if (!currentRefresh(generation, projectId)) return null;
    render(state);
    if (state.baseline) say("");
    return state;
  } catch (error) {
    if (!currentRefresh(generation, projectId)) return null;
    if (error.status === 409) say("Import a schedule into this project.");
    else say("The planner state could not be served: " + error.message, "error");
    return null;
  }
}

async function refreshProjects(selected) {
  const rows = await json("/api/projects");
  projects.replaceChildren();
  if (!rows.length) projects.append(new Option("no projects yet", ""));
  for (const project of rows) projects.append(new Option(project.name, project.id));
  if (selected) projects.value = selected;
  await show(projects.value);
}

calculateButton.addEventListener("click", async () => {
  const projectId = projects.value; if (!projectId) return;
  calculateButton.disabled = true; say("Calculating immutable baseline…");
  try {
    const calculation = await json("/api/projects/" + projectId + "/calculations", {method: "POST"});
    if (!selectedProject(projectId)) return;
    const state = await show(projectId);
    if (!state) return;
    if (!renderedCalculation(state, calculation)) {
      say("The baseline changed before this calculation could be displayed. Review the current state and calculate it if needed.", "error");
      return;
    }
    say("Baseline calculated and stored.");
  } catch (error) { if (projects.value === projectId) say(error.message, "error"); }
  finally { calculateButton.disabled = false; }
});

createProjectForm.addEventListener("submit", async (event) => {
  event.preventDefault(); say("Creating project…");
  try {
    const created = await json("/api/projects", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name: document.querySelector("#project-name").value, timezone: document.querySelector("#project-timezone").value})});
    await refreshProjects(created.id); say("Project created. Import an MSPDI/XML schedule.");
    createProjectForm.reset(); document.querySelector("#project-timezone").value = "UTC";
  } catch (error) { say(error.message, "error"); }
});

importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const projectId = projects.value; const file = fileInput.files[0];
  if (!projectId) { say("Create or select a project first.", "error"); return; }
  if (!file) return;
  const data = new FormData(); data.append("file", file);
  say("Importing and preserving the source baseline…");
  try {
    const imported = await json("/api/projects/" + projectId + "/imports", {method: "POST", body: data});
    if (!selectedProject(projectId)) return;
    const state = await show(projectId);
    if (renderedImport(state, imported)) say("Schedule imported. Calculate the baseline next.");
  } catch (error) { say(error.message, "error"); }
});

scenarioForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentState || !activitySelect.value) return;
  const projectId = currentState.project_id;
  const expectedVersionId = currentState.current_version_id;
  const activityUid = activitySelect.value;
  const seconds = Math.round(Number(durationInput.value) * 3600);
  applyScenario.disabled = true; say("Calculating scenario…");
  try {
    const state = await json("/api/projects/" + projectId + "/scenario", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({expected_version_id: expectedVersionId, activity_uid: activityUid, planned_duration_seconds: seconds})});
    if (!selectedProject(projectId)) return;
    if (!renderedScenario(state, projectId, activityUid, seconds)) {
      render(state);
      say("The scenario was superseded before it could be displayed. Review the current state and try again.", "error");
      return;
    }
    render(state); say("Scenario calculated and stored. Changed and downstream rows are marked.");
  } catch (error) {
    if (projects.value !== projectId) return;
    say(error.message + (error.status === 409 ? " Reloaded current state." : ""), "error");
    if (error.status === 409) await show(projects.value);
  } finally { if (projects.value === projectId) applyScenario.disabled = false; }
});

resetScenario.addEventListener("click", async () => {
  if (!currentState) return;
  const projectId = currentState.project_id;
  const expectedVersionId = currentState.current_version_id;
  resetScenario.disabled = true; say("Resetting to baseline…");
  try {
    const state = await json("/api/projects/" + projectId + "/scenario/reset", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({expected_version_id: expectedVersionId})});
    if (projects.value !== projectId) return;
    render(state); say("Scenario reset. The baseline result is active again.");
  } catch (error) {
    if (projects.value !== projectId) return;
    say(error.message + (error.status === 409 ? " Reloaded current state." : ""), "error");
    if (error.status === 409) await show(projectId);
  }
  finally { if (selectedProject(projectId)) resetScenario.disabled = resetIsDisabled(currentState); }
});

activitySelect.addEventListener("change", syncDuration);
body.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-activity-uid]");
  if (!button) return;
  activitySelect.value = button.dataset.activityUid; syncDuration();
  scenarioSection.scrollIntoView({behavior: "smooth", block: "start"});
});
projects.addEventListener("change", () => show(projects.value));

(async function start() {
  try { await refreshProjects(); }
  catch (error) { say(error.message, "error"); }
})();
