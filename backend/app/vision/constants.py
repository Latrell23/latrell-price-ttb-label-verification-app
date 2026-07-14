DEFAULT_TIMEOUT_SECONDS = 4.5
DEFAULT_MAX_IMAGE_EDGE = 1600
DEFAULT_JPEG_QUALITY = 85

VISION_PROMPT = """
Extract visible TTB alcohol label fields only.
Use null for missing, obscured, unreadable, or uncertain fields.
Do not infer values from product knowledge or reconstruct hidden text.
For government_warning, copy the full visible warning verbatim, preserving case,
punctuation, spacing, line text, and the colon; if incomplete or unreadable,
return null.
Set raw_text to readable visible label text, or null if none.
Set extraction_confidence from 0.0 to 1.0 for readability/certainty.
For non-label images, return null label fields, readable raw_text if any, and
low or zero confidence.
""".strip()
