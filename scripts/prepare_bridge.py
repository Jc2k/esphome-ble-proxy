#!/usr/bin/env python3
"""Build a private, legacy-partition-sized transition image."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from firmware_security import (
    ROOT,
    STREAMS,
    validate_managed_partition_table,
    validate_private_inputs,
)


# Arduino-ESP32's long-standing default layout allows 0x140000 bytes per OTA
# app slot. Refuse to produce a bridge that cannot fit that conservative limit.
LEGACY_OTA_SLOT_SIZE = 0x140000


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in STREAMS:
        choices = " | ".join(STREAMS)
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} ({choices})")

    stream = STREAMS[sys.argv[1]]
    validate_private_inputs(stream, ROOT / "migrations" / "secrets.yaml")
    subprocess.run(
        [sys.executable, "-m", "esphome", "compile", str(stream.bridge_config)],
        cwd=ROOT,
        check=True,
    )

    build = (
        stream.bridge_config.parent
        / ".esphome"
        / "build"
        / stream.bridge_build_name
        / "build"
    )
    ota_firmware = build / "firmware.ota.bin"
    partition_table = build / "partition_table" / "partition-table.bin"
    generated_main = build.parent / "src" / "main.cpp"
    for path in (ota_firmware, partition_table, generated_main):
        if not path.is_file():
            raise FileNotFoundError(f"missing bridge build output: {path}")

    validate_managed_partition_table(partition_table)

    size = ota_firmware.stat().st_size
    if size > LEGACY_OTA_SLOT_SIZE:
        raise RuntimeError(
            f"bridge image is {size} bytes; legacy limit is {LEGACY_OTA_SLOT_SIZE}"
        )

    generated = generated_main.read_text()
    if "set_noise_psk" not in generated:
        raise RuntimeError("bridge firmware does not embed the existing API key")
    if stream.slug.endswith("wifi") and "add_sta(" not in generated:
        raise RuntimeError("Wi-Fi bridge does not embed the existing Wi-Fi network")

    print(f"Bridge OTA ({size}/{LEGACY_OTA_SLOT_SIZE} bytes): {ota_firmware}")
    print(f"Partition table: {partition_table}")


if __name__ == "__main__":
    main()
