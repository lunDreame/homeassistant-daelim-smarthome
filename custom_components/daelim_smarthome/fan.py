"""Fan platform for Daelim SmartHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DeviceSubTypes, Types

GROUP_FAN_DEVICE_KEY = "type_fan"
GROUP_FAN_DEVICE_NAME = "환기"
FAN_ICON = "mdi:fan"

FAN_SPEED_OFF = "00"
FAN_SPEED_LOW = "01"
FAN_SPEED_MID = "02"
FAN_SPEED_HIGH = "03"

_FAN_SUPPORTED_FEATURES = (
    FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF | FanEntityFeature.SET_SPEED
)


def _coerce_speed(raw: Any) -> str:
    """Normalize raw fan speed value to 00/01/02/03."""
    if raw is None:
        return FAN_SPEED_OFF
    value = str(raw).strip()
    if value in ("", "0", "00"):
        return FAN_SPEED_OFF
    if value in ("1", "01"):
        return FAN_SPEED_LOW
    if value in ("2", "02"):
        return FAN_SPEED_MID
    if value in ("3", "03"):
        return FAN_SPEED_HIGH
    return FAN_SPEED_OFF


def _percentage_to_speed(percentage: int | None) -> str:
    if percentage is None:
        return FAN_SPEED_LOW
    if percentage <= 0:
        return FAN_SPEED_OFF
    if percentage < 35:
        return FAN_SPEED_LOW
    if percentage < 70:
        return FAN_SPEED_MID
    return FAN_SPEED_HIGH


def _speed_to_percentage(speed: str) -> int:
    if speed == FAN_SPEED_LOW:
        return 33
    if speed == FAN_SPEED_MID:
        return 66
    if speed == FAN_SPEED_HIGH:
        return 100
    return 0


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
    """Set up Daelim fans from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    devices = list(control_info.get("fan", []))
    initial = await client.device_query("fan", "all") if devices else None

    group_by_type = entry.options.get("group_by_type", True)

    entities = []
    seen = set()
    for dev in devices:
        uid = dev.get("uid")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        name = dev.get("uname", uid)
        entities.append(
            DaelimFanEntity(
                client,
                entry.entry_id,
                uid,
                name,
                entry.data["complex"],
                group_by_type,
            )
        )
    entity_by_uid = {entity._device_id: entity for entity in entities}

    def _handle_device_body(body: dict, write_state: bool = True) -> None:
        for item in _iter_items_from_body(body):
            if item.get("device") != "fan":
                continue
            uid = item.get("uid")
            if not uid:
                continue
            entity = entity_by_uid.get(uid)
            if not entity:
                continue
            entity._update_from_item(item)
            if write_state and entity.hass:
                entity.async_write_ha_state()

    if initial:
        _handle_device_body(initial, write_state=False)
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


class DaelimFanEntity(FanEntity):
    """Daelim fan entity."""

    _attr_should_poll = False
    _attr_supported_features = _FAN_SUPPORTED_FEATURES
    _attr_speed_count = 3

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        group_by_type: bool,
    ) -> None:
        """Initialize fan."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = name
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_fan"
        self._attr_icon = FAN_ICON
        self._is_on = False
        self._speed = FAN_SPEED_OFF
        self._complex_name = complex_name
        self._group_by_type = group_by_type

    def _update_from_item(self, item: dict[str, Any]) -> None:
        self._is_on = item.get("arg1") == "on"
        speed = _coerce_speed(item.get("arg2"))
        self._speed = speed if self._is_on else FAN_SPEED_OFF

    def _apply_invoke_response(self, resp: dict | None) -> None:
        if not resp or "item" not in resp:
            return
        items = resp.get("item")
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for item in items:
            if item.get("uid") == self._device_id and item.get("device", "fan") == "fan":
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
                        f"{self._entry_id}_{GROUP_FAN_DEVICE_KEY}",
                    )
                },
                manufacturer=MANUFACTURER,
                model=self._complex_name,
                name=GROUP_FAN_DEVICE_NAME,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
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
        return _speed_to_percentage(self._speed)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on fan."""
        speed = _percentage_to_speed(percentage)
        if speed == FAN_SPEED_OFF:
            resp = await self._client.device_invoke("fan", self._device_id, "off")
            self._apply_invoke_response(resp)
            self.async_write_ha_state()
            return

        if percentage is None:
            resp = await self._client.device_invoke("fan", self._device_id, "on")
        elif not self._is_on:
            await self._client.device_invoke("fan", self._device_id, "on")
            resp = await self._client.device_invoke(
                "fan", self._device_id, "on", arg2=speed, arg3=""
            )
        else:
            resp = await self._client.device_invoke(
                "fan", self._device_id, "on", arg2=speed, arg3=""
            )

        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off fan."""
        resp = await self._client.device_invoke("fan", self._device_id, "off")
        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed."""
        await self.async_turn_on(percentage=percentage)

    async def async_update(self) -> None:
        """State updates are handled by MMF response listeners."""
        return
