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
    {"france", "french republic", "republic of france"},
    {"italy", "italian republic", "republic of italy"},
    {"spain", "kingdom of spain", "espana", "españa"},
    {"germany", "federal republic of germany", "deutschland"},
    {"portugal", "portuguese republic", "republic of portugal"},
    {"australia", "commonwealth of australia"},
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
    """Compare application fields with extracted label fields and return a verdict."""
    started_at = perf_counter()
    confidence_score = _read_confidence(extracted)

    # Run each field through the comparison rule required for that field.
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

    # Approve only labels where every individual field passes.
    verdict = (
        "APPROVED"
        if all(result.status == "PASS" for result in results)
        else "NEEDS_REVIEW"
    )

    # Include comparison latency without changing the response contract.
    latency_ms = (perf_counter() - started_at) * 1000
    return VerificationResult(
        results=results,
        overall_verdict=verdict,
        latency_ms=latency_ms,
        confidence_score=confidence_score,
    )


def verify_batch(
    pairs: list[tuple[ApplicationData, ExtractedLabel]]
) -> BatchResult:
    """Verify multiple application and label pairs and summarize their outcomes."""
    # Reuse single-label verification so batch behavior stays consistent.
    items = [verify_label(application, extracted) for application, extracted in pairs]

    # Count final verdicts for the batch summary payload.
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
    """Compare a text field using normalized fuzzy matching."""
    expected = getattr(application, field)
    found = getattr(extracted, field)

    # Missing extracted values fail because there is nothing to compare.
    status = "FAIL"
    match_score = 0.0
    if found is not None:
        normalized_expected = _normalize_text(expected)
        normalized_found = _normalize_text(found)
        if len(normalized_expected) <= 4 or len(normalized_found) <= 4:
            status = (
                "PASS" if normalized_expected == normalized_found else "FAIL"
            )
            match_score = 1.0 if status == "PASS" else 0.0
        else:
            score = _fuzzy_score(normalized_expected, normalized_found)
            status = "PASS" if score >= FUZZY_THRESHOLD else "FAIL"
            match_score = _clamp_score(score / 100)

    return FieldResult(
        field=field,
        match_type="FUZZY",
        expected=expected,
        found=found,
        status=status,
        match_score=match_score,
    )


def _compare_country(
    expected: str,
    found: str | None,
) -> FieldResult:
    """Compare countries after punctuation and synonym normalization."""
    # Missing extracted countries fail because origin is a required label field.
    status = "FAIL"
    match_score = 0.0
    if found is not None:
        normalized_expected = _normalize_country(expected)
        normalized_found = _normalize_country(found)
        countries_match = _countries_match(normalized_expected, normalized_found)
        status = "PASS" if countries_match else "FAIL"
        match_score = 1.0 if countries_match else 0.0

    return FieldResult(
        field="country_of_origin",
        match_type="COUNTRY_SYNONYM",
        expected=expected,
        found=found,
        status=status,
        match_score=match_score,
    )


def _compare_abv(
    expected: str,
    found: str | None,
) -> FieldResult:
    """Compare ABV values numerically within the configured tolerance."""
    # Parse numbers from both values before applying the tolerance check.
    expected_value = _parse_abv(expected, allow_plain_number=True)
    found_value = _parse_abv(found) if found is not None else None
    match_score = _numeric_match_score(
        expected_value,
        found_value,
        tolerance=ABV_TOLERANCE,
    )
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
        match_score=match_score,
    )


def _compare_net_contents(
    expected: str,
    found: str | None,
) -> FieldResult:
    """Compare net contents after converting supported units to milliliters."""
    # Convert both values into milliliters before applying the tolerance check.
    expected_ml = _parse_net_contents_ml(expected)
    found_ml = _parse_net_contents_ml(found) if found is not None else None
    match_score = _numeric_match_score(
        expected_ml,
        found_ml,
        tolerance=NET_CONTENTS_TOLERANCE_ML,
    )
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
        match_score=match_score,
    )


def _compare_government_warning(
    expected: str,
    found: str | None,
) -> FieldResult:
    """Compare the government warning exactly, ignoring OCR casing noise."""
    expected_normalized = _normalize_government_warning(expected)
    found_normalized = _normalize_government_warning(found) if found is not None else None
    score = (
        _fuzzy_score(expected_normalized, found_normalized) / 100
        if found_normalized is not None
        else 0.0
    )
    status = (
        "PASS"
        if found_normalized is not None and expected_normalized == found_normalized
        else "FAIL"
    )
    return FieldResult(
        field="government_warning",
        match_type="EXACT_CASE_INSENSITIVE",
        expected=expected,
        found=found,
        status=status,
        match_score=1.0 if status == "PASS" else _clamp_score(score),
    )


