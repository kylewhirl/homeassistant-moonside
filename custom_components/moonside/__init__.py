"""Set up the Moonside custom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MoonsideApiClient, MoonsideApiError, ThemeDefinition
from .const import (
    CONF_THEME_SWITCHES,
    DOMAIN,
    FIREBASE_API_KEY,
    LOGGER,
    PLATFORMS,
)
from .coordinator import MoonsideDataUpdateCoordinator
from .data import MoonsideRuntimeData


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load a config entry."""

    hass.data.setdefault(DOMAIN, {})
    merged_options = _merge_entry_options(entry)

    session = async_get_clientsession(hass)
    api = MoonsideApiClient(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        FIREBASE_API_KEY,
    )

    coordinator = MoonsideDataUpdateCoordinator(hass, api, merged_options)
    await coordinator.async_config_entry_first_refresh()

    themes = await _resolve_theme_definitions(api, merged_options.get(CONF_THEME_SWITCHES, []))

    async def handle_stream_update(device_id: str, update: dict[str, Any] | None) -> None:
        coordinator.handle_stream_update(device_id, update)

    async def handle_stream_error(error: Exception) -> None:
        LOGGER.warning("Moonside realtime stream issue: %s", error)

    unsubscribe = await api.async_subscribe_to_updates(
        handle_stream_update,
        handle_stream_error,
        coordinator.async_refresh_from_cloud,
    )

    entry_data = MoonsideRuntimeData(api=api, coordinator=coordinator, themes=themes, unsubscribe=unsubscribe)
    hass.data[DOMAIN][entry.entry_id] = entry_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime: MoonsideRuntimeData | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if runtime:
        if runtime.unsubscribe:
            runtime.unsubscribe()
        await runtime.api.async_close()
    return unload_ok


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry option updates."""

    await hass.config_entries.async_reload(entry.entry_id)


def _merge_entry_options(entry: ConfigEntry) -> dict[str, Any]:
    merged = dict(entry.data)
    merged.update(entry.options)
    return merged


async def _resolve_theme_definitions(
    api: MoonsideApiClient,
    theme_names: list[str] | None,
) -> list[ThemeDefinition]:
    names = [name.strip() for name in (theme_names or []) if name.strip()]
    if not names:
        return []
    try:
        library = await api.async_fetch_theme_library()
    except MoonsideApiError as error:
        LOGGER.warning("Failed to fetch Moonside theme catalog: %s", error)
        return []

    definitions: list[ThemeDefinition] = []
    for name in names:
        definition = library.get(name.lower())
        if definition:
            definitions.append(definition)
        else:
            LOGGER.warning('Theme "%s" is not present in Moonside\'s catalog', name)
    return definitions
