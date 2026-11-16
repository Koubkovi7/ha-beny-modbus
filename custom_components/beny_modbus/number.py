"""Volatile charging-current limit. Never writes permanent register 0x0203."""
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfElectricCurrent
from .entity import BenyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BenyCurrentNumber(entry.runtime_data)])

class BenyCurrentNumber(BenyEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 6
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator):
        super().__init__(coordinator, "current_limit")

    @property
    def available(self):
        return (super().available and self.coordinator.device.control_enabled
                and 6 <= self.coordinator.data.permanent_limit <= 32)

    @property
    def native_max_value(self):
        permanent = self.coordinator.data.permanent_limit
        return min(self.coordinator.device.max_current, permanent) if permanent >= 6 else 6

    @property
    def native_value(self):
        return self.coordinator.data.current_limit

    async def async_set_native_value(self, value):
        await self.coordinator.command("current", value)
