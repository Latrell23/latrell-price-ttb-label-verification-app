from app.verification.models import ExtractedLabel


class FakeVisionService:
    """Deterministic vision service used by tests and local sample scripts."""

    def __init__(self, label: ExtractedLabel | None = None) -> None:
        """Store the label fixture returned by future extraction calls."""
        self.label = label or ExtractedLabel(
            brand_name="Acme Estate",
            class_type="Red Wine",
            abv="13.5%",
            net_contents="750 mL",
            producer="Acme Cellars",
            country_of_origin="United States",
            government_warning=(
                "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, "
                "WOMEN SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY "
                "BECAUSE OF THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF "
                "ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO DRIVE A CAR OR "
                "OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS."
            ),
            raw_text="ACME ESTATE RED WINE ALC. 13.5% BY VOL. 750 mL",
            extraction_confidence=0.98,
        )
        self.calls: list[tuple[bytes, str | None]] = []

    def extract_label(
        self, image_bytes: bytes, content_type: str | None = None
    ) -> ExtractedLabel:
        """Record the call and return the configured fixture label."""
        self.calls.append((image_bytes, content_type))
        return self.label
