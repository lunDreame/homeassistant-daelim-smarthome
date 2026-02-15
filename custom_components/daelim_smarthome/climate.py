"""Climate platform for Daelim SmartHome (Heater/Cooler)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim climate entities from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    entities = []
    seen_uids: set[str] = set()

    for device_type, hvac_mode, min_temp, max_temp in [
        ("heating", HVACMode.HEAT, 5, 40),
        ("heater", HVACMode.HEAT, 5, 40),
        ("cooling", HVACMode.COOL, 18, 30),
        ("cooler", HVACMode.COOL, 18, 30),
    ]:
        devices = control_info.get(device_type, [])
        if not devices:
            resp = await client.device_query(device_type, "all")
            if resp and "item" in resp:
                for item in resp["item"]:
                    if item.get("device") != device_type:
                        continue
                    uid = item.get("uid")
                    if uid and uid not in seen_uids:
                        seen_uids.add(uid)
                        devices.append({"uid": uid, "uname": uid})

        for dev in devices:
            uid = dev.get("uid")
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)
            name = dev.get("uname", uid)
            entities.append(
                DaelimClimateEntity(
                    client,
                    entry.entry_id,
                    uid,
                    name,
                    entry.data["complex"],
                    device_type,
                    hvac_mode,
                    min_temp,
                    max_temp,
                )
            )

    async_add_entities(entities)


class DaelimClimateEntity(ClimateEntity):
    """Daelim heater/cooler entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        device_type: str,
        hvac_mode: HVACMode,
        min_temp: int,
        max_temp: int,
    ) -> None:
        """Initialize climate."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_climate"
        self._complex_name = complex_name
        self._device_type = device_type
        self._hvac_mode = hvac_mode
        self._min_temp = min_temp
        self._max_temp = max_temp

        self._active = False
        self._target_temp = 24
        self._current_temp = 24

        if hvac_mode == HVACMode.HEAT:
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
            self._attr_icon = "mdi:radiator"
        else:
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
            self._attr_icon = "mdi:snowflake"

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
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        return self._hvac_mode if self._active else HVACMode.OFF

    @property
    def current_temperature(self) -> float:
        """Return current temperature."""
        return float(self._current_temp)

    @property
    def target_temperature(self) -> float:
        """Return target temperature."""
        return float(self._target_temp)

    @property
    def min_temp(self) -> float:
        """Return min temperature."""
        return float(self._min_temp)

    @property
    def max_temp(self) -> float:
        """Return max temperature."""
        return float(self._max_temp)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        active = hvac_mode == self._hvac_mode
        resp = await self._client.device_invoke(
            self._device_type,
            self._device_id,
            "on" if active else "off",
        )
        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._active = item.get("arg1") == "on"
                    self._target_temp = int(item.get("arg2", self._target_temp))
                    self._current_temp = int(item.get("arg3", self._current_temp))
                    break
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        resp = await self._client.device_invoke(
            self._device_type,
            self._device_id,
            "on",
            arg2=str(int(temp)),
        )
        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._active = item.get("arg1") == "on"
                    self._target_temp = int(item.get("arg2", temp))
                    self._current_temp = int(item.get("arg3", self._current_temp))
                    break
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update state."""
        resp = await self._client.device_query(self._device_type, "all")
        if not resp or "item" not in resp:
            return
        for item in resp["item"]:
            if item.get("uid") == self._device_id:
                self._active = item.get("arg1") == "on"
                self._target_temp = int(item.get("arg2", self._target_temp))
                self._current_temp = int(item.get("arg3", self._current_temp))
                break
