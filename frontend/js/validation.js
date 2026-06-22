import { FIELDS, MAX_UPLOAD_BYTES, SUPPORTED_IMAGE_TYPES } from "./constants.js";
import { fieldElement } from "./dom.js";

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
    if (fieldElement(field.name).value.trim() === "") {
      errors.push({ field: field.name, message: "Complete this field." });
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
    if (rowField(row, field.name).value.trim() === "") {
      errors.push({ field: field.name, message: "Complete this field." });
    }
  });

  return errors;
}
