import { API_BASE_URL, ERROR_MESSAGES, FIELDS } from "./constants.js";
import {
  getReviewLabels,
  isTimeoutError,
  parseResponseBody,
  postReviewLabelVerification,
  postReviewQueueVerification,
} from "./api.js";
import { createFieldResultRow, failedFieldCount, formatVerdict } from "./rendering.js";


const REVIEW_DECISIONS = {
  accepted: "Accepted",
  flagged: "Flagged",
};


// Boots the reviewer queue and wires reviewer actions.
export function initializeReviewApp() {
  const elements = getReviewElements();
  const state = {
    labels: [],
    results: new Map(),
    decisions: new Map(),
    submittedIds: new Set(),
    loadingIds: new Set(),
    loadingAll: false,
  };

  elements.runAllButton.addEventListener("click", () => runAllReviews(elements, state));
  loadReviewQueue(elements, state);
}


function getReviewElements() {
  return {
    queueStatus: document.querySelector("#review-queue-status"),
    queueSummary: document.querySelector("#review-summary"),
    queueError: document.querySelector("#review-error"),
    reviewList: document.querySelector("#review-list"),
    runAllButton: document.querySelector("#run-all-reviews"),
  };
}


async function loadReviewQueue(elements, state) {
  setQueueStatus(elements, "Loading review queue...");
  clearError(elements);
  elements.runAllButton.disabled = true;

  try {
    const response = await getReviewLabels();
    const body = await parseResponseBody(response);
    if (!response.ok) {
      showError(elements, messageForErrorBody(body, "The review queue could not be loaded."));
      return;
    }

    state.labels = body.items || [];
    renderReviewQueue(elements, state);
  } catch (_error) {
    showError(elements, "Could not reach the review service. Please check the connection and try again.");
  } finally {
    elements.runAllButton.disabled = state.labels.length === 0;
    setQueueStatus(elements, "");
  }
}


async function runSingleReview(elements, state, labelId) {
  state.loadingIds.add(labelId);
  renderReviewQueue(elements, state);
  clearError(elements);

  try {
    const response = await postReviewLabelVerification(labelId);
    const body = await parseResponseBody(response);
    if (!response.ok) {
      showError(elements, messageForErrorBody(body, "This label could not be reviewed."));
      return;
    }

    state.results.set(labelId, body);
    state.decisions.delete(labelId);
    state.submittedIds.delete(labelId);
  } catch (error) {
    showError(
      elements,
      isTimeoutError(error)
        ? ERROR_MESSAGES.request_timeout
        : "Could not reach the review service. Please try again."
    );
  } finally {
    state.loadingIds.delete(labelId);
    renderReviewQueue(elements, state);
  }
}


async function runAllReviews(elements, state) {
  state.loadingAll = true;
  state.loadingIds = new Set(state.labels.map((label) => label.id));
  elements.runAllButton.disabled = true;
  setQueueStatus(elements, "Running AI review across the queue...");
  clearError(elements);
  renderReviewQueue(elements, state);

  try {
    const response = await postReviewQueueVerification();
    const body = await parseResponseBody(response);
    if (!response.ok) {
      showError(elements, messageForErrorBody(body, "The review queue could not be checked."));
      return;
    }

    (body.items || []).forEach((item) => {
      state.results.set(item.client_id, item);
      state.decisions.delete(item.client_id);
      state.submittedIds.delete(item.client_id);
    });
  } catch (error) {
    showError(
      elements,
      isTimeoutError(error)
        ? ERROR_MESSAGES.request_timeout
        : "Could not reach the review service. Please try again."
    );
  } finally {
    state.loadingAll = false;
    state.loadingIds.clear();
    elements.runAllButton.disabled = state.labels.length === 0;
    setQueueStatus(elements, "");
    renderReviewQueue(elements, state);
  }
}


function renderReviewQueue(elements, state) {
  renderReviewSummary(elements, state);
  elements.reviewList.innerHTML = "";

  state.labels.forEach((label) => {
    elements.reviewList.append(createReviewCard(label, state, elements));
  });
}


function renderReviewSummary(elements, state) {
  const reviewed = Array.from(state.results.values()).filter(
    (item) => item.status === "completed"
  );
  const approved = reviewed.filter(
    (item) => item.result && item.result.overall_verdict === "APPROVED"
  ).length;
  const needsReview = reviewed.length - approved;
  const accepted = Array.from(state.decisions.values()).filter(
    (decision) => decision === "accepted"
  ).length;
  const flagged = Array.from(state.decisions.values()).filter(
    (decision) => decision === "flagged"
  ).length;
  const submitted = state.submittedIds.size;

  elements.queueSummary.innerHTML = "";
  [
    ["Labels", state.labels.length],
    ["AI reviewed", reviewed.length],
    ["Approved", approved],
    ["Needs review", needsReview],
    ["Accepted", accepted],
    ["Flagged", flagged],
    ["Submitted", submitted],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "review-stat";
    item.innerHTML = `<span></span><strong></strong>`;
    item.querySelector("span").textContent = label;
    item.querySelector("strong").textContent = value;
    elements.queueSummary.append(item);
  });
}


