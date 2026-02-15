"""Light platform for Daelim SmartHome."""

from __future__ import annotations

import re
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

REGEX_3_LEVEL = re.compile(r"Lt([0-9]{0,2})-([0-9]{0,2})", re.I)
MIN_3_LEVEL, MID_3_LEVEL, MAX_3_LEVEL = 1, 3, 6


def _brightness_from_api(device_id: str, raw: str | None) -> int:
    """Convert API brightness to 0-255."""
    if raw is None or raw == "":
        return 0
    if REGEX_3_LEVEL.match(device_id) and len(raw) <= 1:
        # 0,1,3,6 -> 0, 33, 66, 100
        val = int(raw) if raw else 0
        if val == 0:
            return 0
        if val <= 1:
            return 85
        if val <= 3:
            return 170
        return 255
    # 10,20,...80
    return min(255, int(int(raw) / 100 * 255)) if raw else 0


def _brightness_to_api(device_id: str, value: int, adjustable: bool) -> str:
    """Convert 0-255 to API format."""
    if not adjustable:
        return "on" if value > 0 else "off"
    pct = int(value / 255 * 100)
    if REGEX_3_LEVEL.match(device_id):
        if pct == 0:
            return "0"
        if pct < 35:
            return str(MIN_3_LEVEL)
        if pct < 70:
            return str(MID_3_LEVEL)
        return str(MAX_3_LEVEL)
    return str(max(10, min(80, (pct // 10) * 10)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim lights from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    lights_data = control_info.get("light", []) or control_info.get("lightbulb", [])
    if not lights_data:
        resp = await client.device_query("light", "all")
        if resp and "item" in resp:
            seen = set()
            for item in resp["item"]:
                if item.get("device") != "light":
                    continue
                uid = item.get("uid")
                if uid and uid not in seen:
                    seen.add(uid)
                    lights_data.append({"uid": uid, "uname": uid})

    entities = []
    for dev in lights_data:
        uid = dev.get("uid")
        if not uid:
            continue
        name = dev.get("uname", uid)
        entities.append(
            DaelimLightEntity(client, entry.entry_id, uid, name, entry.data["complex"])
        )
    async_add_entities(entities)


class DaelimLightEntity(LightEntity):
    """Daelim light entity."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize light."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_light"
        self._is_on = False
        self._brightness = 0
        self._brightness_adjustable = False
        self._complex_name = complex_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._attr_name,
        )

    @property
    def is_on(self) -> bool:
        """Return if light is on."""
        return self._is_on

    @property
    def brightness(self) -> int | None:
        """Return brightness 0-255."""
        return self._brightness if self._is_on else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        self._brightness_adjustable = getattr(
            self, "_brightness_adjustable", True
        )
        arg2 = _brightness_to_api(
            self._device_id, brightness, self._brightness_adjustable
        )
        is_on = brightness > 0
        resp = await self._client.device_invoke(
            "light",
            self._device_id,
            "on" if is_on else "off",
            arg2=arg2 if (is_on and self._brightness_adjustable) else None,
            arg3="y" if (is_on and self._brightness_adjustable) else None,
        )
        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._is_on = item.get("arg1") == "on"
                    self._brightness = _brightness_from_api(
                        self._device_id,
                        item.get("arg2"),
                    )
                    break
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        resp = await self._client.device_invoke(
            "light", self._device_id, "off"
        )
        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._is_on = item.get("arg1") == "on"
                    self._brightness = 0
                    break
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update state."""
        resp = await self._client.device_query("light", "all")
        if not resp or "item" not in resp:
            return
        for item in resp["item"]:
            if item.get("uid") == self._device_id and item.get("device") == "light":
                self._is_on = item.get("arg1") == "on"
                dimming = item.get("dimming", "n")
                self._brightness_adjustable = dimming == "y"
                self._brightness = _brightness_from_api(
                    self._device_id,
                    item.get("arg2"),
                )
                break
