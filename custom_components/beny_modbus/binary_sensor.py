"""Actual charging, connector presence and fault state."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from .entity import BenyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        BenyBinary(entry.runtime_data, "charging", None, lambda d: d.connector == 2),
        BenyBinary(entry.runtime_data, "connected", BinarySensorDeviceClass.PLUG, lambda d: d.connector != 0),
        BenyBinary(entry.runtime_data, "fault", BinarySensorDeviceClass.PROBLEM, lambda d: d.faults != 0),
    ])

class BenyBinary(BenyEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, device_class, getter):
        super().__init__(coordinator, key)
        self._attr_device_class = device_class
        self.getter = getter
        if key == "fault":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        return self.getter(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if self._attr_translation_key != "fault":
            return None
        names = [
            "over_voltage", "under_voltage", "over_current", "over_temperature",
            "poor_grounding", "neutral_live_reversal", "leakage", "charge_guidance",
            "emergency_stop", "cable_resistance", "connector_lock", "contactor",
            "reserved_12", "reserved_13", "reserved_14", "other",
        ]
        mask = self.coordinator.data.faults
        return {"raw": mask, "codes": [name for bit, name in enumerate(names) if mask & (1 << bit)]}
