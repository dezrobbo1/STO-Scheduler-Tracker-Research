"use strict";

const elements = {
  emptyState: document.querySelector("#emptyState"),
  workspace: document.querySelector("#workspace"),
  fileInput: document.querySelector("#fileInput"),
  importButton: document.querySelector("#importButton"),
  emptyImportButton: document.querySelector("#emptyImportButton"),
  resetButton: document.querySelector("#resetButton"),
  exportButton: document.querySelector("#exportButton"),
  fileName: document.querySelector("#fileName"),
  projectName: document.querySelector("#projectName"),
  projectStats: document.querySelector("#projectStats"),
  editorTitle: document.querySelector("#editorTitle"),
  editorMeta: document.querySelector("#editorMeta"),
  editorUnavailable: document.querySelector("#editorUnavailable"),
  durationForm: document.querySelector("#durationForm"),
  durationHours: document.querySelector("#durationHours"),
  durationMinutes: document.querySelector("#durationMinutes"),
  durationSeconds: document.querySelector("#durationSeconds"),
  editorResult: document.querySelector("#editorResult"),
  searchInput: document.querySelector("#searchInput"),
  scheduleGrid: document.querySelector("#scheduleGrid"),
  scheduleRows: document.querySelector("#scheduleRows"),
  timelineHeader: document.querySelector("#timelineHeader"),
  rowSummary: document.querySelector("#rowSummary"),
  statusMessage: document.querySelector("#statusMessage"),
  filterButtons: Array.from(document.querySelectorAll(".filter-button")),
};

let workspaceState = null;
let selectedTaskId = null;
let activeFilter = "all";
let collapsedIds = new Set();
let statusTimer = null;
let recalculationPending = false;

function showStatus(message, error = false) {
  window.clearTimeout(statusTimer);
  elements.statusMessage.textContent = message;
  elements.statusMessage.classList.toggle("error", error);
  elements.statusMessage.classList.add("visible");
  statusTimer = window.setTimeout(() => {
    elements.statusMessage.classList.remove("visible");
  }, error ? 6500 : 4200);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    throw new Error(`The local workspace returned HTTP ${response.status}.`);
  }
  if (!response.ok) {
    throw new Error(payload.error || `The local workspace returned HTTP ${response.status}.`);
  }
  return payload;
}

function shortHash(value) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "—";
}

function formatScheduleDate(value) {
  if (!value) return "—";
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : value;
}

function parseScheduleDate(value) {
  if (!value) return null;
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$/,
  );
  if (!match) return Number.NaN;
  const milliseconds = Number(`0.${match[7] || "0"}`) * 1000;
  return Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6]),
    milliseconds,
  );
}

function formatTimelineDate(milliseconds) {
  const date = new Date(milliseconds);
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const parts = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (remainder) parts.push(`${remainder}s`);
  return parts.join(" ") || "0m";
}

function formatDelta(seconds) {
  if (!Number.isFinite(seconds) || seconds === 0) return "—";
  const sign = seconds > 0 ? "+" : "−";
  return `${sign}${formatDuration(Math.abs(seconds))}`;
}

function plainReason(code) {
  const known = {
    SUMMARY_TASK: "Summary rows are imported hierarchy and are not calculated.",
    CALCULATION_PROFILE_UNAVAILABLE: "The schedule is outside the current calculation profile.",
    CALCULATION_UNAVAILABLE: "The bounded scheduler could not calculate this schedule.",
    INELIGIBLE_PREDECESSOR: "A predecessor is outside the current calculation profile.",
    RELATIONSHIP_TYPE_UNSUPPORTED: "A dependency type is not supported by the current scheduler.",
    RELATIONSHIP_LAG_UNSUPPORTED: "A dependency lag is not supported by the current scheduler.",
    PROGRESS_STATE_PRESENT: "The activity already contains progress state.",
    ACTUAL_STATE_PRESENT: "The activity already contains actual state.",
    ACTIVITY_INACTIVE: "The activity is inactive.",
    DURATION_FORMAT_UNSUPPORTED: "The imported duration format is not currently supported.",
    MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED: "The assigned resources use different working calendars.",
    WORK_UNITS_INCONSISTENT: "Imported work, duration, and assignment units are inconsistent.",
  };
  return known[code] || `${code.toLowerCase().replaceAll("_", " ")}.`;
}

