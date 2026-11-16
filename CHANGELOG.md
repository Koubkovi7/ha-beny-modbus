# Changelog

## 0.1.2 - 2026-11-16

- Show the actual setup failure in the form and in Home Assistant logs.
- Distinguish TCP connection failures, reply timeouts, closed connections and
  Modbus exceptions, including the requested function and register.
- Show actual values when rejecting an unknown charger state or identity.
- Display the Modbus unit address in a numeric input box instead of a slider.
- Add regression coverage for failed connection/read diagnostics without writes
  or retries. Charging behavior and communication parameters remain unchanged.

## 0.1.1 — 2026-11-15

- Add HACS metadata and repository validation.
- Expand Czech and English setup instructions and field help.
- Suggest port 502, Modbus TCP and unit address 1; all remain editable.
- Document recommended RS485 settings and the difference between Modbus TCP
  and transparent RTU over TCP.
- Prepare public documentation in English and Czech and an MIT license.
- Keep local addresses, MAC addresses and the privately supplied manufacturer
  spreadsheet outside the public distribution.

No change to charging commands or polling behavior.

## 0.1.0 — 2026-11-15

- Initial local release for single-connector BENY Smart BCP-...-L chargers.
- Charging authorization, volatile current limit, measurements and diagnostics.
- Serialized reads, single-write commands and duplicate START suppression.
- 61 protocol/control tests passed with in-memory streams.

Hardware and Home Assistant runtime validation remain pending.
