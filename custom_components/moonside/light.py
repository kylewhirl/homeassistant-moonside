"""Light entities backed by the Moonside cloud API."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DeviceState, MoonsideApiClient
from .const import DOMAIN
from .data import MoonsideRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Moonside lights."""

    runtime: MoonsideRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    entities: dict[str, MoonsideLightEntity] = {}

    @callback
    def _sync_entities() -> None:
        new_entities: list[MoonsideLightEntity] = []
        for device_id in coordinator.data.keys():
            if device_id not in entities:
                entity = MoonsideLightEntity(runtime, device_id)
                entities[device_id] = entity
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class MoonsideLightEntity(CoordinatorEntity[dict[str, DeviceState]], LightEntity):
    """Representation of a single Moonside lamp."""

    _attr_supported_color_modes = {ColorMode.HS}
    _attr_has_entity_name = True

    def __init__(self, runtime: MoonsideRuntimeData, device_id: str) -> None:
        super().__init__(runtime.coordinator)
        self._api: MoonsideApiClient = runtime.api
        self._device_id = device_id
        self._attr_unique_id = device_id
        self._attr_name = None

    @property
    def _state(self) -> DeviceState:
        return self.coordinator.data.get(self._device_id, {})

    @property
    def available(self) -> bool:
        return self._device_id in self.coordinator.data

    @property
    def name(self) -> str | None:
        data = self._state
        return data.get("deviceName") or self._device_id

    @property
    def device_info(self) -> DeviceInfo:
        data = self._state
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="Moonside",
            name=data.get("deviceName") or self._device_id,
            model=data.get("deviceModel") or data.get("subModel") or "Lamp",
            sw_version=data.get("deviceFirmVersion"),
        )

    @property
    def is_on(self) -> bool | None:
        return self._parse_power_state(self._state)

    @property
    def brightness(self) -> int | None:
        return self._parse_brightness(self._state)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        return self._parse_hs(self._state)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            level = self._convert_brightness(kwargs[ATTR_BRIGHTNESS])
            await self._api.async_send_control(self._device_id, f"BRIGH{level}")
            self.coordinator.handle_stream_update(self._device_id, {"brightness": level})
        if ATTR_HS_COLOR in kwargs:
            hs = kwargs[ATTR_HS_COLOR]
            command = self._build_color_command(hs)
            await self._api.async_send_control(self._device_id, command)
            self.coordinator.handle_stream_update(self._device_id, {"controlData": command})
        if ATTR_BRIGHTNESS not in kwargs and ATTR_HS_COLOR not in kwargs:
            await self._api.async_send_control(self._device_id, "LEDON")
            self.coordinator.handle_stream_update(self._device_id, {"controlData": "LEDON"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._api.async_send_control(self._device_id, "LEDOFF")
        self.coordinator.handle_stream_update(self._device_id, {"controlData": "LEDOFF"})

    def _parse_power_state(self, data: DeviceState) -> bool:
        command = str(data.get("controlData", "")).upper()
        if "LEDON" in command:
            return True
        if "LEDOFF" in command:
            return False
        if (
            command.startswith("THEME")
            or command.startswith("COLOR")
            or command.startswith("PIXEL")
            or command.startswith("BRIGH")
        ):
            return True
        if isinstance(data.get("on"), bool):
            return bool(data["on"])
        return False

    def _parse_brightness(self, data: DeviceState) -> int | None:
        if isinstance(data.get("brightness"), (int, float)):
            level = int(data["brightness"])
            return self._scale_brightness(level)
        command = str(data.get("controlData", ""))
        if command.upper().startswith("BRIGH"):
            try:
                level = int(command[5:])
            except ValueError:
                return None
            return self._scale_brightness(level)
        return None

    def _parse_hs(self, data: DeviceState) -> tuple[float, float] | None:
        command = str(data.get("controlData", ""))
        if command.upper().startswith("COLOR") and len(command) >= 14:
            payload = command[5:]
            if payload.isdigit() and len(payload) == 9:
                rgb = (
                    int(payload[0:3]) / 255,
                    int(payload[3:6]) / 255,
                    int(payload[6:9]) / 255,
                )
                return self._rgb_to_hs(rgb)
        hex_val = data.get("colorHEXDecimal")
        if isinstance(hex_val, int):
            hex_string = f"{hex_val:06x}"
            rgb = (
                int(hex_string[0:2], 16) / 255,
                int(hex_string[2:4], 16) / 255,
                int(hex_string[4:6], 16) / 255,
            )
            return self._rgb_to_hs(rgb)
        return None

    def _convert_brightness(self, value: Any) -> int:
        ha_level = int(value)
        return max(1, min(100, round(ha_level * 100 / 255)))

    def _scale_brightness(self, value: int) -> int:
        return max(1, min(255, round(value * 255 / 100)))

    def _build_color_command(self, hs: tuple[float, float]) -> str:
        r, g, b = self._hs_to_rgb(hs)
        return "COLOR" + "".join(str(max(0, min(255, channel))).zfill(3) for channel in (r, g, b))

    def _hs_to_rgb(self, hs: tuple[float, float]) -> tuple[int, int, int]:
        h, s = hs
        s = max(0.0, min(1.0, s / 100))
        h = h % 360
        v = 1.0
        c = v * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = v - c
        r, g, b = 0.0, 0.0, 0.0
        if 0 <= h < 60:
            r, g = c, x
        elif 60 <= h < 120:
            r, g = x, c
        elif 120 <= h < 180:
            g, b = c, x
        elif 180 <= h < 240:
            g, b = x, c
        elif 240 <= h < 300:
            r, b = x, c
        else:
            r, b = c, x
        return (
            int(round((r + m) * 255)),
            int(round((g + m) * 255)),
            int(round((b + m) * 255)),
        )

    def _rgb_to_hs(self, rgb: tuple[float, float, float]) -> tuple[float, float]:
        r, g, b = rgb
        max_val = max(r, g, b)
        min_val = min(r, g, b)
        delta = max_val - min_val
        if delta == 0:
            hue = 0
        elif max_val == r:
            hue = 60 * (((g - b) / delta) % 6)
        elif max_val == g:
            hue = 60 * (((b - r) / delta) + 2)
        else:
            hue = 60 * (((r - g) / delta) + 4)
        saturation = 0 if max_val == 0 else (delta / max_val) * 100
        return round(hue, 2), round(saturation, 2)
