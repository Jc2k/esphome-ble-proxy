#!/usr/bin/env python3
"""Build and verify a credential-free image that retains legacy OTA recovery."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from firmware_security import ROOT, STREAMS, validate_private_inputs, verify_build


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in STREAMS:
        choices = " | ".join(STREAMS)
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} ({choices})")

    stream = STREAMS[sys.argv[1]]
    validate_private_inputs(stream, ROOT / "migrations" / "secrets.yaml")
    subprocess.run(
        [sys.executable, "-m", "esphome", "compile", str(stream.verification_config)],
        cwd=ROOT,
        check=True,
    )
    build = verify_build(stream, verification=True)
    print(build.ota_firmware)


if __name__ == "__main__":
    main()
