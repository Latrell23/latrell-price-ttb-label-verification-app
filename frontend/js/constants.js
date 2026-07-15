const config = window.APP_CONFIG || {};

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const API_BASE_URL = (config.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
export const FRONTEND_TIMEOUT_MS = 5000;
export const MAX_BATCH_ROWS = positiveInteger(config.MAX_BATCH_ROWS, 5);
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const SUPPORTED_IMAGE_TYPE_PREFIX = "image/";

export const FIELDS = [
  { name: "brand_name", label: "Brand Name", type: "input" },
  { name: "class_type", label: "Class / Type", type: "input" },
  { name: "abv", label: "Alcohol By Volume", type: "input" },
  { name: "net_contents", label: "Net Contents", type: "input" },
  { name: "producer", label: "Producer", type: "input" },
  { name: "country_of_origin", label: "Country of Origin", type: "input" },
  { name: "government_warning", label: "Government Warning", type: "textarea" },
];

export const ERROR_MESSAGES = {
  missing_image: "Choose one label image.",
  missing_items: "Add at least one label.",
  malformed_items: "The batch could not be prepared. Please try again.",
  empty_batch: "Add at least one label.",
  too_many_items: `Verify no more than ${MAX_BATCH_ROWS} labels at once.`,
  duplicate_client_id: "The batch could not be prepared. Please try again.",
  duplicate_image_field: "The batch could not be prepared. Please try again.",
  missing_upload_fields: "Choose an image for each label.",
  missing_required_fields: "Complete the highlighted fields.",
  blank_required_fields: "Complete the highlighted fields.",
  unsupported_media_type: "Please choose an image file.",
  file_too_large: "Please choose an image that is 10 MB or smaller.",
  empty_file: "The selected file could not be read as an image.",
  invalid_image: "The selected file could not be read as an image.",
  vision_extraction_failed: "The label could not be checked right now. Please try again.",
  vision_result_unreadable: "The label could not be checked right now. Please try again.",
  vision_not_configured: "The label could not be checked right now. Please try again.",
  request_timeout: "The verification service took too long to respond. Please try again.",
  internal_error: "The label could not be checked right now. Please try again.",
};
