import { API_BASE_URL, REVIEW_TIMEOUT_MS } from "./constants.js";

export class FrontendTimeoutError extends Error {
  constructor(message = "The AI review service timed out.") {
    super(message);
    this.name = "FrontendTimeoutError";
    this.code = "request_timeout";
  }
}

export function isTimeoutError(error) {
  return error instanceof FrontendTimeoutError || error?.code === "request_timeout";
}

function createRequestTimeout(timeoutMs = REVIEW_TIMEOUT_MS) {
  const controller = new AbortController();
  let timeoutId = null;
  let timedOut = false;

  function clear() {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
      timeoutId = null;
    }
  }

  function reset() {
    clear();
    timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }

  function handleError(error) {
    if (timedOut || error?.name === "AbortError") {
      throw new FrontendTimeoutError();
    }
    throw error;
  }

  reset();

  return {
    signal: controller.signal,
    reset,
    clear,
    handleError,
    get timedOut() {
      return timedOut;
    },
  };
}

// Safely parses JSON responses when the server sends JSON.
export async function parseResponseBody(response) {
  const contentType = response.headers.get("content-type") || "";

  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

// Loads the backend-owned simulated review queue.
export async function getReviewLabels() {
  const response = await fetch(`${API_BASE_URL}/review/labels`, {
    headers: { Accept: "application/json" },
  });
  return response;
}

// Verifies one backend-owned review label.
export async function postReviewLabelVerification(labelId) {
  const timeout = createRequestTimeout(REVIEW_TIMEOUT_MS);

  try {
    return await fetch(
      `${API_BASE_URL}/review/labels/${encodeURIComponent(labelId)}/verify`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
        signal: timeout.signal,
      }
    );
  } catch (error) {
    timeout.handleError(error);
  } finally {
    timeout.clear();
  }
}

// Verifies every backend-owned review label in the queue.
export async function postReviewQueueVerification() {
  const timeout = createRequestTimeout(REVIEW_TIMEOUT_MS);

  try {
    return await fetch(`${API_BASE_URL}/review/verify`, {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: timeout.signal,
    });
  } catch (error) {
    timeout.handleError(error);
  } finally {
    timeout.clear();
  }
}
