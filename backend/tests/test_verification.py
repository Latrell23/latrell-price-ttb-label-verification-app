from app.verification import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    VerificationResult,
    verify_batch,
    verify_label,
)


WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
    "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH "
    "PROBLEMS."
)


def application(**overrides: str) -> ApplicationData:
    data = {
        "brand_name": "Acme Estate",
        "class_type": "Red Wine",
        "abv": "13.5",
        "net_contents": "750 ml",
        "producer": "Acme Cellars",
        "country_of_origin": "United States",
        "government_warning": WARNING,
    }
    data.update(overrides)
    return ApplicationData(**data)


def extracted(**overrides: str | None) -> ExtractedLabel:
    data = {
        "brand_name": "Acme Estate",
        "class_type": "Red Wine",
        "abv": "13.5%",
        "net_contents": "750 mL",
        "producer": "Acme Cellars",
        "country_of_origin": "USA",
        "government_warning": WARNING,
        "raw_text": "label OCR text",
        "extraction_confidence": 0.98,
    }
    data.update(overrides)
    return ExtractedLabel(**data)


def result_for_field(result: VerificationResult, field: str) -> FieldResult:
    return next(item for item in result.results if item.field == field)


def test_extracted_label_accepts_nullable_field_values() -> None:
    label = ExtractedLabel(
        brand_name=None,
        class_type=None,
        abv=None,
        net_contents=None,
        producer=None,
        country_of_origin=None,
        government_warning=None,
        raw_text=None,
        extraction_confidence=None,
    )

    assert label.brand_name is None
    assert label.government_warning is None


def test_verification_and_batch_results_serialize_expected_shapes() -> None:
    result = verify_label(application(), extracted())
    batch = verify_batch([(application(), extracted())])

    serialized_result = result.model_dump()
    serialized_batch = batch.model_dump()

    assert set(serialized_result) == {"results", "overall_verdict", "latency_ms"}
    assert len(serialized_result["results"]) == 7
    assert serialized_result["overall_verdict"] == "APPROVED"
    assert set(serialized_batch) == {"items", "summary"}
    assert serialized_batch["summary"] == {
        "passed": 1,
        "needs_review": 0,
        "total": 1,
    }


def test_brand_passes_for_minor_ocr_typo_above_threshold() -> None:
    result = verify_label(
        application(brand_name="Acme Estate"),
        extracted(brand_name="Acme Estae"),
    )

    assert result_for_field(result, "brand_name").status == "PASS"


def test_case_only_brand_difference_passes() -> None:
    result = verify_label(
        application(brand_name="Acme Estate"),
        extracted(brand_name="ACME ESTATE"),
    )

    assert result_for_field(result, "brand_name").status == "PASS"


def test_short_brand_exact_match_passes_after_normalization() -> None:
    result = verify_label(application(brand_name="ACME"), extracted(brand_name="acme"))

    assert result_for_field(result, "brand_name").status == "PASS"


def test_short_brand_subset_match_fails() -> None:
    result = verify_label(
        application(brand_name="ACME"),
        extracted(brand_name="ACME RESERVE SPECIAL EDITION"),
    )

    assert result_for_field(result, "brand_name").status == "FAIL"


def test_brand_fails_for_unrelated_value_below_threshold() -> None:
    result = verify_label(
        application(brand_name="Acme Estate"),
        extracted(brand_name="Different Winery"),
    )

    assert result_for_field(result, "brand_name").status == "FAIL"


def test_class_type_passes_despite_case_and_spacing_differences() -> None:
    result = verify_label(
        application(class_type="Red Wine"),
        extracted(class_type="  RED    wine  "),
    )

    assert result_for_field(result, "class_type").status == "PASS"


def test_producer_fails_when_extracted_value_is_missing() -> None:
    result = verify_label(application(), extracted(producer=None))

    producer = result_for_field(result, "producer")
    assert producer.status == "FAIL"
    assert producer.found is None


def test_usa_matches_united_states() -> None:
    result = verify_label(
        application(country_of_origin="USA"),
        extracted(country_of_origin="United States"),
    )

    assert result_for_field(result, "country_of_origin").status == "PASS"


