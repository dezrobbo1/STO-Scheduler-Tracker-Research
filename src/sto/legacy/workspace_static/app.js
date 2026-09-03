"use strict";

const SESSION_KEY = "sto-prototype0-workspace-id";
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const state = {
  view: null,
  selectedId: null,
  expanded: new Set(),
  filter: "all",
  query: "",
  taskById: new Map(),
  childrenByParent: new Map(),
  timeline: null,
  noticeTimer: null,
  renderTimer: null,
};

const elements = {
  fileInput: document.querySelector("#fileInput"),
  dropZone: document.querySelector("#dropZone"),
  emptyState: document.querySelector("#emptyState"),
  workspace: document.querySelector("#workspace"),
  resetButton: document.querySelector("#resetButton"),
  exportButton: document.querySelector("#exportButton"),
  projectName: document.querySelector("#projectName"),
  sourceFile: document.querySelector("#sourceFile"),
  projectStart: document.querySelector("#projectStart"),
  projectFinish: document.querySelector("#projectFinish"),
  scenarioState: document.querySelector("#scenarioState"),
  taskCount: document.querySelector("#taskCount"),
  supportedCount: document.querySelector("#supportedCount"),
  relationshipCount: document.querySelector("#relationshipCount"),
  movedCount: document.querySelector("#movedCount"),
  searchInput: document.querySelector("#searchInput"),
  taskFilter: document.querySelector("#taskFilter"),
  expandAllButton: document.querySelector("#expandAllButton"),
  collapseAllButton: document.querySelector("#collapseAllButton"),
  scheduleScroller: document.querySelector("#scheduleScroller"),
  timelineHeader: document.querySelector("#timelineHeader"),
  taskRows: document.querySelector("#taskRows"),
  noRows: document.querySelector("#noRows"),
  inspectorEmpty: document.querySelector("#inspectorEmpty"),
  inspectorContent: document.querySelector("#inspectorContent"),
  inspectorBadge: document.querySelector("#inspectorBadge"),
  inspectorWbs: document.querySelector("#inspectorWbs"),
  inspectorTaskName: document.querySelector("#inspectorTaskName"),
  inspectorTaskMeta: document.querySelector("#inspectorTaskMeta"),
  inspectorImportedDates: document.querySelector("#inspectorImportedDates"),
  inspectorCalculatedDates: document.querySelector("#inspectorCalculatedDates"),
  durationForm: document.querySelector("#durationForm"),
  durationHours: document.querySelector("#durationHours"),
  recalculateButton: document.querySelector("#recalculateButton"),
  unsupportedPanel: document.querySelector("#unsupportedPanel"),
  unsupportedReasons: document.querySelector("#unsupportedReasons"),
  loadingOverlay: document.querySelector("#loadingOverlay"),
  loadingTitle: document.querySelector("#loadingTitle"),
  loadingDetail: document.querySelector("#loadingDetail"),
  notice: document.querySelector("#notice"),
};

function unwrapWorkspace(payload) {
  return payload && payload.workspace ? payload.workspace : payload;
}

function errorMessage(payload, fallback) {
  if (payload && typeof payload.error === "string") return payload.error;
  if (payload && payload.error && typeof payload.error.message === "string") {
    return payload.error.message;
  }
  if (payload && typeof payload.message === "string") return payload.message;
  return fallback;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    // A non-JSON response is reported using the HTTP status below.
  }
  if (!response.ok) {
    throw new Error(errorMessage(payload, `Request failed (${response.status})`));
  }
  return payload;
}

function showLoading(title, detail) {
  elements.loadingTitle.textContent = title;
  elements.loadingDetail.textContent = detail;
  elements.loadingOverlay.hidden = false;
}

function hideLoading() {
  elements.loadingOverlay.hidden = true;
}

