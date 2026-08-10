#!/usr/bin/env python3
"""Build and stage immutable private migration artifacts for one device."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from ipaddress import AddressValueError, IPv4Address
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.request import urlopen

import yaml

from firmware_security import (
    EXPECTED_MANAGED_PARTITIONS,
    ROOT,
    STREAMS,
    build_directory,
    parse_partition_table,
    validate_managed_partition_table,
    validate_private_inputs,
    validate_version,
)


DEVICE_STREAMS = {
    "ble1": "ip101-ethernet",
    "ble3": "ip101-ethernet",
}


def device_address(value: str) -> IPv4Address:
    try:
        address = IPv4Address(value)
    except AddressValueError as error:
        raise argparse.ArgumentTypeError(f"invalid IPv4 address: {value}") from error
    if address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast:
        raise argparse.ArgumentTypeError(
            f"IPv4 address is not suitable for a reserved device address: {address}"
        )
    return address


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_clean_worktree(allow_dirty: bool) -> bool:
    dirty = bool(git_output("status", "--porcelain"))
    if dirty and not allow_dirty:
        raise RuntimeError(
            "refusing to stage production artifacts from a dirty worktree; "
            "commit or stash the reviewed source first"
        )
    return dirty


def require_private_file(path: Path) -> None:
    permissions = stat.S_IMODE(path.stat().st_mode)
    if permissions & 0o077:
        raise PermissionError(
            f"{path} must not be accessible by group or other users; run chmod 600 {path}"
        )


def require_device_credentials(path: Path, device: str) -> None:
    secrets = yaml.safe_load(path.read_text())
    if not isinstance(secrets, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    if secrets.get("migration_device") != device:
        raise ValueError(
            f"{path} must contain migration_device: {device} to bind the private "
            "credentials to this staging run"
        )

    ci_secrets_path = ROOT / "tests" / "secrets.ci.yaml"
    ci_secrets = yaml.safe_load(ci_secrets_path.read_text())
    credential_keys = (
        "api_encryption_key",
        "legacy_ota_password",
        "wifi_ssid",
        "wifi_password",
    )
    reused_ci_keys = [
        key
        for key in credential_keys
        if key in secrets and secrets.get(key) == ci_secrets.get(key)
    ]
    if reused_ci_keys:
        raise ValueError(
            "refusing to stage public CI-only credentials: "
            + ", ".join(reused_ci_keys)
        )


def build(stream_slug: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_bridge.py"), stream_slug],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_migration.py"), stream_slug],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_verification.py"), stream_slug],
        cwd=ROOT,
        check=True,
    )


def verify_published_release(stream_slug: str, signing_key: Path) -> dict[str, str | int]:
    manifest_url = (
        "https://unrouted.uk/esphome-ble-proxy/firmware/"
        f"{stream_slug}/manifest.json"
    )
    with urlopen(manifest_url, timeout=30) as response:
        if not response.geturl().startswith(manifest_url.rsplit("/", 1)[0] + "/"):
            raise ValueError("published manifest redirected outside its HTTPS stream")
        manifest = json.load(response)

    version = manifest.get("version")
    builds = manifest.get("builds")
    if not isinstance(version, str) or not isinstance(builds, list) or len(builds) != 1:
        raise ValueError(f"unexpected published manifest structure: {manifest_url}")
    validate_version(version)
    if not isinstance(builds[0], dict):
        raise ValueError(f"published manifest build is not an object: {manifest_url}")
    ota = builds[0].get("ota")
    if not isinstance(ota, dict):
        raise ValueError(f"published manifest has no OTA build: {manifest_url}")
    firmware_url = ota.get("path")
    expected_md5 = ota.get("md5")
    expected_url_prefix = (
        "https://unrouted.uk/esphome-ble-proxy/firmware/" f"{stream_slug}/"
    )
    if not isinstance(firmware_url, str) or not firmware_url.startswith(
        expected_url_prefix
    ):
        raise ValueError("published firmware URL is missing or is not HTTPS")
    if not isinstance(expected_md5, str) or len(expected_md5) != 32:
        raise ValueError("published firmware MD5 is missing or malformed")

    with urlopen(firmware_url, timeout=60) as response:
        if not response.geturl().startswith(expected_url_prefix):
            raise ValueError("published firmware redirected outside its HTTPS stream")
        firmware = response.read(4 * 1024 * 1024 + 1)
    if len(firmware) > 4 * 1024 * 1024:
        raise ValueError("published firmware unexpectedly exceeds 4 MiB")
    actual_md5 = hashlib.md5(firmware, usedforsecurity=False).hexdigest()
    if actual_md5 != expected_md5.lower():
        raise ValueError(
            f"published firmware MD5 mismatch: expected {expected_md5}, got {actual_md5}"
        )

    with tempfile.TemporaryDirectory(prefix="published-firmware-") as directory:
        firmware_path = Path(directory) / "firmware.bin"
        firmware_path.write_bytes(firmware)
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
                str(firmware_path),
            ],
            cwd=ROOT,
            check=True,
        )

    return {
        "version": version,
        "manifest_url": manifest_url,
        "firmware_url": firmware_url,
        "bytes": len(firmware),
        "md5": actual_md5,
        "sha256": hashlib.sha256(firmware).hexdigest(),
    }


def stage(args: argparse.Namespace) -> Path:
    stream = STREAMS[DEVICE_STREAMS[args.device]]
    secrets = ROOT / "migrations" / "secrets.yaml"
    validate_private_inputs(stream, secrets)
    require_private_file(secrets)
    require_device_credentials(secrets, args.device)
    require_private_file(stream.signing_key)
    dirty = require_clean_worktree(args.allow_dirty)
    published_release = verify_published_release(stream.slug, stream.signing_key)

    output_root = args.output_root.resolve()
    destination = output_root / args.device
    if destination.exists():
        raise FileExistsError(
            f"{destination} already exists; move it aside rather than overwriting audited artifacts"
        )

    build(stream.slug)

    bridge_build = (
        stream.bridge_config.parent
        / ".esphome"
        / "build"
        / stream.bridge_build_name
        / "build"
    )
    migration_build = build_directory(stream, migration=True)
    verification_build = build_directory(stream, verification=True)
    sources = {
        "bridge.firmware.bin": bridge_build / "firmware.ota.bin",
        "migration.firmware.bin": migration_build / "firmware.ota.bin",
        "verification.firmware.bin": verification_build / "firmware.ota.bin",
        "partition-table.bin": bridge_build / "partition_table" / "partition-table.bin",
        "partitions.csv": bridge_build.parent / "partitions.csv",
    }
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f"missing {name}: {source}")

    migration_partition_table = migration_build / "partition_table" / "partition-table.bin"
    verification_partition_table = (
        verification_build / "partition_table" / "partition-table.bin"
    )
    bridge_partitions = parse_partition_table(sources["partition-table.bin"])
    migration_partitions = parse_partition_table(
        migration_partition_table, allow_trailing_signature=True
    )
    verification_partitions = parse_partition_table(
        verification_partition_table, allow_trailing_signature=True
    )
    if not bridge_partitions == migration_partitions == verification_partitions:
        raise RuntimeError("transition firmware partition layouts differ")
    validate_managed_partition_table(sources["partition-table.bin"])

    output_root_created = not output_root.exists()
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_root_created or output_root == (ROOT / "private-artifacts").resolve():
        output_root.chmod(0o700)
    temporary = Path(tempfile.mkdtemp(prefix=f".{args.device}-", dir=output_root))
    temporary.chmod(0o700)
    try:
        artifact_data: dict[str, dict[str, int | str]] = {}
        for name, source in sources.items():
            target = temporary / name
            shutil.copyfile(source, target)
            target.chmod(0o600)
            artifact_data[name] = {
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
            }

        checksums = temporary / "SHA256SUMS"
        checksums.write_text(
            "".join(
                f"{details['sha256']}  {name}\n"
                for name, details in sorted(artifact_data.items())
            )
        )
        checksums.chmod(0o600)

        metadata = {
            "device": args.device,
            "device_address": str(args.device_address),
            "stream": stream.slug,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_commit": git_output("rev-parse", "HEAD"),
            "source_dirty": dirty,
            "signing_key_sha256": sha256(stream.signing_key),
            "published_release": published_release,
            "artifacts": artifact_data,
            "target_partitions": {
                label: {
                    "type": entry.type,
                    "subtype": entry.subtype,
                    "offset": entry.offset,
                    "size": entry.size,
                }
                for label, entry in EXPECTED_MANAGED_PARTITIONS.items()
            },
        }
        metadata_file = temporary / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        metadata_file.chmod(0o600)

        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print(f"Staged private artifacts for {args.device}: {destination}")
    print(
        "Verify before every upload: "
        f"(cd {destination} && shasum -a 256 -c SHA256SUMS)"
    )
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", choices=sorted(DEVICE_STREAMS))
    parser.add_argument(
        "--device-address",
        type=device_address,
        required=True,
        help="reserved IPv4 address of the exact migration target",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "private-artifacts",
        help="private staging directory (default: private-artifacts/)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow a dirty source tree for disposable test builds only",
    )
    return parser.parse_args()


if __name__ == "__main__":
    stage(parse_args())
