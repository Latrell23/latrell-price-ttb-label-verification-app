import { FIELDS } from "./constants.js";
import { errorElement, fieldElement } from "./dom.js";
import { validateImageFile } from "./validation.js";

// Keeps the single-label submit button enabled when the form is idle.
export function refreshSubmitState(elements) {
  elements.verifyButton.disabled = false;
}

// Clears the visual and accessible error state for one single-label field.
export function clearFieldError(name) {
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

// Clears all single-label form-level and field-level errors.
export function clearErrors(elements) {
  elements.formError.hidden = true;
  elements.formError.textContent = "";
  clearFieldError("image");
  FIELDS.forEach((field) => clearFieldError(field.name));
}

// Shows the main single-label form error message.
export function showFormError(elements, message) {
  elements.formError.textContent = message;
  elements.formError.hidden = false;
  elements.formError.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// Shows a field-level error on the single-label form.
export function showFieldError(name, message) {
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

// Toggles the single-label form loading state.
export function setLoading(elements, isLoading) {
  elements.singleControls.forEach((control) => {
    control.disabled = isLoading;
  });
  elements.loadingMessage.hidden = !isLoading;
  elements.verifyButton.textContent = isLoading ? "Checking Label..." : "Verify Label";

  if (!isLoading) {
    refreshSubmitState(elements);
  }
}

// Creates the stateful preview controller for the single-label image.
export function createSinglePreviewController(elements) {
  let previewUrl = "";

  // Updates the single-label preview after the selected file changes.
  function updateImagePreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }

    if (!elements.imageInput.files || elements.imageInput.files.length === 0) {
      elements.previewWrap.hidden = true;
      elements.selectedFileName.textContent = "";
      elements.imagePreview.removeAttribute("src");
      refreshSubmitState(elements);
      return;
    }

    const file = elements.imageInput.files[0];
    clearFieldError("image");
    const imageError = validateImageFile(file);
    if (imageError) {
      showFieldError("image", imageError);
    }
    previewUrl = URL.createObjectURL(file);
    elements.selectedFileName.textContent = file.name;
    elements.imagePreview.src = previewUrl;
    elements.previewWrap.hidden = false;
    refreshSubmitState(elements);
  }

  // Releases the current single-label object URL when it is no longer needed.
  function revokePreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }
  }

  return { updateImagePreview, revokePreview };
}

// Shows the main batch form error message.
export function showBatchFormError(elements, message) {
  elements.batchFormError.textContent = message;
  elements.batchFormError.hidden = false;
  elements.batchFormError.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// Clears the main batch form error message.
export function clearBatchFormError(elements) {
  elements.batchFormError.hidden = true;
  elements.batchFormError.textContent = "";
}

// Switches between single-label and batch modes.
export function updateMode(elements, mode, firstBatchImage) {
  const isBatch = mode === "batch";
  elements.singleTab.classList.toggle("active", !isBatch);
  elements.batchTab.classList.toggle("active", isBatch);
  elements.singleTab.setAttribute("aria-selected", String(!isBatch));
  elements.batchTab.setAttribute("aria-selected", String(isBatch));
  elements.form.hidden = isBatch;
  elements.batchForm.hidden = !isBatch;
  elements.form.toggleAttribute("hidden", isBatch);
  elements.batchForm.toggleAttribute("hidden", !isBatch);
  elements.resultsView.hidden = true;
  elements.resultList.innerHTML = "";

  if (isBatch && firstBatchImage) {
    firstBatchImage.focus({ preventScroll: true });
  }
}

// Resets whichever form is currently active.
export function resetForm(elements, singlePreviewController, batchController) {
  if (elements.batchForm.hidden) {
    elements.form.reset();
    clearErrors(elements);
    singlePreviewController.updateImagePreview();
    refreshSubmitState(elements);
  } else {
    elements.batchForm.reset();
    batchController.clearBatchErrors();
    batchController.resetBatchForm();
  }

  elements.resultsView.hidden = true;
  elements.resultList.innerHTML = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
}
