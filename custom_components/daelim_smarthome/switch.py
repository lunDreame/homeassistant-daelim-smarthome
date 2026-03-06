"""Switch platform for Daelim SmartHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DeviceSubTypes, Types

GROUP_OUTLET_DEVICE_KEY = "type_outlet"
GROUP_OUTLET_DEVICE_NAME = "콘센트"
OUTLET_ICON = "mdi:power-socket-eu"
GROUP_GAS_DEVICE_KEY = "type_gas"
GROUP_GAS_DEVICE_NAME = "가스밸브"
GAS_ICON_ON = "mdi:valve-open"
GAS_ICON_OFF = "mdi:valve-closed"


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
    """Set up Daelim switches from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    outlet_devices = list(control_info.get("wallsocket", []))
    outlet_devices.extend(list(control_info.get("outlet", [])))
    initial_outlet = await client.device_query("wallsocket", "all") if outlet_devices else None

    gas_devices = list(control_info.get("gas", []))
    initial_gas = await client.device_query("gas", "all") if gas_devices else None

    group_by_type = entry.options.get("group_by_type", True)

    outlet_entities: list[DaelimOutletEntity] = []
    seen_outlet = set()
    for dev in outlet_devices:
        uid = dev.get("uid")
        if not uid or uid in seen_outlet:
            continue
        seen_outlet.add(uid)
        name = dev.get("uname", uid)
        outlet_entities.append(
            DaelimOutletEntity(
                client,
                entry.entry_id,
                uid,
                name,
                entry.data["complex"],
                group_by_type,
            )
        )
    outlet_by_uid = {entity._device_id: entity for entity in outlet_entities}

    gas_entities: list[DaelimGasSwitchEntity] = []
    seen_gas = set()
    for dev in gas_devices:
        uid = dev.get("uid")
        if not uid or uid in seen_gas:
            continue
        seen_gas.add(uid)
        name = dev.get("uname", uid)
        gas_entities.append(
            DaelimGasSwitchEntity(
                client,
                entry.entry_id,
                uid,
                name,
                entry.data["complex"],
                group_by_type,
            )
        )
    gas_by_uid = {entity._device_id: entity for entity in gas_entities}

    def _handle_device_body(body: dict, write_state: bool = True) -> None:
        for item in _iter_items_from_body(body):
            device = item.get("device")
            uid = item.get("uid")
            if not uid:
                continue
            entity: DaelimOutletEntity | DaelimGasSwitchEntity | None = None
            if device in ("wallsocket", "outlet"):
                entity = outlet_by_uid.get(uid)
            elif device == "gas":
                entity = gas_by_uid.get(uid)
            if not entity:
                continue
            entity._update_from_item(item)
            if write_state and entity.hass:
                entity.async_write_ha_state()

    if initial_outlet:
        _handle_device_body(initial_outlet, write_state=False)
    if initial_gas:
        _handle_device_body(initial_gas, write_state=False)
    async_add_entities([*outlet_entities, *gas_entities])
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
            DeviceSubTypes.WALL_SOCKET_QUERY_RESPONSE,
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
            DeviceSubTypes.WALL_SOCKET_INVOKE_RESPONSE,
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


class DaelimOutletEntity(SwitchEntity):
    """Daelim outlet (wall socket) entity."""

    _attr_should_poll = False

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        group_by_type: bool,
    ) -> None:
        """Initialize outlet."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = name
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_outlet"
        self._attr_icon = OUTLET_ICON
        self._is_on = False
        self._complex_name = complex_name
        self._group_by_type = group_by_type

    def _update_from_item(self, item: dict[str, Any]) -> None:
        self._is_on = item.get("arg1") == "on"

    def _apply_invoke_response(self, resp: dict | None) -> None:
        for item in _iter_items_from_body(resp):
            if item.get("uid") == self._device_id and item.get("device") in ("wallsocket", "outlet"):
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
                        f"{self._entry_id}_{GROUP_OUTLET_DEVICE_KEY}",
                    )
                },
                manufacturer=MANUFACTURER,
                model=self._complex_name,
                name=GROUP_OUTLET_DEVICE_NAME,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
        )

    @property
    def is_on(self) -> bool:
        """Return if switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on outlet."""
        resp = await self._client.wallsocket_invoke(self._device_id, "on")
        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off outlet."""
        resp = await self._client.wallsocket_invoke(self._device_id, "off")
        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """State updates are handled by MMF response listeners."""
        return


class DaelimGasSwitchEntity(SwitchEntity):
    """Daelim gas valve switch."""

    _attr_should_poll = False

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        group_by_type: bool,
    ) -> None:
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._device_name = name
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_gas_switch"
        self._is_on = False
        self._complex_name = complex_name
        self._group_by_type = group_by_type

    def _update_from_item(self, item: dict[str, Any]) -> None:
        self._is_on = item.get("arg1") == "on"

    def _apply_invoke_response(self, resp: dict | None) -> None:
        for item in _iter_items_from_body(resp):
            if item.get("uid") == self._device_id and item.get("device") == "gas":
                self._update_from_item(item)
                return

    @property
    def device_info(self) -> DeviceInfo:
        if self._group_by_type:
            return DeviceInfo(
                identifiers={
                    (
                        DOMAIN,
                        f"{self._entry_id}_{GROUP_GAS_DEVICE_KEY}",
                    )
                },
                manufacturer=MANUFACTURER,
                model=self._complex_name,
                name=GROUP_GAS_DEVICE_NAME,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._device_name,
        )

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def icon(self) -> str:
        return GAS_ICON_ON if self._is_on else GAS_ICON_OFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Gas valve open is not supported by policy; keep state as-is.
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        resp = await self._client.device_invoke("gas", self._device_id, "off")
        self._apply_invoke_response(resp)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """State updates are handled by MMF response listeners."""
        return
