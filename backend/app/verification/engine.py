import re
import string
from difflib import SequenceMatcher
from time import perf_counter

from app.verification.models import (
    ApplicationData,
    BatchResult,
    ExtractedLabel,
    FieldResult,
    VerificationResult,
)

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - exercised only in no-dependency local envs
    fuzz = None


FUZZY_THRESHOLD = 90
ABV_TOLERANCE = 0.1
NET_CONTENTS_TOLERANCE_ML = 1
FL_OZ_TO_ML = 29.5735

FUZZY_FIELDS = ("brand_name", "class_type", "producer")
FIELD_ORDER = (
    "brand_name",
    "class_type",
    "abv",
    "net_contents",
    "producer",
    "country_of_origin",
    "government_warning",
)

COUNTRY_SYNONYM_GROUPS = (
    {"usa", "united states", "united states of america"},
    {"uk", "united kingdom"},
)

UNIT_FACTORS_TO_ML = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "cl": 10.0,
    "oz": FL_OZ_TO_ML,
    "fl oz": FL_OZ_TO_ML,
    "fluid ounce": FL_OZ_TO_ML,
    "fluid ounces": FL_OZ_TO_ML,
}


def verify_label(
    application: ApplicationData, extracted: ExtractedLabel
) -> VerificationResult:
    started_at = perf_counter()
    results = [
        _compare_fuzzy_field(application, extracted, "brand_name"),
        _compare_fuzzy_field(application, extracted, "class_type"),
        _compare_abv(application.abv, extracted.abv),
        _compare_net_contents(application.net_contents, extracted.net_contents),
        _compare_fuzzy_field(application, extracted, "producer"),
        _compare_country(application.country_of_origin, extracted.country_of_origin),
        _compare_government_warning(
            application.government_warning,
            extracted.government_warning,
        ),
    ]
    verdict = (
        "APPROVED"
        if all(result.status == "PASS" for result in results)
        else "NEEDS_REVIEW"
    )
    latency_ms = (perf_counter() - started_at) * 1000
    return VerificationResult(
        results=results,
        overall_verdict=verdict,
        latency_ms=latency_ms,
    )


def verify_batch(
    pairs: list[tuple[ApplicationData, ExtractedLabel]]
) -> BatchResult:
    items = [verify_label(application, extracted) for application, extracted in pairs]
    passed = sum(item.overall_verdict == "APPROVED" for item in items)
    needs_review = sum(item.overall_verdict == "NEEDS_REVIEW" for item in items)
    return BatchResult(
        items=items,
        summary={
            "passed": passed,
            "needs_review": needs_review,
            "total": len(items),
        },
    )


def _compare_fuzzy_field(
    application: ApplicationData,
    extracted: ExtractedLabel,
    field: str,
) -> FieldResult:
    expected = getattr(application, field)
    found = getattr(extracted, field)
    status = "FAIL"
    if found is not None:
        score = _fuzzy_score(_normalize_text(expected), _normalize_text(found))
        status = "PASS" if score >= FUZZY_THRESHOLD else "FAIL"
    return FieldResult(
        field=field,
        match_type="FUZZY",
        expected=expected,
        found=found,
        status=status,
    )


def _compare_country(expected: str, found: str | None) -> FieldResult:
    status = "FAIL"
    if found is not None:
        normalized_expected = _normalize_country(expected)
        normalized_found = _normalize_country(found)
        status = (
            "PASS"
            if _countries_match(normalized_expected, normalized_found)
            else "FAIL"
        )
    return FieldResult(
        field="country_of_origin",
        match_type="COUNTRY_SYNONYM",
        expected=expected,
        found=found,
        status=status,
    )


def _compare_abv(expected: str, found: str | None) -> FieldResult:
    expected_value = _parse_abv(expected)
    found_value = _parse_abv(found) if found is not None else None
    status = (
        "PASS"
        if expected_value is not None
        and found_value is not None
        and abs(expected_value - found_value) <= ABV_TOLERANCE
        else "FAIL"
    )
    return FieldResult(
        field="abv",
        match_type="NUMERIC_ABV",
        expected=expected,
        found=found,
        status=status,
    )


def _compare_net_contents(expected: str, found: str | None) -> FieldResult:
    expected_ml = _parse_net_contents_ml(expected)
    found_ml = _parse_net_contents_ml(found) if found is not None else None
    status = (
        "PASS"
        if expected_ml is not None
        and found_ml is not None
        and abs(expected_ml - found_ml) <= NET_CONTENTS_TOLERANCE_ML
        else "FAIL"
    )
    return FieldResult(
        field="net_contents",
        match_type="UNIT_NORMALIZED",
        expected=expected,
        found=found,
        status=status,
    )


def _compare_government_warning(expected: str, found: str | None) -> FieldResult:
    status = "PASS" if found is not None and expected.strip() == found.strip() else "FAIL"
    return FieldResult(
        field="government_warning",
        match_type="EXACT_CASE_SENSITIVE",
        expected=expected,
        found=found,
        status=status,
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _fuzzy_score(expected: str, found: str) -> float:
    if fuzz is not None:
        return float(fuzz.WRatio(expected, found))
    return SequenceMatcher(None, expected, found).ratio() * 100


def _normalize_country(value: str) -> str:
    without_punctuation = value.translate(str.maketrans("", "", string.punctuation))
    return _normalize_text(without_punctuation)


def _countries_match(expected: str, found: str) -> bool:
    if expected == found:
        return True
    return any(expected in group and found in group for group in COUNTRY_SYNONYM_GROUPS)


def _parse_abv(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return None
    return float(match.group(0))


def _parse_net_contents_ml(value: str | None) -> float | None:
    if value is None:
        return None
    unit_pattern = (
        r"fluid\s+ounces?|fl\s*oz|milliliters?|liters?|ml|cl|l|oz"
    )
    match = re.search(
        rf"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>{unit_pattern})\b",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None

    unit = _normalize_unit(match.group("unit"))
    factor = UNIT_FACTORS_TO_ML.get(unit)
    if factor is None:
        return None
    return float(match.group("amount")) * factor


def _normalize_unit(unit: str) -> str:
    normalized = _normalize_text(unit)
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized == "floz":
        return "fl oz"
    return normalized
