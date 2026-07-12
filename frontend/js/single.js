import { ERROR_MESSAGES, FIELDS } from "./constants.js";
import { fieldElement } from "./dom.js";
import { isTimeoutError, parseResponseBody, postSingleVerification } from "./api.js";
import { renderResults } from "./rendering.js";
import {
  clearErrors,
  clearFieldError,
  refreshSubmitState,
  setLoading,
  showFieldError,
  showFormError,
} from "./ui.js";
import { validateSingleInputs } from "./validation.js";

// Builds the multipart payload for the single-label endpoint.
export function buildFormData(elements) {
  const formData = new FormData();
  formData.append("image", elements.imageInput.files[0]);
  FIELDS.forEach((field) => {
    formData.append(field.name, fieldElement(field.name).value.trim());
  });
  return formData;
}

// Maps a backend error response onto the single-label form.
export function applyServerError(elements, body) {
  const error = body && body.error ? body.error : {};
  const code = error.code || "internal_error";
  const message =
    ERROR_MESSAGES[code] || "The label could not be checked right now. Please try again.";

  showFormError(elements, message);

  if (Array.isArray(error.details)) {
    error.details.forEach((detail) => {
      const field = detail.field;
      if (field === "image") {
        showFieldError("image", message);
      } else if (FIELDS.some((item) => item.name === field)) {
        showFieldError(field, detail.message || "Complete this field.");
      }
    });
  }
}

// Shows client-side validation errors on the single-label form.
export function showSingleValidationErrors(errors) {
  errors.forEach((error) => {
    showFieldError(error.field, error.message);
  });
}

// Handles single-label submission from validation through rendering.
export async function submitVerification(event, elements) {
  event.preventDefault();
  clearErrors(elements);
  elements.resultsView.hidden = true;
  elements.resultList.innerHTML = "";

  const validationErrors = validateSingleInputs(elements);
  if (validationErrors.length > 0) {
    showSingleValidationErrors(validationErrors);
    showFormError(elements, "Complete the highlighted fields.");
    refreshSubmitState(elements);
    return;
  }

  setLoading(elements, true);

  try {
    const response = await postSingleVerification(buildFormData(elements));
    const body = await parseResponseBody(response);

    if (!response.ok) {
      applyServerError(elements, body);
      return;
    }

    renderResults(elements, body);
  } catch (error) {
    showFormError(
      elements,
      isTimeoutError(error)
        ? ERROR_MESSAGES.request_timeout
        : "Could not reach the verification service. Please check the connection and try again."
    );
  } finally {
    setLoading(elements, false);
  }
}

// Wires single-label input events to preview and field-error behavior.
export function bindSingleEvents(elements, singlePreviewController) {
  elements.imageInput.addEventListener("change", singlePreviewController.updateImagePreview);
  FIELDS.forEach((field) => {
    const element = fieldElement(field.name);
    element.addEventListener("input", () => {
      clearFieldError(field.name);
      refreshSubmitState(elements);
    });
  });
}
