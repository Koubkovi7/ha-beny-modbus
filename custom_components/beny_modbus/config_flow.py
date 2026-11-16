"""UI setup; discovery/validation never writes to the charger."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback

from .const import (
    DOMAIN, CONF_UNIT, CONF_TRANSPORT, CONF_MAX_CURRENT, CONF_CONTROL,
    DEFAULT_MAX_CURRENT, DEFAULT_PORT,
)
from .library.protocol import BenyError, ModbusClient
from .library.device import BenyDevice, CommandRejected

def connection_schema(defaults=None):
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_NAME, default=d.get(CONF_NAME, "BENY Wallbox")): str,
        vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)):
            vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required(CONF_TRANSPORT, default=d.get(CONF_TRANSPORT, "tcp")):
            vol.In({"rtu_over_tcp": "Modbus RTU over TCP", "tcp": "Modbus TCP"}),
        vol.Required(CONF_UNIT, default=d.get(CONF_UNIT, 1)):
            vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
    })

def options_schema(defaults=None):
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_MAX_CURRENT, default=d.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT)):
            vol.All(vol.Coerce(int), vol.Range(min=6, max=32)),
        vol.Required(CONF_CONTROL, default=d.get(CONF_CONTROL, True)): bool,
    })

async def validate_connection(data):
    client = ModbusClient(
        data[CONF_HOST], data[CONF_PORT], data[CONF_UNIT], data[CONF_TRANSPORT]
    )
    try:
        device = BenyDevice(client)
        identity = await device.identify()
        await device.poll()
        return identity
    finally:
        await client.close()

class BenyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BenyOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip().lower().rstrip(".")
            unique = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_UNIT]}"
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured()
            try:
                await validate_connection(user_input)
            except CommandRejected:
                errors["base"] = "unsupported_device"
            except (BenyError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                self._connection_data = user_input
                return await self.async_step_limits()
        return self.async_show_form(
            step_id="user", data_schema=connection_schema(user_input), errors=errors
        )

    async def async_step_limits(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=self._connection_data[CONF_NAME],
                data={**self._connection_data, **user_input},
            )
        return self.async_show_form(step_id="limits", data_schema=options_schema())

    async def async_step_reconfigure(self, user_input=None):
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip().lower().rstrip(".")
            unique = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_UNIT]}"
            if any(e.entry_id != entry.entry_id and e.unique_id == unique
                   for e in self._async_current_entries()):
                errors["base"] = "already_configured"
            else:
                try:
                    await validate_connection(user_input)
                except CommandRejected:
                    errors["base"] = "unsupported_device"
                except (BenyError, ValueError):
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data={**entry.data, **user_input},
                        title=user_input[CONF_NAME], unique_id=unique,
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=connection_schema(user_input or entry.data), errors=errors,
        )

class BenyOptionsFlow(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema({**self.config_entry.data, **self.config_entry.options}),
        )