function createStat(value, label, extraClass = "") {
  const stat = document.createElement("div");
  stat.className = `stat ${extraClass}`.trim();
  const strong = document.createElement("strong");
  strong.textContent = String(value);
  const span = document.createElement("span");
  span.textContent = label;
  stat.append(strong, span);
  return stat;
}

function renderProject() {
  const state = workspaceState;
  elements.fileName.textContent = `${state.display_name} · ${shortHash(state.source.sha256)}`;
  elements.projectName.textContent = state.project.name || state.display_name;
  elements.projectStats.replaceChildren(
    createStat(state.counts.tasks, "tasks"),
    createStat(state.counts.summary_tasks, "summaries"),
    createStat(state.counts.supported_activities, "calculated", "supported"),
    createStat(state.counts.unsupported_activities, "imported only"),
    createStat(state.scenario.moved_activity_count, "moved", state.scenario.changed ? "moved" : ""),
  );
  elements.importButton.textContent = "Replace XML…";
  elements.resetButton.disabled = !state.scenario.changed;
  const changeCount = state.scenario.duration_overrides.length;
  elements.resetButton.textContent = changeCount ? `Reset scenario (${changeCount})` : "Reset scenario";
  elements.exportButton.disabled = false;
}

function selectedRow() {
  return workspaceState?.tasks.find((row) => row.id === selectedTaskId) || null;
}

function renderEditor() {
  const row = selectedRow();
  elements.editorResult.textContent = "";
  if (!row) {
    elements.editorTitle.textContent = "Select a task";
    elements.editorMeta.textContent = "Choose a calculated activity in the table.";
    elements.durationForm.hidden = true;
    elements.editorUnavailable.hidden = false;
    elements.editorUnavailable.textContent = "Select a calculated, non-milestone activity to change its working duration.";
    return;
  }

  elements.editorTitle.textContent = row.name;
  elements.editorTitle.title = row.name;
  const wbs = row.wbs || row.outline_number || "No WBS";
  const outline = row.outline_number || "No outline number";
  const scope = row.kind === "summary" ? "Summary · imported only" : row.supported ? "Calculated subset" : "Imported only";
  elements.editorMeta.textContent = `WBS ${wbs} · Outline ${outline} · ${row.id} · ${scope}`;

  if (!row.editable) {
    elements.durationForm.hidden = true;
    elements.editorUnavailable.hidden = false;
    if (row.milestone && row.supported) {
      elements.editorUnavailable.textContent = "This zero-duration milestone is calculated, but its duration cannot be changed.";
    } else {
      const primaryReason = row.primary_reason;
      elements.editorUnavailable.textContent = primaryReason
        ? `${plainReason(primaryReason)} Code: ${primaryReason}`
        : "This row is not editable in the current calculation profile.";
    }
    return;
  }

  elements.editorUnavailable.hidden = true;
  elements.durationForm.hidden = false;
  const seconds = row.scenario_duration_seconds;
  elements.durationHours.value = String(Math.floor(seconds / 3600));
  elements.durationMinutes.value = String(Math.floor((seconds % 3600) / 60));
  elements.durationSeconds.value = String(seconds % 60);
}

function timelineBounds() {
  const values = [];
  for (const row of workspaceState.tasks) {
    for (const value of [
      row.imported_start,
      row.imported_finish,
      row.calculated_start,
      row.calculated_finish,
    ]) {
      const parsed = parseScheduleDate(value);
      if (Number.isFinite(parsed)) values.push(parsed);
    }
  }
  if (!values.length) {
    const now = Date.now();
    return { start: now, finish: now + 3600000 };
  }
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max(3600000, (maximum - minimum) * 0.015);
  return { start: minimum - padding, finish: maximum + padding };
}

