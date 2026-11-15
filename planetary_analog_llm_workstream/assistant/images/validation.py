"""URL, host and content-type validation for image providers.

The assistant never fetches a URL produced by a language model. Every asset URL
must be HTTPS, belong to a documented NASA provider host, and carry no embedded
credentials or non-default port. This blocks SSRF and arbitrary-host fetching.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

NASA_IMAGE_HOSTS = frozenset(
    {"images-api.nasa.gov", "images-assets.nasa.gov", "images.nasa.gov"}
)
GIBS_HOSTS = frozenset({"gibs.earthdata.nasa.gov"})
PDS_HOSTS = frozenset(
    {
        "pds.nasa.gov",
        "pds-geosciences.wustl.edu",
        "oderest.rsl.wustl.edu",
        "planetarydata.jpl.nasa.gov",
        "lroc.sese.asu.edu",
        "hirise.lpl.arizona.edu",
    }
)

PROVIDER_HOSTS: dict[str, frozenset[str]] = {
    "nasa_image_library": NASA_IMAGE_HOSTS,
    "gibs": GIBS_HOSTS,
    "pds": PDS_HOSTS,
}

_IP_LITERAL = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")


class UnsafeAssetURL(ValueError):
    """Raised when a provider URL fails validation."""


def validate_provider_url(url: str, provider: str) -> str:
    """Return a normalised URL or raise ``UnsafeAssetURL``."""

    if not isinstance(url, str) or not url.strip():
        raise UnsafeAssetURL("empty URL")
    candidate = url.strip()
    parts = urlsplit(candidate)

    if parts.scheme != "https":
        raise UnsafeAssetURL(f"only https URLs are allowed, got scheme '{parts.scheme}'")
    if parts.username or parts.password:
        raise UnsafeAssetURL("URL must not embed credentials")
    if parts.port not in (None, 443):
        raise UnsafeAssetURL("URL must not use a non-default port")

    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeAssetURL("URL has no host")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeAssetURL("local hosts are not allowed")
    if _IP_LITERAL.match(host):
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:  # pragma: no cover - defensive
            raise UnsafeAssetURL("invalid IP literal") from exc
        raise UnsafeAssetURL(f"IP literal hosts are not allowed ({address})")

    allowed = PROVIDER_HOSTS.get(provider)
    if allowed is None:
        raise UnsafeAssetURL(f"unknown provider '{provider}'")
    if host not in allowed:
        raise UnsafeAssetURL(f"host '{host}' is not an allowed {provider} host")

    return candidate


def validate_content_type(value: str | None, *, allow_json: bool = False) -> bool:
    if not value:
        return False
    media_type = value.split(";", 1)[0].strip().lower()
    if media_type.startswith("image/"):
        return True
    if allow_json and media_type in {"application/json", "application/hal+json"}:
        return True
    return False


def safe_optional_url(url: str | None, provider: str) -> str | None:
    if not url:
        return None
    return validate_provider_url(url, provider)
