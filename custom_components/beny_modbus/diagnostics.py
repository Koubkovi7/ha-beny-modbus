"""Diagnostic export deliberately omits IP, name and user identifiers."""
from dataclasses import asdict
from .const import VERSION

async def async_get_config_entry_diagnostics(hass, entry):
    c = entry.runtime_data
    return {
        "integration_version": VERSION,
        "identity": asdict(c.device.identity) if c.device.identity else None,
        "transport": entry.data["transport"],
        "max_current": c.device.max_current,
        "control_enabled": c.device.control_enabled,
        "watchdog_seconds": c.device.watchdog_seconds,
        "last_update_success": c.last_update_success,
        "last_success": c.last_success.isoformat() if c.last_success else None,
        "registers": asdict(c.data) if c.data else None,
    }