function appendAncestors(ids, rowById) {
  for (const id of Array.from(ids)) {
    let row = rowById.get(id);
    const visited = new Set();
    while (row?.parent_id && !visited.has(row.parent_id)) {
      visited.add(row.parent_id);
      ids.add(row.parent_id);
      row = rowById.get(row.parent_id);
    }
  }
}

function filteredRows() {
  const rows = workspaceState.tasks;
  const rowById = new Map(rows.map((row) => [row.id, row]));
  const query = elements.searchInput.value.trim().toLocaleLowerCase();
  const included = new Set(
    rows
      .filter((row) => {
        const passesFilter = activeFilter === "all"
          || (activeFilter === "supported" && row.supported)
          || (activeFilter === "changed" && (row.moved || row.scenario_changed));
        const passesSearch = !query
          || `${row.name} ${row.wbs || ""} ${row.outline_number || ""} ${row.id}`.toLocaleLowerCase().includes(query);
        return passesFilter && passesSearch;
      })
      .map((row) => row.id),
  );
  appendAncestors(included, rowById);

  return rows.filter((row) => {
    if (!included.has(row.id)) return false;
    if (query) return true;
    let parentId = row.parent_id;
    const visited = new Set();
    while (parentId && !visited.has(parentId)) {
      if (collapsedIds.has(parentId)) return false;
      visited.add(parentId);
      parentId = rowById.get(parentId)?.parent_id;
    }
    return true;
  });
}

function createTextCell(className, text, role = "cell") {
  const cell = document.createElement("div");
  cell.className = className;
  cell.setAttribute("role", role);
  cell.textContent = text;
  return cell;
}

function makeBar(kind, startValue, finishValue, bounds, milestone) {
  const start = parseScheduleDate(startValue);
  const finish = parseScheduleDate(finishValue);
  if (!Number.isFinite(start) || !Number.isFinite(finish)) return null;
  const span = bounds.finish - bounds.start;
  const left = Math.max(0, Math.min(100, ((start - bounds.start) / span) * 100));
  const right = Math.max(left, Math.min(100, ((finish - bounds.start) / span) * 100));
  const bar = document.createElement("span");
  bar.className = `gantt-bar ${kind}${milestone ? " milestone" : ""}`;
  bar.style.left = `${left}%`;
  if (!milestone) bar.style.width = `${Math.max(0.18, right - left)}%`;
  bar.title = `${kind === "imported" ? "Imported" : "Calculated"}: ${formatScheduleDate(startValue)} → ${formatScheduleDate(finishValue)}`;
  bar.setAttribute("aria-hidden", "true");
  return bar;
}

