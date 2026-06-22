(function () {
  const config = window.APP_CONFIG || {};
  const apiBaseUrl = (config.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
  const maxBatchRows = 5;

  const fields = [
    { name: "brand_name", label: "Brand Name", type: "input" },
    { name: "class_type", label: "Class / Type", type: "input" },
    { name: "abv", label: "Alcohol By Volume", type: "input" },
    { name: "net_contents", label: "Net Contents", type: "input" },
    { name: "producer", label: "Producer", type: "input" },
    { name: "country_of_origin", label: "Country of Origin", type: "input" },
    { name: "government_warning", label: "Government Warning", type: "textarea" },
  ];

  const errorMessages = {
    missing_image: "Choose one label image.",
    missing_items: "Add at least one label.",
    malformed_items: "The batch could not be prepared. Please try again.",
    empty_batch: "Add at least one label.",
    too_many_items: "Verify no more than 5 labels at once.",
    duplicate_client_id: "The batch could not be prepared. Please try again.",
    duplicate_image_field: "The batch could not be prepared. Please try again.",
    missing_upload_fields: "Choose an image for each label.",
    missing_required_fields: "Complete the highlighted fields.",
    blank_required_fields: "Complete the highlighted fields.",
    unsupported_media_type: "Please choose a JPG, PNG, or WebP image.",
    file_too_large: "Please choose an image that is 10 MB or smaller.",
    empty_file: "The selected file could not be read as an image.",
    invalid_image: "The selected file could not be read as an image.",
    vision_extraction_failed: "The label could not be checked right now. Please try again.",
    vision_result_unreadable: "The label could not be checked right now. Please try again.",
    vision_not_configured: "The label could not be checked right now. Please try again.",
    internal_error: "The label could not be checked right now. Please try again.",
  };

  const singleTab = document.querySelector("#single-tab");
  const batchTab = document.querySelector("#batch-tab");
  const form = document.querySelector("#verification-form");
  const batchForm = document.querySelector("#batch-form");
  const imageInput = document.querySelector("#image");
  const formError = document.querySelector("#form-error");
  const previewWrap = document.querySelector("#image-preview-wrap");
  const selectedFileName = document.querySelector("#selected-file-name");
  const imagePreview = document.querySelector("#image-preview");
  const loadingMessage = document.querySelector("#loading-message");
  const verifyButton = document.querySelector("#verify-button");
  const batchRowsContainer = document.querySelector("#batch-rows");
  const batchFormError = document.querySelector("#batch-form-error");
  const addBatchRowButton = document.querySelector("#add-batch-row");
  const batchLoadingMessage = document.querySelector("#batch-loading-message");
  const batchSubmitButton = document.querySelector("#batch-submit-button");
  const resultsView = document.querySelector("#results-view");
  const verdictBanner = document.querySelector("#verdict-banner");
  const resultsHeading = document.querySelector("#results-heading");
  const resultList = document.querySelector("#result-list");
  const resetButton = document.querySelector("#reset-button");
  const singleControls = Array.from(form.querySelectorAll("input, textarea, button"));

  let previewUrl = "";
  let rowCounter = 0;
  let batchRows = [];
  let batchProgressTimer = null;

  function fieldElement(name) {
    return document.querySelector(`#${name}`);
  }

  function errorElement(name) {
    return document.querySelector(`#${name}-error`);
  }

  function hasImage() {
    return imageInput.files && imageInput.files.length > 0;
  }

  function refreshSubmitState() {
    verifyButton.disabled = false;
  }

  function clearFieldError(name) {
    const element = fieldElement(name);
    const error = errorElement(name);

    element.classList.remove("invalid");
    element.removeAttribute("aria-invalid");
    element.removeAttribute("aria-describedby");

    if (error) {
      error.hidden = true;
      error.textContent = "";
    }
  }

  function clearErrors() {
    formError.hidden = true;
    formError.textContent = "";
    clearFieldError("image");
    fields.forEach((field) => clearFieldError(field.name));
  }

  function showFormError(message) {
    formError.textContent = message;
    formError.hidden = false;
    formError.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function showFieldError(name, message) {
    const element = fieldElement(name);
    const error = errorElement(name);

    if (!element || !error) {
      return;
    }

    element.classList.add("invalid");
    element.setAttribute("aria-invalid", "true");
    element.setAttribute("aria-describedby", error.id);
    error.textContent = message;
    error.hidden = false;
  }

  function validateRequiredInputs() {
    let isValid = true;

    if (!hasImage()) {
      showFieldError("image", "Choose one label image.");
      isValid = false;
    }

    fields.forEach((field) => {
      if (fieldElement(field.name).value.trim() === "") {
        showFieldError(field.name, "Complete this field.");
        isValid = false;
      }
    });

    return isValid;
  }

  function setLoading(isLoading) {
    singleControls.forEach((control) => {
      control.disabled = isLoading;
    });
    loadingMessage.hidden = !isLoading;
    verifyButton.textContent = isLoading ? "Checking Label..." : "Verify Label";

    if (!isLoading) {
      refreshSubmitState();
    }
  }

  function updateImagePreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }

    if (!hasImage()) {
      previewWrap.hidden = true;
      selectedFileName.textContent = "";
      imagePreview.removeAttribute("src");
      refreshSubmitState();
      return;
    }

    const file = imageInput.files[0];
    previewUrl = URL.createObjectURL(file);
    selectedFileName.textContent = file.name;
    imagePreview.src = previewUrl;
    previewWrap.hidden = false;
    clearFieldError("image");
    refreshSubmitState();
  }

  function formatVerdict(verdict) {
    return verdict === "APPROVED" ? "APPROVED" : "NEEDS REVIEW";
  }

  function createFieldResultRow(result) {
    const field = fields.find((item) => item.name === result.field);
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

  function renderResults(data) {
    const approved = data.overall_verdict === "APPROVED";
    resultsHeading.textContent = formatVerdict(data.overall_verdict);
    verdictBanner.className = `verdict-banner ${approved ? "approved" : "needs-review"}`;
    resultList.innerHTML = "";

    data.results.forEach((result) => {
      resultList.append(createFieldResultRow(result));
    });

    resetButton.textContent = "Check Another Label";
    resultsView.hidden = false;
    resultsView.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function failedFieldCount(result) {
    return result.results.filter((fieldResult) => fieldResult.status === "FAIL").length;
  }

  function renderBatchResults(data) {
    const summary = data.summary;
    resultsHeading.textContent =
      `${summary.passed} passed / ${summary.needs_review} need review / ${summary.total} total`;
    verdictBanner.className = "verdict-banner batch-summary";
    resultList.innerHTML = "";

    data.items.forEach((item, index) => {
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
      toggle.addEventListener("click", () => {
        details.hidden = !details.hidden;
        toggle.textContent = details.hidden ? "Show Details" : "Hide Details";
      });

      card.append(toggle, details);
      resultList.append(card);
    });

    resetButton.textContent = "Check Another Batch";
    resultsView.hidden = false;
    resultsView.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function applyServerError(body) {
    const error = body && body.error ? body.error : {};
    const code = error.code || "internal_error";
    const message = errorMessages[code] || "The label could not be checked right now. Please try again.";

    showFormError(message);

    if (Array.isArray(error.details)) {
      error.details.forEach((detail) => {
        const field = detail.field;
        if (field === "image") {
          showFieldError("image", message);
        } else if (fields.some((item) => item.name === field)) {
          showFieldError(field, detail.message || "Complete this field.");
        }
      });
    }
  }

  async function parseResponseBody(response) {
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

  function buildFormData() {
    const formData = new FormData();
    formData.append("image", imageInput.files[0]);
    fields.forEach((field) => {
      formData.append(field.name, fieldElement(field.name).value.trim());
    });
    return formData;
  }

  async function submitVerification(event) {
    event.preventDefault();
    clearErrors();
    resultsView.hidden = true;
    resultList.innerHTML = "";

    if (!validateRequiredInputs()) {
      showFormError("Complete the highlighted fields.");
      refreshSubmitState();
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${apiBaseUrl}/verify`, {
        method: "POST",
        body: buildFormData(),
        headers: { Accept: "application/json" },
      });
      const body = await parseResponseBody(response);

      if (!response.ok) {
        applyServerError(body);
        return;
      }

      renderResults(body);
    } catch (_error) {
      showFormError(
        "Could not reach the verification service. Please check the connection and try again."
      );
    } finally {
      setLoading(false);
    }
  }

  function batchControls() {
    return Array.from(batchForm.querySelectorAll("input, textarea, button"));
  }

  function showBatchFormError(message) {
    batchFormError.textContent = message;
    batchFormError.hidden = false;
    batchFormError.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function clearBatchFormError() {
    batchFormError.hidden = true;
    batchFormError.textContent = "";
  }

  function setBatchLoading(isLoading, total) {
    batchControls().forEach((control) => {
      control.disabled = isLoading;
    });

    if (isLoading) {
      batchSubmitButton.textContent = "Checking Batch...";
      startBatchProgress(total);
    } else {
      batchSubmitButton.textContent = "Verify Batch";
      stopBatchProgress();
      updateBatchAddButton();
    }
  }

  function renderBatchProgress(total, completed, percent, message) {
    batchLoadingMessage.innerHTML = "";

    const progressHeader = document.createElement("div");
    progressHeader.className = "progress-header";

    const progressText = document.createElement("span");
    progressText.textContent = message;

    const progressCount = document.createElement("strong");
    progressCount.textContent = `${completed} of ${total}`;

    const progressTrack = document.createElement("div");
    progressTrack.className = "progress-track";
    progressTrack.setAttribute("aria-hidden", "true");

    const progressFill = document.createElement("div");
    progressFill.className = "progress-fill";
    progressFill.style.width = `${percent}%`;

    progressHeader.append(progressText, progressCount);
    progressTrack.append(progressFill);
    batchLoadingMessage.append(progressHeader, progressTrack);
  }

  function startBatchProgress(total) {
    stopBatchProgress();
    batchLoadingMessage.hidden = true;

    batchProgressTimer = window.setTimeout(() => {
      batchLoadingMessage.hidden = false;
      renderBatchProgress(total, 0, 0, "Sending labels...");
    }, 500);
  }

  function updateBatchProgress(total, completed, message) {
    if (batchProgressTimer) {
      window.clearTimeout(batchProgressTimer);
      batchProgressTimer = null;
    }

    batchLoadingMessage.hidden = false;
    const percent = total > 0 ? Math.round((completed / total) * 100) : 100;
    renderBatchProgress(total, completed, percent, message);
  }

  function finishBatchProgress(total) {
    updateBatchProgress(total, total, "Batch complete.");
  }

  function stopBatchProgress() {
    if (batchProgressTimer) {
      window.clearTimeout(batchProgressTimer);
      batchProgressTimer = null;
    }
    batchLoadingMessage.hidden = true;
    batchLoadingMessage.innerHTML = "";
  }

  function updateMode(mode) {
    const isBatch = mode === "batch";
    singleTab.classList.toggle("active", !isBatch);
    batchTab.classList.toggle("active", isBatch);
    singleTab.setAttribute("aria-selected", String(!isBatch));
    batchTab.setAttribute("aria-selected", String(isBatch));
    form.hidden = isBatch;
    batchForm.hidden = !isBatch;
    form.toggleAttribute("hidden", isBatch);
    batchForm.toggleAttribute("hidden", !isBatch);
    resultsView.hidden = true;
    resultList.innerHTML = "";

    if (isBatch) {
      const firstBatchImage = batchRows[0] ? rowField(batchRows[0], "image") : null;
      if (firstBatchImage) {
        firstBatchImage.focus({ preventScroll: true });
      }
    }
  }

  function updateBatchAddButton() {
    addBatchRowButton.disabled = batchRows.length >= maxBatchRows;
  }

  function rowField(row, name) {
    return row.element.querySelector(`[data-field="${name}"]`);
  }

  function rowError(row, name) {
    return row.element.querySelector(`[data-error-for="${name}"]`);
  }

  function clearRowError(row, name) {
    const element = rowField(row, name);
    const error = rowError(row, name);
    if (element) {
      element.classList.remove("invalid");
      element.removeAttribute("aria-invalid");
      element.removeAttribute("aria-describedby");
    }
    if (error) {
      error.hidden = true;
      error.textContent = "";
    }
  }

  function showRowError(row, name, message) {
    const element = rowField(row, name);
    const error = rowError(row, name);
    if (!element || !error) {
      return;
    }

    element.classList.add("invalid");
    element.setAttribute("aria-invalid", "true");
    element.setAttribute("aria-describedby", error.id);
    error.textContent = message;
    error.hidden = false;
  }

  function updateRowNumbers() {
    batchRows.forEach((row, index) => {
      row.element.querySelector(".batch-row-title").textContent = `Label ${index + 1}`;
      const removeButton = row.element.querySelector(".remove-row");
      removeButton.hidden = batchRows.length === 1;
    });
  }

  function createBatchRow() {
    const rowId = `batch-${rowCounter}`;
    rowCounter += 1;

    const rowElement = document.createElement("article");
    rowElement.className = "batch-row";
    rowElement.innerHTML = `
      <div class="batch-row-header">
        <h2 class="batch-row-title">Label</h2>
        <button class="secondary-button compact remove-row" type="button">Remove</button>
      </div>
      <section class="form-section">
        <label class="file-control" for="${rowId}-image">
          <span class="file-label">Choose Label Image</span>
          <input
            id="${rowId}-image"
            data-field="image"
            type="file"
            accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
          />
        </label>
        <p id="${rowId}-image-error" data-error-for="image" class="field-error" hidden></p>
        <div class="image-preview-wrap" data-preview-wrap hidden>
          <p class="selected-file-name" data-file-name></p>
          <img alt="Selected label preview" data-preview-image />
        </div>
      </section>
      <section class="form-section">
        <div class="field-grid" data-field-grid></div>
      </section>
    `;

    const row = { id: rowId, element: rowElement, previewUrl: "" };
    const fieldGrid = rowElement.querySelector("[data-field-grid]");
    fields.forEach((field) => {
      const wrapper = document.createElement("div");
      wrapper.className = `field ${field.name === "government_warning" ? "field-full" : ""}`;
      const inputId = `${rowId}-${field.name}`;
      const fieldControl = field.type === "textarea"
        ? `<textarea id="${inputId}" data-field="${field.name}" rows="4"></textarea>`
        : `<input id="${inputId}" data-field="${field.name}" type="text" autocomplete="off" />`;
      wrapper.innerHTML = `
        <label for="${inputId}">${field.label}</label>
        ${fieldControl}
        <p id="${inputId}-error" data-error-for="${field.name}" class="field-error" hidden></p>
      `;
      fieldGrid.append(wrapper);
    });

    const imageField = rowField(row, "image");
    imageField.addEventListener("change", () => {
      updateBatchImagePreview(row);
      clearRowError(row, "image");
    });

    fields.forEach((field) => {
      rowField(row, field.name).addEventListener("input", () => {
        clearRowError(row, field.name);
      });
    });

    rowElement.querySelector(".remove-row").addEventListener("click", () => {
      removeBatchRow(row);
    });

    batchRowsContainer.append(rowElement);
    batchRows.push(row);
    updateRowNumbers();
    updateBatchAddButton();
  }

  function updateBatchImagePreview(row) {
    if (row.previewUrl) {
      URL.revokeObjectURL(row.previewUrl);
      row.previewUrl = "";
    }

    const input = rowField(row, "image");
    const preview = row.element.querySelector("[data-preview-wrap]");
    const fileName = row.element.querySelector("[data-file-name]");
    const image = row.element.querySelector("[data-preview-image]");

    if (!input.files || input.files.length === 0) {
      preview.hidden = true;
      fileName.textContent = "";
      image.removeAttribute("src");
      return;
    }

    const file = input.files[0];
    row.previewUrl = URL.createObjectURL(file);
    fileName.textContent = file.name;
    image.src = row.previewUrl;
    preview.hidden = false;
  }

  function removeBatchRow(row) {
    if (batchRows.length <= 1) {
      return;
    }
    if (row.previewUrl) {
      URL.revokeObjectURL(row.previewUrl);
    }
    row.element.remove();
    batchRows = batchRows.filter((item) => item !== row);
    updateRowNumbers();
    updateBatchAddButton();
  }

  function clearBatchErrors() {
    clearBatchFormError();
    batchRows.forEach((row) => {
      clearRowError(row, "image");
      fields.forEach((field) => clearRowError(row, field.name));
    });
  }

  function validateBatchRows() {
    let isValid = true;
    batchRows.forEach((row) => {
      const image = rowField(row, "image");
      if (!image.files || image.files.length === 0) {
        showRowError(row, "image", "Choose one label image.");
        isValid = false;
      }

      fields.forEach((field) => {
        if (rowField(row, field.name).value.trim() === "") {
          showRowError(row, field.name, "Complete this field.");
          isValid = false;
        }
      });
    });

    return isValid;
  }

  function buildBatchFormData() {
    const formData = new FormData();
    const items = batchRows.map((row, index) => {
      const item = {
        client_id: row.id,
        image_field: `image_${index}`,
      };

      fields.forEach((field) => {
        item[field.name] = rowField(row, field.name).value.trim();
      });

      formData.append(`image_${index}`, rowField(row, "image").files[0]);
      return item;
    });

    formData.append("items", JSON.stringify(items));
    return formData;
  }

  function applyBatchServerError(body) {
    const error = body && body.error ? body.error : {};
    const code = error.code || "internal_error";
    const message = errorMessages[code] || "The batch could not be checked right now. Please try again.";
    showBatchFormError(message);

    if (Array.isArray(error.details)) {
      error.details.forEach((detail) => {
        const imageMatch = /^image_(\d+)$/.exec(detail.field || "");
        if (imageMatch) {
          const row = batchRows[Number(imageMatch[1])];
          if (row) {
            showRowError(row, "image", detail.message || "Choose one label image.");
          }
        }
      });
    }
  }

  async function readBatchStream(response, total, orderedClientIds) {
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

    function handleLine(line) {
      if (!line.trim()) {
        return;
      }

      const event = JSON.parse(line);
      if (event.type === "item") {
        items.push(event.item);
        updateBatchProgress(
          total,
          event.progress.completed,
          event.progress.completed === total ? "Finishing batch..." : "Checking labels..."
        );
      } else if (event.type === "complete") {
        summary = event.summary;
        latencyMs = event.latency_ms;
        finishBatchProgress(total);
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

  async function submitBatch(event) {
    event.preventDefault();
    clearBatchErrors();
    resultsView.hidden = true;
    resultList.innerHTML = "";

    if (!validateBatchRows()) {
      showBatchFormError("Complete the highlighted fields.");
      return;
    }

    setBatchLoading(true, batchRows.length);

    try {
      const orderedClientIds = batchRows.map((row) => row.id);
      const response = await fetch(`${apiBaseUrl}/verify/batch/stream`, {
        method: "POST",
        body: buildBatchFormData(),
        headers: { Accept: "application/x-ndjson" },
      });

      if (!response.ok) {
        const body = await parseResponseBody(response);
        applyBatchServerError(body);
        return;
      }

      const body = await readBatchStream(response, batchRows.length, orderedClientIds);
      renderBatchResults(body);
    } catch (_error) {
      showBatchFormError(
        "Could not reach the verification service. Please check the connection and try again."
      );
    } finally {
      setBatchLoading(false, batchRows.length);
    }
  }

  function resetBatchForm() {
    batchRows.forEach((row) => {
      if (row.previewUrl) {
        URL.revokeObjectURL(row.previewUrl);
      }
      row.element.remove();
    });
    batchRows = [];
    clearBatchFormError();
    createBatchRow();
  }

  function resetForm() {
    if (batchForm.hidden) {
      form.reset();
      clearErrors();
      updateImagePreview();
      refreshSubmitState();
    } else {
      batchForm.reset();
      clearBatchErrors();
      resetBatchForm();
    }

    resultsView.hidden = true;
    resultList.innerHTML = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  singleTab.addEventListener("click", () => updateMode("single"));
  batchTab.addEventListener("click", () => updateMode("batch"));
  imageInput.addEventListener("change", updateImagePreview);
  fields.forEach((field) => {
    const element = fieldElement(field.name);
    element.addEventListener("input", () => {
      clearFieldError(field.name);
      refreshSubmitState();
    });
  });
  addBatchRowButton.addEventListener("click", () => {
    if (batchRows.length < maxBatchRows) {
      createBatchRow();
    }
  });
  form.addEventListener("submit", submitVerification);
  batchForm.addEventListener("submit", submitBatch);
  resetButton.addEventListener("click", resetForm);

  createBatchRow();
  refreshSubmitState();
})();
