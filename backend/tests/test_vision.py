import base64
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.verification.models import ExtractedLabel
from app.vision import (
    DEFAULT_JPEG_QUALITY,
    DEFAULT_TIMEOUT_SECONDS,
    FakeVisionService,
    ImagePreprocessor,
    OpenAIVisionService,
    VisionAPIError,
    VisionConfigurationError,
    VisionImageValidationError,
    VisionParseError,
    extract_label_with_timeout_sync,
)


WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD "
    "NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE RISK OF "
    "BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR "
    "ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH "
    "PROBLEMS."
)


@pytest.fixture(autouse=True)
def configured_openai_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "test-model")


class FakeOpenAIResponses:
    def __init__(
        self,
        response: Any | None = None,
        exception: Exception | None = None,
        side_effects: list[Any] | None = None,
    ):
        self.response = response
        self.exception = exception
        self.side_effects = side_effects or []
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.side_effects:
            effect = self.side_effects.pop(0)
            if callable(effect):
                effect = effect()
            if isinstance(effect, Exception):
                raise effect
            return effect
        if self.exception is not None:
            raise self.exception
        return self.response


class FakeOpenAIClient:
    def __init__(
        self,
        response: Any | None = None,
        exception: Exception | None = None,
        side_effects: list[Any] | None = None,
    ):
        self.responses = FakeOpenAIResponses(response, exception, side_effects)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def label(**overrides: Any) -> ExtractedLabel:
    data = {
        "brand_name": "Acme Estate",
        "class_type": "Red Wine",
        "abv": "13.5%",
        "net_contents": "750 mL",
        "producer": "Acme Cellars",
        "country_of_origin": "United States",
        "government_warning": WARNING,
        "raw_text": "ACME ESTATE RED WINE ALC. 13.5% BY VOL. 750 mL",
        "extraction_confidence": 0.98,
    }
    data.update(overrides)
    return ExtractedLabel(**data)


def image_bytes(size: tuple[int, int] = (320, 240), mode: str = "RGB") -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new(mode, size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "ACME ESTATE\nRED WINE\nALC. 13.5% BY VOL.", fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def heic_image_bytes(size: tuple[int, int] = (320, 240)) -> bytes:
    from PIL import Image, ImageDraw
    from pillow_heif import register_heif_opener

    register_heif_opener()
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "ACME ESTATE\nRED WINE\nALC. 13.5% BY VOL.", fill="black")
    output = BytesIO()
    image.save(output, format="HEIF")
    return output.getvalue()


def openai_response(parsed: Any | None = None) -> SimpleNamespace:
    return SimpleNamespace(output_parsed=parsed)


def test_openai_service_returns_parsed_extracted_label() -> None:
    expected = label()
    client = FakeOpenAIClient(openai_response(parsed=expected))
    service = OpenAIVisionService(client=client, model="test-model")

    actual = service.extract_label(image_bytes(), "image/png")

    assert actual == expected


def test_openai_request_uses_env_model_schema_and_base64_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "vision-test-model")
    client = FakeOpenAIClient(openai_response(parsed=label()))
    service = OpenAIVisionService(client=client)

    service.extract_label(image_bytes(), "image/png")

    call = client.responses.calls[0]
    assert call["model"] == "vision-test-model"
    assert DEFAULT_TIMEOUT_SECONDS == 4.6
    assert call["text_format"] is ExtractedLabel
    assert call["store"] is False
    content = call["input"][0]["content"]
    assert content[0]["text"].startswith("Extract visible TTB alcohol label fields")
    assert content[1]["type"] == "input_image"
    assert content[1]["detail"] == "high"
    prefix, encoded = content[1]["image_url"].split(",", 1)
    assert prefix == "data:image/jpeg;base64"
    assert base64.b64decode(encoded).startswith(b"\xff\xd8")


def test_openai_model_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "openai-test")
    service = OpenAIVisionService(
        client=FakeOpenAIClient(openai_response(parsed=label()))
    )

    assert service.model == "openai-test"


def test_openai_reasoning_effort_is_optional_and_env_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "none")
    client = FakeOpenAIClient(openai_response(parsed=label()))
    service = OpenAIVisionService(client=client)

    service.extract_label(image_bytes(), "image/png")

    assert client.responses.calls[0]["reasoning"] == {"effort": "none"}


