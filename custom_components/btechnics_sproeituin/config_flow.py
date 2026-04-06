"""Config flow voor Btechnics Sproeituin."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_MQTT_BASE, CONF_DEVICE_NAME


class SproeituinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow handler."""
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_MQTT_BASE])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get(CONF_DEVICE_NAME, "Sproeituin"),
                data=user_input
            )

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_NAME, default="Sproeituin"): str,
            vol.Required(CONF_MQTT_BASE,   default="sproeituin"):  str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors
        )