function showNotice(message, kind = "info") {
  window.clearTimeout(state.noticeTimer);
  elements.notice.textContent = message;
  elements.notice.classList.toggle("error", kind === "error");
  elements.notice.hidden = false;
  state.noticeTimer = window.setTimeout(() => {
    elements.notice.hidden = true;
  }, kind === "error" ? 9000 : 5000);
}

function parseWallClock(value) {
  if (!value || typeof value !== "string") return null;
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?/
  );
  if (!match) return null;
  return Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6] || 0)
  );
}

function formatDate(value, includeYear = false) {
  if (!value || typeof value !== "string") return "—";
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return value;
  const month = MONTHS[Number(match[2]) - 1] || match[2];
  const year = includeYear ? ` ${match[1]}` : "";
  return `${match[3]} ${month}${year} ${match[4]}:${match[5]}`;
}

function formatAxisDate(value) {
  const date = new Date(value);
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = MONTHS[date.getUTCMonth()];
  const hour = String(date.getUTCHours()).padStart(2, "0");
  return `${day} ${month} ${hour}:00`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds === 0) return "0 h";
  const hours = seconds / 3600;
  const display = Number.isInteger(hours) ? String(hours) : hours.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return `${display} h`;
}

function supportReasons(task) {
  return (
    task.support_reasons ||
    task.support_reason_codes ||
    task.reason_codes ||
    task.supportReasons ||
    []
  );
}

function importedDates(task) {
  return task.imported || {
    start: task.imported_start,
    finish: task.imported_finish,
  };
}

function calculatedDates(task) {
  return task.calculated || {
    base_start: task.base_calculated_start,
    base_finish: task.base_calculated_finish,
    current_start: task.current_calculated_start ?? task.calculated_start,
    current_finish: task.current_calculated_finish ?? task.calculated_finish,
    changed: task.changed,
    start_delta_seconds: task.start_delta_seconds,
    finish_delta_seconds: task.finish_delta_seconds,
  };
}

function durationValues(task) {
  const nested = task.duration || {};
  return {
    imported: nested.imported_seconds ?? task.imported_duration_seconds ?? null,
    current: nested.current_seconds ?? task.current_duration_seconds ?? null,
  };
}

function isSummary(task) {
  return task.kind === "summary" || task.kind === "wbs" || task.summary === true;
}

function isSupported(task) {
  return (
    task.supported === true ||
    task.eligible === true ||
    task.calculation_supported === true
  );
}

function isMoved(task) {
  const calculated = calculatedDates(task);
  return calculated.changed === true || task.moved === true;
}

function normalizeView(view) {
  if (!view || !Array.isArray(view.tasks)) {
    throw new Error("The workspace returned an invalid task view.");
  }
  return view;
}

function rebuildIndexes() {
  state.taskById = new Map(state.view.tasks.map((task) => [task.id, task]));
  state.childrenByParent = new Map();
  for (const task of state.view.tasks) {
    const parentId = task.parent_id ?? null;
    if (!state.childrenByParent.has(parentId)) state.childrenByParent.set(parentId, []);
    state.childrenByParent.get(parentId).push(task.id);
  }
}

function ancestorsOf(taskId) {
  const ancestors = [];
  let task = state.taskById.get(taskId);
  const visited = new Set();
  while (task && task.parent_id && !visited.has(task.parent_id)) {
    visited.add(task.parent_id);
    ancestors.push(task.parent_id);
    task = state.taskById.get(task.parent_id);
  }
  return ancestors;
}

function revealTask(taskId) {
  for (const ancestor of ancestorsOf(taskId)) state.expanded.add(ancestor);
}

