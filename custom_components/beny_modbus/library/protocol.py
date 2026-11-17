"""Small asynchronous Modbus client for BENY v3.8 (FC03, FC04, FC16).

No write retries. A missing acknowledgement is an unknown outcome, not proof
that the charger did not receive the command. Close broken connections so that
late replies cannot be mistaken for replies to subsequent requests.
"""

import asyncio
import logging
import struct
import time


_LOGGER = logging.getLogger(__name__)
_READ_ATTEMPTS = 2
_READ_RETRY_DELAY = 0.25


class BenyError(Exception):
    """Communication or device error."""


class TransportError(BenyError):
    """Connection/response failure; only read requests may be retried."""


class ModbusException(BenyError):
    def __init__(self, function: int, code: int, address: int | None = None):
        self.function, self.code = function, code
        self.address = address
        register = f" register 0x{address:04X}" if address is not None else ""
        super().__init__(f"Modbus FC{function:02d}{register}: exception 0x{code:02X}")


class WriteUncertain(BenyError):
    """A write was attempted, but its outcome is not confirmed."""


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


class ModbusClient:
    def __init__(self, host, port, unit=1, transport="rtu_over_tcp",
                 timeout=10.0, gap=0.15, connect_delay=1.0):
        if not host or not 1 <= int(port) <= 65535 or not 1 <= int(unit) <= 247:
            raise ValueError("Invalid host, port or Modbus address")
        if transport not in ("tcp", "rtu_over_tcp"):
            raise ValueError("Unsupported transport")
        if not 0 < timeout <= 10 or not 0 <= gap <= 1:
            raise ValueError("Invalid timeout or request gap")
        if not 0 <= connect_delay <= 5:
            raise ValueError("Invalid connection settling delay")
        self.host, self.port, self.unit = host, int(port), int(unit)
        self.transport, self.timeout, self.gap = transport, timeout, gap
        self.connect_delay = connect_delay
        self._reader = self._writer = None
        self._lock = asyncio.Lock()
        self._tid = 0
        self._last_end = 0.0

    async def close(self):
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(0.5):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass

    async def read(self, function: int, address: int, count: int = 1):
        if function not in (3, 4) or not 1 <= count <= 125:
            raise ValueError("Invalid read")
        if not 0 <= address <= 65535 or address + count > 65536:
            raise ValueError("Invalid register address")
        pdu = struct.pack(">BHH", function, address, count)
        for attempt in range(_READ_ATTEMPTS):
            try:
                reply = await self._exchange(pdu)
                break
            except TransportError as err:
                if attempt + 1 == _READ_ATTEMPTS:
                    raise TransportError(
                        f"{err}; read failed after {_READ_ATTEMPTS} attempts"
                    ) from err
                # _exchange closed the failed connection. Retry this read only;
                # never retry writes, Modbus exceptions or malformed replies.
                _LOGGER.debug("Retrying read after communication failure: %s", err)
                await asyncio.sleep(_READ_RETRY_DELAY)
        if len(reply) != 2 + 2 * count or reply[1] != 2 * count:
            await self.close()
            raise BenyError(
                f"FC{function:02d} register 0x{address:04X}: unexpected register count "
                f"(expected {count}, reply byte count {reply[1] if len(reply) > 1 else 'missing'})"
            )
        return list(struct.unpack(f">{count}H", reply[2:]))

    async def write(self, address: int, value: int):
        if not 0 <= address <= 65535 or type(value) is not int or not 0 <= value <= 65535:
            raise ValueError("Invalid register write")
        # FC16 writing ONE register is illustrated in the supplied BENY manual.
        pdu = struct.pack(">BHHBH", 16, address, 1, 2, value)
        reply = await self._exchange(pdu, writing=True)
        if reply != struct.pack(">BHH", 16, address, 1):
            await self.close()
            raise WriteUncertain("Write acknowledgement does not match request")

    async def _exchange(self, pdu: bytes, writing=False) -> bytes:
        async with self._lock:
            await asyncio.sleep(max(0, self.gap - (time.monotonic() - self._last_end)))
            attempted = False
            address = int.from_bytes(pdu[1:3], "big")
            request = f"FC{pdu[0]:02d} register 0x{address:04X} (unit {self.unit}, {self.transport})"
            phase = "opening TCP connection"
            try:
                if self._writer is None or self._writer.is_closing():
                    async with asyncio.timeout(self.timeout):
                        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
                    # The previous client allowed the gateway to settle after
                    # every connection. Do not spend the response timeout here.
                    phase = "waiting after TCP connection"
                    await asyncio.sleep(self.connect_delay)
                async with asyncio.timeout(self.timeout):
                    phase = "sending Modbus request"
                    self._tid = (self._tid + 1) & 0xFFFF
                    if self.transport == "tcp":
                        frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit) + pdu
                    else:
                        frame = bytes([self.unit]) + pdu
                        frame += struct.pack("<H", crc16(frame))
                    _LOGGER.debug("%s: TX %s", request, frame.hex(" "))
                    attempted = True
                    self._writer.write(frame)
                    await self._writer.drain()
                    phase = "waiting for Modbus response"
                    if self.transport == "tcp":
                        header = await self._reader.readexactly(7)
                        _LOGGER.debug("%s: RX TCP header %s", request, header.hex(" "))
                        tid, protocol, length, unit = struct.unpack(">HHHB", header)
                        if (tid != self._tid or protocol != 0 or unit != self.unit
                                or not 2 <= length <= 254):
                            raise BenyError(
                                f"Invalid Modbus TCP header: received [{header.hex(' ')}] "
                                f"(transaction {tid}, protocol {protocol}, length {length}, unit {unit}); "
                                f"expected transaction {self._tid}, protocol 0, length 2..254, unit {self.unit}"
                            )
                        reply = await self._reader.readexactly(length - 1)
                        _LOGGER.debug("%s: RX TCP PDU %s", request, reply.hex(" "))
                    else:
                        header = await self._reader.readexactly(2)
                        _LOGGER.debug("%s: RX RTU header %s", request, header.hex(" "))
                        unit, function = header
                        if unit != self.unit or function not in (pdu[0], pdu[0] | 0x80):
                            raise BenyError(
                                f"Unexpected RTU address or function: received [{header.hex(' ')}] "
                                f"(unit {unit}, function 0x{function:02X}); expected unit {self.unit}, "
                                f"function 0x{pdu[0]:02X} or 0x{pdu[0] | 0x80:02X}"
                            )
                        if function & 0x80:
                            tail = await self._reader.readexactly(3)
                        elif function in (3, 4):
                            count_byte = await self._reader.readexactly(1)
                            if not 2 <= count_byte[0] <= 250 or count_byte[0] % 2:
                                raise BenyError(
                                    f"Invalid RTU byte count: received 0x{count_byte[0]:02X}; "
                                    "expected an even number in 2..250"
                                )
                            tail = count_byte + await self._reader.readexactly(count_byte[0] + 2)
                        else:
                            tail = await self._reader.readexactly(6)
                        frame = header + tail
                        _LOGGER.debug("%s: RX RTU frame %s", request, frame.hex(" "))
                        if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
                            raise BenyError(
                                f"RTU CRC mismatch: received [{frame.hex(' ')}]"
                            )
                        reply = frame[1:-2]
                    if reply[0] == pdu[0] | 0x80:
                        if len(reply) != 2:
                            raise BenyError("Malformed exception response")
                        raise ModbusException(pdu[0], reply[1], address)
                    if reply[0] != pdu[0]:
                        raise BenyError("Unexpected function code")
                    return reply
            except ModbusException:
                # A valid exception is a definite rejection, not a lost reply.
                raise
            except asyncio.CancelledError:
                await self.close()
                raise
            except (OSError, TimeoutError, asyncio.IncompleteReadError, BenyError) as err:
                await self.close()
                if isinstance(err, TimeoutError):
                    detail = f"timeout after {self.timeout:g} s while {phase}"
                elif isinstance(err, asyncio.IncompleteReadError):
                    detail = (
                        f"peer closed connection while {phase}; "
                        f"received {len(err.partial)} of {err.expected} expected bytes"
                    )
                else:
                    detail = f"{phase}: {type(err).__name__}: {err}"
                if writing and attempted:
                    raise WriteUncertain(
                        f"{request}: write outcome unknown; {detail}; read back before retrying"
                    ) from err
                if isinstance(err, (OSError, TimeoutError, asyncio.IncompleteReadError)):
                    raise TransportError(f"{request}: {detail}") from err
                raise BenyError(f"{request}: {detail}") from err
            finally:
                self._last_end = time.monotonic()
