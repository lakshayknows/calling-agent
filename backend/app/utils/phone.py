"""Phone-number normalization helpers."""

from __future__ import annotations

import re


def normalize_number(raw: str, *, default_country_code: str = "91") -> str:
    """Return digits-only E.164-style number (no leading +).

    A bare 10-digit local number gets the default country code prepended
    (India by default). Numbers that already include a country code pass
    through unchanged.
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) <= 10:
        digits = f"{default_country_code}{digits}"
    return digits
