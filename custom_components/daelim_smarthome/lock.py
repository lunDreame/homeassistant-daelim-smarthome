"""Lock platform for Daelim SmartHome (Gas valve)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up Daelim gas valves as locks (Secured=off, Unsecured=on)."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    control_info = client.menu_response.get("controlinfo", {})

    devices = control_info.get("gas", [])
    if not devices:
        resp = await client.device_query("gas", "all")
        if resp and "item" in resp:
            seen = set()
            for item in resp["item"]:
                if item.get("device") != "gas":
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
            DaelimGasLockEntity(client, entry.entry_id, uid, name, entry.data["complex"])
        )
    async_add_entities(entities)


class DaelimGasLockEntity(LockEntity):
    """Daelim gas valve as lock. Locked=gas off (safe), Unlocked=gas on."""

    def __init__(
        self,
        client,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize gas lock."""
        self._client = client
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_gas"
        self._is_locked = True  # locked = gas off (safe)
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
    def is_locked(self) -> bool:
        """Return if locked (gas off)."""
        return self._is_locked

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock - turn gas off."""
        resp = await self._client.device_invoke("gas", self._device_id, "off")
        if resp and "item" in resp:
            for item in resp["item"]:
                if item.get("uid") == self._device_id:
                    self._is_locked = item.get("arg1") != "on"
                    break
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock - cannot turn gas on via API, only off."""
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update state."""
        resp = await self._client.device_query("gas", "all")
        if not resp or "item" not in resp:
            return
        for item in resp["item"]:
            if item.get("uid") == self._device_id:
                self._is_locked = item.get("arg1") != "on"
                break
