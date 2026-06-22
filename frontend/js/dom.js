// Collects every fixed page element used by the app.
export function getElements() {
  const form = document.querySelector("#verification-form");
  const batchForm = document.querySelector("#batch-form");

  return {
    singleTab: document.querySelector("#single-tab"),
    batchTab: document.querySelector("#batch-tab"),
    form,
    batchForm,
    imageInput: document.querySelector("#image"),
    formError: document.querySelector("#form-error"),
    previewWrap: document.querySelector("#image-preview-wrap"),
    selectedFileName: document.querySelector("#selected-file-name"),
    imagePreview: document.querySelector("#image-preview"),
    loadingMessage: document.querySelector("#loading-message"),
    verifyButton: document.querySelector("#verify-button"),
    batchRowsContainer: document.querySelector("#batch-rows"),
    batchFormError: document.querySelector("#batch-form-error"),
    addBatchRowButton: document.querySelector("#add-batch-row"),
    batchLoadingMessage: document.querySelector("#batch-loading-message"),
    batchSubmitButton: document.querySelector("#batch-submit-button"),
    resultsView: document.querySelector("#results-view"),
    verdictBanner: document.querySelector("#verdict-banner"),
    resultsHeading: document.querySelector("#results-heading"),
    resultList: document.querySelector("#result-list"),
    resetButton: document.querySelector("#reset-button"),
    singleControls: Array.from(form.querySelectorAll("input, textarea, button")),
  };
}

// Finds a single-label field control by backend field name.
export function fieldElement(name) {
  return document.querySelector(`#${name}`);
}

// Finds a single-label field error element by backend field name.
export function errorElement(name) {
  return document.querySelector(`#${name}-error`);
}
