(function () {
  const config = window.APP_CONFIG || {};
  const apiBaseUrl = (config.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

  const fields = [
    { name: "brand_name", label: "Brand Name" },
    { name: "class_type", label: "Class / Type" },
    { name: "abv", label: "Alcohol By Volume" },
    { name: "net_contents", label: "Net Contents" },
    { name: "producer", label: "Producer" },
    { name: "country_of_origin", label: "Country of Origin" },
    { name: "government_warning", label: "Government Warning" },
  ];

  const errorMessages = {
    missing_image: "Choose one label image.",
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

  const form = document.querySelector("#verification-form");
  const imageInput = document.querySelector("#image");
  const formError = document.querySelector("#form-error");
  const previewWrap = document.querySelector("#image-preview-wrap");
  const selectedFileName = document.querySelector("#selected-file-name");
  const imagePreview = document.querySelector("#image-preview");
  const loadingMessage = document.querySelector("#loading-message");
  const verifyButton = document.querySelector("#verify-button");
  const resultsView = document.querySelector("#results-view");
  const verdictBanner = document.querySelector("#verdict-banner");
  const resultsHeading = document.querySelector("#results-heading");
  const resultList = document.querySelector("#result-list");
  const resetButton = document.querySelector("#reset-button");
  const controls = Array.from(form.querySelectorAll("input, textarea, button"));
  let previewUrl = "";

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
    controls.forEach((control) => {
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

  function renderResults(data) {
    const approved = data.overall_verdict === "APPROVED";
    resultsHeading.textContent = formatVerdict(data.overall_verdict);
    verdictBanner.className = `verdict-banner ${approved ? "approved" : "needs-review"}`;
    resultList.innerHTML = "";

    data.results.forEach((result) => {
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

      resultList.append(row);
    });

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

  function resetForm() {
    form.reset();
    clearErrors();
    resultsView.hidden = true;
    resultList.innerHTML = "";
    updateImagePreview();
    refreshSubmitState();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  imageInput.addEventListener("change", updateImagePreview);
  fields.forEach((field) => {
    const element = fieldElement(field.name);
    element.addEventListener("input", () => {
      clearFieldError(field.name);
      refreshSubmitState();
    });
  });
  form.addEventListener("submit", submitVerification);
  resetButton.addEventListener("click", resetForm);
  refreshSubmitState();
})();
