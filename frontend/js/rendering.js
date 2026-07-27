import { FIELDS } from "./constants.js";

// Converts API verdict codes into user-facing text.
export function formatVerdict(verdict) {
  return verdict === "APPROVED" ? "APPROVED" : "NEEDS REVIEW";
}

// Builds one field comparison row for a reviewer result.
export function createFieldResultRow(
  result,
  labels = { expected: "Expected", found: "Found" }
) {
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
      <p><strong></strong> <span></span></p>
      <p><strong></strong> <span></span></p>
    `;
    details.querySelector("p:first-child strong").textContent = `${labels.expected}:`;
    details.querySelector("p:last-child strong").textContent = `${labels.found}:`;
    details.querySelector("p:first-child span").textContent = result.expected || "";
    details.querySelector("p:last-child span").textContent =
      result.found === null || result.found === undefined || result.found === ""
        ? "Not found on label"
        : result.found;
    row.append(details);

    if (result.field === "government_warning") {
      row.append(createGovernmentWarningDiff(result, labels));
    }
  }

  return row;
}

// Builds a strict warning-statement helper with word-level differences.
export function createGovernmentWarningDiff(result, labels = { expected: "Application Value", found: "Image value" }) {
  const section = document.createElement("section");
  section.className = "warning-diff";

  const note = document.createElement("p");
  note.className = "warning-diff-note";
  note.textContent =
    "Strict warning statement check failed. Review highlighted differences against the label image before rejecting.";
  section.append(note);

  const grid = document.createElement("div");
  grid.className = "warning-diff-grid";
  grid.append(
    createDiffBlock(labels.expected, result.expected || "", result.found || ""),
    createDiffBlock(labels.found, result.found || "", result.expected || "")
  );
  section.append(grid);
  return section;
}


function createDiffBlock(title, value, comparisonValue) {
  const block = document.createElement("article");
  block.className = "warning-diff-block";
  const heading = document.createElement("h4");
  heading.textContent = title;
  const text = document.createElement("p");
  appendHighlightedWords(text, value, comparisonValue);
  block.append(heading, text);
  return block;
}


function appendHighlightedWords(container, value, comparisonValue) {
  const words = tokenizeWords(value);
  const differingIndexes = unmatchedWordIndexes(words, tokenizeWords(comparisonValue));

  if (!words.length) {
    container.textContent = "Not found on label";
    return;
  }

  words.forEach((word, index) => {
    const span = document.createElement("span");
    span.textContent = word;
    if (differingIndexes.has(index)) {
      span.className = "warning-diff-highlight";
    }
    container.append(span);
    if (index < words.length - 1) {
      container.append(document.createTextNode(" "));
    }
  });
}


function tokenizeWords(value) {
  return String(value || "").trim().split(/\s+/).filter(Boolean);
}


function unmatchedWordIndexes(words, comparisonWords) {
  const left = words.map(normalizeDiffWord);
  const right = comparisonWords.map(normalizeDiffWord);
  const longestMatches = Array.from({ length: left.length + 1 }, () =>
    Array(right.length + 1).fill(0)
  );

  for (let leftIndex = left.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = right.length - 1; rightIndex >= 0; rightIndex -= 1) {
      longestMatches[leftIndex][rightIndex] =
        left[leftIndex] === right[rightIndex]
          ? longestMatches[leftIndex + 1][rightIndex + 1] + 1
          : Math.max(
              longestMatches[leftIndex + 1][rightIndex],
              longestMatches[leftIndex][rightIndex + 1]
            );
    }
  }

  const unmatched = new Set();
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex] === right[rightIndex]) {
      leftIndex += 1;
      rightIndex += 1;
    } else if (
      longestMatches[leftIndex + 1][rightIndex] >=
      longestMatches[leftIndex][rightIndex + 1]
    ) {
      unmatched.add(leftIndex);
      leftIndex += 1;
    } else {
      rightIndex += 1;
    }
  }

  while (leftIndex < left.length) {
    unmatched.add(leftIndex);
    leftIndex += 1;
  }

  return unmatched;
}


function normalizeDiffWord(word) {
  return word.replace(/[.,;:()]/g, "").toLowerCase();
}

// Formats a 0.0 to 1.0 backend confidence score for reviewers.
export function formatConfidence(score) {
  return confidenceLabel(score);
}

// Converts confidence scores into compact reviewer-facing bands.
export function confidenceLabel(score) {
  if (score >= 0.8) {
    return "High";
  }
  if (score >= 0.5) {
    return "Medium";
  }
  return "Low";
}

// Counts failed fields for a compact review summary.
export function failedFieldCount(result) {
  return result.results.filter((fieldResult) => fieldResult.status === "FAIL").length;
}