function installView(nextView, { preserveSelection = true } = {}) {
  state.view = normalizeView(unwrapWorkspace(nextView));
  rebuildIndexes();

  if (!preserveSelection || !state.taskById.has(state.selectedId)) {
    state.selectedId =
      state.view.recommended_task_id ||
      state.view.recommended_activity_id ||
      state.view.recommended_editable_task?.activity_id ||
      state.view.tasks.find((task) => isSupported(task) && !task.milestone)?.id ||
      null;
  }

  if (state.expanded.size === 0) {
    for (const task of state.view.tasks) {
      if (isSummary(task) && Number(task.outline_level || 0) <= 1) {
        state.expanded.add(task.id);
      }
    }
  }
  if (state.selectedId) revealTask(state.selectedId);

  const workspaceId = state.view.workspace_id;
  if (workspaceId) window.sessionStorage.setItem(SESSION_KEY, workspaceId);

  state.timeline = buildTimeline(state.view.tasks);
  renderAll();
}

function buildTimeline(tasks) {
  const values = [];
  for (const task of tasks) {
    const imported = importedDates(task);
    const calculated = calculatedDates(task);
    for (const value of [
      imported.start,
      imported.finish,
      calculated.base_start,
      calculated.base_finish,
      calculated.current_start,
      calculated.current_finish,
    ]) {
      const parsed = parseWallClock(value);
      if (parsed !== null) values.push(parsed);
    }
  }
  if (values.length === 0) {
    const now = Date.UTC(2026, 0, 1);
    return { start: now, finish: now + 86400000, span: 86400000, width: 960 };
  }
  let start = Math.min(...values);
  let finish = Math.max(...values);
  const rawSpan = Math.max(finish - start, 3600000);
  const padding = Math.max(rawSpan * 0.025, 3600000);
  start -= padding;
  finish += padding;
  const span = finish - start;
  const days = span / 86400000;
  const width = Math.round(Math.min(3200, Math.max(900, days * 44)));
  document.documentElement.style.setProperty("--gantt-width", `${width}px`);
  return { start, finish, span, width };
}

function timelinePosition(value) {
  const parsed = parseWallClock(value);
  if (parsed === null || !state.timeline) return null;
  return Math.max(0, Math.min(100, ((parsed - state.timeline.start) / state.timeline.span) * 100));
}

function renderTimelineHeader() {
  elements.timelineHeader.replaceChildren();
  const axis = document.createElement("div");
  axis.className = "timeline-axis";
  const tickCount = 8;
  for (let index = 0; index <= tickCount; index += 1) {
    const ratio = index / tickCount;
    const tick = document.createElement("div");
    tick.className = "timeline-tick";
    tick.style.left = `${ratio * 100}%`;
    const label = document.createElement("span");
    label.textContent = formatAxisDate(state.timeline.start + state.timeline.span * ratio);
    tick.append(label);
    axis.append(tick);
  }
  elements.timelineHeader.append(axis);
}

function renderSummary() {
  const inventory =
    state.view.inventory || state.view.source_inventory || state.view.counts || {};
  const calculation =
    state.view.calculation || state.view.profile_counts || state.view.counts || {};
  const scenario = state.view.scenario || {};
  const project = state.view.project || {};
  const source = state.view.source || {};

  elements.projectName.textContent = project.name || project.title || "Untitled shutdown";
  elements.sourceFile.textContent =
    source.file_name || source.source_filename || source.filename || "Imported MSPDI XML";
  elements.projectStart.textContent = formatDate(project.start, true);
  elements.projectFinish.textContent = formatDate(project.finish, true);
  elements.scenarioState.textContent = scenario.active
    ? `Revision ${state.view.revision ?? 1}`
    : "Original";
  elements.taskCount.textContent = String(inventory.tasks ?? state.view.tasks.length);
  elements.supportedCount.textContent = String(
    calculation.eligible_activities ??
      calculation.calculated_activities ??
      calculation.calculated_tasks ??
      state.view.tasks.filter(isSupported).length
  );
  elements.relationshipCount.textContent = String(
    inventory.relationships ?? state.view.relationship_count ?? 0
  );
  elements.movedCount.textContent = String(
    scenario.moved_task_count ??
      scenario.moved_activities ??
      state.view.counts?.changed_activities ??
      state.view.tasks.filter(isMoved).length
  );
  elements.resetButton.disabled = !scenario.active;
  elements.exportButton.disabled = false;
}

