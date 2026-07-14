from typing import Literal

from pydantic import BaseModel


Status = Literal["PASS", "FAIL"]
OverallVerdict = Literal["APPROVED", "NEEDS_REVIEW"]
BatchItemStatus = Literal["completed", "failed"]
MatchType = Literal[
    "FUZZY",
    "COUNTRY_SYNONYM",
    "NUMERIC_ABV",
    "UNIT_NORMALIZED",
    "EXACT_CASE_SENSITIVE",
    "EXACT_CASE_INSENSITIVE",
]


class ApplicationData(BaseModel):
    """Application-submitted label values expected to appear on the image."""

    brand_name: str
    class_type: str
    abv: str
    net_contents: str
    producer: str
    country_of_origin: str
    government_warning: str


class ExtractedLabel(BaseModel):
    """Vision-extracted label values read from the uploaded image."""

    brand_name: str | None
    class_type: str | None
    abv: str | None
    net_contents: str | None
    producer: str | None
    country_of_origin: str | None
    government_warning: str | None
    raw_text: str | None
    extraction_confidence: float | None


class FieldResult(BaseModel):
    """Result of comparing one application field with one extracted field."""

    field: str
    match_type: MatchType
    expected: str
    found: str | None
    status: Status


class VerificationResult(BaseModel):
    """Single-label verification result returned by the API."""

    results: list[FieldResult]
    overall_verdict: OverallVerdict
    latency_ms: float


class ErrorDetail(BaseModel):
    """Field-level API error detail."""

    field: str
    message: str


class APIError(BaseModel):
    """Stable API error payload without the outer error wrapper."""

    code: str
    message: str
    details: list[ErrorDetail]


class BatchVerificationSummary(BaseModel):
    """Aggregate counts for a batch verification response."""

    passed: int
    needs_review: int
    completed: int
    failed: int
    total: int


class BatchVerificationItem(BaseModel):
    """Per-label batch verification outcome."""

    client_id: str
    file_name: str | None
    status: BatchItemStatus
    result: VerificationResult | None
    error: APIError | None


class BatchVerificationResponse(BaseModel):
    """Batch verification API response with partial-result support."""

    items: list[BatchVerificationItem]
    summary: BatchVerificationSummary
    latency_ms: float


class BatchResult(BaseModel):
    """Batch verification result with item details and aggregate counts."""

    items: list[VerificationResult]
    summary: dict[str, int]
