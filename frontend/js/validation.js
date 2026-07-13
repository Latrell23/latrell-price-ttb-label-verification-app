import { FIELDS, MAX_UPLOAD_BYTES, SUPPORTED_IMAGE_TYPES } from "./constants.js";
import { fieldElement } from "./dom.js";

const ABV_MESSAGE = "Enter ABV as a percent or proof, such as 13.5% or 27 proof.";
const NET_CONTENTS_MESSAGE = "Enter net contents with a number and unit, such as 750 mL.";

const ABV_PATTERN = /^(?:\d+(?:\.\d+)?\s*(?:%|percent|percent\s+abv|%\s*abv|abv)?|\d+(?:\.\d+)?\s*proof)$/i;
const NET_CONTENTS_PATTERN = /^\d+(?:\.\d+)?\s*(?:ml|milliliter|milliliters|l|liter|liters|cl|oz|fl\s*oz|fluid\s+ounce|fluid\s+ounces)$/i;

// Validates one selected image before sending it to the backend.
export function validateImageFile(file) {
  if (!file) {
    return "Choose one label image.";
  }
  if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
    return "Please choose a JPG, PNG, or WebP image.";
  }
  if (file.size === 0) {
    return "The selected file is empty.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "Please choose an image that is 10 MB or smaller.";
  }
  return "";
}

export function validateAbv(value) {
  const normalized = value.trim();
  if (normalized === "") {
    return "Complete this field.";
  }
  if (!ABV_PATTERN.test(normalized)) {
    return ABV_MESSAGE;
  }
  return "";
}

export function validateNetContents(value) {
  const normalized = value.trim();
  if (normalized === "") {
    return "Complete this field.";
  }
  if (!NET_CONTENTS_PATTERN.test(normalized)) {
    return NET_CONTENTS_MESSAGE;
  }
  return "";
}

function validateApplicationField(field, value) {
  if (field.name === "abv") {
    return validateAbv(value);
  }
  if (field.name === "net_contents") {
    return validateNetContents(value);
  }
  return value.trim() === "" ? "Complete this field." : "";
}

// Returns validation errors for the single-label form.
export function validateSingleInputs(elements) {
  const errors = [];

  if (!elements.imageInput.files || elements.imageInput.files.length === 0) {
    errors.push({ field: "image", message: "Choose one label image." });
  } else {
    const imageError = validateImageFile(elements.imageInput.files[0]);
    if (imageError) {
      errors.push({ field: "image", message: imageError });
    }
  }

  FIELDS.forEach((field) => {
    const error = validateApplicationField(field, fieldElement(field.name).value);
    if (error) {
      errors.push({ field: field.name, message: error });
    }
  });

  return errors;
}

// Returns validation errors for one batch row.
export function validateBatchRow(row, rowField) {
  const errors = [];
  const image = rowField(row, "image");

  if (!image.files || image.files.length === 0) {
    errors.push({ field: "image", message: "Choose one label image." });
  } else {
    const imageError = validateImageFile(image.files[0]);
    if (imageError) {
      errors.push({ field: "image", message: imageError });
    }
  }

  FIELDS.forEach((field) => {
    const error = validateApplicationField(field, rowField(row, field.name).value);
    if (error) {
      errors.push({ field: field.name, message: error });
    }
  });

  return errors;
}
