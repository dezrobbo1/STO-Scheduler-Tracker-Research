// A read-only view of one stored calculation. No framework and no build step:
// the page fetches two routes and renders what they return.
"use strict";

const projects = document.querySelector("#project");
const calculate = document.querySelector("#calculate");
const status = document.querySelector("#status");
const provenanceSection = document.querySelector("#provenance-section");
const provenance = document.querySelector("#provenance");
const rowsSection = document.querySelector("#rows-section");
const body = document.querySelector("#rows tbody");
const chartSection = document.querySelector("#chart-section");
const chart = document.querySelector("#chart");
const summariesSection = document.querySelector("#summaries-section");
const summaryBody = document.querySelector("#summaries tbody");

function say(message, kind) {
  status.textContent = message;
  if (kind) status.dataset.kind = kind; else delete status.dataset.kind;
}

function moment(value) {
  // The API returns wall-clock without an offset, which is what a schedule
  // date is; showing it verbatim keeps it that way rather than shifting it
  // into the reader's zone.
  return value ? value.replace("T", " ").slice(0, 16) : "";
}

function hours(seconds) {
  return seconds === null || seconds === undefined ? "" : (seconds / 3600).toFixed(1) + " h";
}

async function json(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch (error) { /* keep status */ }
    const failure = new Error(detail);
    // Carried, because the page has to tell "there is no calculation" from
    // "there is one and the server refused to serve it". Reporting an
    // integrity refusal as an absence hides the very thing the check exists
    // to surface.
    failure.status = response.status;
    throw failure;
  }
  return response.json();
}

function describe(result) {
  const counts = result.counts;
  provenance.replaceChildren();
  const facts = [
    ["Document", result.canonical_hash.slice(0, 16) + "…"],
    ["Result", result.fingerprint.slice(0, 16) + "…"],
    ["Window", moment(result.horizon_start) + " → " + moment(result.horizon_finish)],
    ["Progress policy", result.progress_policy],
    ["Status date", statusDate(result)],
    ["Engine", Object.entries(result.profiles).map(([k, v]) => k + " " + v).join(", ")],
    ["Activities", counts.activities + " (" + counts.scheduled + " scheduled)"],
    ["Summaries", String(counts.summaries)],
    ["Agreeing with the file", counts.agreeing_with_source + " of " + counts.compared_with_source],
  ];
  const edges = edgeSummary(result.relationships);
  if (edges) facts.push(["Relationships", edges]);
  for (const [term, value] of facts) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    provenance.append(dt, dd);
  }
  provenanceSection.hidden = false;
}

function statusDate(result) {
  // A file whose status date fell outside the compiled window had it removed,
  // so the passes ran without one. That is not the same as a file that never
  // carried one, and a page showing only "none" would say it was.
  if (result.status_time) return moment(result.status_time);
  if (result.status_time_outside_window) {
    return "discarded — the file's status date fell outside the compiled window";
  }
  return "none in the file";
}

function edgeSummary(edges) {
  if (!edges || edges.length === 0) return "";
  const perCode = new Map();
  for (const edge of edges) perCode.set(edge.code, (perCode.get(edge.code) ?? 0) + 1);
  return [...perCode]
    .sort((a, b) => b[1] - a[1])
    .map(([code, n]) => code + " ×" + n)
    .join(", ");
}

// --- the bar ---------------------------------------------------------------
// A schedule people read is a schedule with a shape, and a table of timestamps
// has none. This is the smallest thing that gives one: a horizontal band per
// row, positioned against the whole calculation's extent. The outline behind
// it is what the file said, so a row that moved shows the movement rather than
// asking the reader to subtract two timestamps in their head.

function instant(value) {
  // A schedule date is wall-clock with no offset, and `Date.parse` reads one
  // as a local instant -- so across a daylight-saving transition two
  // consecutive midnights come out 23 hours apart and every bar on the chart
  // shifts. The components are read directly into a UTC epoch, where an hour
  // is always an hour.
  if (!value) return NaN;
  const parts = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(value);
  if (!parts) return NaN;
  return Date.UTC(
    Number(parts[1]),
    Number(parts[2]) - 1,
    Number(parts[3]),
    Number(parts[4]),
    Number(parts[5]),
    Number(parts[6] ?? 0)
  );
}

function moments(result) {
  const values = [];
  for (const row of result.activities) {
    for (const key of ["early_start", "early_finish", "source_start", "source_finish"]) {
      if (row[key]) values.push(instant(row[key]));
    }
  }
  for (const row of result.summaries) {
    for (const key of ["span_start", "span_finish", "source_start", "source_finish"]) {
      if (row[key]) values.push(instant(row[key]));
    }
  }
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return null;
  const from = Math.min(...finite);
  const to = Math.max(...finite);
  return to > from ? { from, span: to - from } : null;
}

function band(scale, start, finish, className) {
  if (!scale || !start) return null;
  const from = instant(start);
  const to = instant(finish ?? start);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  const element = document.createElement("span");
  element.className = className;
  const left = ((from - scale.from) / scale.span) * 100;
  // A milestone has no width of its own; a hairline keeps it visible instead
  // of rendering as nothing at all.
  const width = Math.max(((to - from) / scale.span) * 100, 0.4);
  element.style.left = Math.max(0, Math.min(100, left)) + "%";
  element.style.width = Math.max(0, Math.min(100 - left, width)) + "%";
  return element;
}

