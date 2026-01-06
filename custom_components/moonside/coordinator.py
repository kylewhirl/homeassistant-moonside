"""Coordinator that mirrors the Homebridge polling + realtime hybrid."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import DeviceState, MoonsideApiClient
from .const import (
    CONF_ENABLE_POLLING,
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    LOGGER,
    POLLING_MIN_INTERVAL,
)


class MoonsideDataUpdateCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """Keep Moonside device state in sync."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: MoonsideApiClient,
        entry_options: dict[str, Any],
    ) -> None:
        self.api = api
        self.devices: dict[str, DeviceState] = {}
        enable_polling: bool = entry_options.get(CONF_ENABLE_POLLING, False)
        interval_seconds = max(
            POLLING_MIN_INTERVAL,
            int(entry_options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)),
        )
        update_interval = timedelta(seconds=interval_seconds) if enable_polling else None
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} devices",
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> dict[str, DeviceState]:
        devices = await self.api.async_fetch_devices()
        self.devices = devices
        return deepcopy(self.devices)

    async def async_refresh_from_cloud(self) -> None:
        await self.async_request_refresh()

    def handle_stream_update(self, device_id: str, update: DeviceState | None) -> None:
        if update is None:
            if device_id in self.devices:
                del self.devices[device_id]
        else:
            merged = self._merge_dicts(self.devices.get(device_id, {}), update)
            self.devices[device_id] = merged
        self.async_set_updated_data(deepcopy(self.devices))

    def _merge_dicts(self, base: DeviceState, update: DeviceState) -> DeviceState:
        merged = dict(base)
        for key, value in update.items():
            if (
                isinstance(value, dict)
                and isinstance(merged.get(key), dict)
            ):
                merged[key] = self._merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged
