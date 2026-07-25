import { API_BASE_URL, FRONTEND_TIMEOUT_MS } from "./constants.js";

export class FrontendTimeoutError extends Error {
  constructor(message = "The verification service timed out.") {
    super(message);
    this.name = "FrontendTimeoutError";
    this.code = "request_timeout";
  }
}

export function isTimeoutError(error) {
  return error instanceof FrontendTimeoutError || error?.code === "request_timeout";
}

function createRequestTimeout(timeoutMs = FRONTEND_TIMEOUT_MS) {
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

// Sends a single-label verification request.
export async function postSingleVerification(formData) {
  const timeout = createRequestTimeout();

  try {
    return await fetch(`${API_BASE_URL}/verify`, {
      method: "POST",
      body: formData,
      headers: { Accept: "application/json" },
      signal: timeout.signal,
    });
  } catch (error) {
    timeout.handleError(error);
  } finally {
    timeout.clear();
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
  const timeout = createRequestTimeout();

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
  const timeout = createRequestTimeout();

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

// Sends a streaming batch verification request.
export async function postBatchVerification(formData) {
  const timeout = createRequestTimeout();

  try {
    const response = await fetch(`${API_BASE_URL}/verify/batch/stream`, {
      method: "POST",
      body: formData,
      headers: { Accept: "application/x-ndjson" },
      signal: timeout.signal,
    });
    return { response, timeout };
  } catch (error) {
    timeout.clear();
    timeout.handleError(error);
  }
}

// Reads newline-delimited batch stream events into the final batch response shape.
export async function readBatchStream(response, orderedClientIds, callbacks = {}) {
  const timeout = callbacks.timeout || null;

  if (!response.body) {
    if (timeout) {
      timeout.clear();
    }
    throw new Error("Streaming response is not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let summary = null;
  let latencyMs = 0;
  const items = [];
  const order = new Map(orderedClientIds.map((clientId, index) => [clientId, index]));

  // Handles one complete newline-delimited stream event.
  function buildResult() {
    items.sort((left, right) => {
      return (order.get(left.client_id) || 0) - (order.get(right.client_id) || 0);
    });

    return {
      items,
      summary,
      latency_ms: latencyMs,
    };
  }

  function handleLine(line) {
    if (!line.trim()) {
      return null;
    }

    const event = JSON.parse(line);
    if (timeout) {
      timeout.reset();
    }

    if (event.type === "item") {
      items.push(event.item);
      if (callbacks.onItem) {
        callbacks.onItem(event);
      }
    } else if (event.type === "complete") {
      summary = event.summary;
      latencyMs = event.latency_ms;
      if (callbacks.onComplete) {
        callbacks.onComplete(event);
      }
    }

    return event.type;
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex >= 0) {
        const eventType = handleLine(buffer.slice(0, newlineIndex));
        buffer = buffer.slice(newlineIndex + 1);
        if (eventType === "complete") {
          if (timeout) {
            timeout.clear();
          }
          reader.cancel().catch(() => {});
          return buildResult();
        }
        newlineIndex = buffer.indexOf("\n");
      }

      if (done) {
        if (buffer.trim()) {
          const eventType = handleLine(buffer);
          if (eventType === "complete") {
            if (timeout) {
              timeout.clear();
            }
            return buildResult();
          }
        }
        break;
      }
    }

    if (!summary) {
      throw new Error("Batch stream ended before completion.");
    }

    return buildResult();
  } catch (error) {
    if (timeout) {
      timeout.handleError(error);
    }
    throw error;
  } finally {
    if (timeout) {
      timeout.clear();
    }
  }
}
