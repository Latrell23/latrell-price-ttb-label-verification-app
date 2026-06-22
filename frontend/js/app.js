import { createBatchController } from "./batch.js";
import { getElements } from "./dom.js";
import { bindSingleEvents, submitVerification } from "./single.js";
import { createSinglePreviewController, refreshSubmitState, resetForm, updateMode } from "./ui.js";

// Boots the frontend and wires all page interactions.
function initializeApp() {
  const elements = getElements();
  const singlePreviewController = createSinglePreviewController(elements);
  const batchController = createBatchController(elements);

  // Switches the page into single-label mode.
  function handleSingleTabClick() {
    updateMode(elements, "single");
  }

  // Switches the page into batch mode and focuses the first batch image field.
  function handleBatchTabClick() {
    updateMode(elements, "batch", batchController.getFirstBatchImage());
  }

  // Submits the single-label form.
  function handleSingleSubmit(event) {
    submitVerification(event, elements);
  }

  // Submits the batch form.
  function handleBatchSubmit(event) {
    batchController.submitBatch(event);
  }

  // Adds a batch row if the limit has not been reached.
  function handleAddBatchRow() {
    batchController.addRowIfAllowed();
  }

  // Resets whichever form is currently visible.
  function handleResetClick() {
    resetForm(elements, singlePreviewController, batchController);
  }

  elements.singleTab.addEventListener("click", handleSingleTabClick);
  elements.batchTab.addEventListener("click", handleBatchTabClick);
  elements.addBatchRowButton.addEventListener("click", handleAddBatchRow);
  elements.form.addEventListener("submit", handleSingleSubmit);
  elements.batchForm.addEventListener("submit", handleBatchSubmit);
  elements.resetButton.addEventListener("click", handleResetClick);

  bindSingleEvents(elements, singlePreviewController);
  batchController.createBatchRow();
  refreshSubmitState(elements);
}

initializeApp();