def test_united_states_matches_usa() -> None:
    result = verify_label(
        application(country_of_origin="United States"),
        extracted(country_of_origin="USA"),
    )

    assert result_for_field(result, "country_of_origin").status == "PASS"


def test_usa_punctuation_matches_united_states_of_america() -> None:
    result = verify_label(
        application(country_of_origin="U.S.A."),
        extracted(country_of_origin="United States of America"),
    )

    assert result_for_field(result, "country_of_origin").status == "PASS"


def test_direct_country_equality_passes_case_insensitively() -> None:
    result = verify_label(
        application(country_of_origin="France"),
        extracted(country_of_origin="france"),
    )

    assert result_for_field(result, "country_of_origin").status == "PASS"


def test_expanded_country_synonyms_pass() -> None:
    examples = [
        ("France", "French Republic"),
        ("Italy", "Republic of Italy"),
        ("Spain", "España"),
        ("Germany", "Deutschland"),
        ("Portugal", "Portuguese Republic"),
        ("Australia", "Commonwealth of Australia"),
    ]

    for expected, found in examples:
        result = verify_label(
            application(country_of_origin=expected),
            extracted(country_of_origin=found),
        )

        assert result_for_field(result, "country_of_origin").status == "PASS"


def test_different_countries_fail() -> None:
    result = verify_label(
        application(country_of_origin="France"),
        extracted(country_of_origin="Germany"),
    )

    assert result_for_field(result, "country_of_origin").status == "FAIL"


def test_extracted_bare_abv_number_fails_without_context() -> None:
    result = verify_label(application(abv="13.5%"), extracted(abv="13.5"))

    assert result_for_field(result, "abv").status == "FAIL"


def test_alc_by_vol_matches_plain_abv() -> None:
    result = verify_label(
        application(abv="13.5"),
        extracted(abv="ALC. 13.5% BY VOL."),
    )

    assert result_for_field(result, "abv").status == "PASS"


def test_proof_statement_abv_matches_percent() -> None:
    result = verify_label(
        application(abv="45%"),
        extracted(abv="45% Alc./Vol. (90 Proof)"),
    )

    assert result_for_field(result, "abv").status == "PASS"


def test_proof_only_abv_is_divided_by_two() -> None:
    result = verify_label(application(abv="45%"), extracted(abv="90 Proof"))

    assert result_for_field(result, "abv").status == "PASS"


def test_proof_only_does_not_match_same_numeric_abv() -> None:
    result = verify_label(application(abv="90%"), extracted(abv="90 Proof"))

    assert result_for_field(result, "abv").status == "FAIL"


def test_bare_number_without_abv_context_fails() -> None:
    result = verify_label(application(abv="13.5%"), extracted(abv="Batch No. 13.5"))

    assert result_for_field(result, "abv").status == "FAIL"


def test_abv_difference_within_tolerance_passes() -> None:
    result = verify_label(application(abv="13.5"), extracted(abv="13.6%"))

    assert result_for_field(result, "abv").status == "PASS"


def test_abv_difference_greater_than_tolerance_fails() -> None:
    result = verify_label(application(abv="13.5"), extracted(abv="13.7%"))

    assert result_for_field(result, "abv").status == "FAIL"


def test_missing_or_unparseable_abv_fails() -> None:
    missing = verify_label(application(), extracted(abv=None))
    unparseable = verify_label(application(), extracted(abv="not listed"))

    assert result_for_field(missing, "abv").status == "FAIL"
    assert result_for_field(unparseable, "abv").status == "FAIL"


def test_net_contents_spacing_and_case_normalization_passes() -> None:
    result = verify_label(
        application(net_contents="750 mL"),
        extracted(net_contents="750ml"),
    )

    assert result_for_field(result, "net_contents").status == "PASS"


def test_net_contents_ml_case_variant_passes() -> None:
    result = verify_label(
        application(net_contents="750 ml"),
        extracted(net_contents="750mL"),
    )

    assert result_for_field(result, "net_contents").status == "PASS"


def test_liters_convert_to_milliliters() -> None:
    result = verify_label(
        application(net_contents="0.75 L"),
        extracted(net_contents="750 ml"),
    )

    assert result_for_field(result, "net_contents").status == "PASS"


