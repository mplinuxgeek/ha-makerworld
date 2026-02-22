"""Config flow for MakerWorld integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COOKIE,
    CONF_MAX_MODELS,
    CONF_USER,
    CONF_USER_AGENT,
    DEFAULT_MAX_MODELS,
    DEFAULT_UA,
    DOMAIN,
)


class MakerWorldConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MakerWorld."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            user = user_input[CONF_USER].lstrip("@")
            await self.async_set_unique_id(user)
            self._abort_if_unique_id_configured()

            data = {
                CONF_USER: user,
                CONF_COOKIE: user_input[CONF_COOKIE],
                CONF_USER_AGENT: user_input.get(CONF_USER_AGENT, DEFAULT_UA),
            }
            return self.async_create_entry(title=f"MakerWorld {user}", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_USER): str,
                vol.Required(CONF_COOKIE): str,
                vol.Optional(CONF_USER_AGENT, default=DEFAULT_UA): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Handle reconfiguration from the integration/device configure action."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            new_data = {
                **entry.data,
                CONF_COOKIE: user_input[CONF_COOKIE],
                CONF_USER_AGENT: user_input.get(CONF_USER_AGENT, DEFAULT_UA),
            }
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            return self.async_abort(reason="reconfigure_successful")

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COOKIE,
                    default=entry.data.get(CONF_COOKIE, ""),
                ): str,
                vol.Optional(
                    CONF_USER_AGENT,
                    default=entry.data.get(CONF_USER_AGENT, DEFAULT_UA),
                ): str,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return MakerWorldOptionsFlowHandler(config_entry)


class MakerWorldOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for MakerWorld."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_max = self._entry.options.get(CONF_MAX_MODELS, DEFAULT_MAX_MODELS)

        schema = vol.Schema(
            {
                vol.Optional(CONF_MAX_MODELS, default=current_max): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
