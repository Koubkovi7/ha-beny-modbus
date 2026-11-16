"""Common device identity and availability."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

class BenyEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        identity = coordinator.device.identity
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title, manufacturer="BENY",
            model=identity.model,
            sw_version=f"raw 0x{identity.firmware_raw:04X}",
            hw_version=f"raw 0x{identity.hardware_raw:04X}",
        )