function renderScheduleRow(row, bounds, index) {
  const gridRow = document.createElement("div");
  gridRow.className = [
    "schedule-row",
    row.kind === "summary" ? "summary" : "",
    row.moved ? "moved" : "",
    row.id === selectedTaskId ? "selected" : "",
  ].filter(Boolean).join(" ");
  gridRow.setAttribute("role", "row");
  gridRow.setAttribute("aria-rowindex", String(index + 2));
  if (row.id === selectedTaskId) gridRow.setAttribute("aria-selected", "true");

  const wbsValue = row.wbs || row.outline_number || "—";
  const wbsCell = createTextCell("wbs-cell", wbsValue);
  wbsCell.title = wbsValue;
  gridRow.append(wbsCell);

  const taskCell = document.createElement("div");
  taskCell.className = "task-cell";
  taskCell.setAttribute("role", "cell");
  const indent = document.createElement("span");
  indent.className = "indent";
  indent.style.width = `${Math.max(0, row.outline_level || 0) * 15}px`;
  taskCell.append(indent);
  if (row.kind === "summary") {
    const searchActive = Boolean(elements.searchInput.value.trim());
    const effectivelyCollapsed = collapsedIds.has(row.id) && !searchActive;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tree-toggle";
    toggle.dataset.rowId = row.id;
    toggle.textContent = effectivelyCollapsed ? "▸" : "▾";
    toggle.setAttribute("aria-label", `${effectivelyCollapsed ? "Expand" : "Collapse"} ${row.name}`);
    toggle.setAttribute("aria-expanded", String(!effectivelyCollapsed));
    toggle.disabled = searchActive;
    if (searchActive) toggle.title = "Clear the search to collapse hierarchy rows";
    toggle.addEventListener("click", () => {
      if (collapsedIds.has(row.id)) collapsedIds.delete(row.id);
      else collapsedIds.add(row.id);
      renderGrid();
      focusGridControl(row.id, "tree-toggle");
    });
    taskCell.append(toggle);
  } else {
    const toggleSpacer = document.createElement("span");
    toggleSpacer.className = "tree-toggle-spacer";
    toggleSpacer.setAttribute("aria-hidden", "true");
    taskCell.append(toggleSpacer);
  }
  const select = document.createElement("button");
  select.type = "button";
  select.className = "task-select";
  select.dataset.rowId = row.id;
  select.disabled = recalculationPending;
  select.setAttribute("aria-label", `Select ${row.name}, WBS ${row.wbs || row.outline_number || "not set"}, ${row.id}`);
  select.title = row.name;
  const name = document.createElement("span");
  name.className = "task-name";
  name.textContent = row.name;
  const id = document.createElement("span");
  id.className = "task-id";
  id.textContent = row.id;
  select.append(name, id);
  select.addEventListener("click", () => {
    selectedTaskId = row.id;
    renderEditor();
    renderGrid();
    focusGridControl(row.id, "task-select");
  });
  taskCell.append(select);
  gridRow.append(taskCell);

  const scopeCell = document.createElement("div");
  scopeCell.setAttribute("role", "cell");
  const scope = document.createElement("span");
  scope.className = `scope-pill ${row.kind === "summary" ? "summary" : row.supported ? "supported" : ""}`;
  scope.textContent = row.kind === "summary" ? "Summary" : row.supported ? "Calculated" : "Imported only";
  if (row.reason_codes?.length) {
    const orderedReasons = [
      row.primary_reason,
      ...row.reason_codes.filter((reason) => reason !== row.primary_reason),
    ].filter(Boolean);
    scope.title = orderedReasons.join(", ");
  }
  scopeCell.append(scope);
  gridRow.append(scopeCell);

  const durationCell = document.createElement("div");
  durationCell.className = "duration-cell";
  durationCell.setAttribute("role", "cell");
  const currentDuration = document.createElement("span");
  currentDuration.className = "current";
  currentDuration.textContent = formatDuration(row.scenario_duration_seconds);
  currentDuration.setAttribute("aria-hidden", "true");
  durationCell.append(currentDuration);
  if (row.scenario_changed) {
    const originalDuration = document.createElement("span");
    originalDuration.className = "original";
    originalDuration.textContent = formatDuration(row.imported_duration_seconds);
    originalDuration.setAttribute("aria-hidden", "true");
    durationCell.append(originalDuration);
  }
  durationCell.setAttribute(
    "aria-label",
    row.scenario_changed
      ? `Current duration ${formatDuration(row.scenario_duration_seconds)}. Original duration ${formatDuration(row.imported_duration_seconds)}.`
      : `Duration ${formatDuration(row.scenario_duration_seconds)}.`,
  );
  gridRow.append(durationCell);

  for (const value of [row.imported_start, row.imported_finish, row.calculated_start, row.calculated_finish]) {
    gridRow.append(createTextCell(`date-cell${value ? "" : " empty"}`, formatScheduleDate(value)));
  }

  const effectiveDelta = row.finish_delta_seconds || row.start_delta_seconds;
  const deltaCell = createTextCell(`change-cell${row.moved ? " changed" : ""}`, formatDelta(effectiveDelta));
  deltaCell.title = row.impact === "edited" ? "Edited activity" : row.impact === "downstream" ? "Downstream activity moved" : "No scenario movement";
  gridRow.append(deltaCell);

  const gantt = document.createElement("div");
  gantt.className = "gantt-cell";
  gantt.setAttribute("role", "cell");
  gantt.setAttribute("aria-label", `Imported ${formatScheduleDate(row.imported_start)} to ${formatScheduleDate(row.imported_finish)}; calculated ${formatScheduleDate(row.calculated_start)} to ${formatScheduleDate(row.calculated_finish)}`);
  const importedBar = makeBar("imported", row.imported_start, row.imported_finish, bounds, row.milestone);
  const calculatedBar = makeBar("calculated", row.calculated_start, row.calculated_finish, bounds, row.milestone);
  if (importedBar) gantt.append(importedBar);
  if (calculatedBar) gantt.append(calculatedBar);
  gridRow.append(gantt);
  return gridRow;
}

