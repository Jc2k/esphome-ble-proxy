# `kitchen-proxy` Wi-Fi migration worksheet

This is the canary procedure for the first Wi-Fi migration and for the
`pico32-wifi` release stream. Stop at every gate and preserve the logs. Never
continue merely because an upload command returned success.

## Current state

- Device: `kitchen-proxy`
- Stream: `pico32-wifi`
- Device IPv4/DHCP reservation: **record before staging**
- Existing API key, OTA password and Wi-Fi credentials: **not yet selected in
  ignored local secrets**
- Serial recovery: **expected to be the easiest of the remaining devices**
- Private artifacts: ignored `private-artifacts/kitchen-proxy/metadata.json`
  after staging
- Public target: `v1.0.1` (revalidated by the staging command)

Do not use an existing file under `migrations/.esphome/`. Those build paths are
shared between devices and may contain test or another device's credentials.
Do not combine this migration with credential rotation, a bootloader update,
Secure Boot or eFuse changes.

## Gate 1: prepare immutable private artifacts

1. Record Kitchen's reserved IPv4 address and confirm serial recovery can be
   reached if necessary.
2. Put only Kitchen's existing production values in the ignored
   `migrations/secrets.yaml`:

   ```yaml
   migration_device: "kitchen-proxy"
   api_encryption_key: "..."
   legacy_ota_password: "..."
   wifi_ssid: "..."
   wifi_password: "..."
   ```

3. Restrict the secrets and PICO32 signing key:

   ```sh
   chmod 600 migrations/secrets.yaml .firmware-signing-key-pico32-wifi.pem
   ```

4. From a clean, reviewed worktree, stage artifacts bound to the exact device
   and address:

   ```sh
   export KITCHEN_IP="192.0.2.10"
   uv run python scripts/prepare_device_migration.py kitchen-proxy \
     --device-address "$KITCHEN_IP"
   (cd private-artifacts/kitchen-proxy && shasum -a 256 -c SHA256SUMS)
   ```

The staging command refuses to overwrite an existing artifact directory. It
also verifies the live public release and signature, checks that the supplied
credentials exactly match ignored `migrate_from/kitchen-proxy.yaml`, rejects
CI placeholders or credentials bound to another device, and makes every
artifact private (`0700` directory and `0600` files).

## Gate 2: baseline and first bridge boot

Use the explicit address throughout; do not rely on mDNS:

```sh
uv run esphome logs --device "$KITCHEN_IP" \
  migrate_from/kitchen-proxy.yaml
```

Record the current ESPHome version, ESP32 revision, flash size if reported,
Wi-Fi address and signal, uptime/reset reason, encrypted API connection, and
Bluetooth advertisement flow in Home Assistant. Abort on unexplained resets or
unstable Wi-Fi.

Verify the hashes, then install the exact private bridge artifact:

```sh
(cd private-artifacts/kitchen-proxy && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$KITCHEN_IP" \
  --file private-artifacts/kitchen-proxy/bridge.firmware.bin \
  migrations/pico32-wifi.bridge.yaml
uv run esphome logs --device "$KITCHEN_IP" \
  migrations/pico32-wifi.bridge.yaml
```

The bridge contains Kitchen's current station credentials and retains
password-protected legacy OTA. If it cannot join Wi-Fi, wait at least one minute
for its open, MAC-suffixed fallback AP and use the captive portal only to recover
connectivity. Then stop: correct both ignored source files, move the rejected
private artifact directory aside, and stage a fresh audited set. Do not upload
the migration image from an artifact set whose bridge needed corrected Wi-Fi
credentials.

Require all of:

- Wi-Fi and encrypted API reconnect at the expected address;
- flash size is at least `0x400000`;
- partition diagnostics list the running slot and all five partitions;
- Home Assistant continues receiving Bluetooth advertisements; and
- a controlled restart returns to a stable bridge.

If `OTA-compatible layout: YES` is reported, skip Gate 3. Do not rewrite a
partition table for an NVS-only size difference.

## Gate 3: incompatible app layout only

This gate is unnecessary unless the diagnostic explicitly reports
`OTA-compatible layout: NO`. First install the same hashed bridge a second time
and require its running partition offset to differ from the first bridge boot:

```sh
uv run esphome upload --device "$KITCHEN_IP" \
  --file private-artifacts/kitchen-proxy/bridge.firmware.bin \
  migrations/pico32-wifi.bridge.yaml
uv run esphome logs --device "$KITCHEN_IP" \
  migrations/pico32-wifi.bridge.yaml
```

With stable power and the log stream open, perform the only high-risk step:

```sh
(cd private-artifacts/kitchen-proxy && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$KITCHEN_IP" --partition-table \
  --file private-artifacts/kitchen-proxy/partition-table.bin \
  migrations/pico32-wifi.bridge.yaml
```

Do not interrupt power, reset the device, retry blindly after an error, or
upload a bootloader. After reboot require exactly:

| Partition | Offset | Size |
| --- | ---: | ---: |
| `otadata` | `0x009000` | `0x002000` |
| `phy_init` | `0x00B000` | `0x001000` |
| `app0` | `0x010000` | `0x1C0000` |
| `app1` | `0x1D0000` | `0x1C0000` |
| `nvs` | `0x390000` | `0x06D000` |

Require `Exact managed layout: YES`, `OTA-compatible layout: YES`, stable
Wi-Fi, and one controlled restart before continuing.

## Gate 4: persist Wi-Fi and API credentials

```sh
(cd private-artifacts/kitchen-proxy && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$KITCHEN_IP" \
  --file private-artifacts/kitchen-proxy/migration.firmware.bin \
  migrations/pico32-wifi.migration.yaml
uv run esphome logs --device "$KITCHEN_IP" \
  migrations/pico32-wifi.logs.yaml
```

Require all of:

- `API key migration: succeeded`;
- `Wi-Fi credentials persisted for public firmware`;
- `OTA-compatible layout: YES`;
- Wi-Fi, encrypted API, Bluetooth proxy and advertisement flow are healthy;
- `Firmware Update` offers `v1.0.1`; and
- a controlled restart reconnects without the fallback AP.

Remain on the migration image if any check fails. It retains legacy OTA and an
open, MAC-suffixed captive-portal fallback AP.

## Gate 4.5: credential-free verification image

The verification image contains neither station credentials nor an API key and
does not write either one. It retains legacy OTA and the fallback AP. Successful
Wi-Fi and encrypted API reconnection therefore proves both credentials were
loaded from NVS.

```sh
(cd private-artifacts/kitchen-proxy && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$KITCHEN_IP" \
  --file private-artifacts/kitchen-proxy/verification.firmware.bin \
  migrations/pico32-wifi.verification.yaml
uv run esphome logs --device "$KITCHEN_IP" \
  migrations/pico32-wifi.logs.yaml
```

Require encrypted API and Home Assistant to reconnect, `API key migration: not
requested`, both partition-layout checks to report `YES`, Wi-Fi/BLE/HTTP OTA to
remain healthy, and advertisements to continue. Perform one controlled restart
and require another clean reconnection before continuing.

## Gate 5: public HTTP OTA and soak

Install `v1.0.1` through Home Assistant's `Firmware Update` entity. This removes
legacy ESPHome OTA; later updates use the signed `pico32-wifi` HTTP release
stream.

After reboot, verify version `1.0.1`, encrypted API, Wi-Fi, Bluetooth proxy,
advertisement flow, HTTP OTA, and the absence of the legacy `esphome.ota`
component. Perform one controlled restart, then soak Kitchen for at least 24
hours before preparing `bedroom-proxy`.
