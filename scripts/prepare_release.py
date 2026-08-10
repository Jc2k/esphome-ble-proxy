#!/usr/bin/env python3
"""Build all versioned streams and prepare GitHub Release and Pages assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from firmware_security import ROOT, STREAMS, FirmwareStream, VerifiedBuild, validate_version, verify_build


REPOSITORY_URL = "https://github.com/Jc2k/esphome-ble-proxy"
PAGES_URL = "https://unrouted.uk/esphome-ble-proxy"


def versioned_config(stream: FirmwareStream, version: str) -> Path:
    validate_version(version)
    source = stream.release_config.read_text()
    marker = 'firmware_version: "0.0.0"'
    if source.count(marker) != 1:
        raise RuntimeError(f"expected exactly one {marker!r} in {stream.release_config}")

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=stream.release_config.parent,
        prefix=".release-",
        suffix=".yaml",
        delete=False,
    )
    with handle:
        handle.write(source.replace(marker, f'firmware_version: "{version}"'))
    return Path(handle.name)


def build_stream(stream: FirmwareStream, version: str) -> VerifiedBuild:
    if not stream.signing_key.is_file():
        raise FileNotFoundError(f"missing stream signing key: {stream.signing_key}")
    config = versioned_config(stream, version)
    try:
        subprocess.run(
            [sys.executable, "-m", "esphome", "compile", str(config)],
            cwd=ROOT,
            check=True,
        )
    finally:
        config.unlink(missing_ok=True)
    return verify_build(stream)


def prepare_assets(version: str, builds: list[VerifiedBuild]) -> None:
    release_assets = ROOT / "release-assets"
    site = ROOT / "site"
    shutil.rmtree(release_assets, ignore_errors=True)
    shutil.rmtree(site, ignore_errors=True)
    release_assets.mkdir()
    checksums: list[str] = []

    for build in builds:
        stream = build.stream
        version_dir = site / "firmware" / stream.slug / f"v{version}"
        version_dir.mkdir(parents=True)

        ota_name = "firmware.bin"
        factory_name = "firmware.factory.bin"
        pages_ota = version_dir / ota_name
        pages_factory = version_dir / factory_name
        asset_ota = release_assets / f"{stream.slug}.firmware.bin"
        asset_factory = release_assets / f"{stream.slug}.firmware.factory.bin"
        shutil.copy2(build.ota_firmware, pages_ota)
        shutil.copy2(build.factory_firmware, pages_factory)
        shutil.copy2(build.ota_firmware, asset_ota)
        shutil.copy2(build.factory_firmware, asset_factory)

        digest = hashlib.md5(build.ota_firmware.read_bytes(), usedforsecurity=False).hexdigest()
        manifest = {
            "name": stream.display_name,
            "version": version,
            "builds": [
                {
                    "chipFamily": "ESP32",
                    "ota": {
                        "md5": digest,
                        "path": f"{PAGES_URL}/firmware/{stream.slug}/v{version}/{ota_name}",
                        "release_url": f"{REPOSITORY_URL}/releases/tag/v{version}",
                        "summary": f"{stream.display_name} v{version}",
                    },
                }
            ],
        }
        manifest_text = json.dumps(manifest, indent=2) + "\n"
        (site / "firmware" / stream.slug / "manifest.json").write_text(manifest_text)
        (release_assets / f"{stream.slug}.manifest.json").write_text(manifest_text)

        for asset in (asset_ota, asset_factory):
            sha256 = hashlib.sha256(asset.read_bytes()).hexdigest()
            checksums.append(f"{sha256}  {asset.name}")

    (release_assets / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    (site / ".nojekyll").touch()
    links = "\n".join(
        f'<li><a href="firmware/{stream.slug}/manifest.json">{stream.display_name}</a></li>'
        for stream in STREAMS.values()
    )
    (site / "index.html").write_text(
        "<!doctype html>\n"
        '<html lang="en"><meta charset="utf-8">\n'
        "<title>ESPHome BLE proxy firmware</title>\n"
        "<h1>ESPHome BLE proxy firmware</h1>\n"
        f'<p>Latest release: <a href="{REPOSITORY_URL}/releases/tag/v{version}">v{version}</a></p>\n'
        "<p>Signed, credential-free firmware streams:</p>\n"
        f"<ul>{links}</ul>\n"
        "<p>Existing devices must receive their private migration image first.</p>\n"
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} VERSION")
    version = sys.argv[1]
    validate_version(version)
    builds = [build_stream(stream, version) for stream in STREAMS.values()]
    prepare_assets(version, builds)


if __name__ == "__main__":
    main()
