"""Config flow for the Moonside integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MoonsideApiClient,
    MoonsideApiError,
    MoonsideAuthenticationError,
    MoonsideCommunicationError,
)
from .const import (
    CONF_ENABLE_POLLING,
    CONF_POLLING_INTERVAL,
    CONF_THEME_SWITCHES,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    FIREBASE_API_KEY,
)

THEME_DELIMITERS = (",", "\n")


class MoonsideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Moonside."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            themes = _parse_theme_input(user_input.get(CONF_THEME_SWITCHES))
            data = dict(user_input)
            data[CONF_THEME_SWITCHES] = themes
            try:
                await self._test_credentials(data)
            except MoonsideAuthenticationError:
                errors["base"] = "auth"
            except MoonsideCommunicationError:
                errors["base"] = "connection"
            except MoonsideApiError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_EMAIL], data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input),
            errors=errors,
        )

    async def _test_credentials(self, data: dict) -> None:
        session = async_get_clientsession(self.hass)
        api = MoonsideApiClient(
            session,
            data[CONF_EMAIL],
            data[CONF_PASSWORD],
            FIREBASE_API_KEY,
        )
        try:
            await api.async_fetch_devices()
        finally:
            await api.async_close()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return MoonsideOptionsFlowHandler(config_entry)


class MoonsideOptionsFlowHandler(config_entries.OptionsFlow):
    """Allow updating advanced settings."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.config_entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            data[CONF_THEME_SWITCHES] = _parse_theme_input(user_input.get(CONF_THEME_SWITCHES))
            return self.async_create_entry(title="", data=data)
        current = {
            key: self.config_entry.options.get(key, self.config_entry.data.get(key))
            for key in (
                CONF_THEME_SWITCHES,
                CONF_ENABLE_POLLING,
                CONF_POLLING_INTERVAL,
            )
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(current, include_auth=False),
            errors=errors,
        )


def _build_schema(
    existing: dict | None,
    *,
    include_auth: bool = True,
) -> vol.Schema:
    existing = existing or {}
    schema: dict = {}
    if include_auth:
        schema[vol.Required(CONF_EMAIL, default=existing.get(CONF_EMAIL, vol.UNDEFINED))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL),
        )
        schema[vol.Required(CONF_PASSWORD)] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
        )
    schema[vol.Optional(
        CONF_THEME_SWITCHES,
        default=_format_theme_input(existing.get(CONF_THEME_SWITCHES)),
    )] = selector.TextSelector(
        selector.TextSelectorConfig(multiline=True),
    )
    schema[vol.Optional(
        CONF_ENABLE_POLLING,
        default=existing.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING),
    )] = selector.BooleanSelector()
    schema[vol.Optional(
        CONF_POLLING_INTERVAL,
        default=existing.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
    )] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=5, max=600, step=1, mode=selector.NumberSelectorMode.BOX),
    )
    return vol.Schema(schema)


def _parse_theme_input(raw: str | list[str] | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        sanitized = raw
        for delimiter in THEME_DELIMITERS:
            sanitized = sanitized.replace(delimiter, "\n")
        values = sanitized.splitlines()
    return [value.strip() for value in values if value and value.strip()]


def _format_theme_input(value: list[str] | str | None) -> str:
    if isinstance(value, list):
        return "\n".join(value)
    if isinstance(value, str):
        return value
    return ""