def test_openai_malformed_structured_output_raises_parse_error() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(openai_response(parsed={"brand_name": "Acme"})),
        model="test-model",
    )

    with pytest.raises(VisionParseError):
        service.extract_label(image_bytes())


def test_openai_sdk_exception_translates_to_api_error() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(exception=RuntimeError("quota")),
        model="test-model",
    )

    with pytest.raises(VisionAPIError):
        service.extract_label(image_bytes())


def test_openai_retryable_error_retries_once_within_timeout_budget() -> None:
    class APIConnectionError(Exception):
        pass

    expected = label()
    client = FakeOpenAIClient(
        side_effects=[
            APIConnectionError("temporary"),
            openai_response(parsed=expected),
        ]
    )
    service = OpenAIVisionService(client=client, model="test-model")

    actual = service.extract_label(image_bytes())

    assert actual == expected
    assert len(client.responses.calls) == 2
    assert 4.0 < client.responses.calls[0]["timeout"] < DEFAULT_TIMEOUT_SECONDS
    assert 2.25 <= client.responses.calls[1]["timeout"] < DEFAULT_TIMEOUT_SECONDS


def test_openai_retryable_5xx_retries_once() -> None:
    class APIStatusError(Exception):
        status_code = 503

    expected = label()
    client = FakeOpenAIClient(
        side_effects=[
            APIStatusError("temporary"),
            openai_response(parsed=expected),
        ]
    )
    service = OpenAIVisionService(client=client, model="test-model")

    assert service.extract_label(image_bytes()) == expected
    assert len(client.responses.calls) == 2


@pytest.mark.parametrize(
    ("exception_name", "status_code"),
    [
        ("TimeoutError", None),
        ("APITimeoutError", None),
        ("RateLimitError", 429),
        ("BadRequestError", 400),
    ],
)
def test_openai_timeout_and_4xx_errors_do_not_retry(
    exception_name: str,
    status_code: int | None,
) -> None:
    exception_type = type(exception_name, (Exception,), {})
    exception = exception_type("do not retry")
    if status_code is not None:
        exception.status_code = status_code
    client = FakeOpenAIClient(exception=exception)
    service = OpenAIVisionService(client=client, model="test-model")

    with pytest.raises(VisionAPIError):
        service.extract_label(image_bytes())

    assert len(client.responses.calls) == 1


def test_openai_skips_retry_when_failure_leaves_too_little_time() -> None:
    class APIStatusError(Exception):
        status_code = 503

    def slow_failure() -> Exception:
        time.sleep(0.2)
        return APIStatusError("late failure")

    client = FakeOpenAIClient(
        side_effects=[slow_failure, openai_response(parsed=label())]
    )
    service = OpenAIVisionService(client=client, model="test-model")

    with pytest.raises(VisionAPIError):
        service.extract_label(
            image_bytes(),
            deadline=time.monotonic() + 2.5,
        )

    assert len(client.responses.calls) == 1


def test_preprocessing_reduces_provider_timeout() -> None:
    class DelayedPreprocessor:
        def process(self, data: bytes, content_type: str | None = None):
            time.sleep(0.08)
            return ImagePreprocessor().process(data, content_type)

    client = FakeOpenAIClient(openai_response(parsed=label()))
    service = OpenAIVisionService(
        client=client,
        model="test-model",
        preprocessor=DelayedPreprocessor(),
    )

    service.extract_label(
        image_bytes(),
        deadline=time.monotonic() + 0.4,
    )

    assert 0.1 < client.responses.calls[0]["timeout"] < 0.25


def test_openai_non_retryable_error_does_not_retry() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(exception=RuntimeError("quota")),
        model="test-model",
    )

    with pytest.raises(VisionAPIError):
        service.extract_label(image_bytes())

    assert len(service.client.responses.calls) == 1


def test_openai_service_closes_shared_client() -> None:
    client = FakeOpenAIClient(openai_response(parsed=label()))
    service = OpenAIVisionService(client=client, model="test-model")

    service.close()

    assert client.closed is True


