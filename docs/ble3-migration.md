# `ble3` Ethernet migration worksheet

This is the canary procedure for `ble3`. Stop at every gate and preserve the
logs. Never continue merely because an upload command returned success.

## Current state

- Device: `ble3`
- Stream: `ip101-ethernet`
- Device IPv4/DHCP reservation: `10.192.170.143`
- Existing API encryption key: **ready in ignored local secrets**
- Existing ESPHome OTA password: **ready in ignored local secrets**
- Serial recovery: **theoretically possible; avoid unless recovery is required**
- Private artifacts: **not built**
- Public target: `v1.0.0`

Do not use an existing file under `migrations/.esphome/`. Those build paths are
shared between devices and may contain test or another device's credentials.

## Gate 1: prepare immutable private artifacts

1. Confirm `ble3` has a fixed IPv4 address and that physical/serial recovery is
   possible if the partition-table write is interrupted.
2. Put only `ble3`'s existing values in the ignored
   `migrations/secrets.yaml`:

   ```yaml
   migration_device: "ble3"
   api_encryption_key: "..."
   legacy_ota_password: "..."
   wifi_ssid: "unused-for-ethernet"
   wifi_password: "unused-for-ethernet"
   ```

   Restrict the file before building:

   ```sh
   chmod 600 migrations/secrets.yaml .firmware-signing-key-ip101-ethernet.pem
   ```

3. Require a clean, reviewed worktree, then build and stage the artifacts:

   ```sh
   uv run python scripts/prepare_device_migration.py ble3 \
     --device-address 10.192.170.143
   (cd private-artifacts/ble3 && shasum -a 256 -c SHA256SUMS)
   ```

The staging command refuses to overwrite an existing `ble3` directory. The
directory and files are private (`0700`/`0600`) and ignored by Git. Preserve
`metadata.json` and `SHA256SUMS` with the migration log. It also refuses the
repository's public CI-only credentials or credentials explicitly bound to a
different device.

## Gate 2: baseline and first bridge boot

Set the explicit reserved address; do not use mDNS during this procedure:

```sh
export BLE3_IP="10.192.170.143"
uv run esphome logs --device "$BLE3_IP" migrate_from/ble3.yaml
```

Record the existing ESPHome version, MAC address, uptime, reset reason,
Ethernet state and Bluetooth proxy health. Abort on unexplained resets or link
instability.

Verify the staged hashes again, then upload the exact bridge artifact:

```sh
(cd private-artifacts/ble3 && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$BLE3_IP" \
  --file private-artifacts/ble3/bridge.firmware.bin \
  migrations/ip101-ethernet.bridge.yaml
uv run esphome logs --device "$BLE3_IP" \
  migrations/ip101-ethernet.bridge.yaml
```

Require all of:

- Ethernet and encrypted API reconnect at the reserved IP;
- flash size is at least `0x400000`;
- the partition diagnostic lists the running slot and all five partitions;
- a controlled restart returns to a stable bridge.

If `Target managed layout: YES` is reported, skip Gate 3 and continue to Gate
4. If it reports `NO`, continue with the second bridge boot.

## Gate 3: second bridge boot and partition-table update

Upload the same hashed bridge a second time. After reboot, require the running
partition offset to differ from the first bridge boot.

```sh
uv run esphome upload --device "$BLE3_IP" \
  --file private-artifacts/ble3/bridge.firmware.bin \
  migrations/ip101-ethernet.bridge.yaml
uv run esphome logs --device "$BLE3_IP" \
  migrations/ip101-ethernet.bridge.yaml
```

Keep the log stream open in one terminal. In a second terminal, perform the
only high-risk operation:

```sh
(cd private-artifacts/ble3 && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$BLE3_IP" --partition-table \
  --file private-artifacts/ble3/partition-table.bin \
  migrations/ip101-ethernet.bridge.yaml
```

Do not remove power, reset the device, or change the network while this runs.
If ESPHome rejects the table, preserve the output and stop; do not retry
blindly. Do not upload a bootloader.

After reboot, the partition diagnostic must show exactly:

| Partition | Offset | Size |
| --- | ---: | ---: |
| `otadata` | `0x009000` | `0x002000` |
| `phy_init` | `0x00B000` | `0x001000` |
| `app0` | `0x010000` | `0x1C0000` |
| `app1` | `0x1D0000` | `0x1C0000` |
| `nvs` | `0x390000` | `0x070000` |

Require `Target managed layout: YES` and one controlled restart before
continuing.

## Gate 4: signed migration image

```sh
(cd private-artifacts/ble3 && shasum -a 256 -c SHA256SUMS)
uv run esphome upload --device "$BLE3_IP" \
  --file private-artifacts/ble3/migration.firmware.bin \
  migrations/ip101-ethernet.migration.yaml
uv run esphome logs --device "$BLE3_IP" \
  migrations/ip101-ethernet.migration.yaml
```

Require all of:

- `API encryption key persisted for credential-free updates`;
- `Target managed layout: YES`;
- Ethernet, API and Bluetooth proxy are healthy;
- the `Firmware Update` entity offers `v1.0.0`;
- a controlled restart succeeds.

Remain on the migration image if any check fails. It retains legacy ESPHome
OTA as the recovery path.

## Gate 5: public HTTP OTA and soak

Install `v1.0.0` through the Home Assistant `Firmware Update` entity. This is
the final transition to signed HTTP OTA and removes legacy ESPHome OTA.

After reboot, verify version `1.0.0`, encrypted API, Ethernet, Bluetooth proxy
and the update entity. (`v1.0.0` predates the partition diagnostic; the layout
was already verified on the migration image.) Perform one controlled power
cycle. Then soak `ble3` for at least 24 hours before preparing another device.

Do not combine this migration with an API-key rotation, bootloader update,
Secure Boot or eFuse changes.
