from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from firmware_security import STREAMS, validate_private_inputs, validate_version  # noqa: E402


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