def test_production_vision_service_is_reused_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.vision import dependencies

    client = FakeOpenAIClient(openai_response(parsed=label()))
    service = OpenAIVisionService(client=client, model="test-model")
    dependencies.get_vision_service.cache_clear()
    monkeypatch.setattr(dependencies, "OpenAIVisionService", lambda: service)

    assert dependencies.get_vision_service() is service
    assert dependencies.get_vision_service() is service

    dependencies.close_vision_service()

    assert client.closed is True
    assert dependencies.get_vision_service.cache_info().currsize == 0


def test_openai_missing_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    with pytest.raises(VisionConfigurationError):
        OpenAIVisionService()


def test_openai_missing_model_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(VisionConfigurationError):
        OpenAIVisionService(client=FakeOpenAIClient(openai_response(parsed=label())))


def test_openai_client_disables_retries_and_uses_service_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openai

    captured: dict[str, Any] = {}

    def fake_openai(**kwargs: Any) -> FakeOpenAIClient:
        captured.update(kwargs)
        return FakeOpenAIClient(openai_response(parsed=label()))

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    service = OpenAIVisionService(
        api_key="test-key",
        model="test-model",
        timeout_seconds=1.25,
    )

    assert isinstance(service.client, FakeOpenAIClient)
    assert captured == {
        "api_key": "test-key",
        "timeout": 1.25,
        "max_retries": 0,
    }


def test_unknown_fields_remain_none() -> None:
    expected = label(producer=None, country_of_origin=None)
    service = OpenAIVisionService(
        client=FakeOpenAIClient(openai_response(parsed=expected))
    )

    actual = service.extract_label(image_bytes())

    assert actual.producer is None
    assert actual.country_of_origin is None


def test_government_warning_is_preserved_verbatim() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(openai_response(parsed=label()))
    )

    actual = service.extract_label(image_bytes())

    assert actual.government_warning == WARNING


def test_incomplete_government_warning_can_return_none() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(
            openai_response(parsed=label(government_warning=None))
        )
    )

    actual = service.extract_label(image_bytes())

    assert actual.government_warning is None


def test_null_like_government_warning_string_becomes_none() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(
            openai_response(parsed=label(government_warning="null"))
        )
    )

    actual = service.extract_label(image_bytes())

    assert actual.government_warning is None


def test_partial_blurry_response_returns_partial_label() -> None:
    partial = label(
        class_type=None,
        producer=None,
        government_warning=None,
        extraction_confidence=0.36,
    )
    service = OpenAIVisionService(
        client=FakeOpenAIClient(openai_response(parsed=partial))
    )

    actual = service.extract_label(image_bytes())

    assert actual.brand_name == "Acme Estate"
    assert actual.class_type is None
    assert actual.extraction_confidence == 0.36


def test_non_label_image_returns_null_fields_and_low_confidence() -> None:
    non_label = ExtractedLabel(
        brand_name=None,
        class_type=None,
        abv=None,
        net_contents=None,
        producer=None,
        country_of_origin=None,
        government_warning=None,
        raw_text=None,
        extraction_confidence=0.0,
    )
    service = OpenAIVisionService(
        client=FakeOpenAIClient(openai_response(parsed=non_label))
    )

    actual = service.extract_label(image_bytes())

    assert actual.brand_name is None
    assert actual.government_warning is None
    assert actual.extraction_confidence == 0.0


def test_preprocessor_downscales_converts_to_jpeg_and_preserves_aspect_ratio() -> None:
    processed = ImagePreprocessor(max_long_edge=2048).process(image_bytes((4096, 2048)))

    assert processed.content_type == "image/jpeg"
    assert processed.width == 2048
    assert processed.height == 1024
    assert processed.data[:2] == b"\xff\xd8"


def test_preprocessor_does_not_upscale_small_images() -> None:
    processed = ImagePreprocessor(max_long_edge=2048).process(image_bytes((300, 200)))

    assert processed.width == 300
    assert processed.height == 200


def test_preprocessor_accepts_heic_uploads() -> None:
    processed = ImagePreprocessor(max_long_edge=2048).process(
        heic_image_bytes((300, 200)),
        "image/heic",
    )

    assert processed.content_type == "image/jpeg"
    assert processed.width == 300
    assert processed.height == 200
    assert processed.data[:2] == b"\xff\xd8"


def test_preprocessor_default_max_edge_is_latency_optimized() -> None:
    processed = ImagePreprocessor().process(image_bytes((3200, 2400)))

    assert DEFAULT_JPEG_QUALITY == 80
    assert processed.width == 1152
    assert processed.height == 864


