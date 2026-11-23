"""BENY measured values, enums, and raw firmware diagnostics."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    EntityCategory, UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfEnergy,
    UnitOfPower, UnitOfTime,
)
from .entity import BenyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    entities = []
    for phase in range(3):
        entities.extend([
            BenySensor(c, f"voltage_l{phase + 1}", lambda d, p=phase: d.voltages[p],
                       SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT),
            BenySensor(c, f"current_l{phase + 1}", lambda d, p=phase: d.currents[p],
                       SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT),
        ])
    entities.extend([
        BenySensor(c, "estimated_power", lambda d: d.estimated_power_w,
                   SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
        # Session counter resets on reconnect. No lifetime/Energy dashboard claim.
        BenySensor(c, "session_energy", lambda d: d.energy_kwh,
                   SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR),
        BenySensor(c, "allowed_current", lambda d: d.allowed_current,
                   SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE),
        BenySensor(c, "permanent_current", lambda d: d.permanent_limit,
                   SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, diagnostic=True),
        BenySensor(c, "connector_status",
                   lambda d: ["disconnected", "connected_idle", "charging", "waiting"][d.connector],
                   SensorDeviceClass.ENUM,
                   options=["disconnected", "connected_idle", "charging", "waiting"]),
        BenySensor(c, "watchdog_timeout", lambda d: c.device.watchdog_seconds,
                   SensorDeviceClass.DURATION, UnitOfTime.SECONDS, diagnostic=True),
        BenySensor(c, "last_communication", lambda d: c.last_success,
                   SensorDeviceClass.TIMESTAMP, diagnostic=True),
    ])
    async_add_entities(entities)

class BenySensor(BenyEntity, SensorEntity):
    def __init__(self, coordinator, key, getter, device_class=None, unit=None,
                 state_class=None, diagnostic=False, options=None):
        super().__init__(coordinator, key)
        self.getter = getter
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_options = options
        if key == "estimated_power":
            self._attr_suggested_display_precision = 1
            self._attr_extra_state_attributes = {"assumed_power_factor": 1.0}
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key == "last_communication":
            # A timestamp changing every two seconds need not fill the recorder.
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        return self.getter(self.coordinator.data)
