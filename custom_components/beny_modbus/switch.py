"""Charging authorization is distinct from actual charging."""
from homeassistant.components.switch import SwitchEntity
from .entity import BenyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BenyEnableSwitch(entry.runtime_data)])

class BenyEnableSwitch(BenyEntity, SwitchEntity):
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator):
        super().__init__(coordinator, "charging_enabled")

    @property
    def available(self):
        return super().available and self.coordinator.device.control_enabled

    @property
    def is_on(self):
        return self.coordinator.data.enabled

    async def async_turn_on(self, **kwargs):
        await self.coordinator.command("start")

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command("stop")
