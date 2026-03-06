"""Climate platform for Daelim SmartHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DeviceSubTypes, Types

GROUP_HEAT_DEVICE_KEY = "type_heating"
GROUP_HEAT_DEVICE_NAME = "난방"
GROUP_COOL_DEVICE_KEY = "type_cooling"
GROUP_COOL_DEVICE_NAME = "에어컨"
HEATING_ICON = "mdi:radiator"
COOLING_ICON = "mdi:snowflake"


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iter_items_from_body(body: dict | None) -> list[dict[str, Any]]:
    if not body:
        return []
    items = body.get("item")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    return items


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim climate entities from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    group_by_type = entry.options.get("group_by_type", True)
    entities: list[ClimateEntity] = []
    seen_uids: set[str] = set()
    initial_responses: list[dict | None] = []
    for (
        device_types,
        hvac_mode,
        min_temp,
        max_temp,
        group_device_key,
        group_device_name,
        icon,
    ) in [
        (
            ("heating", "heater"),
            HVACMode.HEAT,
            5,
            40,
            GROUP_HEAT_DEVICE_KEY,
            GROUP_HEAT_DEVICE_NAME,
            HEATING_ICON,
        ),
        (
            ("cooling", "cooler"),
            HVACMode.COOL,
            18,
            30,
            GROUP_COOL_DEVICE_KEY,
            GROUP_COOL_DEVICE_NAME,
            COOLING_ICON,
        ),
    ]:
        devices: list[dict[str, Any]] = []
        known_uids: set[str] = set()
        for device_type in device_types:
            for dev in list(control_info.get(device_type, [])):
                uid = dev.get("uid")
                if not uid or uid in known_uids:
                    continue
                known_uids.add(uid)
                devices.append(dev)

        if devices:
            for device_type in device_types:
                resp = await client.device_query(device_type, "all")
                initial_responses.append(resp)

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
                    device_types[0],
                    hvac_mode,
                    min_temp,
                    max_temp,
                    group_by_type,
                    group_device_key,
                    group_device_name,
                    icon,
                )
            )

    entities_by_uid: dict[str, list[DaelimClimateEntity]] = {}
    for entity in entities:
        if not isinstance(entity, DaelimClimateEntity):
            continue
        entities_by_uid.setdefault(entity._device_id, []).append(entity)

    def _handle_device_body(body: dict, write_state: bool = True) -> None:
        for item in _iter_items_from_body(body):
            uid = item.get("uid")
            if not uid:
                continue
            candidates = entities_by_uid.get(uid, [])
            for entity in candidates:
                if not entity._matches_item(item):
                    continue
                entity._update_from_item(item)
                if write_state and entity.hass:
                    entity.async_write_ha_state()

    for resp in initial_responses:
        _handle_device_body(resp, write_state=False)

    async_add_entities(entities)
    listeners = data.setdefault("listeners", [])
    listeners.append(
        client.register_response_listener(
            Types.DEVICE,
            DeviceSubTypes.QUERY_RESPONSE,
            _handle_device_body,
        )
    )
    listeners.append(
        client.register_response_listener(
            Types.DEVICE,
            DeviceSubTypes.INVOKE_RESPONSE,
            _handle_device_body,
        )
    )
    listeners.append(
        client.register_response_listener(
            Types.DEVICE,
            DeviceSubTypes.INVOKE_NOTIFICATION,
            _handle_device_body,
        )
    )


class DaelimClimateEntity(ClimateEntity):
    """Daelim heater/cooler entity."""

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
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
        group_by_type: bool,
        group_device_key: str,
        group_device_name: str,
        icon: str,
    ) -> None:
        """Initialize climate."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = name
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_climate"
        self._complex_name = complex_name
        self._device_type = device_type
        self._hvac_mode = hvac_mode
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._group_by_type = group_by_type
        self._group_device_key = group_device_key
        self._group_device_name = group_device_name
        if device_type in ("heating", "heater"):
            self._compatible_device_types = {"heating", "heater"}
        else:
            self._compatible_device_types = {"cooling", "cooler"}

        self._active = False
        self._target_temp = 24
        self._current_temp = 24

        if hvac_mode == HVACMode.HEAT:
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        else:
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
        self._attr_icon = icon

    def _matches_item(self, item: dict[str, Any]) -> bool:
        return (
            item.get("uid") == self._device_id
            and item.get("device") in self._compatible_device_types
        )

    def _update_from_item(self, item: dict[str, Any]) -> None:
        self._active = item.get("arg1") == "on"
        self._target_temp = _to_int(item.get("arg2"), self._target_temp)
        self._current_temp = _to_int(item.get("arg3"), self._current_temp)

    def _apply_invoke_response(self, resp: dict | None) -> None:
        for item in _iter_items_from_body(resp):
            if self._matches_item(item):
                self._update_from_item(item)
                return

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        if self._group_by_type:
            return DeviceInfo(
                identifiers={
                    (
                        DOMAIN,
                        f"{self._entry_id}_{self._group_device_key}",
                    )
                },
                manufacturer=MANUFACTURER,
                model=self._complex_name,
                name=self._group_device_name,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
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
        self._apply_invoke_response(resp)
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
        self._apply_invoke_response(resp)
        if not self._active:
            self._target_temp = int(temp)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """State updates are handled by MMF response listeners."""
        return