function renderGrid() {
  if (!workspaceState?.loaded) return;
  const bounds = timelineBounds();
  const middle = bounds.start + (bounds.finish - bounds.start) / 2;
  const startLabel = document.createElement("span");
  startLabel.textContent = formatTimelineDate(bounds.start);
  const middleLabel = document.createElement("span");
  middleLabel.textContent = formatTimelineDate(middle);
  const finishLabel = document.createElement("span");
  finishLabel.textContent = formatTimelineDate(bounds.finish);
  elements.timelineHeader.replaceChildren(startLabel, middleLabel, finishLabel);

  const rows = filteredRows();
  const fragment = document.createDocumentFragment();
  rows.forEach((row, index) => fragment.append(renderScheduleRow(row, bounds, index)));
  elements.scheduleRows.replaceChildren(fragment);
  elements.scheduleGrid.setAttribute("aria-rowcount", String(rows.length + 1));
  elements.rowSummary.textContent = `Showing ${rows.length} of ${workspaceState.tasks.length} rows · ${workspaceState.counts.supported_activities} activities have calculated dates under ${workspaceState.calculation.profile}.`;
}

function focusGridControl(rowId, className) {
  const replacement = Array.from(elements.scheduleRows.querySelectorAll(`.${className}`))
    .find((candidate) => candidate.dataset.rowId === rowId);
  replacement?.focus();
}

function setRecalculationPending(pending) {
  recalculationPending = pending;
  elements.durationForm.querySelectorAll("input, button").forEach((control) => {
    control.disabled = pending;
  });
  elements.scheduleRows.querySelectorAll(".task-select").forEach((control) => {
    control.disabled = pending;
  });
  elements.importButton.disabled = pending;
  elements.emptyImportButton.disabled = pending;
  elements.resetButton.disabled = pending || !workspaceState?.scenario.changed;
  elements.exportButton.disabled = pending || !workspaceState?.loaded;
}

function renderAll() {
  const loaded = Boolean(workspaceState?.loaded);
  elements.emptyState.hidden = loaded;
  elements.workspace.hidden = !loaded;
  if (!loaded) return;
  renderProject();
  renderEditor();
  renderGrid();
}

let importTrigger = elements.importButton;
for (const trigger of [elements.importButton, elements.emptyImportButton]) {
  trigger.addEventListener("click", () => {
    importTrigger = trigger;
    elements.fileInput.click();
  });
}

