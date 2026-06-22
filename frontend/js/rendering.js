import { FIELDS } from "./constants.js";

// Converts API verdict codes into user-facing text.
export function formatVerdict(verdict) {
  return verdict === "APPROVED" ? "APPROVED" : "NEEDS REVIEW";
}

// Builds one field comparison row for single and batch results.
export function createFieldResultRow(result) {
  const field = FIELDS.find((item) => item.name === result.field);
  const row = document.createElement("article");
  const statusPass = result.status === "PASS";
  row.className = `result-row ${statusPass ? "pass" : "fail"}`;

  const header = document.createElement("div");
  header.className = "result-row-header";

  const label = document.createElement("h3");
  label.textContent = field ? field.label : result.field;

  const status = document.createElement("span");
  status.className = `result-status ${statusPass ? "pass" : "fail"}`;
  status.textContent = statusPass ? "PASS - Matches" : "FAIL - Check this field";

  header.append(label, status);
  row.append(header);

  if (!statusPass) {
    const details = document.createElement("div");
    details.className = "result-details";
    details.innerHTML = `
      <p><strong>Expected:</strong> <span></span></p>
      <p><strong>Found:</strong> <span></span></p>
    `;
    details.querySelector("p:first-child span").textContent = result.expected || "";
    details.querySelector("p:last-child span").textContent =
      result.found === null || result.found === undefined || result.found === ""
        ? "Not found on label"
        : result.found;
    row.append(details);
  }

  return row;
}

// Renders the full single-label verification result.
export function renderResults(elements, data) {
  const approved = data.overall_verdict === "APPROVED";
  elements.resultsHeading.textContent = formatVerdict(data.overall_verdict);
  elements.verdictBanner.className = `verdict-banner ${approved ? "approved" : "needs-review"}`;
  elements.resultList.innerHTML = "";

  data.results.forEach((result) => {
    elements.resultList.append(createFieldResultRow(result));
  });

  elements.resetButton.textContent = "Check Another Label";
  elements.resultsView.hidden = false;
  elements.resultsView.scrollIntoView({ block: "start", behavior: "smooth" });
}

// Counts failed fields for a compact batch card summary.
export function failedFieldCount(result) {
  return result.results.filter((fieldResult) => fieldResult.status === "FAIL").length;
}

// Builds one batch result card with optional field-level drilldown.
export function createBatchResultCard(item, index) {
  const completed = item.status === "completed" && item.result;
  const approved = completed && item.result.overall_verdict === "APPROVED";
  const card = document.createElement("article");
  card.className = `batch-result-card ${approved ? "pass" : "fail"}`;

  const header = document.createElement("div");
  header.className = "batch-result-header";

  const titleWrap = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = `Label ${index + 1}`;
  const fileName = document.createElement("p");
  fileName.className = "selected-file-name";
  fileName.textContent = item.file_name || "No file name";
  titleWrap.append(title, fileName);

  const status = document.createElement("span");
  status.className = `result-status ${approved ? "pass" : "fail"}`;
  status.textContent = completed ? formatVerdict(item.result.overall_verdict) : "ERROR";

  header.append(titleWrap, status);
  card.append(header);

  const summaryLine = document.createElement("p");
  summaryLine.className = "batch-card-summary";
  if (completed) {
    const failedCount = failedFieldCount(item.result);
    summaryLine.textContent =
      failedCount === 0 ? "All fields match." : `${failedCount} field(s) need review.`;
  } else {
    summaryLine.textContent =
      (item.error && item.error.message) || "This label could not be checked.";
  }
  card.append(summaryLine);

  const details = document.createElement("div");
  details.className = "batch-drilldown";
  details.hidden = true;

  if (completed) {
    item.result.results.forEach((fieldResult) => {
      details.append(createFieldResultRow(fieldResult));
    });
  } else if (item.error) {
    const errorDetails = document.createElement("div");
    errorDetails.className = "result-details";
    const detailText = item.error.details && item.error.details.length
      ? item.error.details.map((detail) => detail.message).join(" ")
      : item.error.message;
    errorDetails.textContent = detailText;
    details.append(errorDetails);
  }

  const toggle = document.createElement("button");
  toggle.className = "secondary-button compact";
  toggle.type = "button";
  toggle.textContent = "Show Details";
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    details.hidden = !details.hidden;
    toggle.textContent = details.hidden ? "Show Details" : "Hide Details";
    toggle.setAttribute("aria-expanded", String(!details.hidden));
  });

  card.append(toggle, details);
  return card;
}

// Renders the full batch verification summary and item cards.
export function renderBatchResults(elements, data) {
  const summary = data.summary;
  elements.resultsHeading.textContent =
    `${summary.passed} passed / ${summary.needs_review} need review / ${summary.total} total`;
  elements.verdictBanner.className = "verdict-banner batch-summary";
  elements.resultList.innerHTML = "";

  data.items.forEach((item, index) => {
    elements.resultList.append(createBatchResultCard(item, index));
  });

  elements.resetButton.textContent = "Check Another Batch";
  elements.resultsView.hidden = false;
  elements.resultsView.scrollIntoView({ block: "start", behavior: "smooth" });
}
