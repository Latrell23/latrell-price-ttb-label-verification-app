const config = window.APP_CONFIG || {};

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const API_BASE_URL = (config.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
export const REVIEW_TIMEOUT_MS = positiveInteger(config.REVIEW_TIMEOUT_MS, 45000);

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
  review_label_not_found: "The requested review label was not found.",
  review_image_unavailable: "The review image could not be loaded.",
  invalid_image: "The review image could not be read.",
  vision_extraction_failed: "The label could not be checked right now. Please try again.",
  vision_result_unreadable: "The label could not be checked right now. Please try again.",
  vision_not_configured: "The label could not be checked right now. Please try again.",
  request_timeout: "The AI review service took too long to respond. Please try again.",
  internal_error: "The label could not be checked right now. Please try again.",
};
