import argparse
from pathlib import Path
import hashlib
import struct
import sys

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from firmware_security import (  # noqa: E402
    EXPECTED_MANAGED_PARTITIONS,
    STREAMS,
    parse_partition_table,
    validate_managed_partition_table,
    validate_private_inputs,
    validate_version,
)
from prepare_device_migration import (  # noqa: E402
    build as build_device_artifacts,
    device_address,
    require_device_credentials,
)


def partition_table_bytes(*, app1_size: int = 0x1C0000, checksum: bool = True) -> bytes:
    entries = []
    for label, entry in EXPECTED_MANAGED_PARTITIONS.items():
        size = app1_size if label == "app1" else entry.size
        entries.append(
            struct.pack(
                "<HBBII16sI",
                0x50AA,
                entry.type,
                entry.subtype,
                entry.offset,
                size,
                label.encode().ljust(16, b"\0"),
                0,
            )
        )
    if checksum:
        body = b"".join(entries)
        entries.append(
            struct.pack("<H14s", 0xEBEB, b"\xFF" * 14)
            + hashlib.md5(body, usedforsecurity=False).digest()
        )
    return b"".join(entries).ljust(0xC00, b"\xFF")


def test_all_public_configs_are_credential_free() -> None:
    public_files = list((ROOT / "firmware").glob("*.release.yaml"))
    public_files += list((ROOT / "packages").glob("*.yaml"))
    public_files = [
        path
        for path in public_files
        if not path.name.startswith(("bridge-", "migrate-"))
    ]
    for path in public_files:
        text = path.read_text()
        assert "!secret" not in text, path
        assert "wifi_password" not in text, path
        assert "api_encryption_key:" not in text, path
        assert "legacy_ota_password" not in text, path


@pytest.mark.parametrize("version", ["1.0.0", "12.34.56", "0.0.1"])
def test_semantic_versions_are_accepted(version: str) -> None:
    validate_version(version)


@pytest.mark.parametrize("version", ["v1.0.0", "1.0", "01.0.0", "1.0.0-dev"])
def test_non_release_versions_are_rejected(version: str) -> None:
    with pytest.raises(ValueError):
        validate_version(version)


def test_private_inputs_accept_public_ci_values(tmp_path: Path) -> None:
    stream = STREAMS["ip101-wifi"]
    key = tmp_path / stream.signing_key.name
    key.write_text("test-only")
    replacement = stream.__class__(
        **{**stream.__dict__, "signing_key": key}
    )
    validate_private_inputs(replacement, ROOT / "tests" / "secrets.ci.yaml")


def test_private_inputs_reject_placeholder_api_key(tmp_path: Path) -> None:
    stream = STREAMS["ip101-ethernet"]
    key = tmp_path / stream.signing_key.name
    key.write_text("test-only")
    replacement = stream.__class__(
        **{**stream.__dict__, "signing_key": key}
    )
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(
        'api_encryption_key: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="\n'
        'legacy_ota_password: "long-enough-password"\n'
    )
    with pytest.raises(ValueError):
        validate_private_inputs(replacement, secrets)


def test_managed_partition_table_is_accepted(tmp_path: Path) -> None:
    table = tmp_path / "partition-table.bin"
    table.write_bytes(partition_table_bytes())
    validate_managed_partition_table(table)
    assert parse_partition_table(table) == EXPECTED_MANAGED_PARTITIONS


def test_changed_managed_partition_is_rejected(tmp_path: Path) -> None:
    table = tmp_path / "partition-table.bin"
    table.write_bytes(partition_table_bytes(app1_size=0x180000))
    with pytest.raises(ValueError, match="does not exactly match"):
        validate_managed_partition_table(table)


def test_partition_table_without_checksum_is_rejected(tmp_path: Path) -> None:
    table = tmp_path / "partition-table.bin"
    table.write_bytes(partition_table_bytes(checksum=False))
    with pytest.raises(ValueError, match="no MD5 checksum"):
        parse_partition_table(table)


def test_partition_table_with_bad_checksum_is_rejected(tmp_path: Path) -> None:
    table = tmp_path / "partition-table.bin"
    data = bytearray(partition_table_bytes())
    data[0x2C] ^= 1
    table.write_bytes(data)
    with pytest.raises(ValueError, match="checksum is invalid"):
        parse_partition_table(table)


def test_signed_partition_table_requires_explicit_trailing_allowance(tmp_path: Path) -> None:
    table = tmp_path / "signed-partition-table.bin"
    table.write_bytes(partition_table_bytes() + b"signature")
    with pytest.raises(ValueError, match="must be 3072 bytes"):
        parse_partition_table(table)
    assert parse_partition_table(
        table, allow_trailing_signature=True
    ) == EXPECTED_MANAGED_PARTITIONS


def test_device_artifact_build_runs_bridge_then_migration(monkeypatch) -> None:
    commands = []

    def record(command, **_kwargs):
        commands.append(command)

    monkeypatch.setattr("prepare_device_migration.subprocess.run", record)
    build_device_artifacts("ip101-ethernet")

    assert [Path(command[1]).name for command in commands] == [
        "prepare_bridge.py",
        "prepare_migration.py",
    ]
    assert all(command[-1] == "ip101-ethernet" for command in commands)


def test_device_staging_credentials_are_bound_to_target(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(
        'migration_device: "ble3"\n'
        'api_encryption_key: "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="\n'
        'legacy_ota_password: "device-specific-password"\n'
    )
    require_device_credentials(secrets, "ble3")
    with pytest.raises(ValueError, match="migration_device: ble1"):
        require_device_credentials(secrets, "ble1")


def test_device_staging_rejects_ci_credentials(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(
        'migration_device: "ble3"\n'
        'api_encryption_key: "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="\n'
        'legacy_ota_password: "device-specific-password"\n'
    )
    with pytest.raises(ValueError, match="CI-only credentials"):
        require_device_credentials(secrets, "ble3")


@pytest.mark.parametrize("value", ["10.192.170.143", "192.168.1.42"])
def test_device_staging_accepts_reserved_ipv4(value: str) -> None:
    assert str(device_address(value)) == value


@pytest.mark.parametrize("value", ["not-an-ip", "0.0.0.0", "127.0.0.1", "224.0.0.1"])
def test_device_staging_rejects_unsafe_ipv4(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        device_address(value)
