DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT_SECONDS = 4.5
DEFAULT_MAX_IMAGE_EDGE = 2048
DEFAULT_JPEG_QUALITY = 85

VISION_PROMPT = """
Extract TTB alcohol label information from the image.
Return only fields visible in the image.
If a field is missing, obscured, unreadable, or uncertain, return null.
Copy government_warning verbatim exactly as printed, preserving case,
punctuation, internal spacing, line text, and the colon.
If the full government warning is not visible/readable, return
government_warning as null; do not reconstruct the statutory warning from
memory.
Do not infer missing values from general product knowledge.
Set raw_text to the visible label text you can read; use null if no text is
readable.
Set extraction_confidence from 0.0 to 1.0 based on image readability and
extraction certainty.
For valid non-label images, return null label fields, readable raw_text if any,
and low or zero extraction_confidence.
""".strip()
