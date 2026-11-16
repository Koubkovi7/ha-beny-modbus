"""Small asynchronous Modbus client for BENY v3.8 (FC03, FC04, FC16).

No write retries. A missing acknowledgement is an unknown outcome, not proof
that the charger did not receive the command. Close broken connections so that
late replies cannot be mistaken for replies to subsequent requests.
"""

import asyncio
import struct
import time


class BenyError(Exception):
    """Communication or device error."""


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
                 timeout=2.0, gap=0.08):
        if not host or not 1 <= int(port) <= 65535 or not 1 <= int(unit) <= 247:
            raise ValueError("Invalid host, port or Modbus address")
        if transport not in ("tcp", "rtu_over_tcp"):
            raise ValueError("Unsupported transport")
        if not 0 < timeout <= 10 or not 0 <= gap <= 1:
            raise ValueError("Invalid timeout or request gap")
        self.host, self.port, self.unit = host, int(port), int(unit)
        self.transport, self.timeout, self.gap = transport, timeout, gap
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
        reply = await self._exchange(pdu)
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
                async with asyncio.timeout(self.timeout):
                    if self._writer is None or self._writer.is_closing():
                        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
                    phase = "sending Modbus request"
                    self._tid = (self._tid + 1) & 0xFFFF
                    if self.transport == "tcp":
                        frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit) + pdu
                    else:
                        frame = bytes([self.unit]) + pdu
                        frame += struct.pack("<H", crc16(frame))
                    attempted = True
                    self._writer.write(frame)
                    await self._writer.drain()
                    phase = "waiting for Modbus response"
                    if self.transport == "tcp":
                        header = await self._reader.readexactly(7)
                        tid, protocol, length, unit = struct.unpack(">HHHB", header)
                        if (tid != self._tid or protocol != 0 or unit != self.unit
                                or not 2 <= length <= 254):
                            raise BenyError("Invalid Modbus TCP header")
                        reply = await self._reader.readexactly(length - 1)
                    else:
                        header = await self._reader.readexactly(2)
                        unit, function = header
                        if unit != self.unit or function not in (pdu[0], pdu[0] | 0x80):
                            raise BenyError("Unexpected RTU address or function")
                        if function & 0x80:
                            tail = await self._reader.readexactly(3)
                        elif function in (3, 4):
                            count_byte = await self._reader.readexactly(1)
                            if not 2 <= count_byte[0] <= 250 or count_byte[0] % 2:
                                raise BenyError("Invalid RTU byte count")
                            tail = count_byte + await self._reader.readexactly(count_byte[0] + 2)
                        else:
                            tail = await self._reader.readexactly(6)
                        frame = header + tail
                        if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
                            raise BenyError("RTU CRC mismatch")
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
                raise BenyError(f"{request}: {detail}") from err
            finally:
                self._last_end = time.monotonic()