function matchingTaskIds() {
  const query = state.query.trim().toLocaleLowerCase();
  const direct = new Set();
  for (const task of state.view.tasks) {
    const filterMatches =
      state.filter === "all" ||
      (state.filter === "supported" && isSupported(task)) ||
      (state.filter === "moved" && isMoved(task));
    if (!filterMatches) continue;
    const queryMatches =
      !query ||
      String(task.name || "").toLocaleLowerCase().includes(query) ||
      String(task.wbs || "").toLocaleLowerCase().includes(query) ||
      String(task.outline_number || "").toLocaleLowerCase().includes(query) ||
      String(task.id || "").toLocaleLowerCase().includes(query) ||
      String(task.source_uid ?? "").toLocaleLowerCase().includes(query);
    if (queryMatches) direct.add(task.id);
  }
  if (!query && state.filter === "all") return null;
  const withAncestors = new Set(direct);
  for (const taskId of direct) {
    for (const ancestor of ancestorsOf(taskId)) withAncestors.add(ancestor);
  }
  return withAncestors;
}

function hierarchyVisible(task) {
  let current = task;
  const visited = new Set();
  while (current && current.parent_id && !visited.has(current.parent_id)) {
    visited.add(current.parent_id);
    if (!state.expanded.has(current.parent_id)) return false;
    current = state.taskById.get(current.parent_id);
  }
  return true;
}

function makeCell(className = "") {
  const cell = document.createElement("div");
  cell.className = `cell ${className}`.trim();
  cell.setAttribute("role", "cell");
  return cell;
}

function makeStatusBadge(task) {
  const badge = document.createElement("span");
  if (isMoved(task)) {
    badge.className = "status-badge moved";
    badge.textContent = "Moved";
  } else if (isSummary(task)) {
    badge.className = "status-badge";
    badge.textContent = "Summary";
  } else if (isSupported(task)) {
    badge.className = "status-badge supported";
    badge.textContent = "Calculated";
  } else {
    badge.className = "status-badge unsupported";
    badge.textContent = "View only";
  }
  return badge;
}

function appendBar(track, kind, startValue, finishValue, title, milestone = false) {
  const start = timelinePosition(startValue);
  const finish = timelinePosition(finishValue);
  if (start === null || finish === null) return;
  const bar = document.createElement("span");
  bar.className = `gantt-bar ${kind}${milestone ? " milestone" : ""}`;
  bar.style.left = `${start}%`;
  bar.style.width = `${Math.max(finish - start, 0.22)}%`;
  bar.title = title;
  track.append(bar);
}

function makeGanttCell(task) {
  const cell = makeCell("gantt-cell");
  const track = document.createElement("div");
  track.className = "gantt-track";
  const imported = importedDates(task);
  const calculated = calculatedDates(task);
  appendBar(
    track,
    "imported",
    imported.start,
    imported.finish,
    `Imported: ${formatDate(imported.start)} → ${formatDate(imported.finish)}`,
    Boolean(task.milestone)
  );
  if (calculated.current_start && calculated.current_finish) {
    if (
      isMoved(task) &&
      calculated.base_start &&
      calculated.base_finish
    ) {
      appendBar(
        track,
        "original",
        calculated.base_start,
        calculated.base_finish,
        `Before change: ${formatDate(calculated.base_start)} → ${formatDate(calculated.base_finish)}`,
        Boolean(task.milestone)
      );
    }
    appendBar(
      track,
      "calculated",
      calculated.current_start,
      calculated.current_finish,
      `Our calculation: ${formatDate(calculated.current_start)} → ${formatDate(calculated.current_finish)}`,
      Boolean(task.milestone)
    );
  }
  cell.append(track);
  return cell;
}

