"""Light platform for Daelim SmartHome."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DeviceSubTypes, Types

REGEX_3_LEVEL = re.compile(r"Lt([0-9]{0,2})-([0-9]{0,2})", re.I)
PROFILE_3_LEVEL = "3level"
PROFILE_8_STEP = "8step"
MIN_3_LEVEL, MID_3_LEVEL, MAX_3_LEVEL = 1, 3, 6
GROUP_LIGHT_DEVICE_KEY = "type_light"
GROUP_LIGHT_DEVICE_NAME = "조명"


def _normalize_raw(raw: Any) -> str | None:
    """Normalize brightness raw value to string."""
    if raw is None:
        return None
    raw_str = str(raw).strip()
    if raw_str == "":
        return None
    return raw_str


def _coerce_dimming_flag(value: Any) -> bool | None:
    """Convert dimming field to bool when present."""
    if value is None:
        return None
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower == "y":
            return True
        if lower == "n":
            return False
    return None


def _supports_3_level(device_id: str) -> bool:
    return REGEX_3_LEVEL.match(device_id) is not None


def _default_profile(device_id: str) -> str:
    return PROFILE_3_LEVEL if _supports_3_level(device_id) else PROFILE_8_STEP


def _is_8_step_raw(raw: str | None) -> bool:
    """refs-style 8-step payload: 10..80 (or 100 for full)."""
    if raw is None or len(raw) < 2:
        return False
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        return False
    return val in (10, 20, 30, 40, 50, 60, 70, 80, 100)


def _update_profile_and_max3(
    device_id: str,
    raw: str | None,
    profile: str,
    max_3_level: int,
) -> tuple[str, int]:
    """Update brightness profile and 3-level max from latest raw value."""
    if raw is None:
        return profile, max_3_level

    if _is_8_step_raw(raw):
        return PROFILE_8_STEP, max_3_level

    if _supports_3_level(device_id) and len(raw) <= 1:
        try:
            max_3_level = max(max_3_level, int(float(raw)))
        except (TypeError, ValueError):
            pass
        return PROFILE_3_LEVEL, max_3_level

    return profile, max_3_level


def _brightness_from_api(raw: str, profile: str, max_3_level: int) -> int:
    """Convert API brightness payload to 0-255."""
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        return 0

    if profile == PROFILE_8_STEP:
        if val <= 0:
            return 0
        if val >= 100:
            return 255
        clamped = max(0, min(80, val))
        return max(0, min(255, round((clamped / 80) * 255)))

    # 3-level (some complexes are 0,1,2,3; some are 0,1,3,6)
    if val <= 0:
        return 0
    if max_3_level <= 3:
        clamped = max(1, min(max_3_level, val))
        return max(1, min(255, round((clamped / max_3_level) * 255)))
    if val <= 1:
        return 85
    if val <= 3:
        return 170
    return 255


def _brightness_to_api(
    value_255: int,
    adjustable: bool,
    profile: str,
    max_3_level: int,
) -> str:
    """Convert HA brightness (0-255) to API payload."""
    if not adjustable:
        return "on" if value_255 > 0 else "off"

    pct = max(0, min(100, round((value_255 / 255) * 100)))
    if profile == PROFILE_8_STEP:
        # refs behavior: 8-step => 10,20,...80 and full => 100
        step = round((pct / 100) * 8)
        if step <= 0:
            return "0"
        if step >= 8:
            return "100"
        return str(step * 10)

    level = max(0, min(3, round((pct / 100) * 3)))
    if level == 0:
        return "0"
    if max_3_level <= 3:
        return str(level)
    if level == 1:
        return str(MIN_3_LEVEL)
    if level == 2:
        return str(MID_3_LEVEL)
    return str(max_3_level)


def _iter_items_from_body(body: dict | None) -> list[dict[str, Any]]:
    """Return normalized item list from MMF response body."""
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
    """Set up Daelim lights from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    lights_data = list(control_info.get("light", []))
    lights_data.extend(list(control_info.get("lightbulb", [])))
    initial = await client.device_query("light", "all") if lights_data else None

    group_by_type = entry.options.get("group_by_type", True)

    entities = []
    seen = set()
    for dev in lights_data:
        uid = dev.get("uid")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        name = dev.get("uname", uid)
        entities.append(
            DaelimLightEntity(
                client,
                entry.entry_id,
                uid,
                name,
                entry.data["complex"],
                _coerce_dimming_flag(dev.get("dimming")) is True,
                group_by_type,
            )
        )

    entity_by_uid = {entity._device_id: entity for entity in entities}

    def _handle_device_body(body: dict, write_state: bool = True) -> None:
        for item in _iter_items_from_body(body):
            if item.get("device") != "light":
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


class DaelimLightEntity(LightEntity):
    """Daelim light entity."""
    _attr_should_poll = False

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        brightness_adjustable: bool,
        group_by_type: bool,
    ) -> None:
        """Initialize light."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_light"
        self._is_on = False
        self._brightness = 0
        self._brightness_adjustable = brightness_adjustable
        self._complex_name = complex_name
        self._group_by_type = group_by_type
        self._brightness_profile = _default_profile(device_id)
        self._max_3_level = MAX_3_LEVEL
        self._refresh_color_mode()

    def _refresh_color_mode(self) -> None:
        if self._brightness_adjustable:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    def _update_from_item(self, item: dict[str, Any]) -> None:
        self._is_on = item.get("arg1") == "on"

        dimming = _coerce_dimming_flag(item.get("dimming"))
        if dimming is not None:
            self._brightness_adjustable = dimming
            self._refresh_color_mode()

        raw = _normalize_raw(item.get("arg2"))
        (
            self._brightness_profile,
            self._max_3_level,
        ) = _update_profile_and_max3(
            self._device_id,
            raw,
            self._brightness_profile,
            self._max_3_level,
        )

        if not self._brightness_adjustable:
            self._brightness = 255 if self._is_on else 0
            return

        if raw is None:
            if not self._is_on:
                self._brightness = 0
                return
            if self._brightness <= 0:
                self._brightness = 255
            return

        self._brightness = _brightness_from_api(
            raw,
            self._brightness_profile,
            self._max_3_level,
        )

    def _apply_invoke_response(self, resp: dict | None) -> None:
        if not resp or "item" not in resp:
            return
        items = resp.get("item")
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for item in items:
            if item.get("uid") == self._device_id and item.get("device", "light") == "light":
                self._update_from_item(item)
                return

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        if self._group_by_type:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry_id}_{GROUP_LIGHT_DEVICE_KEY}")},
                manufacturer=MANUFACTURER,
                model=self._complex_name,
                name=GROUP_LIGHT_DEVICE_NAME,
            )
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
        if not self._brightness_adjustable:
            return None
        return self._brightness if self._is_on else 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        target_brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        is_on = target_brightness > 0

        if self._brightness_adjustable and is_on:
            arg2 = _brightness_to_api(
                int(target_brightness),
                True,
                self._brightness_profile,
                self._max_3_level,
            )
            resp = await self._client.device_invoke(
                "light",
                self._device_id,
                "on",
                arg2=arg2,
                arg3="y",
            )
        else:
            resp = await self._client.device_invoke(
                "light",
                self._device_id,
                "on" if is_on else "off",
            )

        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        resp = await self._client.device_invoke("light", self._device_id, "off")
        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """State updates are handled by MMF response listeners."""
        return
