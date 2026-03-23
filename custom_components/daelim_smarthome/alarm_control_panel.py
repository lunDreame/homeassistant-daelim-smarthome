"""Alarm control panel platform for Daelim SmartHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MANUFACTURER,
    GuardSubTypes,
    Types,
)

SECURITY_DEVICE = ("SD-000000", "방범모드")
GUARD_MODE_OFF = "0"
GUARD_MODE_AWAY = "1"


def _iter_items_from_body(body: dict | None) -> list[dict[str, Any]]:
    if not body:
        return []
    items = body.get("item")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    return items


def _normalize_guard_mode(raw: Any) -> str | None:
    value = str(raw).strip().lower()
    if value in ("1", "on", "away", "arm", "armed_away"):
        return GUARD_MODE_AWAY
    if value in ("0", "off", "disarm", "disarmed"):
        return GUARD_MODE_OFF
    return None


def _extract_guard_mode(body: dict | None) -> str | None:
    if not body:
        return None

    mode = _normalize_guard_mode(body.get("mode"))
    if mode is not None:
        return mode

    for item in _iter_items_from_body(body):
        mode = _normalize_guard_mode(item.get("mode"))
        if mode is not None:
            return mode
        mode = _normalize_guard_mode(item.get("arg1"))
        if mode is not None:
            return mode
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim guard mode alarm control panel."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]

    entity = DaelimGuardModeEntity(
        client,
        entry.entry_id,
        SECURITY_DEVICE[0],
        SECURITY_DEVICE[1],
        entry.data["complex"],
    )

    initial = await client.query_guard_mode()
    entity._update_from_body(initial)

    async_add_entities([entity])

    def _handle_guard_body(body: dict) -> None:
        entity._update_from_body(body)
        if entity.hass:
            entity.async_write_ha_state()

    listeners = data.setdefault("listeners", [])
    listeners.append(
        client.register_response_listener(
            Types.GUARD,
            GuardSubTypes.QUERY_RESPONSE,
            _handle_guard_body,
        )
    )
    listeners.append(
        client.register_response_listener(
            Types.GUARD,
            GuardSubTypes.ACTIVATE_RESPONSE,
            _handle_guard_body,
        )
    )


class DaelimGuardModeEntity(AlarmControlPanelEntity):
    """Daelim guard/security mode entity."""

    _attr_should_poll = False
    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = False

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize guard mode entity."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_guard"
        self._complex_name = complex_name
        self._guard_mode = GUARD_MODE_OFF

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
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the current alarm state."""
        if self._guard_mode == GUARD_MODE_AWAY:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    def _update_from_body(self, body: dict | None) -> None:
        mode = _extract_guard_mode(body)
        if mode is None:
            return
        self._guard_mode = mode

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disable away mode."""
        resp = await self._client.set_guard_mode(GUARD_MODE_OFF, password=code)
        if resp is not None:
            self._update_from_body(resp)
            if _extract_guard_mode(resp) is None:
                self._guard_mode = GUARD_MODE_OFF
            self.async_write_ha_state()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Enable away mode."""
        resp = await self._client.set_guard_mode(GUARD_MODE_AWAY, password=code)
        if resp is not None:
            self._update_from_body(resp)
            if _extract_guard_mode(resp) is None:
                self._guard_mode = GUARD_MODE_AWAY
            self.async_write_ha_state()