def test_invalid_image_bytes_raise_validation_error_without_api_call() -> None:
    client = FakeOpenAIClient(openai_response(parsed=label()))
    service = OpenAIVisionService(client=client)

    with pytest.raises(VisionImageValidationError):
        service.extract_label(b"not an image")

    assert client.responses.calls == []


def test_api_timeout_translates_to_service_exception() -> None:
    service = OpenAIVisionService(
        client=FakeOpenAIClient(exception=TimeoutError("slow"))
    )

    with pytest.raises(VisionAPIError):
        service.extract_label(image_bytes())


def test_openai_api_timeout_translates_to_service_exception() -> None:
    class APITimeoutError(Exception):
        pass

    service = OpenAIVisionService(
        client=FakeOpenAIClient(exception=APITimeoutError("slow"))
    )

    with pytest.raises(VisionAPIError, match="timed out"):
        service.extract_label(image_bytes())


def test_missing_parsed_output_raises_parse_error() -> None:
    service = OpenAIVisionService(client=FakeOpenAIClient(openai_response()))

    with pytest.raises(VisionParseError):
        service.extract_label(image_bytes())


def test_openai_refusal_without_parsed_output_raises_parse_error() -> None:
    refusal = SimpleNamespace(
        output_parsed=None,
        output=[{"type": "message", "content": [{"type": "refusal"}]}],
    )
    service = OpenAIVisionService(client=FakeOpenAIClient(refusal))

    with pytest.raises(VisionParseError):
        service.extract_label(image_bytes())


@pytest.mark.parametrize(
    "exception_name",
    ["ContentFilterFinishReasonError", "LengthFinishReasonError"],
)
def test_incomplete_openai_structured_output_raises_parse_error(
    exception_name: str,
) -> None:
    sdk_exception = type(exception_name, (Exception,), {})("incomplete")
    service = OpenAIVisionService(client=FakeOpenAIClient(exception=sdk_exception))

    with pytest.raises(VisionParseError):
        service.extract_label(image_bytes())


def test_fake_vision_service_is_mockable_without_client() -> None:
    fake = FakeVisionService(label(brand_name="Fixture Brand"))

    actual = fake.extract_label(b"bytes", "image/png")

    assert actual.brand_name == "Fixture Brand"
    assert fake.calls == [(b"bytes", "image/png")]


def test_sync_timeout_helper_raises_api_error_for_slow_extraction() -> None:
    class SlowVisionService:
        def extract_label(
            self,
            image_bytes: bytes,
            content_type: str | None = None,
            *,
            deadline: float | None = None,
        ) -> ExtractedLabel:
            time.sleep(0.1)
            return label()

    with pytest.raises(VisionAPIError) as error:
        extract_label_with_timeout_sync(
            SlowVisionService(),
            image_bytes(),
            "image/png",
            timeout_seconds=0.01,
        )

    assert error.value.reason == "endpoint_deadline"


def test_sample_script_mock_mode_returns_populated_label(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import run_vision_sample

        monkeypatch.setattr(
            sys,
            "argv",
            ["run_vision_sample.py", "--mock"],
        )

        exit_code = run_vision_sample.main()
    finally:
        sys.path.remove(str(scripts_dir))

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["brand_name"] == "Acme Estate"
    assert output["government_warning"].startswith("GOVERNMENT WARNING:")
    assert output["extraction_confidence"] > 0


def test_phase6_benchmark_mock_mode_reports_latency_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import benchmark_phase6

        jsonl_path = tmp_path / "benchmark.jsonl"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "benchmark_phase6.py",
                "--mock",
                "--runs",
                "1",
                "--fixture-dir",
                str(tmp_path / "fixtures"),
                "--jsonl",
                str(jsonl_path),
            ],
        )

        exit_code = benchmark_phase6.main()
    finally:
        sys.path.remove(str(scripts_dir))

    output = json.loads(capsys.readouterr().out)
    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert exit_code == 0
    assert output["run_count"] == 7
    assert output["targets"]["warm_single_label_max_ms"] == 5000
    assert len(records) == 7
    assert any(record["error_code"] == "invalid_image" for record in records)
    assert all(record["config"]["provider"] == "fake" for record in records)