function makeTaskRow(task) {
  const row = document.createElement("div");
  row.className = "schedule-row task-row";
  if (isSummary(task)) row.classList.add("summary");
  if (isMoved(task)) row.classList.add("moved");
  if (task.id === state.selectedId) row.classList.add("selected");
  row.setAttribute("role", "row");
  row.tabIndex = 0;
  row.dataset.taskId = task.id;
  row.dataset.testid = `task-row-${task.id}`;
  row.dataset.supported = isSupported(task) ? "true" : "false";
  row.dataset.calculatedStart = calculatedDates(task).current_start || "";
  row.dataset.calculatedFinish = calculatedDates(task).current_finish || "";
  row.setAttribute("aria-selected", task.id === state.selectedId ? "true" : "false");

  const taskCell = makeCell("task-cell");
  const level = Math.max(0, Number(task.outline_level || 0));
  taskCell.style.paddingLeft = `${8 + level * 15}px`;
  const children = state.childrenByParent.get(task.id) || [];
  if (children.length > 0) {
    const toggle = document.createElement("button");
    toggle.className = "tree-toggle";
    toggle.type = "button";
    toggle.textContent = state.expanded.has(task.id) ? "−" : "+";
    toggle.setAttribute(
      "aria-label",
      `${state.expanded.has(task.id) ? "Collapse" : "Expand"} ${task.name || "task"}`
    );
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (state.expanded.has(task.id)) state.expanded.delete(task.id);
      else state.expanded.add(task.id);
      renderRows();
    });
    taskCell.append(toggle);
  } else {
    const spacer = document.createElement("span");
    spacer.className = "tree-spacer";
    taskCell.append(spacer);
  }
  const label = document.createElement("span");
  label.className = "task-label";
  const name = document.createElement("strong");
  name.textContent = task.name || "Unnamed task";
  const meta = document.createElement("small");
  meta.textContent = [task.outline_number, task.wbs].filter(Boolean).join(" · ") || task.id;
  label.append(name, meta);
  taskCell.append(label);
  row.append(taskCell);

  const statusCell = makeCell();
  statusCell.append(makeStatusBadge(task));
  row.append(statusCell);

  const durationCell = makeCell("number-cell");
  durationCell.textContent = formatDuration(durationValues(task).current);
  row.append(durationCell);

  const imported = importedDates(task);
  const calculated = calculatedDates(task);
  for (const value of [imported.start, imported.finish]) {
    const cell = makeCell("date-cell");
    cell.textContent = formatDate(value);
    row.append(cell);
  }
  for (const value of [calculated.current_start, calculated.current_finish]) {
    const cell = makeCell(`date-cell${value ? "" : " not-calculated"}`);
    cell.textContent = formatDate(value);
    row.append(cell);
  }
  row.append(makeGanttCell(task));

  const select = () => selectTask(task.id);
  row.addEventListener("click", select);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select();
    }
  });
  return row;
}

function renderRows() {
  if (!state.view) return;
  const retainedScrollTop = elements.scheduleScroller.scrollTop;
  const matches = matchingTaskIds();
  const fragment = document.createDocumentFragment();
  let count = 0;
  for (const task of state.view.tasks) {
    const visible = matches ? matches.has(task.id) : hierarchyVisible(task);
    if (!visible) continue;
    fragment.append(makeTaskRow(task));
    count += 1;
  }
  elements.taskRows.replaceChildren(fragment);
  elements.noRows.hidden = count !== 0;
  elements.scheduleScroller.scrollTop = retainedScrollTop;
}

function humanizeReason(value) {
  return String(value || "Unsupported in the current calculation profile")
    .toLocaleLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toLocaleUpperCase());
}

