"""Single-connector BENY Smart charger; no tariff or load-balancing logic."""

import asyncio
import math
import time
from dataclasses import dataclass

from .protocol import BenyError, ModbusException, WriteUncertain


class CommandRejected(BenyError):
    """A command is not safe or not confirmed."""


@dataclass(frozen=True)
class Identity:
    model: str
    firmware_raw: int
    hardware_raw: int
    phases: int


@dataclass(frozen=True)
class Snapshot:
    energy_kwh: float
    voltages: tuple
    currents: tuple
    faults: int
    connector: int
    allowed_current: int | None
    current_limit: int
    enabled: bool
    permanent_limit: int


class BenyDevice:
    def __init__(self, client, max_current=6, control_enabled=True, clock=time.monotonic):
        if type(max_current) is not int or not 6 <= max_current <= 32:
            raise ValueError("Installation current limit must be 6–32 A")
        self.client, self.max_current = client, max_current
        self.control_enabled, self.clock = control_enabled, clock
        self.lock = asyncio.Lock()
        self.identity = None
        self.snapshot = None
        self.watchdog_seconds = None
        self._allowed_supported = True
        self._last_start = self._last_stop = float("-inf")

    async def _one(self, function, address):
        return (await self.client.read(function, address, 1))[0]

    async def identify(self):
        async with self.lock:
            attribute = await self._one(4, 0)
            # Deliberately individual reads: old BENY/Waveshare setup rejected blocks.
            parts = []
            for address in range(1, 11):
                parts.append((await self._one(4, address)).to_bytes(2, "big"))
            model_bytes = b"".join(parts)
            model = model_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
            fw, hw = await self._one(4, 0x0B), await self._one(4, 0x0C)
            if attribute not in (1, 3) or not model.startswith("BCP-") or not model.endswith("-L"):
                raise CommandRejected("This version supports single-connector BENY Smart (-L) chargers only")
            self.identity = Identity(model, fw, hw, attribute)
            return self.identity

    async def read_watchdog(self):
        async with self.lock:
            try:
                value = await self._one(3, 0x0205)
            except ModbusException as err:
                if err.code not in (1, 2, 3):
                    raise
                value = None
            # Only read it. No silent changes to charger-side safety settings.
            self.watchdog_seconds = value if value is not None and 10 <= value <= 3600 else None
            return self.watchdog_seconds

    async def poll(self):
        async with self.lock:
            values = []
            for address in range(0x0100, 0x0109):
                values.append(await self._one(4, address))
            allowed = None
            if self._allowed_supported:
                try:
                    allowed = await self._one(4, 0x0109)
                except ModbusException as err:
                    if err.code not in (1, 2, 3):
                        raise
                    self._allowed_supported = False
            current = await self._one(3, 0x0200)
            enabled = await self._one(3, 0x0201)
            permanent = await self._one(3, 0x0203)
            if enabled not in (0, 1) or values[8] not in (0, 1, 2, 3):
                raise BenyError("Unknown charger state; controls require a known state")
            self.snapshot = Snapshot(
                values[0] / 10, tuple(v / 10 for v in values[1:4]),
                tuple(v / 10 for v in values[4:7]), values[7], values[8],
                allowed, current, bool(enabled), permanent,
            )
            return self.snapshot

    def _controls(self):
        if not self.control_enabled:
            raise CommandRejected("Control is disabled in the integration options")

    def _ceiling(self, permanent):
        if not 6 <= permanent <= 32:
            raise CommandRejected("Cannot validate the charger permanent current limit")
        return min(self.max_current, permanent)

    async def _write_verified(self, address, value):
        uncertain = None
        try:
            await self.client.write(address, value)
        except WriteUncertain as err:
            uncertain = err
        # Never repeat the write after a missing acknowledgement.
        try:
            actual = await self._one(3, address)
        except BenyError as err:
            raise CommandRejected("Command outcome unknown; no automatic retry was sent") from err
        if actual != value:
            raise CommandRejected("Charger did not confirm the requested value") from uncertain

    async def set_current(self, value):
        self._controls()
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value != int(value)):
            raise CommandRejected("Current must be a whole number of amperes")
        async with self.lock:
            ceiling = self._ceiling(await self._one(3, 0x0203))
            if not 6 <= value <= ceiling:
                raise CommandRejected(f"Current must be between 6 and {ceiling} A")
            if await self._one(3, 0x0200) == int(value):
                return False
            await self._write_verified(0x0200, int(value))
            return True

    async def start(self):
        self._controls()
        async with self.lock:
            enabled = await self._one(3, 0x0201)
            if enabled == 1:
                return False  # Authorized but not charging is NOT a reason to restart.
            if enabled != 0:
                raise CommandRejected("Unknown authorization state")
            now = self.clock()
            if now - max(self._last_start, self._last_stop) < 30:
                raise CommandRejected("Wait 30 seconds before another start attempt")
            faults = await self._one(4, 0x0107)
            connector = await self._one(4, 0x0108)
            if faults or connector not in (0, 1, 3):
                raise CommandRejected("Charger has a fault or conflicting state; check Plug&Play")
            ceiling = self._ceiling(await self._one(3, 0x0203))
            current = await self._one(3, 0x0200)
            target = min(current, ceiling) if current >= 6 else 6
            if target != current:
                await self._write_verified(0x0200, target)
            # Record BEFORE sending. Unknown outcomes must not trigger rapid retries.
            self._last_start = self.clock()
            await self._write_verified(0x0201, 1)
            return True

    async def stop(self):
        self._controls()
        async with self.lock:
            self._last_stop = self.clock()
            try:
                enabled = await self._one(3, 0x0201)
                connector = await self._one(4, 0x0108)
                if enabled == 0 and connector != 2:
                    return False
            except BenyError:
                # A manual stop still gets one attempt if its pre-read fails.
                pass
            await self._write_verified(0x0201, 0)
            return True
