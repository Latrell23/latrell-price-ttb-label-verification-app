import assert from "node:assert/strict";
import test from "node:test";

globalThis.window = { APP_CONFIG: {} };

const { validateAbv, validateImageFile, validateNetContents } = await import("./validation.js");

test("validateImageFile accepts image MIME types matching the picker", () => {
  assert.equal(validateImageFile({ type: "image/gif", size: 1024 }), "");
  assert.equal(validateImageFile({ type: "image/heic", size: 1024 }), "");
});

test("validateImageFile rejects non-image MIME types", () => {
  assert.match(validateImageFile({ type: "application/pdf", size: 1024 }), /image file/);
});

test("validateAbv accepts percent and proof values", () => {
  ["13.5", "13.5%", "13.5% ABV", "13.5 percent", "27 proof", "80 proof"].forEach(
    (value) => {
      assert.equal(validateAbv(value), "");
    }
  );
});

test("validateAbv rejects non-numeric values", () => {
  ["banana", "proof", "%", "thirteen percent"].forEach((value) => {
    assert.match(validateAbv(value), /Enter ABV/);
  });
});

test("validateNetContents accepts supported numeric units", () => {
  ["750 mL", "1 L", "75 cl", "25.4 fl oz", "750 milliliters"].forEach((value) => {
    assert.equal(validateNetContents(value), "");
  });
});

test("validateNetContents rejects missing numbers or units", () => {
  ["750", "mL", "big bottle"].forEach((value) => {
    assert.match(validateNetContents(value), /Enter net contents/);
  });
});