function renderInspector() {
  const task = state.taskById.get(state.selectedId);
  elements.inspectorEmpty.hidden = Boolean(task);
  elements.inspectorContent.hidden = !task;
  if (!task) return;

  const imported = importedDates(task);
  const calculated = calculatedDates(task);
  const duration = durationValues(task);
  const downstreamCount =
    task.downstream_count ?? task.eligible_downstream_count ?? 0;

  elements.inspectorBadge.replaceWith(makeStatusBadge(task));
  elements.inspectorBadge = document.querySelector("#inspectorContent .status-badge");
  elements.inspectorBadge.id = "inspectorBadge";
  elements.inspectorWbs.textContent = task.wbs || task.outline_number || task.id;
  elements.inspectorTaskName.textContent = task.name || "Unnamed task";
  elements.inspectorTaskMeta.textContent = isSummary(task)
    ? "Summary task · imported dates only"
    : `${downstreamCount} calculated downstream task${downstreamCount === 1 ? "" : "s"}`;
  elements.inspectorImportedDates.textContent = `${formatDate(imported.start, true)} → ${formatDate(
    imported.finish,
    true
  )}`;
  elements.inspectorCalculatedDates.textContent = calculated.current_start
    ? `${formatDate(calculated.current_start, true)} → ${formatDate(calculated.current_finish, true)}`
    : "Not calculated in the current profile";

  const editable = isSupported(task) && !task.milestone && !isSummary(task);
  elements.durationForm.hidden = !editable;
  elements.unsupportedPanel.hidden = editable;
  if (editable) {
    const hours = duration.current / 3600;
    elements.durationHours.value = Number.isInteger(hours)
      ? String(hours)
      : hours.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  } else {
    const reasons = supportReasons(task);
    elements.unsupportedReasons.textContent = isSummary(task)
      ? "Summary dates are displayed from the imported schedule and are not calculated by the current engine."
      : task.milestone && isSupported(task)
        ? "Milestone duration remains zero in this prototype."
        : reasons.map(humanizeReason).join("; ") || "This task is outside the supported calculation subset.";
  }
}

function renderAll() {
  elements.emptyState.hidden = true;
  elements.workspace.hidden = false;
  renderSummary();
  renderTimelineHeader();
  renderRows();
  renderInspector();
}

function selectTask(taskId) {
  if (!state.taskById.has(taskId)) return;
  state.selectedId = taskId;
  revealTask(taskId);
  renderRows();
  renderInspector();
}

function queueRowsRender() {
  window.clearTimeout(state.renderTimer);
  state.renderTimer = window.setTimeout(renderRows, 80);
}

async function importFile(file) {
  if (!file) return;
  if (!/\.(xml|mspdi)$/i.test(file.name)) {
    showNotice("Choose a Microsoft Project XML or MSPDI file.", "error");
    return;
  }
  showLoading("Importing full shutdown", "Reading hierarchy, relationships and calendars…");
  try {
    const payload = await requestJson("/api/import", {
      method: "POST",
      headers: {
        "Content-Type": "application/xml",
        "X-File-Name": encodeURIComponent(file.name),
      },
      body: file,
    });
    state.expanded.clear();
    state.filter = "all";
    state.query = "";
    elements.taskFilter.value = "all";
    elements.searchInput.value = "";
    installView(payload, { preserveSelection: false });
    const supported = state.view.tasks.filter(isSupported).length;
    showNotice(
      supported > 0
        ? `Imported ${state.view.tasks.length} tasks. ${supported} are calculated in this prototype.`
        : `Imported ${state.view.tasks.length} tasks. None are inside the current calculation subset.`
    );
  } catch (error) {
    showNotice(error.message || "The schedule could not be imported.", "error");
  } finally {
    elements.fileInput.value = "";
    hideLoading();
  }
}

