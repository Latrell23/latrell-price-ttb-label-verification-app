import { ERROR_MESSAGES, FIELDS, MAX_BATCH_ROWS } from "./constants.js";
import { parseResponseBody, postBatchVerification, readBatchStream } from "./api.js";
import { renderBatchResults } from "./rendering.js";
import { clearBatchFormError, showBatchFormError } from "./ui.js";
import { validateBatchRow, validateImageFile } from "./validation.js";

// Creates the stateful controller for batch rows and streaming submission.
export function createBatchController(elements) {
  let rowCounter = 0;
  let batchRows = [];
  let batchProgressTimer = null;

  // Collects all enabled controls inside the batch form.
  function batchControls() {
    return Array.from(elements.batchForm.querySelectorAll("input, textarea, button"));
  }

  // Finds a field control inside one batch row.
  function rowField(row, name) {
    return row.element.querySelector(`[data-field="${name}"]`);
  }

  // Finds a field error element inside one batch row.
  function rowError(row, name) {
    return row.element.querySelector(`[data-error-for="${name}"]`);
  }

  // Clears the visual and accessible error state for one batch row field.
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

  // Shows a field-level error inside one batch row.
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

  // Renumbers rows and hides remove buttons when only one row remains.
  function updateRowNumbers() {
    batchRows.forEach((row, index) => {
      row.element.querySelector(".batch-row-title").textContent = `Label ${index + 1}`;
      const removeButton = row.element.querySelector(".remove-row");
      removeButton.hidden = batchRows.length === 1;
    });
  }

  // Enables or disables the add-row button based on the row limit.
  function updateBatchAddButton() {
    elements.addBatchRowButton.disabled = batchRows.length >= MAX_BATCH_ROWS;
  }

  // Adds one blank batch row and wires its field events.
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
      <div class="batch-row-body">
        <section class="form-section image-section">
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
        <section class="form-section fields-section">
          <div class="field-grid" data-field-grid></div>
        </section>
      </div>
    `;

    const row = { id: rowId, element: rowElement, previewUrl: "" };
    const fieldGrid = rowElement.querySelector("[data-field-grid]");
    FIELDS.forEach((field) => {
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
      clearRowError(row, "image");
      updateBatchImagePreview(row);
    });

    FIELDS.forEach((field) => {
      rowField(row, field.name).addEventListener("input", () => {
        clearRowError(row, field.name);
      });
    });

    rowElement.querySelector(".remove-row").addEventListener("click", () => {
      removeBatchRow(row);
    });

    elements.batchRowsContainer.append(rowElement);
    batchRows.push(row);
    updateRowNumbers();
    updateBatchAddButton();
  }

  // Adds a row only when the configured batch limit allows it.
  function addRowIfAllowed() {
    if (batchRows.length < MAX_BATCH_ROWS) {
      createBatchRow();
    }
  }

  // Updates one batch row image preview after file selection.
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
    const imageError = validateImageFile(file);
    if (imageError) {
      showRowError(row, "image", imageError);
    }
    row.previewUrl = URL.createObjectURL(file);
    fileName.textContent = file.name;
    image.src = row.previewUrl;
    preview.hidden = false;
  }

  // Removes one batch row and releases its preview URL.
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

  // Clears batch-level and row-level errors.
  function clearBatchErrors() {
    clearBatchFormError(elements);
    batchRows.forEach((row) => {
      clearRowError(row, "image");
      FIELDS.forEach((field) => clearRowError(row, field.name));
    });
  }

  // Validates every batch row and shows errors where needed.
  function validateBatchRows() {
    let isValid = true;
    batchRows.forEach((row) => {
      const errors = validateBatchRow(row, rowField);
      errors.forEach((error) => {
        showRowError(row, error.field, error.message);
      });
      if (errors.length > 0) {
        isValid = false;
      }
    });

    return isValid;
  }

  // Builds the multipart payload for the batch endpoint.
  function buildBatchFormData() {
    const formData = new FormData();
    const items = batchRows.map((row, index) => {
      const item = {
        client_id: row.id,
        image_field: `image_${index}`,
      };

      FIELDS.forEach((field) => {
        item[field.name] = rowField(row, field.name).value.trim();
      });

      formData.append(`image_${index}`, rowField(row, "image").files[0]);
      return item;
    });

    formData.append("items", JSON.stringify(items));
    return formData;
  }

  // Maps a backend batch error response onto the batch form.
  function applyBatchServerError(body) {
    const error = body && body.error ? body.error : {};
    const code = error.code || "internal_error";
    const message =
      ERROR_MESSAGES[code] || "The batch could not be checked right now. Please try again.";
    showBatchFormError(elements, message);

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

  // Toggles batch form controls and progress UI during submission.
  function setBatchLoading(isLoading, total) {
    batchControls().forEach((control) => {
      control.disabled = isLoading;
    });

    if (isLoading) {
      elements.batchSubmitButton.textContent = "Checking Batch...";
      startBatchProgress(total);
    } else {
      elements.batchSubmitButton.textContent = "Verify Batch";
      stopBatchProgress();
      updateBatchAddButton();
    }
  }

  // Renders the batch progress bar and message.
  function renderBatchProgress(total, completed, percent, message) {
    elements.batchLoadingMessage.innerHTML = "";

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
    elements.batchLoadingMessage.append(progressHeader, progressTrack);
  }

  // Starts delayed batch progress display to avoid flashing on fast responses.
  function startBatchProgress(total) {
    stopBatchProgress();
    elements.batchLoadingMessage.hidden = true;

    batchProgressTimer = window.setTimeout(() => {
      elements.batchLoadingMessage.hidden = false;
      renderBatchProgress(total, 0, 0, "Sending labels...");
    }, 500);
  }

  // Updates batch progress after each streamed item event.
  function updateBatchProgress(total, completed, message) {
    if (batchProgressTimer) {
      window.clearTimeout(batchProgressTimer);
      batchProgressTimer = null;
    }

    elements.batchLoadingMessage.hidden = false;
    const percent = total > 0 ? Math.round((completed / total) * 100) : 100;
    renderBatchProgress(total, completed, percent, message);
  }

  // Marks batch progress complete.
  function finishBatchProgress(total) {
    updateBatchProgress(total, total, "Batch complete.");
  }

  // Hides batch progress and clears any pending timer.
  function stopBatchProgress() {
    if (batchProgressTimer) {
      window.clearTimeout(batchProgressTimer);
      batchProgressTimer = null;
    }
    elements.batchLoadingMessage.hidden = true;
    elements.batchLoadingMessage.innerHTML = "";
  }

  // Handles batch submission from validation through streamed rendering.
  async function submitBatch(event) {
    event.preventDefault();
    clearBatchErrors();
    elements.resultsView.hidden = true;
    elements.resultList.innerHTML = "";

    if (!validateBatchRows()) {
      showBatchFormError(elements, "Complete the highlighted fields.");
      return;
    }

    setBatchLoading(true, batchRows.length);

    try {
      const orderedClientIds = batchRows.map((row) => row.id);
      const response = await postBatchVerification(buildBatchFormData());

      if (!response.ok) {
        const body = await parseResponseBody(response);
        applyBatchServerError(body);
        return;
      }

      const body = await readBatchStream(response, orderedClientIds, {
        onItem(event) {
          updateBatchProgress(
            batchRows.length,
            event.progress.completed,
            event.progress.completed === batchRows.length ? "Finishing batch..." : "Checking labels..."
          );
        },
        onComplete() {
          finishBatchProgress(batchRows.length);
        },
      });
      renderBatchResults(elements, body);
    } catch (_error) {
      showBatchFormError(
        elements,
        "Could not reach the verification service. Please check the connection and try again."
      );
    } finally {
      setBatchLoading(false, batchRows.length);
    }
  }

  // Rebuilds the batch form back to one blank row.
  function resetBatchForm() {
    batchRows.forEach((row) => {
      if (row.previewUrl) {
        URL.revokeObjectURL(row.previewUrl);
      }
      row.element.remove();
    });
    batchRows = [];
    clearBatchFormError(elements);
    createBatchRow();
  }

  // Returns the image input from the first batch row for mode-switch focus.
  function getFirstBatchImage() {
    return batchRows[0] ? rowField(batchRows[0], "image") : null;
  }

  return {
    addRowIfAllowed,
    clearBatchErrors,
    createBatchRow,
    getFirstBatchImage,
    resetBatchForm,
    submitBatch,
  };
}
