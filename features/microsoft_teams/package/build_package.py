"""Build a generic Teams 1.25 bot package without resource-specific consent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
from urllib.parse import urlparse
from uuid import UUID
import zlib
import zipfile


MANIFEST_SCHEMA = "https://developer.microsoft.com/json-schemas/teams/v1.25/MicrosoftTeams.schema.json"


def _require_guid(value: str, label: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a GUID") from exc


def _require_https_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an HTTPS URL")
    return value


def _png(width: int, height: int, pixel: bytes) -> bytes:
    """Create a small RGBA PNG with only the standard library."""
    raw = b"".join(b"\0" + pixel * width for _ in range(height))

    def chunk(kind: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _manifest(
    *,
    app_id: str,
    bot_app_id: str,
    name: str,
    developer_name: str,
    website_url: str,
    privacy_url: str,
    terms_url: str,
    valid_domains: list[str],
) -> dict:
    return {
        "$schema": MANIFEST_SCHEMA,
        "manifestVersion": "1.25",
        "version": "1.0.0",
        "id": app_id,
        "developer": {
            "name": developer_name,
            "websiteUrl": website_url,
            "privacyUrl": privacy_url,
            "termsOfUseUrl": terms_url,
        },
        "name": {"short": name, "full": name},
        "description": {
            "short": "A Bifrost-connected Microsoft Teams bot.",
            "full": "A Bifrost-connected Microsoft Teams bot package for this provider.",
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "accentColor": "#464EB8",
        "bots": [
            {
                "botId": bot_app_id,
                "scopes": ["personal", "team", "groupChat"],
                "isNotificationOnly": False,
            }
        ],
        "validDomains": valid_domains,
        "webApplicationInfo": {
            "id": bot_app_id,
            "resource": f"api://{bot_app_id}",
        },
    }


def build_package(
    *,
    output: Path,
    app_id: str,
    bot_app_id: str,
    name: str,
    developer_name: str,
    website_url: str,
    privacy_url: str,
    terms_url: str,
    valid_domains: list[str],
) -> Path:
    """Write a upload-ready Teams app ZIP and return its path."""
    app_id = _require_guid(app_id, "app_id")
    bot_app_id = _require_guid(bot_app_id, "bot_app_id")
    if not name.strip() or not developer_name.strip():
        raise ValueError("name and developer_name are required")
    website_url = _require_https_url(website_url, "website_url")
    privacy_url = _require_https_url(privacy_url, "privacy_url")
    terms_url = _require_https_url(terms_url, "terms_url")
    if not valid_domains or any(not value.strip() for value in valid_domains):
        raise ValueError("at least one valid domain is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(
        app_id=app_id,
        bot_app_id=bot_app_id,
        name=name.strip(),
        developer_name=developer_name.strip(),
        website_url=website_url,
        privacy_url=privacy_url,
        terms_url=terms_url,
        valid_domains=valid_domains,
    )
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        package.writestr("color.png", _png(192, 192, b"\x46\x4e\xb8\xff"))
        package.writestr("outline.png", _png(32, 32, b"\xff\xff\xff\xff"))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-id", required=True, help="Teams package GUID")
    parser.add_argument("--bot-app-id", required=True, help="Azure Bot / client GUID")
    parser.add_argument("--name", required=True, help="Teams app display name")
    parser.add_argument("--developer-name", required=True)
    parser.add_argument("--website-url", required=True)
    parser.add_argument("--privacy-url", required=True)
    parser.add_argument("--terms-url", required=True)
    parser.add_argument("--valid-domain", action="append", required=True)
    args = parser.parse_args()
    build_package(
        output=args.output,
        app_id=args.app_id,
        bot_app_id=args.bot_app_id,
        name=args.name,
        developer_name=args.developer_name,
        website_url=args.website_url,
        privacy_url=args.privacy_url,
        terms_url=args.terms_url,
        valid_domains=args.valid_domain,
    )


if __name__ == "__main__":
    main()