async function applyDuration(event) {
  event.preventDefault();
  const task = state.taskById.get(state.selectedId);
  if (!task || !isSupported(task) || task.milestone) return;
  const hours = Number(elements.durationHours.value);
  const seconds = Math.round(hours * 3600);
  if (!Number.isFinite(hours) || hours <= 0 || !Number.isSafeInteger(seconds)) {
    showNotice("Enter a duration greater than zero.", "error");
    elements.durationHours.focus();
    return;
  }

  showLoading("Recalculating schedule", "Applying the duration change to the supported network…");
  try {
    const payload = await requestJson(
      `/api/workspaces/${encodeURIComponent(state.view.workspace_id)}/scenario`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activity_id: task.id, duration_seconds: seconds }),
      }
    );
    const nextView = normalizeView(unwrapWorkspace(payload));
    const scenario = nextView.scenario || {};
    const moved =
      scenario.moved_task_count ??
      nextView.counts?.changed_activities ??
      nextView.tasks.filter(isMoved).length;
    if (moved > 0) {
      state.filter = "moved";
      elements.taskFilter.value = "moved";
    } else if (state.filter === "moved") {
      state.filter = "all";
      elements.taskFilter.value = "all";
    }
    installView(nextView);
    showNotice(
      moved > 0
        ? `Recalculated. ${moved} task${moved === 1 ? "" : "s"} moved; the dashed bars show their previous dates.`
        : "Recalculated. No task dates moved for this duration change."
    );
  } catch (error) {
    showNotice(error.message || "The scenario could not be recalculated.", "error");
  } finally {
    hideLoading();
  }
}

async function resetScenario() {
  if (!state.view) return;
  showLoading("Resetting scenario", "Restoring the original calculated dates…");
  try {
    const payload = await requestJson(
      `/api/workspaces/${encodeURIComponent(state.view.workspace_id)}/scenario`,
      { method: "DELETE" }
    );
    state.filter = "all";
    elements.taskFilter.value = "all";
    installView(payload);
    showNotice("Scenario reset to the original imported duration and calculated dates.");
  } catch (error) {
    showNotice(error.message || "The scenario could not be reset.", "error");
  } finally {
    hideLoading();
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function exportWorkspace() {
  if (!state.view) return;
  try {
    const response = await fetch(
      `/api/workspaces/${encodeURIComponent(state.view.workspace_id)}/export`
    );
    if (!response.ok) {
      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        // Use the status fallback below.
      }
      throw new Error(errorMessage(payload, `Export failed (${response.status})`));
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : "sto-schedule-prototype0.json";
    downloadBlob(await response.blob(), filename);
    showNotice("Exported the current prototype state as JSON.");
  } catch (error) {
    showNotice(error.message || "The workspace could not be exported.", "error");
  }
}

async function restoreWorkspace() {
  const workspaceId = window.sessionStorage.getItem(SESSION_KEY);
  if (!workspaceId) return;
  try {
    const payload = await requestJson(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
    installView(payload, { preserveSelection: false });
  } catch (_error) {
    window.sessionStorage.removeItem(SESSION_KEY);
  }
}

elements.fileInput.addEventListener("change", () => importFile(elements.fileInput.files[0]));
elements.dropZone.addEventListener("click", (event) => {
  if (event.target.closest("label")) return;
  elements.fileInput.click();
});
elements.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.fileInput.click();
  }
});
for (const eventName of ["dragenter", "dragover"]) {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("dragging");
  });
}
elements.dropZone.addEventListener("drop", (event) => importFile(event.dataTransfer.files[0]));
elements.searchInput.addEventListener("input", () => {
  state.query = elements.searchInput.value;
  queueRowsRender();
});
elements.taskFilter.addEventListener("change", () => {
  state.filter = elements.taskFilter.value;
  renderRows();
});
elements.expandAllButton.addEventListener("click", () => {
  for (const task of state.view.tasks) {
    if ((state.childrenByParent.get(task.id) || []).length > 0) state.expanded.add(task.id);
  }
  renderRows();
});
elements.collapseAllButton.addEventListener("click", () => {
  state.expanded.clear();
  renderRows();
});
elements.durationForm.addEventListener("submit", applyDuration);
elements.resetButton.addEventListener("click", resetScenario);
elements.exportButton.addEventListener("click", exportWorkspace);

restoreWorkspace();
