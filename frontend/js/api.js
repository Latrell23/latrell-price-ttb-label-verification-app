import { API_BASE_URL } from "./constants.js";

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
export function postSingleVerification(formData) {
  return fetch(`${API_BASE_URL}/verify`, {
    method: "POST",
    body: formData,
    headers: { Accept: "application/json" },
  });
}

// Sends a streaming batch verification request.
export function postBatchVerification(formData) {
  return fetch(`${API_BASE_URL}/verify/batch/stream`, {
    method: "POST",
    body: formData,
    headers: { Accept: "application/x-ndjson" },
  });
}

// Reads newline-delimited batch stream events into the final batch response shape.
export async function readBatchStream(response, orderedClientIds, callbacks = {}) {
  if (!response.body) {
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
  function handleLine(line) {
    if (!line.trim()) {
      return;
    }

    const event = JSON.parse(line);
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
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      handleLine(buffer.slice(0, newlineIndex));
      buffer = buffer.slice(newlineIndex + 1);
      newlineIndex = buffer.indexOf("\n");
    }

    if (done) {
      if (buffer.trim()) {
        handleLine(buffer);
      }
      break;
    }
  }

  if (!summary) {
    throw new Error("Batch stream ended before completion.");
  }

  items.sort((left, right) => {
    return (order.get(left.client_id) || 0) - (order.get(right.client_id) || 0);
  });

  return {
    items,
    summary,
    latency_ms: latencyMs,
  };
}