elements.fileInput.addEventListener("change", async () => {
  const file = elements.fileInput.files?.[0];
  if (!file) return;
  if (workspaceState?.scenario.changed && !window.confirm("Replace this schedule and discard the current duration scenario?")) {
    elements.fileInput.value = "";
    return;
  }
  let importSucceeded = false;
  try {
    showStatus(`Importing ${file.name}…`);
    elements.fileInput.disabled = true;
    elements.importButton.disabled = true;
    elements.emptyImportButton.disabled = true;
    workspaceState = await requestJson("/api/import", {
      method: "POST",
      headers: {
        "Content-Type": "application/xml",
        "X-File-Name": encodeURIComponent(file.name),
      },
      body: file,
    });
    collapsedIds = new Set();
    activeFilter = "all";
    elements.searchInput.value = "";
    elements.filterButtons.forEach((button) => {
      const active = button.dataset.filter === "all";
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    selectedTaskId = null;
    renderAll();
    importSucceeded = true;
    showStatus(`Imported ${workspaceState.counts.tasks} tasks. ${workspaceState.counts.supported_activities} have calculated dates.`);
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    elements.fileInput.disabled = false;
    elements.importButton.disabled = false;
    elements.emptyImportButton.disabled = false;
    elements.fileInput.value = "";
    if (importSucceeded) elements.projectName.focus();
    else importTrigger.focus();
  }
});

elements.durationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const row = selectedRow();
  if (!row?.editable) return;
  const hours = Number(elements.durationHours.value);
  const minutes = Number(elements.durationMinutes.value);
  const remainingSeconds = Number(elements.durationSeconds.value);
  if (
    !Number.isInteger(hours)
    || !Number.isInteger(minutes)
    || !Number.isInteger(remainingSeconds)
    || hours < 0
    || minutes < 0
    || minutes > 59
    || remainingSeconds < 0
    || remainingSeconds > 59
  ) {
    showStatus("Enter whole hours, minutes, and seconds; minutes and seconds must be between 0 and 59.", true);
    return;
  }
  const seconds = hours * 3600 + minutes * 60 + remainingSeconds;
  if (seconds <= 0) {
    showStatus("A non-milestone duration must be greater than zero.", true);
    return;
  }
  if (seconds > workspaceState.limits.maximum_duration_seconds) {
    showStatus("Duration cannot exceed 8,760 hours.", true);
    return;
  }
  const submittedTaskId = row.id;
  const submittedTaskName = row.name;
  setRecalculationPending(true);
  try {
    workspaceState = await requestJson("/api/scenario/recalculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_key: workspaceState.source.document_key,
        revision: workspaceState.scenario.revision,
        activity_id: submittedTaskId,
        duration_seconds: seconds,
      }),
    });
    renderAll();
    const moved = workspaceState.scenario.moved_activity_count;
    const downstream = workspaceState.scenario.downstream_moved_activity_count;
    const message = `${submittedTaskName}: ${formatDuration(seconds)}. Across all current overrides, ${moved} ${moved === 1 ? "activity differs" : "activities differ"} from the import-time calculation; ${downstream} are unedited downstream ${downstream === 1 ? "activity" : "activities"}.`;
    elements.editorResult.textContent = message;
    showStatus(message);
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    setRecalculationPending(false);
  }
});

elements.resetButton.addEventListener("click", async () => {
  const count = workspaceState?.scenario.duration_overrides.length || 0;
  if (!count) return;
  if (!window.confirm(`Reset ${count} duration ${count === 1 ? "change" : "changes"} and restore the import-time calculation?`)) return;
  try {
    workspaceState = await requestJson("/api/scenario/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_key: workspaceState.source.document_key,
        revision: workspaceState.scenario.revision,
      }),
    });
    renderAll();
    showStatus("Scenario reset. Imported schedule remains open.");
  } catch (error) {
    showStatus(error.message, true);
  }
});

elements.exportButton.addEventListener("click", () => {
  if (!workspaceState?.loaded) return;
  const exportState = {
    export_type: "prototype-0-local-schedule-workspace-state",
    ...workspaceState,
  };
  const blobUrl = URL.createObjectURL(
    new Blob([`${JSON.stringify(exportState, null, 2)}\n`], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = "sto-prototype-0-scenario.json";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
  showStatus("Exporting the current prototype state as JSON.");
});

elements.searchInput.addEventListener("input", renderGrid);
elements.filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    elements.filterButtons.forEach((candidate) => {
      const active = candidate === button;
      candidate.classList.toggle("active", active);
      candidate.setAttribute("aria-pressed", String(active));
    });
    renderGrid();
  });
});

requestJson("/api/workspace")
  .then((state) => {
    workspaceState = state;
    selectedTaskId = null;
    renderAll();
  })
  .catch((error) => showStatus(error.message, true));
