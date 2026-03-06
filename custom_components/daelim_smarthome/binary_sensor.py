"""Binary sensor platform for Daelim SmartHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DaelimEventCoordinator

DOOR_DEVICES = [
    ("FD-000000", "세대현관", False),
    ("CE-000000", "공동현관", True),
]
VEHICLE_DEVICE = ("VH-000000", "주차차단기")
VISITOR_DEVICES = [
    ("FD-CAM0", "세대현관 방문자"),
    ("CE-CAM0", "공동현관 방문자"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    entry_id = entry.entry_id
    complex_name = entry.data["complex"]

    coordinator = data["event_coordinator"]
    await coordinator.async_config_entry_first_refresh()

    entities = []

    for device_id, name, is_communal in DOOR_DEVICES:
        entities.append(
            DaelimDoorBinarySensor(
                coordinator, entry, entry_id, device_id, name, complex_name, is_communal
            )
        )

    entities.append(
        DaelimVehicleBinarySensor(
            coordinator, entry, entry_id,
            VEHICLE_DEVICE[0],
            VEHICLE_DEVICE[1],
            complex_name,
        )
    )

    for device_id, name in VISITOR_DEVICES:
        entities.append(
            DaelimVisitorBinarySensor(
                coordinator, entry, entry_id, device_id, name, complex_name
            )
        )

    async_add_entities(entities)


class DaelimDoorBinarySensor(CoordinatorEntity[DaelimEventCoordinator], BinarySensorEntity):
    """Daelim door motion sensor - FCM trigger via event coordinator."""

    _attr_device_class = "motion"

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
        is_communal: bool,
    ) -> None:
        """Initialize door sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_door"
        self._attr_is_on = False
        self._complex_name = complex_name
        self._is_communal = is_communal
        self._reset_timer: Any = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._attr_name,
        )

    def _get_duration(self) -> int:
        """Get motion duration from options."""
        return self._entry.options.get("door_duration", 5)

    def _trigger_motion(self) -> None:
        """Set motion on and schedule reset."""
        if self._reset_timer:
            try:
                self._reset_timer()
            except Exception:
                pass
        self._attr_is_on = True
        self.async_write_ha_state()
        duration = self._get_duration()

        @callback
        def _reset_cb() -> None:
            self._attr_is_on = False
            self._reset_timer = None
            self.async_write_ha_state()

        self._reset_timer = self.hass.async_call_later(duration, _reset_cb)

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update - check for trigger flags."""
        if not self.coordinator.data:
            return
        key = "door_communal_trigger" if self._is_communal else "door_front_trigger"
        if self.coordinator.data.get(key):
            self._trigger_motion()


class DaelimVehicleBinarySensor(CoordinatorEntity[DaelimEventCoordinator], BinarySensorEntity):
    """Daelim vehicle (parking) motion sensor - FCM trigger via event coordinator."""

    _attr_device_class = "motion"

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize vehicle sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_vehicle"
        self._attr_is_on = False
        self._complex_name = complex_name
        self._reset_timer: Any = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._attr_name,
        )

    def _get_duration(self) -> int:
        """Get motion duration from options."""
        return self._entry.options.get("vehicle_duration", 5)

    def _trigger_motion(self) -> None:
        """Set motion on and schedule reset."""
        if self._reset_timer:
            try:
                self._reset_timer()
            except Exception:
                pass
        self._attr_is_on = True
        self.async_write_ha_state()
        duration = self._get_duration()

        @callback
        def _reset_cb() -> None:
            self._attr_is_on = False
            self._reset_timer = None
            self.async_write_ha_state()

        self._reset_timer = self.hass.async_call_later(duration, _reset_cb)

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update - check for trigger flags."""
        if not self.coordinator.data or not self.coordinator.data.get("vehicle_trigger"):
            return
        self._trigger_motion()


class DaelimVisitorBinarySensor(CoordinatorEntity[DaelimEventCoordinator], BinarySensorEntity):
    """Daelim visitor (intercom) motion sensor - FCM VISITOR_PICTURE_STORED."""

    _attr_device_class = "motion"

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        entry_id: str,
        device_id: str,
        name: str,
        complex_name: str,
    ) -> None:
        """Initialize visitor sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._entry_id = entry_id
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{device_id}_visitor"
        self._attr_is_on = False
        self._complex_name = complex_name
        self._reset_timer: Any = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._device_id}")},
            manufacturer=MANUFACTURER,
            model=self._complex_name,
            name=self._attr_name,
        )

    def _get_duration(self) -> int:
        """Get motion duration from options."""
        return self._entry.options.get("camera_duration", 180)

    def _trigger_motion(self) -> None:
        """Set motion on and schedule reset."""
        if self._reset_timer:
            try:
                self._reset_timer()
            except Exception:
                pass
        self._attr_is_on = True
        self.async_write_ha_state()
        duration = self._get_duration()

        @callback
        def _reset_cb() -> None:
            self._attr_is_on = False
            self._reset_timer = None
            self.async_write_ha_state()

        self._reset_timer = self.hass.async_call_later(duration, _reset_cb)

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update - check for trigger flags."""
        if not self.coordinator.data:
            return
        if not self.coordinator.data.get("camera_motion_trigger"):
            return
        # For FD-CAM0 (front) and CE-CAM0 (communal) - trigger both on any visitor
        # since FCM doesn't include location; or we could add location parsing
        self._trigger_motion()
