"""Read-only polling plus explicitly requested, serialized control actions."""
import asyncio
from datetime import timedelta
from functools import partial
import logging

from homeassistant.components import persistent_notification
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CONF_UNIT, CONF_TRANSPORT, CONF_MAX_CURRENT, CONF_CONTROL, POLL_SECONDS,
)
from .library.protocol import ModbusClient, BenyError
from .library.device import BenyDevice

_LOGGER = logging.getLogger(__name__)

class BenyCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.entry = entry
        data = {**entry.data, **entry.options}
        self.client = ModbusClient(
            data[CONF_HOST], data[CONF_PORT], data[CONF_UNIT], data[CONF_TRANSPORT]
        )
        self.device = BenyDevice(
            self.client, data[CONF_MAX_CURRENT], data[CONF_CONTROL]
        )
        self.last_success = None
        self._cancel_poll = self._cancel_start_check = None
        self._tick_task = None
        self._closed = False
        self._check_generation = 0
        self._command_lock = asyncio.Lock()
        super().__init__(
            hass, _LOGGER, name=entry.title, config_entry=entry,
            update_interval=None, always_update=True,
        )

    async def _async_setup(self):
        try:
            await self.device.identify()
        except BenyError as err:
            raise UpdateFailed(str(err)) from err
        try:
            await self.device.read_watchdog()
        except BenyError:
            # Unsupported/failed optional read must not hide mandatory telemetry.
            _LOGGER.debug("BENY watchdog setting could not be read")

    async def _async_update_data(self):
        try:
            snapshot = await self.device.poll()
        except BenyError as err:
            raise UpdateFailed(str(err)) from err
        self.last_success = dt_util.utcnow()
        if snapshot.connector == 2:
            self.cancel_start_check()
        return snapshot

    def start_polling(self):
        # Independent of entity listeners: reading also maintains Modbus activity.
        # No START writes here, including during reconnects.
        self._cancel_poll = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=POLL_SECONDS)
        )

    async def _tick(self, _now):
        if self._closed or (self._tick_task and not self._tick_task.done()):
            return
        self._tick_task = asyncio.current_task()
        try:
            await self.async_refresh()
        finally:
            self._tick_task = None

    def cancel_start_check(self):
        self._check_generation += 1
        if self._cancel_start_check:
            self._cancel_start_check()
            self._cancel_start_check = None

    def _notify(self, text):
        persistent_notification.async_create(
            self.hass, text, title=f"{self.entry.title}: kontrola nabíjení",
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_start",
        )

    async def _check_start(self, generation, _now):
        if generation != self._check_generation:
            return
        self._cancel_start_check = None
        if self._closed:
            return
        await self.async_refresh()
        if self._closed or generation != self._check_generation:
            return
        if not self.last_update_success:
            self._notify("Po požadavku na start nelze ověřit stav wallboxu. Další start nebyl odeslán.")
        elif self.data.connector != 2:
            self._notify(
                "Do 2 minut nebylo zaznamenáno nabíjení. Auto může být nabité, "
                "nepřipojené nebo čekat podle vlastního plánu. Další start nebyl odeslán."
            )

    async def command(self, name, value=None):
        async with self._command_lock:
            if self._closed:
                raise HomeAssistantError("Integrace se vypíná.")
            if name == "stop":
                self.cancel_start_check()
            try:
                if name == "start":
                    changed = await self.device.start()
                    if changed:
                        self.cancel_start_check()
                        persistent_notification.async_dismiss(
                            self.hass, f"{DOMAIN}_{self.entry.entry_id}_start"
                        )
                        self._cancel_start_check = async_call_later(
                            self.hass, 120, partial(self._check_start, self._check_generation)
                        )
                elif name == "stop":
                    await self.device.stop()
                elif name == "current":
                    await self.device.set_current(value)
                else:
                    raise ValueError("Unknown command")
            except BenyError as err:
                await self.async_refresh()
                raise HomeAssistantError(f"BENY: {err}") from err
            await self.async_refresh()

    async def shutdown(self):
        self._closed = True
        self.cancel_start_check()
        if self._cancel_poll:
            self._cancel_poll()
            self._cancel_poll = None
        task = self._tick_task
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Unload/restart does not send START, STOP or restore old setpoints.
        async with self._command_lock:
            async with self.device.lock:
                await self.client.close()
