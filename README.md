# ESPHome BLE proxy firmware

This repository builds three signed, credential-free ESPHome Bluetooth proxy
firmware streams. Devices check a manifest on GitHub Pages and pull their own
OTA image over HTTPS. Releases, `v*` tags, release notes, firmware assets and
Pages deployment are created by semantic-release in the same shape as
[`Jc2k/esphome-activlink`](https://github.com/Jc2k/esphome-activlink).

## Production devices and release streams

| Existing device | Public stream | Network | Board configuration |
| --- | --- | --- | --- |
| `ble1` | `ip101-ethernet` | IP101 Ethernet | `esp32doit-devkit-v1` |
| `ble3` | `ip101-ethernet` | IP101 Ethernet | `esp32doit-devkit-v1` |
| `ble2` | `ip101-wifi` | Wi-Fi | `esp32doit-devkit-v1` |
| `bedroom-proxy` | `pico32-wifi` | Wi-Fi | `pico32` |
| `kitchen-proxy` | `pico32-wifi` | Wi-Fi | `pico32` |

All public configurations use `name_add_mac_suffix`, so devices on the same
stream retain distinct identities without putting per-device names or secrets
in release binaries.

The source files in `migrate_from/` contain production credentials and are
intentionally ignored. They must never be force-added or copied into an issue,
release, build log or public commit. Rotate the current API, OTA and fallback-AP
credentials after migration because they were present in plaintext source.

Private bridge and migration builds also contain credentials. They are built
locally from the ignored `migrations/secrets.yaml`; they are never uploaded as
release assets. Bridge images are intentionally minimal and unsigned. They only
exist to move an older partition layout to the current one before the first
signed image establishes the permanent OTA trust key.

## Security model

Each stream has an independent ECDSA signing key. The migration image is the
first signed image; it establishes the trust key used to authenticate every
later HTTP OTA image. Production firmware also rejects version downgrades.
MD5 in the ESPHome manifest detects transfer damage; the firmware signature is
what provides authenticity.

These devices use the original ESP32 family. ESPHome's hardware-backed NVS
encryption feature does **not** support original ESP32, so saved Wi-Fi and API
credentials cannot be encrypted by this design. Original ESP32 can support
hardware Secure Boot, but the safe procedure depends on chip revision and an
up-to-date bootloader. Neither is yet known, and bootloader/eFuse changes have a
real remote-brick risk. This initial migration therefore uses signed OTA without
burning eFuses. Capture each device's chip revision and ESP-IDF/bootloader logs
before considering a separate irreversible hardening phase.

Keep all three private signing keys offline as well as in GitHub Actions. Losing
a key prevents the corresponding migrated devices from accepting future OTA
images. Do not migrate a device until its key is backed up.

## Release infrastructure

The release workflow expects these repository Actions secrets:

- `FIRMWARE_SIGNING_KEY_IP101_ETHERNET`
- `FIRMWARE_SIGNING_KEY_IP101_WIFI`
- `FIRMWARE_SIGNING_KEY_PICO32_WIFI`

Generate each key once:

```sh
uv sync
uv run python -m espsecure generate-signing-key --version 1 \
  .firmware-signing-key-ip101-ethernet.pem
uv run python -m espsecure generate-signing-key --version 1 \
  .firmware-signing-key-ip101-wifi.pem
uv run python -m espsecure generate-signing-key --version 1 \
  .firmware-signing-key-pico32-wifi.pem
```

Copy the complete PEM contents into the matching Actions secret and make an
offline backup. The files are ignored by Git.

Every push and pull request validates all nine YAML roots, checks that all three
private bridge images fit a conservative 1,310,720-byte legacy OTA slot, and
builds all three public streams with throwaway keys. A successful conventional commit on `main`
runs semantic-release. Use `fix:`, `feat:` and `feat!:` (or a
`BREAKING CHANGE:` footer) for patch, minor and major firmware releases.
Dependabot checks ESPHome daily using `fix(deps):` and Actions weekly using
`ci(deps):`.

Pages publishes manifests under:

- `https://unrouted.uk/esphome-ble-proxy/firmware/ip101-ethernet/manifest.json`
- `https://unrouted.uk/esphome-ble-proxy/firmware/ip101-wifi/manifest.json`
- `https://unrouted.uk/esphome-ble-proxy/firmware/pico32-wifi/manifest.json`

## Migrate a device over its existing IP connection

Do not start until the first public release and its Pages manifests are live.
The Ethernet devices are the best first trial because there are no Wi-Fi
credentials to transfer.

For the first Ethernet canary, use the guarded, device-specific
[`ble3` worksheet](docs/ble3-migration.md). It stages immutable private
artifacts and adds explicit go/no-go checks around the partition-table update.
For the first Wi-Fi canary, use the guarded
[`kitchen-proxy` worksheet](docs/kitchen-proxy-migration.md). It additionally
proves that both Wi-Fi and API credentials survive in NVS before legacy OTA is
removed.

For one target device, copy `secrets.example.yaml` to the ignored
`migrations/secrets.yaml` and replace the values with that device's current API
key and OTA password. For a Wi-Fi device, also add its current SSID and password. The Wi-Fi
migration uses ESPHome's `wifi.configure` action with `save: true`; the following
public image contains no configured network, so ESPHome preserves those
user-entered credentials across OTA.

Build both private stages before touching the device:

```sh
uv run python scripts/prepare_bridge.py ip101-ethernet
uv run python scripts/prepare_migration.py ip101-ethernet
# or: ip101-wifi / pico32-wifi
```

First inspect the existing device logs. If they already show the OTA-compatible
layout (`app0` at `0x10000`, `app1` at `0x1D0000`, each `0x1C0000` bytes, and
`nvs` at `0x390000` with at least `0x6D000` bytes), skip directly to the signed
migration below. The managed build deliberately preserves ESPHome 2025.7.x's
`0x6D000` NVS allocation instead of risking a remote partition rewrite merely
to gain 12 KiB of NVS space.

For an older or unknown layout, install the small matching bridge **twice** by
explicit IP, checking that it reconnects after each reboot. Two installs put a
bootable bridge in both legacy app slots, so the new layout can safely select
the app at `0x10000`:

```sh
uv run esphome upload --device 192.0.2.10 \
  migrations/ip101-ethernet.bridge.yaml
uv run esphome upload --device 192.0.2.10 \
  migrations/ip101-ethernet.bridge.yaml
```

With stable power, update only the partition table. This is the one risky step:
power loss can require serial recovery. Do not update the bootloader remotely.

```sh
uv run esphome upload --device 192.0.2.10 --partition-table \
  migrations/ip101-ethernet.bridge.yaml
```

After reboot, require the logs to show the current layout described above, then
install the first signed migration image:

```sh
uv run esphome upload --device 192.0.2.10 \
  migrations/ip101-ethernet.migration.yaml
uv run esphome logs --device 192.0.2.10 \
  migrations/ip101-ethernet.logs.yaml
```

After reboot, inspect logs before installing public firmware. Require all of:

- the expected original ESP32 chip revision and flash size are reported;
- `API key migration: succeeded` appears in the configuration dump;
- Ethernet reconnects, or Wi-Fi reports that its credentials were persisted;
- the Bluetooth proxy and Home Assistant API remain healthy; and
- the `Firmware Update` entity sees the correct stream/version.

Only then install the public release using the Home Assistant update entity.
The device downloads it over HTTPS from Pages; no ESPHome dashboard push is
required. The migration still has legacy ESPHome OTA as a recovery path, while
the public image intentionally removes it.

If a Wi-Fi migration cannot reconnect, leave it on the migration image. Its
open, MAC-suffixed fallback AP exposes ESPHome's captive portal after one minute,
allowing the correct network to be entered without a button. Do not install the
public image until connectivity has survived a power cycle.

## Local checks

```sh
cp tests/secrets.ci.yaml migrations/secrets.yaml
uv sync --locked
uv run pytest
for config in firmware/*.release.yaml migrations/*.bridge.yaml migrations/*.migration.yaml migrations/*.verification.yaml migrations/*.logs.yaml; do
  uv run esphome config "$config"
done
for stream in ip101-ethernet ip101-wifi pico32-wifi; do
  uv run python scripts/prepare_bridge.py "$stream"
done
uv run python scripts/prepare_release.py 0.0.1
```

`prepare_release.py` cryptographically verifies every OTA image, rejects public
generated code that embeds an API key or Wi-Fi provisioning action, and creates
the exact GitHub Release and Pages trees used by CI.
