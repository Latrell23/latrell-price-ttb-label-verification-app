from typing import Literal

from pydantic import BaseModel


Status = Literal["PASS", "FAIL"]
OverallVerdict = Literal["APPROVED", "NEEDS_REVIEW"]
MatchType = Literal[
    "FUZZY",
    "COUNTRY_SYNONYM",
    "NUMERIC_ABV",
    "UNIT_NORMALIZED",
    "EXACT_CASE_SENSITIVE",
]


class ApplicationData(BaseModel):
    brand_name: str
    class_type: str
    abv: str
    net_contents: str
    producer: str
    country_of_origin: str
    government_warning: str


class ExtractedLabel(BaseModel):
    brand_name: str | None
    class_type: str | None
    abv: str | None
    net_contents: str | None
    producer: str | None
    country_of_origin: str | None
    government_warning: str | None
    raw_text: str | None = None
    extraction_confidence: float | None = None


class FieldResult(BaseModel):
    field: str
    match_type: MatchType
    expected: str
    found: str | None
    status: Status


class VerificationResult(BaseModel):
    results: list[FieldResult]
    overall_verdict: OverallVerdict
    latency_ms: float


class BatchResult(BaseModel):
    items: list[VerificationResult]
    summary: dict[str, int]