function createReviewCard(label, state, elements) {
  const item = state.results.get(label.id);
  const decision = state.decisions.get(label.id);
  const submitted = state.submittedIds.has(label.id);
  const loading = state.loadingIds.has(label.id);
  const completed = item && item.status === "completed" && item.result;
  const approved = completed && item.result.overall_verdict === "APPROVED";

  const card = document.createElement("article");
  card.className = `review-card ${completed && approved ? "pass" : ""} ${
    completed && !approved ? "fail" : ""
  }`;

  const imageUrl = label.image_url.startsWith("http")
    ? label.image_url
    : `${API_BASE_URL}${label.image_url}`;
  const header = document.createElement("div");
  header.className = "review-card-header";
  header.innerHTML = `
    <img class="review-thumbnail" alt="" />
    <div class="review-title-block">
      <h2></h2>
      <p></p>
    </div>
    <span class="result-status"></span>
  `;
  header.querySelector("img").src = imageUrl;
  header.querySelector("img").alt = `${label.title} label`;
  header.querySelector("h2").textContent = label.title;
  header.querySelector("p").textContent = `${label.expected.class_type} | ${label.expected.abv} | ${label.expected.net_contents}`;
  const status = header.querySelector(".result-status");
  status.classList.add(approved ? "pass" : "fail");
  status.textContent = statusText(item, loading, decision, submitted);
  card.append(header);

  const expected = document.createElement("dl");
  expected.className = "expected-grid";
  FIELDS.forEach((field) => {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `<dt></dt><dd></dd>`;
    wrapper.querySelector("dt").textContent = field.label;
    wrapper.querySelector("dd").textContent = label.expected[field.name] || "";
    expected.append(wrapper);
  });
  card.append(expected);

  if (item) {
    card.append(createReviewResult(item));
  }

  const actions = document.createElement("div");
  actions.className = "review-actions";
  actions.append(
    actionButton(
      loading ? "Reviewing..." : item ? "Run AI Review Again" : "Run AI Review",
      () => runSingleReview(elements, state, label.id),
      loading || state.loadingAll
    ),
    actionButton(
      "Accept",
      () => setDecision(elements, state, label.id, "accepted"),
      !completed,
      decision === "accepted"
    ),
    actionButton(
      "Flag",
      () => setDecision(elements, state, label.id, "flagged"),
      !completed,
      decision === "flagged"
    ),
    actionButton(
      submitted ? "Review Submitted" : "Submit Review",
      () => submitReview(elements, state, label.id),
      !decision || submitted
    )
  );
  card.append(actions);

  if (submitted) {
    const submittedNote = document.createElement("p");
    submittedNote.className = "review-submitted-note";
    submittedNote.textContent = `Prototype review submitted as ${REVIEW_DECISIONS[decision].toLowerCase()}.`;
    card.append(submittedNote);
  }

  return card;
}


function createReviewResult(item) {
  const section = document.createElement("section");
  section.className = "review-result";

  if (item.status !== "completed" || !item.result) {
    section.textContent =
      (item.error && item.error.message) || "This label could not be checked.";
    return section;
  }

  const summary = document.createElement("p");
  summary.className = "batch-card-summary";
  const failedCount = failedFieldCount(item.result);
  summary.textContent =
    failedCount === 0
      ? "AI found that the JSON matches the image."
      : `${failedCount} JSON field(s) need reviewer attention.`;
  section.append(summary);

  const details = document.createElement("div");
  details.className = "batch-drilldown";
  item.result.results.forEach((fieldResult) => {
    details.append(
      createFieldResultRow(fieldResult, {
        expected: "Application Value",
        found: "Image value",
      })
    );
  });
  section.append(details);
  return section;
}


function actionButton(label, onClick, disabled = false, selected = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = selected ? "secondary-button compact selected" : "secondary-button compact";
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}


function setDecision(elements, state, labelId, decision) {
  state.decisions.set(labelId, decision);
  state.submittedIds.delete(labelId);
  renderReviewQueue(elements, state);
}


function submitReview(elements, state, labelId) {
  if (!state.decisions.has(labelId)) {
    return;
  }
  state.submittedIds.add(labelId);
  renderReviewQueue(elements, state);
}


function statusText(item, loading, decision, submitted) {
  if (loading) {
    return "REVIEWING";
  }
  if (submitted) {
    return "SUBMITTED";
  }
  if (decision) {
    return REVIEW_DECISIONS[decision];
  }
  if (!item) {
    return "NOT REVIEWED";
  }
  if (item.status !== "completed" || !item.result) {
    return "ERROR";
  }
  return formatVerdict(item.result.overall_verdict);
}


function setQueueStatus(elements, message) {
  elements.queueStatus.textContent = message;
  elements.queueStatus.hidden = !message;
}


function clearError(elements) {
  elements.queueError.hidden = true;
  elements.queueError.textContent = "";
}


function showError(elements, message) {
  elements.queueError.textContent = message;
  elements.queueError.hidden = false;
  elements.queueError.scrollIntoView({ block: "nearest", behavior: "smooth" });
}


function messageForErrorBody(body, fallback) {
  const code = body && body.error ? body.error.code : "";
  return ERROR_MESSAGES[code] || (body && body.error && body.error.message) || fallback;
}
