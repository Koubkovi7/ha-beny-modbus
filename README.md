# BENY Modbus for Home Assistant

[Český návod](README.cs.md)

Local control of single-connector BENY Smart BCP-...-L chargers through an
RS485-to-Ethernet gateway. Designed around the BCP-AT2N-L and BENY RS485 Modbus
protocol v3.8. No BENY DLB box is required. This is an independent community
integration, not an official BENY product.

**Version 0.1.1 — initial hardware validation pending.** The protocol/control
suite has 61 simulated tests. This does not validate installation in Home
Assistant or communication with a physical charger. Requires Home Assistant
Core 2026.10.0 or newer; no additional Python packages.

## Install using HACS

Repository: `https://github.com/Koubkovi7/ha-beny-modbus`

1. Open HACS, then its three-dot menu → **Custom repositories**.
2. Add `https://github.com/Koubkovi7/ha-beny-modbus`, type **Integration**.
3. Find **BENY Modbus** and download it.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → BENY Modbus**.
6. Enter your gateway connection. The setup form includes recommendations
   under each field, in English or Czech according to your HA language.
7. Keep the initial current ceiling at 6 A for the first check. Increase it
   only within the verified installation limit.

The repository is prepared for HACS custom-repository installation. It is not
listed in the default HACS catalog. HACS can install the default branch before
the first GitHub release. Published releases should use the manifest version
(for example `v0.1.1`); a tag alone is not a GitHub release.

For manual installation, copy `custom_components/beny_modbus` into your HA
configuration directory, then restart. The resulting path must be
`/config/custom_components/beny_modbus/manifest.json`.

## Gateway and setup recommendations

| Setting | Recommended starting value |
| --- | --- |
| Gateway address | Your actual IP or hostname; DHCP with a router reservation |
| Gateway operating mode | TCP Server |
| Gateway protocol conversion | Modbus TCP to RTU |
| Integration transport | Modbus TCP |
| TCP port | 502, or the actual port configured on your gateway |
| Charger Modbus address | 1, unless changed on the charger |
| RS485 baud rate | 4800 Bd |
| Serial format | 8 data bits, no parity, 1 stop bit (8N1) |
| Plug & Play | Off for remote START/STOP control |
| Integration current ceiling | Initially 6 A; configurable up to 32 A |

Serial settings must be applied in the gateway, not in HA. Port 80 usually
serves the gateway's web interface. **Modbus TCP** adds an MBAP header; a
gateway in **Modbus TCP to RTU** mode performs the conversion. **Modbus RTU
over TCP** instead carries RTU frames with CRC and is only for transparent
gateways. Selecting the wrong mode prevents valid replies.

Avoid other applications controlling the same charger. Check whether the
gateway caches registers or polls RS485 autonomously: cached replies may be
stale, and autonomous polling may keep a charger watchdog alive after HA stops.
Do not connect a BENY DLB box to the same RS485 control link.

To change IP, port or mode later, choose **Reconfigure** on the integration.
Existing entity identifiers are retained. **Configure** changes the current
ceiling and whether controls are enabled. There is no automatic discovery.

## Entities and behavior

- Charging authorization switch (START/STOP), distinct from actual charging.
- Temporary current limit, in whole amperes from 6 A to the lower of the
  integration ceiling and the permanent charger limit.
- Vehicle connected, charging, connector status and fault indicators.
- Voltage/current on each phase and session energy.
- Current offered to the vehicle and Modbus timeout, when supported by firmware.
- Diagnostic permanent limit and last successful communication (the timestamp
  entity is disabled by default to avoid recording every poll).

Session energy is not a lifetime energy counter. Setup, reconnect and HA restart
only read: they do not restore a previous START or current command. The
integration ceiling limits its own commands; changing it does not immediately
reduce charging already in progress and does not change app control.

Polling is serialized, with individual-register reads and a minimum 80 ms
spacing. A new poll is scheduled approximately every 2 seconds, subject to
communication duration. Polling never sends START/STOP. If charging is already
authorized, another START is suppressed. START attempts have a 30-second guard;
STOP does not wait for it. Changing current writes only volatile register
`0x0200`, without STOP/START. Writes use FC16 and readback; uncertain writes are
not automatically repeated. Two minutes after a new START, lack of observed
charging produces a persistent HA notification without restarting the charger.
It is not a phone push notification; the car may simply be full or scheduled.

The earlier contactor-clicking cause was not confirmed by measurement. These
measures prevent repeated software START commands, not every possible cause.
This release has no tariff automation or dynamic load balancing. The charger
watchdog is read only: stopping on loss of HA is not guaranteed or hardware tested.

## First device check

1. Verify model, phase readings, connector state and faults before sending commands.
2. Confirm Plug & Play is off; initially leave the ceiling at 6 A.
3. Connect the vehicle and enable charging once. Compare authorization with
   the charging sensor and measured phase currents.
4. Check current changes within the configured limit, then STOP and verify
   the current falls. Only then add tariff automation.

Diagnostics redact the configured host/name; review logs separately before
posting them. No personal gateway addresses are included in this repository.

## Restore after losing Home Assistant

Reinstall HACS, add the repository, download the integration and enter the
gateway connection again. GitHub preserves the source, not your HA device
configuration, automations or history; keep a Home Assistant backup for those.

## Development

```sh
python tools/check_repository.py
python -m unittest discover -s tests -v
python tools/build_package.py
```

The source/install ZIP is written to `dist/` and includes the integration,
translations, docs, license and tests. It excludes the original manufacturer
spreadsheet, private files and Git metadata. The spreadsheet received from BENY
is retained separately as a development reference.

When sockets are unavailable, `python tests/run_memory.py` runs the same
protocol/control suite with in-memory streams. This does not test OS networking
or the HA runtime. A read-only probe is available from a computer on the LAN:

```sh
python tools/probe.py --host YOUR_GATEWAY_IP --port 502 --transport tcp
```

GitHub Actions run the protocol tests, package checks, hassfest and HACS
custom-repository validation. The HACS job excludes the action-only description,
topics and brands checks; these do not run during custom-repository installation.
Before submitting to the default HACS catalog, add a GitHub repository description
(for example, "Local Home Assistant control of BENY Smart EV chargers over Modbus"),
set relevant topics, provide the required branding and enable those checks.

## References

- BENY RS485 Modbus communication protocol v3.8, dated 2025-08-14.
- [Waveshare RS485 TO ETH (B)](https://www.waveshare.com/wiki/RS485_TO_ETH_%28B%29)
- [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/)
- [HACS integration layout](https://www.hacs.xyz/docs/publish/integration/)
- [Home Assistant config flow](https://contributors.home-assistant.io/core/integrations/config-flow/)

MIT license applies to the integration source. BENY and Waveshare names belong
to their respective owners.
