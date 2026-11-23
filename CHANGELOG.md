# Changelog

## 0.1.6 - 2026-11-23

- Add an enabled-by-default Estimated power sensor (Czech: Příkon (odhad)).
  Sum measured voltage times measured current per phase, in W with measurement
  state class; expose the assumed unity power factor as an attribute.
- Reuse the existing snapshot without additional Modbus requests. Preserve
  coordinator availability so failed updates do not appear as zero power.
- Document the distinction between this estimate, apparent power and measured
  active power; support single-phase, two-phase, three-phase and idle readings.
- Test phase pairing, scaling, rounding, zero currents and independence from
  charging authorization/current limits over TCP and RTU transports.

## 0.1.5 - 2026-11-17

- Include the received header bytes and expected address/function in RTU errors;
  show received and expected MBAP fields for invalid Modbus TCP headers.
- Include the invalid RTU byte count or CRC frame in the error details.
- Log transmitted frames and received headers/bodies at DEBUG level, including
  malformed headers before rejecting them. This helps diagnose transport mode
  mismatches, unexpected data and incorrect replies.
- Cover wrong address/function, TCP bytes on an RTU connection and unexpected
  leading bytes; verify malformed replies close the connection without retries.
- Keep request timing, polling, validation and single-attempt writes unchanged.
  This is a diagnostic release, not a confirmed fix for physical communication.

## 0.1.4 - 2026-11-16

- Restore a 1-second settling delay after every new TCP connection and the
  earlier client's 10-second timeout.
- Give connection establishment and request/response separate timeout budgets;
  the settling delay does not shorten the response timeout.
- Reuse established connections without adding a delay before every register.
  Retries reconnect and wait before sending; cancellation during the delay
  closes the socket without sending a write.
- Add TCP and RTU tests with a simulated gateway that ignores early requests.
- Preserve single-attempt writes, mandatory register validation and current
  limits. Hardware verification of this compatibility change is still pending.

## 0.1.3 - 2026-11-16

- Allow 5 seconds per request and increase the minimum request gap to 150 ms.
- Retry a failed read once after a 250 ms pause and a new TCP connection.
  Retry only connection/response failures, not Modbus exceptions or invalid data.
- Keep every write single-attempt, including START/STOP and current changes.
  A failed readback may be retried without repeating the write.
- Keep mandatory telemetry mandatory and fail incomplete updates.
- Add TCP and RTU regression cases for lost replies, readback recovery,
  exhausted retries, cancellation, invalid responses and single-attempt writes.
- Hardware communication remains under investigation; this change tolerates
  transient failures but does not establish or resolve their underlying cause.

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
