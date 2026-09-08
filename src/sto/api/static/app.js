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
    throw new Error(detail);
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
    ["Engine", Object.entries(result.profiles).map(([k, v]) => k + " " + v).join(", ")],
    ["Activities", counts.activities + " (" + counts.scheduled + " scheduled)"],
    ["Summaries", String(counts.summaries)],
    ["Agreeing with the file", counts.agreeing_with_source + " of " + counts.compared_with_source],
  ];
  for (const [term, value] of facts) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    provenance.append(dt, dd);
  }
  provenanceSection.hidden = false;
}

function render(result) {
  describe(result);
  body.replaceChildren();
  for (const row of result.activities) {
    const tr = document.createElement("tr");
    tr.dataset.disposition = row.disposition;
    const cells = [
      [row.code ?? "", ""],
      [row.name ?? "", ""],
      [moment(row.source_start), ""],
      [moment(row.source_finish), ""],
      [row.disposition === "excluded" ? row.exclusion_code : moment(row.early_start), ""],
      [moment(row.early_finish), ""],
      [hours(row.total_float_seconds), "num"],
      [row.critical === null ? "" : row.critical ? "yes" : "no", ""],
      [row.agrees_with_source === null ? "" : row.agrees_with_source ? "yes" : "no", "agrees"],
    ];
    for (const [text, kind] of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      if (kind === "num") td.className = "num";
      if (kind === "agrees" && row.agrees_with_source !== null) {
        td.dataset.agrees = String(row.agrees_with_source);
      }
      tr.append(td);
    }
    body.append(tr);
  }
  rowsSection.hidden = false;
}

async function show(projectId) {
  provenanceSection.hidden = true;
  rowsSection.hidden = true;
  if (!projectId) return;
  try {
    render(await json(`/api/projects/${projectId}/calculations/latest`));
    say("");
  } catch (error) {
    say("No calculation stored for this project yet. " + error.message);
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
