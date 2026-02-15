"""Fan platform for Daelim SmartHome."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

FAN_SPEED_OFF, FAN_SPEED_LOW, FAN_SPEED_MID, FAN_SPEED_HIGH = "00", "01", "02", "03"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim fans from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    devices = control_info.get("fan", [])
    if not devices:
        resp = await client.device_query("fan", "all")
        if resp and "item" in resp:
            seen = set()
            for item in resp["item"]:
                if item.get("device") != "fan":
                    continue
                uid = item.get("uid")
                if uid and uid not in seen:
                    seen.add(uid)
                    devices.append({"uid": uid, "uname": uid})

    entities = []
    for dev in devices:
        uid = dev.get("uid")
        if not uid:
            continue
        name = dev.get("uname", uid)
        entities.append(
            DaelimFanEntity(client, entry.entry_id, uid, name, entry.data["complex"])
        )
    async_add_entities(entities)


class DaelimFanEntity(FanEntity):
    """Daelim fan entity."""

    _attr_supported_features = FanEntityFeature.SET_SPEED
    _attr_speed_count = 4

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize fan."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_fan"
        self._is_on = False
        self._speed = FAN_SPEED_OFF
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
        """Return if fan is on."""
        return self._is_on

    @property
    def percentage(self) -> int | None:
        """Return speed percentage."""
        if not self._is_on:
            return 0
        idx = int(self._speed) if self._speed else 0
        return min(100, (idx + 1) * 33)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on fan."""
        speed = FAN_SPEED_OFF
        if percentage and percentage > 0:
            if percentage < 35:
                speed = FAN_SPEED_LOW
            elif percentage < 70:
                speed = FAN_SPEED_MID
            else:
                speed = FAN_SPEED_HIGH

        if not self._is_on and speed != FAN_SPEED_OFF:
            resp = await self._client.device_invoke("fan", self._device_id, "on", arg2=speed)
        elif self._is_on and speed != FAN_SPEED_OFF:
            resp = await self._client.device_invoke(
                "fan", self._device_id, "on", arg2=speed, arg3=""
            )
        else:
            resp = await self._client.device_invoke("fan", self._device_id, "off")

        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._is_on = item.get("arg1") == "on"
                    self._speed = item.get("arg2") or FAN_SPEED_OFF
                    break
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off fan."""
        resp = await self._client.device_invoke("fan", self._device_id, "off")
        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._is_on = item.get("arg1") == "on"
                    self._speed = FAN_SPEED_OFF
                    break
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed."""
        await self.async_turn_on(percentage=percentage)

    async def async_update(self) -> None:
        """Update state."""
        resp = await self._client.device_query("fan", "all")
        if not resp or "item" not in resp:
            return
        for item in resp["item"]:
            if item.get("uid") == self._device_id:
                self._is_on = item.get("arg1") == "on"
                self._speed = item.get("arg2") or FAN_SPEED_OFF
                break
