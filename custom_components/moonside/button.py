"""Stateless buttons that trigger configured Moonside themes."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ThemeDefinition
from .const import DOMAIN
from .data import MoonsideRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up configured theme buttons."""

    runtime: MoonsideRuntimeData = hass.data[DOMAIN][entry.entry_id]
    if not runtime.themes:
        return
    coordinator = runtime.coordinator
    entities: dict[str, MoonsideThemeButton] = {}

    @callback
    def _sync_entities() -> None:
        if not runtime.themes:
            return
        new_entities: list[MoonsideThemeButton] = []
        for device_id in coordinator.data.keys():
            for theme in runtime.themes:
                key = f"{device_id}:{theme.id}"
                if key in entities:
                    continue
                entity = MoonsideThemeButton(runtime, device_id, theme)
                entities[key] = entity
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class MoonsideThemeButton(CoordinatorEntity, ButtonEntity):
    """Button that fires a Moonside theme on press."""

    _attr_has_entity_name = True

    def __init__(self, runtime: MoonsideRuntimeData, device_id: str, theme: ThemeDefinition) -> None:
        super().__init__(runtime.coordinator)
        self._api = runtime.api
        self._device_id = device_id
        self._theme = theme
        self._attr_unique_id = f"{device_id}-theme-{theme.id}"
        self._attr_name = theme.name

    @property
    def device_info(self) -> DeviceInfo:
        state = self.coordinator.data.get(self._device_id, {})
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="Moonside",
            name=state.get("deviceName") or self._device_id,
            model=state.get("deviceModel") or "Lamp",
            sw_version=state.get("deviceFirmVersion"),
        )

    async def async_press(self) -> None:
        await self._api.async_send_control(self._device_id, self._theme.control_data)
        self.coordinator.handle_stream_update(
            self._device_id,
            {"controlData": self._theme.control_data},
        )

    @property
    def available(self) -> bool:
        return self._device_id in self.coordinator.data
