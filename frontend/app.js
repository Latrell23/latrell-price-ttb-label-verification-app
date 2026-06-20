(function () {
  const config = window.APP_CONFIG || {};
  const apiBaseUrl = (config.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

  const statusDot = document.querySelector("#status-dot");
  const statusLabel = document.querySelector("#status-label");
  const output = document.querySelector("#health-output");
  const retryButton = document.querySelector("#retry-button");

  function setState(state, label, body) {
    statusDot.className = `dot ${state}`;
    statusLabel.textContent = label;
    output.textContent = body;
  }

  async function checkHealth() {
    setState("pending", "Checking API health...", "Waiting for response...");

    try {
      const response = await fetch(`${apiBaseUrl}/health`, {
        headers: { Accept: "application/json" },
      });

      const body = await response.json();

      if (!response.ok) {
        setState("error", `API returned ${response.status}`, JSON.stringify(body, null, 2));
        return;
      }

      setState("ok", "API health response received", JSON.stringify(body, null, 2));
    } catch (error) {
      setState(
        "error",
        "Could not reach API",
        `${error.message}\n\nConfigured API_BASE_URL: ${apiBaseUrl}`
      );
    }
  }

  retryButton.addEventListener("click", checkHealth);
  checkHealth();
})();