def test_centiliters_convert_to_milliliters() -> None:
    result = verify_label(
        application(net_contents="75 cl"),
        extracted(net_contents="750 ml"),
    )

    assert result_for_field(result, "net_contents").status == "PASS"


def test_fluid_ounces_convert_within_one_ml() -> None:
    result = verify_label(
        application(net_contents="750 ml"),
        extracted(net_contents="25.36 fl oz"),
    )

    assert result_for_field(result, "net_contents").status == "PASS"


def test_different_bottle_sizes_fail() -> None:
    result = verify_label(
        application(net_contents="750 ml"),
        extracted(net_contents="1 L"),
    )

    assert result_for_field(result, "net_contents").status == "FAIL"


def test_missing_or_unparseable_net_contents_fails() -> None:
    missing = verify_label(application(), extracted(net_contents=None))
    unparseable = verify_label(application(), extracted(net_contents="bottle"))

    assert result_for_field(missing, "net_contents").status == "FAIL"
    assert result_for_field(unparseable, "net_contents").status == "FAIL"


def test_correct_all_caps_government_warning_passes() -> None:
    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=WARNING),
    )

    assert result_for_field(result, "government_warning").status == "PASS"


def test_exact_government_warning_passes() -> None:
    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=WARNING),
    )

    assert result_for_field(result, "government_warning").status == "PASS"


def test_government_warning_title_case_passes_case_insensitive_comparison() -> None:
    title_case_warning = WARNING.title()

    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=title_case_warning),
    )

    warning = result_for_field(result, "government_warning")
    assert warning.status == "PASS"
    assert warning.expected == WARNING
    assert warning.found == title_case_warning


def test_government_warning_case_difference_passes() -> None:
    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=WARNING.lower()),
    )

    assert result_for_field(result, "government_warning").status == "PASS"


def test_government_warning_mixed_case_ocr_noise_passes() -> None:
    mixed_case_warning = WARNING.replace("DEFECTS", "DEFects", 1)

    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=mixed_case_warning),
    )

    warning = result_for_field(result, "government_warning")
    assert warning.status == "PASS"
    assert warning.match_type == "EXACT_CASE_INSENSITIVE"


def test_government_warning_missing_colon_fails() -> None:
    missing_colon = WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT WARNING", 1)

    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=missing_colon),
    )

    warning = result_for_field(result, "government_warning")
    assert warning.status == "FAIL"
    assert warning.found == missing_colon


def test_government_warning_punctuation_difference_fails() -> None:
    punctuation_difference = WARNING.replace("PROBLEMS.", "PROBLEMS!", 1)

    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=punctuation_difference),
    )

    assert result_for_field(result, "government_warning").status == "FAIL"


def test_government_warning_leading_and_trailing_whitespace_is_ignored() -> None:
    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=f"  {WARNING}\n"),
    )

    assert result_for_field(result, "government_warning").status == "PASS"


def test_government_warning_internal_whitespace_is_collapsed() -> None:
    spaced_warning = WARNING.replace(
        "SURGEON GENERAL, WOMEN SHOULD",
        "SURGEON GENERAL,\n\tWOMEN   SHOULD",
        1,
    )

    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=spaced_warning),
    )

    assert result_for_field(result, "government_warning").status == "PASS"


def test_misread_government_warning_returns_extracted_text() -> None:
    misread = WARNING.replace("SURGEON", "S URGE0N", 1)

    result = verify_label(
        application(government_warning=WARNING),
        extracted(government_warning=misread),
    )

    warning = result_for_field(result, "government_warning")
    assert warning.status == "FAIL"
    assert warning.found == misread


def test_all_fields_passing_returns_approved() -> None:
    result = verify_label(application(), extracted())

    assert result.overall_verdict == "APPROVED"


def test_one_failed_field_returns_needs_review() -> None:
    result = verify_label(application(), extracted(brand_name="Wrong Brand"))

    assert result.overall_verdict == "NEEDS_REVIEW"


def test_batch_summary_counts_passed_needs_review_and_total() -> None:
    batch = verify_batch(
        [
            (application(), extracted()),
            (application(), extracted(brand_name="Wrong Brand")),
        ]
    )

    assert batch.summary == {
        "passed": 1,
        "needs_review": 1,
        "total": 2,
    }
