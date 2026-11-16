"""Constants for BENY Modbus."""
from homeassistant.const import Platform

DOMAIN = "beny_modbus"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH]
CONF_UNIT = "unit_id"
CONF_TRANSPORT = "transport"
CONF_MAX_CURRENT = "max_current"
CONF_CONTROL = "control_enabled"
DEFAULT_MAX_CURRENT = 6
DEFAULT_PORT = 502
VERSION = "0.1.3"
POLL_SECONDS = 2