def _normalize_government_warning(value: str) -> str:
    """Collapse whitespace and case-fold without changing punctuation."""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_text(value: str) -> str:
    """Collapse whitespace and case-fold text for matching."""
    return " ".join(value.strip().split()).casefold()


def _fuzzy_score(expected: str, found: str) -> float:
    """Return a fuzzy similarity score using rapidfuzz when available."""
    if fuzz is not None:
        return float(fuzz.WRatio(expected, found))

    return SequenceMatcher(None, expected, found).ratio() * 100


def _normalize_country(value: str) -> str:
    """Remove punctuation and normalize country text for comparison."""
    without_punctuation = value.translate(str.maketrans("", "", string.punctuation))
    return _normalize_text(without_punctuation)


def _countries_match(expected: str, found: str) -> bool:
    """Return whether countries match directly or through a synonym group."""
    if expected == found:
        return True

    return any(expected in group and found in group for group in COUNTRY_SYNONYM_GROUPS)


def _parse_abv(value: str | None, *, allow_plain_number: bool = False) -> float | None:
    """Parse an ABV value from percent, alcohol-volume, or proof text."""
    if value is None:
        return None

    percent_match = re.search(r"(?P<amount>\d+(?:\.\d+)?)\s*%", value)
    if percent_match is not None:
        return float(percent_match.group("amount"))

    alc_volume_match = re.search(
        r"(?:alc\.?\s*/?\s*vol\.?|alcohol\s+by\s+volume|abv)"
        r"\D*(?P<amount>\d+(?:\.\d+)?)|"
        r"(?P<prefix_amount>\d+(?:\.\d+)?)\D*"
        r"(?:alc\.?\s*/?\s*vol\.?|alcohol\s+by\s+volume|abv)",
        value,
        re.IGNORECASE,
    )
    if alc_volume_match is not None:
        amount = alc_volume_match.group("amount") or alc_volume_match.group(
            "prefix_amount"
        )
        return float(amount)

    proof_match = re.search(
        r"(?P<amount>\d+(?:\.\d+)?)\s*proof\b",
        value,
        re.IGNORECASE,
    )
    if proof_match is not None:
        return float(proof_match.group("amount")) / 2

    if allow_plain_number:
        plain_number_match = re.fullmatch(r"\s*(?P<amount>\d+(?:\.\d+)?)\s*", value)
        if plain_number_match is not None:
            return float(plain_number_match.group("amount"))

    return None


def _parse_net_contents_ml(value: str | None) -> float | None:
    """Parse supported net contents units and return the amount in milliliters."""
    if value is None:
        return None

    # Match an amount followed by a supported volume unit.
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

    # Normalize the captured unit and convert the amount to milliliters.
    unit = _normalize_unit(match.group("unit"))
    factor = UNIT_FACTORS_TO_ML.get(unit)
    if factor is None:
        return None

    return float(match.group("amount")) * factor


def _normalize_unit(unit: str) -> str:
    """Normalize volume unit text for lookup in the conversion table."""
    normalized = _normalize_text(unit)
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized == "floz":
        return "fl oz"

    return normalized


def _numeric_match_score(
    expected: float | None,
    found: float | None,
    *,
    tolerance: float,
) -> float:
    """Return a confidence score based on numeric distance from tolerance."""
    if expected is None or found is None:
        return 0.0

    difference = abs(expected - found)
    if difference <= tolerance:
        return 1.0

    denominator = max(abs(expected), abs(found), tolerance)
    return _clamp_score(1 - (difference / denominator))


def _read_confidence(extracted: ExtractedLabel) -> float:
    """Return equal-field read coverage as the reviewer confidence score."""
    found_field_count = sum(
        getattr(extracted, field) is not None for field in FIELD_ORDER
    )
    return _clamp_score(found_field_count / len(FIELD_ORDER))


def _clamp_score(value: float) -> float:
    """Clamp scores into the public 0.0 to 1.0 range."""
    return max(0.0, min(1.0, round(value, 4)))
