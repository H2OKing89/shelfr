"""
Audible URL builders for region-aware source links.

Phase 10.3: Source provenance requires building correct Audible URLs
based on the region where an ASIN was resolved.
"""

from __future__ import annotations

from shelfr.utils.validation import is_valid_asin

# Audible domains by region code
# These match the regions supported by the Audnex API
AUDIBLE_DOMAINS: dict[str, str] = {
    "us": "www.audible.com",
    "uk": "www.audible.co.uk",
    "au": "www.audible.com.au",
    "ca": "www.audible.ca",
    "de": "www.audible.de",
    "es": "www.audible.es",
    "fr": "www.audible.fr",
    "in": "www.audible.in",
    "it": "www.audible.it",
    "jp": "www.audible.co.jp",
}

# Default region when none specified
DEFAULT_REGION = "us"


def build_audible_url(asin: str, region: str = DEFAULT_REGION) -> str:
    """Build a region-correct Audible product URL.

    Args:
        asin: Audible ASIN (e.g., "B08G9PRS1K")
        region: Region code (e.g., "us", "uk", "de"). Defaults to "us".

    Returns:
        Full Audible URL (e.g., "https://www.audible.co.uk/pd/B08G9PRS1K")

    Raises:
        ValueError: If ASIN format is invalid.

    Examples:
        >>> build_audible_url("B08G9PRS1K")
        'https://www.audible.com/pd/B08G9PRS1K'

        >>> build_audible_url("B08G9PRS1K", "uk")
        'https://www.audible.co.uk/pd/B08G9PRS1K'

        >>> build_audible_url("B08G9PRS1K", "de")
        'https://www.audible.de/pd/B08G9PRS1K'
    """
    # Validate ASIN format
    if not is_valid_asin(asin):
        raise ValueError(
            f"Invalid ASIN format: '{asin}'. Expected format: B followed by 9 alphanumeric chars."
        )

    # Normalize region to lowercase
    region_lower = region.lower() if region else DEFAULT_REGION

    # Get domain for region, fall back to US if unknown
    domain = AUDIBLE_DOMAINS.get(region_lower, AUDIBLE_DOMAINS[DEFAULT_REGION])

    return f"https://{domain}/pd/{asin}"


def get_audible_domain(region: str = DEFAULT_REGION) -> str:
    """Get the Audible domain for a region.

    Args:
        region: Region code (e.g., "us", "uk"). Defaults to "us".

    Returns:
        Domain without protocol (e.g., "www.audible.co.uk")
    """
    region_lower = region.lower() if region else DEFAULT_REGION
    return AUDIBLE_DOMAINS.get(region_lower, AUDIBLE_DOMAINS[DEFAULT_REGION])


def is_valid_audible_region(region: str | None) -> bool:
    """Check if a region code is valid for Audible.

    Args:
        region: Region code to validate (None returns False)

    Returns:
        True if region is supported by Audible/Audnex
    """
    return region.lower() in AUDIBLE_DOMAINS if region else False
