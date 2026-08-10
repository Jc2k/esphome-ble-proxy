#!/usr/bin/env python3
"""Build-time checks shared by release and private migration workflows."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class FirmwareStream:
    slug: str
    display_name: str
    release_config: Path
    bridge_config: Path
    migration_config: Path
    build_name: str
    bridge_build_name: str
    migration_build_name: str
    signing_key: Path


def _stream(slug: str, display_name: str) -> FirmwareStream:
    return FirmwareStream(
        slug=slug,
        display_name=display_name,
        release_config=ROOT / "firmware" / f"{slug}.release.yaml",
        bridge_config=ROOT / "migrations" / f"{slug}.bridge.yaml",
        migration_config=ROOT / "migrations" / f"{slug}.migration.yaml",
        build_name=slug,
        bridge_build_name=f"{slug}-bridge",
        migration_build_name=f"{slug}-migration",
        signing_key=ROOT / f".firmware-signing-key-{slug}.pem",
    )


STREAMS = {
    stream.slug: stream
    for stream in (
        _stream("ip101-ethernet", "BLE Proxy IP101 Ethernet"),
        _stream("ip101-wifi", "BLE Proxy IP101 Wi-Fi"),
        _stream("pico32-wifi", "BLE Proxy PICO32 Wi-Fi"),
    )
}


@dataclass(frozen=True)
class VerifiedBuild:
    stream: FirmwareStream
    ota_firmware: Path
    factory_firmware: Path


def build_directory(stream: FirmwareStream, migration: bool) -> Path:
    config = stream.migration_config if migration else stream.release_config
    name = stream.migration_build_name if migration else stream.build_name
    return config.parent / ".esphome" / "build" / name / "build"


def _verify_signature(image: Path, signing_key: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "espsecure",
            "verify-signature",
            "--version",
            "1",
            "--keyfile",
            str(signing_key),
            str(image),
        ],
        cwd=ROOT,
        check=True,
    )


def verify_build(stream: FirmwareStream, migration: bool = False) -> VerifiedBuild:
    build = build_directory(stream, migration)
    ota_firmware = build / "firmware.ota.bin"
    factory_firmware = build / "firmware.factory.bin"
    generated_main = build.parent / "src" / "main.cpp"

    for path in (stream.signing_key, ota_firmware, factory_firmware, generated_main):
        if not path.is_file():
            raise FileNotFoundError(f"missing build input: {path}")

    _verify_signature(ota_firmware, stream.signing_key)

    generated = generated_main.read_text()
    setter = "->set_api_encryption_key("
    wifi_action = "WiFiConfigureAction"
    wifi_save = "->set_save("
    if migration:
        if setter not in generated:
            raise RuntimeError("migration firmware does not persist the API encryption key")
        if stream.slug.endswith("wifi") and (
            wifi_action not in generated or wifi_save not in generated
        ):
            raise RuntimeError("Wi-Fi migration firmware does not persist Wi-Fi credentials")
    else:
        if setter in generated:
            raise RuntimeError("public firmware embeds an API encryption key")
        if wifi_action in generated:
            raise RuntimeError("public firmware embeds a Wi-Fi provisioning action")

    return VerifiedBuild(stream, ota_firmware, factory_firmware)


def validate_private_inputs(stream: FirmwareStream, secrets_path: Path) -> None:
    if not stream.signing_key.is_file():
        raise FileNotFoundError(f"missing stream signing key: {stream.signing_key}")
    if not secrets_path.is_file():
        raise FileNotFoundError(f"missing migration secrets: {secrets_path}")

    secrets = yaml.safe_load(secrets_path.read_text())
    if not isinstance(secrets, dict):
        raise ValueError("secrets.yaml must contain a mapping")

    api_key = secrets.get("api_encryption_key")
    if not isinstance(api_key, str):
        raise ValueError("api_encryption_key must be a base64 string")
    try:
        decoded = base64.b64decode(api_key, validate=True)
    except binascii.Error as error:
        raise ValueError("api_encryption_key is not valid base64") from error
    if len(decoded) != 32 or not any(decoded):
        raise ValueError("api_encryption_key must be a nonzero 32-byte key")

    ota_password = secrets.get("legacy_ota_password")
    if not isinstance(ota_password, str) or len(ota_password) < 12 or "replace" in ota_password:
        raise ValueError("legacy_ota_password is missing or looks like a placeholder")

    if stream.slug.endswith("wifi"):
        for key in ("wifi_ssid", "wifi_password"):
            value = secrets.get(key)
            if not isinstance(value, str) or not value or "replace" in value:
                raise ValueError(f"{key} is missing or looks like a placeholder")


def validate_version(version: str) -> None:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError(f"invalid semantic version: {version!r}")