function drawChart(result, scale) {
  // Its own section, at the page's full width, because a track squeezed into a
  // table column gave a seven-week shutdown about three pixels a day and read
  // as a scatter of ticks rather than as a schedule.
  chart.replaceChildren();
  if (!scale) return;
  // Time order, not the order the passes walked. The table below keeps the
  // engine's order; a chart read down the page is read as a sequence.
  const placed = result.activities
    .filter((row) => row.early_start)
    .sort((left, right) => left.early_start.localeCompare(right.early_start));
  for (const row of placed) {
    const line = document.createElement("div");
    line.className = "gantt-row";
    if (row.critical) line.dataset.critical = "true";
    const label = document.createElement("span");
    label.className = "gantt-label";
    label.textContent = (row.code ? row.code + "  " : "") + (row.name ?? "");
    label.title = label.textContent;
    const track = document.createElement("span");
    track.className = "track";
    const imported = band(scale, row.source_start, row.source_finish, "bar imported");
    if (imported) track.append(imported);
    const computed = band(scale, row.early_start, row.early_finish, "bar computed");
    if (computed) track.append(computed);
    line.append(label, track);
    chart.append(line);
  }
  chartSection.hidden = false;
}

function state(row) {
  if (row.disposition === "excluded") return "not calculated";
  const label = { not_started: "not started", in_progress: "in progress", complete: "complete" };
  return label[row.progress_state] ?? row.progress_state ?? "";
}

function placement(row) {
  // What put the row where it is, in the reader's words rather than the
  // engine's. A row that disagrees with the file and says "constraint" has
  // explained itself; one that only disagrees has not.
  if (row.disposition === "excluded") return "";
  const label = {
    relationship: "a predecessor",
    project_start: "the project start",
    constraint: "a constraint",
    actuals: "its own actual dates",
    status_time: "the status date",
  };
  const reason = label[row.placed_by] ?? row.placed_by ?? "";
  const notes = [];
  if (reason) notes.push(reason);
  if (row.constraint_override) notes.push("overriding its logic");
  if (row.assumptions && row.assumptions.length) notes.push("under " + row.assumptions.join(", "));
  return notes.join(", ");
}

function render(result) {
  describe(result);
  const scale = moments(result);
  drawChart(result, scale);
  body.replaceChildren();
  for (const row of result.activities) {
    const tr = document.createElement("tr");
    tr.dataset.disposition = row.disposition;
    if (row.critical) tr.dataset.critical = "true";
    const cells = [
      [row.code ?? "", ""],
      [row.name ?? "", "name"],
      [state(row), ""],
      [moment(row.source_start), ""],
      [moment(row.source_finish), ""],
      [row.disposition === "excluded" ? row.exclusion_code : moment(row.early_start), ""],
      [moment(row.early_finish), ""],
      [placement(row), "reason"],
      [hours(row.total_float_seconds), "num"],
      [row.critical === null ? "" : row.critical ? "yes" : "no", ""],
      [row.agrees_with_source === null ? "" : row.agrees_with_source ? "yes" : "no", "agrees"],
    ];
    for (const [text, kind] of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      if (kind === "num" || kind === "name" || kind === "reason") td.className = kind;
      if ((kind === "name" || kind === "reason") && text) td.title = text;
      if (kind === "agrees" && row.agrees_with_source !== null) {
        td.dataset.agrees = String(row.agrees_with_source);
      }
      tr.append(td);
    }
    body.append(tr);
  }
  rowsSection.hidden = false;

  summaryBody.replaceChildren();
  for (const row of result.summaries) {
    const tr = document.createElement("tr");
    if (!row.span_start) tr.dataset.disposition = "excluded";
    for (const [text, kind] of [
      [row.code ?? "", ""],
      [row.name ?? "", "name"],
      [moment(row.source_start), ""],
      [moment(row.source_finish), ""],
      [row.span_start ? moment(row.span_start) : "nothing placed beneath it", ""],
      [moment(row.span_finish), ""],
      [String(row.placed ?? 0), "num"],
    ]) {
      const td = document.createElement("td");
      td.textContent = text;
      if (kind) td.className = kind;
      if (kind === "name" && text) td.title = text;
      tr.append(td);
    }
    summaryBody.append(tr);
  }
  summariesSection.hidden = false;
}

// The project a render belongs to. The selector stays usable while a request
// is in flight, and two requests can finish out of order, so a response is
// dropped unless it is still the one being waited for -- otherwise the page
// shows one project's schedule under another project's name.
let awaiting = null;

async function show(projectId) {
  provenanceSection.hidden = true;
  rowsSection.hidden = true;
  summariesSection.hidden = true;
  chartSection.hidden = true;
  awaiting = projectId;
  if (!projectId) return;
  try {
    const result = await json(`/api/projects/${projectId}/calculations/latest`);
    if (awaiting !== projectId) return;
    render(result);
    say("");
  } catch (error) {
    if (awaiting !== projectId) return;
    if (error.status === 404) {
      say("No calculation stored for this project yet.");
    } else {
      say("The stored calculation could not be served: " + error.message, "error");
    }
  }
}

calculate.addEventListener("click", async () => {
  const projectId = projects.value;
  if (!projectId) return;
  calculate.disabled = true;
  say("Calculating…");
  try {
    await json(`/api/projects/${projectId}/calculations`, { method: "POST" });
    await show(projectId);
  } catch (error) {
    say(error.message, "error");
  } finally {
    calculate.disabled = false;
  }
});

projects.addEventListener("change", () => show(projects.value));

(async function start() {
  try {
    const rows = await json("/api/projects");
    projects.replaceChildren();
    if (rows.length === 0) {
      projects.append(new Option("no projects yet", ""));
      say("Import a schedule first.");
      return;
    }
    for (const project of rows) projects.append(new Option(project.name, project.id));
    await show(projects.value);
  } catch (error) {
    say(error.message, "error");
  }
})();
