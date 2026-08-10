#!/usr/bin/env python3
"""Build-time checks shared by release and private migration workflows."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import struct
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
    verification_config: Path
    build_name: str
    bridge_build_name: str
    migration_build_name: str
    verification_build_name: str
    signing_key: Path


def _stream(slug: str, display_name: str) -> FirmwareStream:
    return FirmwareStream(
        slug=slug,
        display_name=display_name,
        release_config=ROOT / "firmware" / f"{slug}.release.yaml",
        bridge_config=ROOT / "migrations" / f"{slug}.bridge.yaml",
        migration_config=ROOT / "migrations" / f"{slug}.migration.yaml",
        verification_config=ROOT / "migrations" / f"{slug}.verification.yaml",
        build_name=slug,
        bridge_build_name=f"{slug}-bridge",
        migration_build_name=f"{slug}-migration",
        verification_build_name=f"{slug}-verification",
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


@dataclass(frozen=True)
class PartitionEntry:
    label: str
    type: int
    subtype: int
    offset: int
    size: int


EXPECTED_MANAGED_PARTITIONS = {
    "otadata": PartitionEntry("otadata", 0x01, 0x00, 0x9000, 0x2000),
    "phy_init": PartitionEntry("phy_init", 0x01, 0x01, 0xB000, 0x1000),
    "app0": PartitionEntry("app0", 0x00, 0x10, 0x10000, 0x1C0000),
    "app1": PartitionEntry("app1", 0x00, 0x11, 0x1D0000, 0x1C0000),
    "nvs": PartitionEntry("nvs", 0x01, 0x02, 0x390000, 0x6D000),
}

_PARTITION_ENTRY = struct.Struct("<HBBII16sI")
_PARTITION_MAGIC = 0x50AA
_PARTITION_MD5_MAGIC = 0xEBEB
_PARTITION_TABLE_SIZE = 0xC00


def build_directory(
    stream: FirmwareStream, migration: bool = False, verification: bool = False
) -> Path:
    if migration and verification:
        raise ValueError("a build cannot be both migration and verification")
    if migration:
        config = stream.migration_config
        name = stream.migration_build_name
    elif verification:
        config = stream.verification_config
        name = stream.verification_build_name
    else:
        config = stream.release_config
        name = stream.build_name
    return config.parent / ".esphome" / "build" / name / "build"


def parse_partition_table(
    path: Path, *, allow_trailing_signature: bool = False
) -> dict[str, PartitionEntry]:
    data = path.read_bytes()
    if len(data) < _PARTITION_TABLE_SIZE or (
        len(data) != _PARTITION_TABLE_SIZE and not allow_trailing_signature
    ):
        raise ValueError(
            f"partition table must be {_PARTITION_TABLE_SIZE} bytes, got {len(data)}"
        )
    data = data[:_PARTITION_TABLE_SIZE]

    partitions: dict[str, PartitionEntry] = {}
    checksum_found = False
    for offset in range(0, len(data), _PARTITION_ENTRY.size):
        magic, type_, subtype, address, size, raw_label, _flags = (
            _PARTITION_ENTRY.unpack_from(data, offset)
        )
        if magic == 0xFFFF:
            break
        if magic == _PARTITION_MD5_MAGIC:
            checksum_found = True
            expected_checksum = data[offset + 16 : offset + 32]
            actual_checksum = hashlib.md5(
                data[:offset], usedforsecurity=False
            ).digest()
            if actual_checksum != expected_checksum:
                raise ValueError("partition table MD5 checksum is invalid")
            break
        if magic != _PARTITION_MAGIC:
            raise ValueError(f"invalid partition-table magic 0x{magic:04X} at 0x{offset:X}")
        label = raw_label.split(b"\0", 1)[0].decode("ascii")
        if not label or label in partitions:
            raise ValueError(f"invalid or duplicate partition label: {label!r}")
        partitions[label] = PartitionEntry(label, type_, subtype, address, size)

    if not checksum_found:
        raise ValueError("partition table has no MD5 checksum entry")
    return partitions


def validate_managed_partition_table(
    path: Path, *, allow_trailing_signature: bool = False
) -> None:
    actual = parse_partition_table(
        path, allow_trailing_signature=allow_trailing_signature
    )
    if actual != EXPECTED_MANAGED_PARTITIONS:
        raise ValueError(
            "partition layout does not exactly match the managed layout: "
            f"expected {EXPECTED_MANAGED_PARTITIONS}, got {actual}"
        )


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


def verify_build(
    stream: FirmwareStream, migration: bool = False, verification: bool = False
) -> VerifiedBuild:
    build = build_directory(stream, migration, verification)
    ota_firmware = build / "firmware.ota.bin"
    factory_firmware = build / "firmware.factory.bin"
    partition_table = build / "partition_table" / "partition-table.bin"
    generated_main = build.parent / "src" / "main.cpp"

    for path in (
        stream.signing_key,
        ota_firmware,
        factory_firmware,
        partition_table,
        generated_main,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"missing build input: {path}")

    validate_managed_partition_table(
        partition_table, allow_trailing_signature=True
    )
    _verify_signature(ota_firmware, stream.signing_key)

    generated = generated_main.read_text()
    setter = "->set_api_encryption_key("
    wifi_action = "WiFiConfigureAction"
    wifi_save = "->set_save("
    legacy_ota = "ESPHomeOTAComponent"
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

    if migration or verification:
        if legacy_ota not in generated:
            raise RuntimeError("private transition firmware has no legacy OTA recovery path")
    elif legacy_ota in generated:
        raise RuntimeError("public firmware unexpectedly retains legacy ESPHome OTA")

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
